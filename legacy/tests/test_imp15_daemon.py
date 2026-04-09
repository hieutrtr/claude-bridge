"""Tests for IMP-15: Daemon install/management (systemd/launchd)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_bridge.daemon import (
    get_platform,
    get_service_name,
    get_launchd_label,
    SYSTEMD_UNIT_TEMPLATE,
    LAUNCHD_PLIST_TEMPLATE,
    install_daemon,
    uninstall_daemon,
    is_daemon_installed,
    get_daemon_file_path,
    get_daemon_status,
)

SYSTEMD_SERVICE_NAME = get_service_name("~/.claude-bridge")
LAUNCHD_LABEL = get_launchd_label("~/.claude-bridge")


class TestGetPlatform:
    def test_returns_linux_on_linux(self):
        with patch("platform.system", return_value="Linux"):
            assert get_platform() == "linux"

    def test_returns_macos_on_darwin(self):
        with patch("platform.system", return_value="Darwin"):
            assert get_platform() == "macos"

    def test_returns_other_on_windows(self):
        with patch("platform.system", return_value="Windows"):
            assert get_platform() == "other"


class TestSystemdInstall:
    def test_creates_unit_file(self, tmp_path):
        """install_systemd() creates the unit file at the correct path."""
        from claude_bridge.daemon import install_systemd, _systemd_unit_path
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / f"{SYSTEMD_SERVICE_NAME}.service"

        with patch("claude_bridge.daemon._systemd_unit_path", return_value=unit_path), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, msg = install_systemd(
                bot_dir=str(tmp_path / "bot"),
                bridge_home=str(tmp_path / "bridge"),
                log_path=str(tmp_path / "bridge.log"),
            )

        assert ok is True
        assert unit_path.exists()
        content = unit_path.read_text()
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "ExecStart=" in content

    def test_unit_file_contains_bridge_home(self, tmp_path):
        """systemd unit file includes CLAUDE_BRIDGE_HOME env var."""
        from claude_bridge.daemon import install_systemd
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / f"{SYSTEMD_SERVICE_NAME}.service"
        custom_home = str(tmp_path / "custom-bridge")

        with patch("claude_bridge.daemon._systemd_unit_path", return_value=unit_path), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, _ = install_systemd(
                bot_dir=str(tmp_path / "bot"),
                bridge_home=custom_home,
                log_path=str(tmp_path / "bridge.log"),
            )

        assert ok is True
        content = unit_path.read_text()
        assert custom_home in content

    def test_unit_file_uses_tmux_execstart(self, tmp_path):
        """systemd unit ExecStart uses tmux new-session (not bridge start --foreground)."""
        from claude_bridge.daemon import install_systemd
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / f"{SYSTEMD_SERVICE_NAME}.service"

        with patch("claude_bridge.daemon._systemd_unit_path", return_value=unit_path), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, _ = install_systemd(
                bot_dir=str(tmp_path / "bot"),
                bridge_home=str(tmp_path / "bridge"),
                log_path=str(tmp_path / "bridge.log"),
            )

        assert ok is True
        content = unit_path.read_text()
        assert "tmux new-session" in content
        assert "Type=forking" in content
        assert "RemainAfterExit=yes" in content
        assert "bridge start --foreground" not in content

    def test_unit_file_service_name_in_tmux_commands(self, tmp_path):
        """The service_name appears in ExecStartPre/ExecStart/ExecStop."""
        from claude_bridge.daemon import install_systemd
        bridge_home = str(tmp_path / ".claude-bridge-tam")
        service_name = get_service_name(bridge_home)
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / f"{service_name}.service"

        with patch("claude_bridge.daemon._systemd_unit_path", return_value=unit_path), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, _ = install_systemd(
                bot_dir=str(tmp_path / "bot"),
                bridge_home=bridge_home,
                log_path=str(tmp_path / "bridge.log"),
            )

        assert ok is True
        content = unit_path.read_text()
        assert f"-t {service_name}" in content
        assert f"-s {service_name}" in content

    def test_unit_file_uses_claude_command(self, tmp_path):
        """ExecStart invokes claude (not bridge-cli) via tmux."""
        from claude_bridge.daemon import install_systemd
        unit_dir = tmp_path / ".config" / "systemd" / "user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / f"{SYSTEMD_SERVICE_NAME}.service"

        with patch("claude_bridge.daemon._systemd_unit_path", return_value=unit_path), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, _ = install_systemd(
                bot_dir=str(tmp_path / "bot"),
                bridge_home=str(tmp_path / "bridge"),
                log_path=str(tmp_path / "bridge.log"),
            )

        content = unit_path.read_text()
        assert "claude --dangerously-load-development-channels server:bridge" in content
        assert "--dangerously-skip-permissions" in content

    def test_two_instances_have_different_service_names_in_unit(self, tmp_path):
        """Two instances with different CLAUDE_BRIDGE_HOMEs get different service names."""
        from claude_bridge.daemon import install_systemd
        for suffix in ("alice", "bob"):
            bridge_home = str(tmp_path / f".claude-bridge-{suffix}")
            svc = get_service_name(bridge_home)
            unit_dir = tmp_path / ".config" / "systemd" / "user"
            unit_dir.mkdir(parents=True, exist_ok=True)
            unit_path = unit_dir / f"{svc}.service"

            with patch("claude_bridge.daemon._systemd_unit_path", return_value=unit_path), \
                 patch("subprocess.run", return_value=MagicMock(returncode=0)):
                ok, _ = install_systemd(
                    bot_dir=str(tmp_path / f"bot-{suffix}"),
                    bridge_home=bridge_home,
                    log_path=str(tmp_path / "bridge.log"),
                )
            assert ok is True

        alice_unit = (tmp_path / ".config" / "systemd" / "user" / "claude-bridge-alice.service")
        bob_unit = (tmp_path / ".config" / "systemd" / "user" / "claude-bridge-bob.service")
        assert alice_unit.exists()
        assert bob_unit.exists()
        assert alice_unit.read_text() != bob_unit.read_text()


class TestLaunchdInstall:
    def test_creates_plist_file(self, tmp_path):
        """install_launchd() creates the plist at the correct path."""
        from claude_bridge.daemon import install_launchd
        bridge_home = str(tmp_path / "bridge")
        expected_label = get_launchd_label(bridge_home)
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True)
        plist_path = plist_dir / f"{expected_label}.plist"

        with patch("claude_bridge.daemon._launchd_plist_path", return_value=plist_path), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, msg = install_launchd(
                bot_dir=str(tmp_path / "bot"),
                bridge_home=bridge_home,
                log_path=str(tmp_path / "bridge.log"),
            )

        assert ok is True
        assert plist_path.exists()
        content = plist_path.read_text()
        assert "<?xml" in content
        assert expected_label in content

    def test_plist_contains_bridge_home(self, tmp_path):
        """launchd plist includes CLAUDE_BRIDGE_HOME env var."""
        from claude_bridge.daemon import install_launchd
        plist_dir = tmp_path / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True)
        custom_home = str(tmp_path / "custom-bridge")
        plist_path = plist_dir / f"{get_launchd_label(custom_home)}.plist"

        with patch("claude_bridge.daemon._launchd_plist_path", return_value=plist_path), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok, _ = install_launchd(
                bot_dir=str(tmp_path / "bot"),
                bridge_home=custom_home,
                log_path=str(tmp_path / "bridge.log"),
            )

        assert ok is True
        content = plist_path.read_text()
        assert custom_home in content


class TestIsDaemonInstalled:
    def test_false_when_no_file(self, tmp_path):
        """is_daemon_installed() returns False when no service file exists."""
        fake_path = tmp_path / "nonexistent.service"
        with patch("claude_bridge.daemon._systemd_unit_path", return_value=fake_path), \
             patch("claude_bridge.daemon.get_platform", return_value="linux"):
            assert is_daemon_installed() is False

    def test_true_when_file_exists(self, tmp_path):
        """is_daemon_installed() returns True when service file exists."""
        fake_path = tmp_path / "claude-bridge.service"
        fake_path.write_text("[Unit]\n")
        with patch("claude_bridge.daemon._systemd_unit_path", return_value=fake_path), \
             patch("claude_bridge.daemon.get_platform", return_value="linux"):
            assert is_daemon_installed() is True


class TestUnsupportedPlatform:
    def test_install_fails_gracefully(self):
        """install_daemon returns error message on unsupported platforms."""
        with patch("claude_bridge.daemon.get_platform", return_value="other"):
            ok, msg = install_daemon(
                bot_dir="/tmp/bot",
                bridge_home="/tmp/bridge",
                log_path="/tmp/bridge.log",
            )
        assert ok is False
        assert "Unsupported" in msg

    def test_uninstall_fails_gracefully(self):
        """uninstall_daemon returns error message on unsupported platforms."""
        with patch("claude_bridge.daemon.get_platform", return_value="other"):
            ok, msg = uninstall_daemon()
        assert ok is False
        assert "Unsupported" in msg
