"""Tests for bridge_cmd module — mock tmux_session calls."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch, MagicMock
from argparse import Namespace

import pytest

from claude_bridge.bridge_cmd import (
    cmd_start,
    cmd_stop,
    cmd_logs,
    cmd_restart,
    cmd_status,
    _load_config,
    _build_claude_command,
    _validate_config,
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
            "--dangerously-load-development-channels", "server:bridge",
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
        with patch("claude_bridge.bridge_cmd.session_running", return_value=False):
            args = Namespace()
            assert cmd_stop(args) == 1
            assert "not running" in capsys.readouterr().err

    def test_stop_success(self, capsys):
        with patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.stop_session", return_value=True):
            args = Namespace()
            assert cmd_stop(args) == 0
            assert "stopped" in capsys.readouterr().out.lower()

    def test_stop_failed(self, capsys):
        with patch("claude_bridge.bridge_cmd.session_running", return_value=True), \
             patch("claude_bridge.bridge_cmd.stop_session", return_value=False):
            args = Namespace()
            assert cmd_stop(args) == 1


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
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.session_running", side_effect=[True, False]), \
             patch("claude_bridge.bridge_cmd.stop_session", return_value=True), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
             patch("claude_bridge.bridge_cmd.start_session", return_value=True):
            args = Namespace(foreground=False)
            assert cmd_restart(args) == 0

    def test_restart_when_stopped(self, config_file, config_dir, capsys):
        with patch("claude_bridge.bridge_cmd.CONFIG_PATH", config_file), \
             patch("claude_bridge.bridge_cmd.session_running", return_value=False), \
             patch("claude_bridge.bridge_cmd.tmux_available", return_value=True), \
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
