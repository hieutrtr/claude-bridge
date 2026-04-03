"""Tests for bridge_cmd module — mock tmux_session calls."""

from __future__ import annotations

import json
import os
import shutil
import sys
from unittest.mock import patch, MagicMock
from argparse import Namespace

import pytest

from claude_bridge.bridge_cmd import (
    cmd_start,
    cmd_stop,
    cmd_attach,
    cmd_logs,
    cmd_restart,
    cmd_status,
    _load_config,
    _build_claude_command,
    _validate_config,
    _kill_bridge_processes,
    _unload_launchd_plist,
    _bridge_processes_running,
    _KILL_PATTERNS,
    LAUNCHD_PLIST_PATH,
    main,
    build_parser,
)


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp config directory with valid config."""
    config = {
        "telegram_bot_token": "test-token",
        "bot_dir": str(tmp_path / "bridge-bot"),
        "mode": "channel",
    }
    os.makedirs(tmp_path / "bridge-bot")
    return config


@pytest.fixture
def config_file(tmp_path, config_dir):
    """Write config to a temp file and patch CONFIG_PATH."""
    config_path = str(tmp_path / "config.json")
    with open(config_path, "w") as f:
        json.dump(config_dir, f)
    return config_path


class TestLoadConfig:
    def test_load_valid(self, config_file):
        config = _load_config(config_file)
        assert config is not None
        assert config["mode"] == "channel"

    def test_missing_file(self, tmp_path):
        assert _load_config(str(tmp_path / "nonexistent.json")) is None

    def test_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        assert _load_config(str(bad_file)) is None


class TestBuildClaudeCommand:
    def test_channel_mode(self):
        cmd = _build_claude_command({"mode": "channel", "bot_dir": "/tmp/bot"})
        assert cmd == [
            "claude",
            "--channels", "server:bridge",
            "--dangerously-skip-permissions",
        ]

    def test_mcp_mode(self):
        cmd = _build_claude_command({"mode": "mcp", "bot_dir": "/tmp/bot"})
        assert cmd == ["claude", "--dangerously-skip-permissions"]

    def test_default_mode(self):
        cmd = _build_claude_command({"bot_dir": "/tmp/bot"})
        assert cmd == ["claude", "--dangerously-skip-permissions"]


class TestValidateConfig:
    def test_none_config(self):
        errors = _validate_config(None)
        assert len(errors) == 1
        assert "bridge-cli setup" in errors[0]

    def test_missing_bot_dir_key(self, tmp_path):
        errors = _validate_config({"telegram_bot_token": "tok", "mode": "mcp"})
        assert any("bot_dir missing" in e for e in errors)

    def test_bot_dir_not_found(self, tmp_path):
        errors = _validate_config({
            "bot_dir": str(tmp_path / "missing"),
            "telegram_bot_token": "tok",
            "mode": "mcp",
        })
        assert any("bot_dir not found" in e for e in errors)

    def test_missing_token(self, tmp_path):
        bot_dir = tmp_path / "bot"
        bot_dir.mkdir()
        errors = _validate_config({"bot_dir": str(bot_dir), "mode": "mcp"})
        assert any("token" in e.lower() for e in errors)

    def test_invalid_mode(self, tmp_path):
        bot_dir = tmp_path / "bot"
        bot_dir.mkdir()
        errors = _validate_config({
            "bot_dir": str(bot_dir),
            "telegram_bot_token": "tok",
            "mode": "bad_mode",
        })
        assert any("Unknown mode" in e for e in errors)

    def test_valid_config(self, tmp_path):
        bot_dir = tmp_path / "bot"
        bot_dir.mkdir()
        errors = _validate_config({
            "bot_dir": str(bot_dir),
            "telegram_bot_token": "123:abc",
            "mode": "channel",
        })
        assert errors == []

    def test_empty_mode_allowed(self, tmp_path):
        """Mode defaults to mcp when empty — should not error."""
        bot_dir = tmp_path / "bot"
        bot_dir.mkdir()
        errors = _validate_config({
            "bot_dir": str(bot_dir),
            "telegram_bot_token": "tok",
        })
        assert errors == []

    def test_v01x_config_backward_compat(self, tmp_path):
        """Old v0.1.x config without 'mode' field should be accepted (defaults to mcp)."""
        bot_dir = tmp_path / "bot"
        bot_dir.mkdir()
        # Simulate a v0.1.x config: has bot_dir + token but no 'mode'
        old_config = {
            "bot_dir": str(bot_dir),
            "telegram_bot_token": "123:abc",
            # no 'mode' key — was not present in v0.1.x
        }
        errors = _validate_config(old_config)
        assert errors == [], f"v0.1.x config should be valid, got: {errors}"


class TestCmdStart:
    def test_no_config(self, tmp_path, capsys):
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", str(tmp_path / "nope.json")):
            args = Namespace(foreground=False)
            assert cmd_start(args) == 1
            err = capsys.readouterr().err
            assert "bridge-cli setup" in err

    def test_missing_bot_dir(self, tmp_path, capsys):
        config = {"bot_dir": str(tmp_path / "missing"), "telegram_bot_token": "tok", "mode": "mcp"}
        config_path = str(tmp_path / "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_path):
            args = Namespace(foreground=False)
            assert cmd_start(args) == 1
            assert "bot_dir not found" in capsys.readouterr().err

    def test_missing_token(self, tmp_path, capsys):
        bot_dir = tmp_path / "bot"
        bot_dir.mkdir()
        config = {"bot_dir": str(bot_dir), "mode": "mcp"}
        config_path = str(tmp_path / "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_path):
            args = Namespace(foreground=False)
            assert cmd_start(args) == 1
            assert "token" in capsys.readouterr().err.lower()

    def test_no_tmux(self, config_file, config_dir, capsys):
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=False):
            args = Namespace(foreground=False)
            assert cmd_start(args) == 1
            assert "tmux is not installed" in capsys.readouterr().err

    def test_already_running(self, config_file, config_dir, capsys):
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=True):
            args = Namespace(foreground=False)
            assert cmd_start(args) == 1
            assert "already running" in capsys.readouterr().err

    def test_start_success(self, config_file, config_dir, capsys):
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd.start_session", return_value=True):
            args = Namespace(foreground=False)
            assert cmd_start(args) == 0
            out = capsys.readouterr().out
            assert "started" in out

    def test_start_failed(self, config_file, config_dir, capsys):
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd.start_session", return_value=False):
            args = Namespace(foreground=False)
            assert cmd_start(args) == 1


class TestCmdStop:
    def test_not_running(self, capsys):
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=False), \
             patch("claude_bridge.bridge_cmd.subprocess.run"):
            args = Namespace()
            assert cmd_stop(args) == 1
            assert "not running" in capsys.readouterr().err

    def test_stop_success(self, capsys):
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.stop_session", return_value=True), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=False), \
             patch("claude_bridge.bridge_cmd.subprocess.run"):
            args = Namespace()
            assert cmd_stop(args) == 0
            assert "stopped" in capsys.readouterr().out.lower()

    def test_stop_failed_tmux_but_still_succeeds(self, capsys):
        """Even if tmux stop fails, cmd_stop returns 0 since tmux was running."""
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.stop_session", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=False), \
             patch("claude_bridge.bridge_cmd.subprocess.run"):
            args = Namespace()
            # Returns 0 because tmux_was_running was True (we attempted to stop)
            assert cmd_stop(args) == 0


class TestCmdLogs:
    def test_no_log_file(self, capsys):
        with patch("claude_bridge.bridge_cmd.LOG_PATH", "/nonexistent/path/log"):
            args = Namespace(lines=50, follow=False)
            assert cmd_logs(args) == 1
            assert "No log file" in capsys.readouterr().err

    def test_log_file_exists(self, tmp_path):
        log_file = tmp_path / "bridge-bot.log"
        log_file.write_text("line1\nline2\n")
        with patch("claude_bridge.bridge_cmd.LOG_PATH", str(log_file)), \
             patch("os.execvp") as mock_exec:
            args = Namespace(lines=20, follow=False)
            cmd_logs(args)
            mock_exec.assert_called_once_with("tail", ["tail", "-n20", str(log_file)])

    def test_log_follow(self, tmp_path):
        log_file = tmp_path / "bridge-bot.log"
        log_file.write_text("data\n")
        with patch("claude_bridge.bridge_cmd.LOG_PATH", str(log_file)), \
             patch("os.execvp") as mock_exec:
            args = Namespace(lines=50, follow=True)
            cmd_logs(args)
            mock_exec.assert_called_once_with("tail", ["tail", "-n50", "-f", str(log_file)])


class TestCmdRestart:
    def test_restart_when_running(self, config_file, config_dir, capsys):
        # session_running is called: once in cmd_restart check, once in cmd_stop,
        # once in cmd_start check
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.session_running", side_effect=[True, True, False]), \
             patch("claude_bridge.bridge_cmd.stop_session", return_value=True), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=False), \
             patch("claude_bridge.bridge_cmd.start_session", return_value=True), \
             patch("claude_bridge.bridge_cmd.subprocess.run"):
            args = Namespace(foreground=False)
            assert cmd_restart(args) == 0

    def test_restart_when_stopped(self, config_file, config_dir, capsys):
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd.start_session", return_value=True):
            args = Namespace(foreground=False)
            assert cmd_restart(args) == 0


class TestCmdStatus:
    def test_running(self, tmp_path, capsys):
        config = {"mode": "channel", "bot_dir": "/tmp/bot"}
        config_path = str(tmp_path / "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.get_session_pid", return_value=12345), \
             patch("claude_bridge.bridge_cmd.get_session_uptime", return_value="2h 15m"), \
             patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_path):
            args = Namespace()
            assert cmd_status(args) == 0
            out = capsys.readouterr().out
            assert "running" in out
            assert "12345" in out
            assert "2h 15m" in out

    def test_stopped(self, tmp_path, capsys):
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd.CONFIG_PATH", str(tmp_path / "nope.json")):
            args = Namespace()
            assert cmd_status(args) == 0
            out = capsys.readouterr().out
            assert "stopped" in out

    def test_no_tmux(self, tmp_path, capsys):
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=False), \
             patch("claude_bridge.bridge_cmd.CONFIG_PATH", str(tmp_path / "nope.json")):
            args = Namespace()
            assert cmd_status(args) == 0
            assert "stopped" in capsys.readouterr().out


class TestBuildParser:
    def test_all_subcommands(self):
        parser = build_parser()
        for cmd in ["start", "stop", "attach", "logs", "restart", "status"]:
            args = parser.parse_args([cmd])
            assert args.command == cmd

    def test_start_foreground(self):
        parser = build_parser()
        args = parser.parse_args(["start", "--foreground"])
        assert args.foreground is True

    def test_logs_options(self):
        parser = build_parser()
        args = parser.parse_args(["logs", "-n", "100", "-f"])
        assert args.lines == 100
        assert args.follow is True


class TestMain:
    def test_main_dispatches(self):
        mock_handler = MagicMock(return_value=0)
        with patch("sys.argv", ["bridge", "status"]), \
             patch.dict("claude_bridge.bridge_cmd.COMMANDS", {"status": mock_handler}):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
            mock_handler.assert_called_once()


class TestStopKillsChannelProcesses:
    """Bug 1: cmd_stop should kill bun/channel/claude processes."""

    def test_stop_kills_channel_processes(self, capsys):
        """cmd_stop kills bun server and claude channel processes even when tmux not running."""
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=True), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=False), \
             patch("claude_bridge.bridge_cmd.subprocess.run", mock_run):
            args = Namespace()
            result = cmd_stop(args)
            assert result == 0
            # Verify pkill was called for each pattern
            pkill_calls = [
                c for c in mock_run.call_args_list
                if c[0][0][0] == "pkill"
            ]
            assert len(pkill_calls) == len(_KILL_PATTERNS)

    def test_stop_tmux_and_processes(self, capsys):
        """cmd_stop stops tmux AND kills processes."""
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.stop_session", return_value=True), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=False), \
             patch("claude_bridge.bridge_cmd.subprocess.run"):
            args = Namespace()
            result = cmd_stop(args)
            assert result == 0
            out = capsys.readouterr().out
            assert "stopped" in out.lower()

    def test_stop_nothing_running(self, capsys):
        """cmd_stop returns 1 when nothing is running."""
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=False), \
             patch("claude_bridge.bridge_cmd.subprocess.run"):
            args = Namespace()
            result = cmd_stop(args)
            assert result == 1
            assert "not running" in capsys.readouterr().err


class TestStopUnloadsLaunchd:
    """Bug 1: cmd_stop should unload launchd plist on macOS."""

    def test_stop_unloads_launchd(self, capsys):
        """cmd_stop unloads the launchd plist when on macOS."""
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", return_value=True), \
             patch("claude_bridge.bridge_cmd.subprocess.run"):
            args = Namespace()
            result = cmd_stop(args)
            assert result == 0
            out = capsys.readouterr().out
            assert "launchd" in out.lower()

    def test_unload_launchd_macos(self):
        """_unload_launchd_plist calls launchctl on macOS with plist file present."""
        mock_run = MagicMock()
        with patch("claude_bridge.bridge_cmd.platform.system", return_value="Darwin"), \
             patch("claude_bridge.bridge_cmd.platform.mac_ver", return_value=("14.2.0", ("", "", ""), "")), \
             patch("claude_bridge.bridge_cmd.os.path.isfile", return_value=True), \
             patch("claude_bridge.bridge_cmd.os.getuid", return_value=501), \
             patch("claude_bridge.bridge_cmd.subprocess.run", mock_run):
            result = _unload_launchd_plist()
            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "launchctl"
            assert "bootout" in call_args

    def test_unload_launchd_not_macos(self):
        """_unload_launchd_plist returns False on non-macOS."""
        with patch("claude_bridge.bridge_cmd.platform.system", return_value="Linux"):
            assert _unload_launchd_plist() is False

    def test_unload_launchd_no_plist(self):
        """_unload_launchd_plist returns False when plist file doesn't exist."""
        with patch("claude_bridge.bridge_cmd.platform.system", return_value="Darwin"), \
             patch("claude_bridge.bridge_cmd.os.path.isfile", return_value=False):
            assert _unload_launchd_plist() is False


