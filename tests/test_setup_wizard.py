"""Tests for the setup wizard."""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from claude_bridge.cli import cmd_setup, build_parser
from claude_bridge.db import BridgeDB


@pytest.fixture
def wizard_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bridge_home = home / ".claude-bridge"
    bridge_home.mkdir()
    db = BridgeDB(str(bridge_home / "bridge.db"))
    return {"db": db, "home": home, "bridge_home": bridge_home, "tmp": tmp_path}


class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class TestSetupWizardNonInteractive:
    """Test --no-prompt mode with all flags."""

    def test_creates_config_with_token(self, wizard_env):
        bot_dir = str(wizard_env["tmp"] / "bot")
        args = _Args(
            command="setup",
            token="123:ABC",
            bot_dir=bot_dir,
            no_prompt=True,
        )
        with patch("claude_bridge.cli.cmd_setup_cron", return_value=0):
            result = cmd_setup(wizard_env["db"], args)

        assert result == 0
        config = json.loads((wizard_env["bridge_home"] / "config.json").read_text())
        assert config["telegram_bot_token"] == "123:ABC"

    def test_creates_bot_dir_with_files(self, wizard_env):
        bot_dir = str(wizard_env["tmp"] / "bot")
        args = _Args(
            command="setup",
            token="123:ABC",
            bot_dir=bot_dir,
            no_prompt=True,
        )
        with patch("claude_bridge.cli.cmd_setup_cron", return_value=0):
            cmd_setup(wizard_env["db"], args)

        assert os.path.isfile(os.path.join(bot_dir, "CLAUDE.md"))
        assert os.path.isfile(os.path.join(bot_dir, ".mcp.json"))

    def test_mcp_json_has_token(self, wizard_env):
        bot_dir = str(wizard_env["tmp"] / "bot")
        args = _Args(
            command="setup",
            token="123:ABC",
            bot_dir=bot_dir,
            no_prompt=True,
        )
        with patch("claude_bridge.cli.cmd_setup_cron", return_value=0):
            cmd_setup(wizard_env["db"], args)

        mcp = json.loads(Path(bot_dir, ".mcp.json").read_text())
        assert mcp["mcpServers"]["bridge"]["env"]["TELEGRAM_BOT_TOKEN"] == "123:ABC"

    def test_installs_cron(self, wizard_env):
        bot_dir = str(wizard_env["tmp"] / "bot")
        args = _Args(
            command="setup",
            token="123:ABC",
            bot_dir=bot_dir,
            no_prompt=True,
        )
        with patch("claude_bridge.cli.cmd_setup_cron", return_value=0) as mock_cron:
            cmd_setup(wizard_env["db"], args)
        mock_cron.assert_called_once()

    def test_deploys_channel_server(self, wizard_env):
        bot_dir = str(wizard_env["tmp"] / "bot")
        args = _Args(
            command="setup",
            token="123:ABC",
            bot_dir=bot_dir,
            no_prompt=True,
        )
        with patch("claude_bridge.cli.cmd_setup_cron", return_value=0):
            cmd_setup(wizard_env["db"], args)

        deployed = wizard_env["bridge_home"] / "channel" / "dist" / "server.js"
        # Deployed if bundled server exists in package
        from claude_bridge import get_channel_server_path
        if os.path.isfile(get_channel_server_path()):
            assert deployed.is_file()

    def test_idempotent_reruns(self, wizard_env):
        bot_dir = str(wizard_env["tmp"] / "bot")
        args = _Args(
            command="setup",
            token="123:ABC",
            bot_dir=bot_dir,
            no_prompt=True,
        )
        with patch("claude_bridge.cli.cmd_setup_cron", return_value=0):
            cmd_setup(wizard_env["db"], args)
            # Run again — should not crash
            result = cmd_setup(wizard_env["db"], args)
        assert result == 0


class TestSetupParser:
    def test_parser_has_setup_with_flags(self):
        parser = build_parser()
        args = parser.parse_args([
            "setup", "--token", "123:ABC",
            "--bot-dir", "/tmp/bot",
            "--no-prompt",
        ])
        assert args.command == "setup"
        assert args.token == "123:ABC"
        assert args.bot_dir == "/tmp/bot"
        assert args.no_prompt is True

    def test_parser_setup_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["setup"])
        assert args.command == "setup"
        assert args.token is None
        assert args.bot_dir is None
        assert args.no_prompt is False