class TestAttachFallsBackToLogs:
    """Bug 2: cmd_attach should fall back to log tailing in daemon mode."""

    def test_attach_tmux_session(self):
        """cmd_attach attaches to tmux when session is running."""
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.attach_session", return_value=0) as mock_attach:
            args = Namespace()
            result = cmd_attach(args)
            assert result == 0
            mock_attach.assert_called_once()

    def test_attach_falls_back_to_logs(self, tmp_path, capsys):
        """cmd_attach tails logs when no tmux but daemon processes running."""
        log_file = tmp_path / "bridge-bot.log"
        log_file.write_text("test log line\n")
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.LOG_PATH", str(log_file)), \
             patch("os.execvp") as mock_exec:
            args = Namespace()
            cmd_attach(args)
            out = capsys.readouterr().out
            assert "daemon mode" in out.lower()
            mock_exec.assert_called_once_with("tail", ["tail", "-n50", "-f", str(log_file)])

    def test_attach_daemon_no_log_file(self, capsys):
        """cmd_attach shows error when daemon running but no log file."""
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.LOG_PATH", "/nonexistent/log"):
            args = Namespace()
            result = cmd_attach(args)
            assert result == 1
            assert "no log file" in capsys.readouterr().err.lower()

    def test_attach_nothing_running(self, capsys):
        """cmd_attach shows 'not running' when nothing is running."""
        with patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd._bridge_processes_running", return_value=False):
            args = Namespace()
            result = cmd_attach(args)
            assert result == 1
            assert "not running" in capsys.readouterr().err


class TestUninstallStopsProcesses:
    """Bug 3: _cmd_uninstall should stop processes before removing files."""

    def test_uninstall_stops_processes_first(self, tmp_path, monkeypatch):
        """_cmd_uninstall stops tmux, launchd, and kills processes before removing files."""
        from claude_bridge import cli as cli_module
        from claude_bridge.cli import _cmd_uninstall

        bridge_home = tmp_path / "bridge-home"
        bridge_home.mkdir()
        (bridge_home / "bridge.db").write_text("")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        call_order = []

        def mock_stop_session(*a, **kw):
            call_order.append("stop_session")
            return True

        def mock_unload_launchd():
            call_order.append("unload_launchd")
            return True

        def mock_kill_processes():
            call_order.append("kill_processes")

        original_rmtree = shutil.rmtree
        def mock_rmtree(path, *a, **kw):
            call_order.append("rmtree")

        args = Namespace(force=True)

        import claude_bridge
        with patch.object(claude_bridge, "get_bridge_home", return_value=bridge_home), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.tmux_session.session_running", return_value=True), \
             patch("claude_bridge.tmux_session.stop_session", mock_stop_session), \
             patch("claude_bridge.bridge_cmd.stop_session", mock_stop_session), \
             patch("claude_bridge.bridge_cmd._unload_launchd_plist", mock_unload_launchd), \
             patch("claude_bridge.bridge_cmd._kill_bridge_processes", mock_kill_processes), \
             patch("claude_bridge.bridge_cmd.LAUNCHD_PLIST_PATH", str(tmp_path / "nonexistent.plist")), \
             patch("shutil.rmtree", mock_rmtree), \
             patch("subprocess.run", MagicMock(return_value=MagicMock(stdout="", returncode=0))):
            _cmd_uninstall(args)

        # Verify processes were stopped before files were removed
        assert "stop_session" in call_order
        assert "kill_processes" in call_order
        if "rmtree" in call_order:
            stop_idx = call_order.index("stop_session")
            rmtree_idx = call_order.index("rmtree")
            assert stop_idx < rmtree_idx, "Processes must be stopped before files are removed"


class TestKillBridgeProcesses:
    """Test the _kill_bridge_processes helper."""

    def test_calls_pkill_for_each_pattern(self):
        mock_run = MagicMock()
        with patch("claude_bridge.bridge_cmd.subprocess.run", mock_run):
            _kill_bridge_processes()
            assert mock_run.call_count == len(_KILL_PATTERNS)
            for i, pattern in enumerate(_KILL_PATTERNS):
                call_args = mock_run.call_args_list[i][0][0]
                assert call_args == ["pkill", "-f", pattern]

    def test_ignores_errors(self):
        """_kill_bridge_processes doesn't raise even if pkill fails."""
        with patch("claude_bridge.bridge_cmd.subprocess.run", side_effect=FileNotFoundError):
            _kill_bridge_processes()  # Should not raise
