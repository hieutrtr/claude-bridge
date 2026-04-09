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
    monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(bridge_home))
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


class TestSetupBotGitignore:
    """FIX-03: .mcp.json must be added to .gitignore to prevent token exposure."""

    def _run_setup_bot(self, db, target):
        from claude_bridge.cli import cmd_setup_bot
        import argparse
        args = argparse.Namespace(path=target)
        with patch("claude_bridge.cli._get_bot_token", return_value="test:TOKEN"):
            cmd_setup_bot(db, args)

    def test_gitignore_created_with_mcp_json(self, wizard_env):
        target = str(wizard_env["tmp"] / "botdir")
        os.makedirs(target)
        self._run_setup_bot(wizard_env["db"], target)
        gitignore_path = os.path.join(target, ".gitignore")
        assert os.path.isfile(gitignore_path)
        content = Path(gitignore_path).read_text()
        assert ".mcp.json" in content

    def test_gitignore_appended_if_exists(self, wizard_env):
        target = str(wizard_env["tmp"] / "botdir")
        os.makedirs(target)
        gitignore_path = os.path.join(target, ".gitignore")
        # Pre-existing .gitignore without .mcp.json
        Path(gitignore_path).write_text("*.pyc\n__pycache__/\n")
        self._run_setup_bot(wizard_env["db"], target)
        content = Path(gitignore_path).read_text()
        assert "*.pyc" in content  # original content preserved
        assert ".mcp.json" in content  # entry added

    def test_gitignore_not_duplicated(self, wizard_env):
        target = str(wizard_env["tmp"] / "botdir")
        os.makedirs(target)
        self._run_setup_bot(wizard_env["db"], target)
        # Run again — .mcp.json should not appear twice
        self._run_setup_bot(wizard_env["db"], target)
        content = Path(os.path.join(target, ".gitignore")).read_text()
        assert content.count(".mcp.json") == 1


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


class TestDeployChannelServer:
    """_deploy_channel_server copies bundled server.js to bridge_home/channel/dist/."""

    def test_copies_bundled_when_not_deployed(self, tmp_path):
        """Bundled server exists → copied to bridge_home/channel/dist/server.js."""
        from claude_bridge.cli import _deploy_channel_server

        bundled = tmp_path / "bundled" / "server.js"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("// server")

        bridge_home = str(tmp_path / "bridge")
        with patch("claude_bridge.get_channel_server_path", return_value=str(bundled)):
            result = _deploy_channel_server(bridge_home)

        deployed = tmp_path / "bridge" / "channel" / "dist" / "server.js"
        assert deployed.is_file()
        assert result == str(deployed)

    def test_returns_none_when_bundled_missing(self, tmp_path):
        """Bundled server not found and no default fallback → returns None (no crash)."""
        from claude_bridge.cli import _deploy_channel_server

        bridge_home = str(tmp_path / "bridge")
        # Both bundled and default location are missing
        with patch("claude_bridge.get_channel_server_path", return_value=str(tmp_path / "nonexistent.js")), \
             patch("os.path.expanduser", side_effect=lambda p: p.replace("~", str(tmp_path / "home"))):
            result = _deploy_channel_server(bridge_home)

        assert result is None

    def test_idempotent_when_already_deployed(self, tmp_path):
        """Already deployed → skips copy, returns deployed path."""
        from claude_bridge.cli import _deploy_channel_server

        bundled = tmp_path / "bundled" / "server.js"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("// new version")

        bridge_home = tmp_path / "bridge"
        deployed_dir = bridge_home / "channel" / "dist"
        deployed_dir.mkdir(parents=True)
        deployed = deployed_dir / "server.js"
        deployed.write_text("// already deployed")

        with patch("claude_bridge.get_channel_server_path", return_value=str(bundled)):
            result = _deploy_channel_server(str(bridge_home))

        assert result == str(deployed)
        # Should NOT have overwritten the existing file
        assert deployed.read_text() == "// already deployed"

    def test_creates_nested_dirs(self, tmp_path):
        """Creates bridge_home/channel/dist/ directories if they don't exist."""
        from claude_bridge.cli import _deploy_channel_server

        bundled = tmp_path / "server.js"
        bundled.write_text("// server")

        bridge_home = str(tmp_path / "deep" / "bridge")
        with patch("claude_bridge.get_channel_server_path", return_value=str(bundled)):
            _deploy_channel_server(bridge_home)

        assert (tmp_path / "deep" / "bridge" / "channel" / "dist" / "server.js").is_file()


class TestSetupBotDeploysChannelDist:
    """setup-bot deploys channel dist to CLAUDE_BRIDGE_HOME/channel/dist/ before writing .mcp.json."""

    def _run_setup_bot(self, db, target, bridge_home):
        from claude_bridge.cli import cmd_setup_bot
        import argparse
        args = argparse.Namespace(path=target)
        with patch("claude_bridge.cli._get_bot_token", return_value="test:TOKEN"), \
             patch("claude_bridge.cli.get_bridge_home", return_value=Path(bridge_home)):
            cmd_setup_bot(db, args)

    def test_mcp_json_uses_bridge_home_channel_path_when_deployed(self, tmp_path, monkeypatch):
        """When channel is deployed, .mcp.json points to CLAUDE_BRIDGE_HOME/channel/dist/server.js."""
        bridge_home = tmp_path / ".claude-bridge"
        bridge_home.mkdir()
        bot_dir = str(tmp_path / "bot")
        os.makedirs(bot_dir)
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(bridge_home))

        # Fake a bundled server so it gets deployed
        bundled = tmp_path / "bundled_server.js"
        bundled.write_text("// server")

        db = BridgeDB(str(bridge_home / "bridge.db"))
        with patch("shutil.which", return_value="/usr/bin/bun"), \
             patch("claude_bridge.get_channel_server_path", return_value=str(bundled)), \
             patch("claude_bridge.cli._get_bot_token", return_value="test:TOKEN"):
            from claude_bridge.cli import cmd_setup_bot
            import argparse
            cmd_setup_bot(db, argparse.Namespace(path=bot_dir))
        db.close()

        mcp = json.loads(Path(bot_dir, ".mcp.json").read_text())
        channel_path = mcp["mcpServers"]["bridge"]["args"][1]
        expected = str(bridge_home / "channel" / "dist" / "server.js")
        assert channel_path == expected

    def test_mcp_json_messages_db_path_uses_bridge_home(self, tmp_path, monkeypatch):
        """MESSAGES_DB_PATH in .mcp.json points to CLAUDE_BRIDGE_HOME/messages.db."""
        bridge_home = tmp_path / ".claude-bridge-tam"
        bridge_home.mkdir()
        bot_dir = str(tmp_path / "bot")
        os.makedirs(bot_dir)
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(bridge_home))

        bundled = tmp_path / "server.js"
        bundled.write_text("// server")

        db = BridgeDB(str(bridge_home / "bridge.db"))
        with patch("shutil.which", return_value="/usr/bin/bun"), \
             patch("claude_bridge.get_channel_server_path", return_value=str(bundled)), \
             patch("claude_bridge.cli._get_bot_token", return_value="test:TOKEN"):
            from claude_bridge.cli import cmd_setup_bot
            import argparse
            cmd_setup_bot(db, argparse.Namespace(path=bot_dir))
        db.close()

        mcp = json.loads(Path(bot_dir, ".mcp.json").read_text())
        db_path = mcp["mcpServers"]["bridge"]["env"]["MESSAGES_DB_PATH"]
        assert db_path == str(bridge_home / "messages.db")


class TestDeployChannelServerFallback:
    """_deploy_channel_server falls back to default ~/.claude-bridge for second instances."""

    def test_copies_from_default_when_bundled_missing(self, tmp_path):
        """Bundled missing but default location exists → copies from default."""
        from claude_bridge.cli import _deploy_channel_server

        # Create a server.js in the default location
        default_dir = tmp_path / "home" / ".claude-bridge" / "channel" / "dist"
        default_dir.mkdir(parents=True)
        default_server = default_dir / "server.js"
        default_server.write_text("// from default instance")

        # Second instance bridge home
        second_home = str(tmp_path / ".claude-bridge-tam")

        with patch("claude_bridge.get_channel_server_path", return_value=str(tmp_path / "nonexistent.js")), \
             patch("os.path.expanduser", side_effect=lambda p: p.replace("~", str(tmp_path / "home"))):
            result = _deploy_channel_server(second_home)

        deployed = tmp_path / ".claude-bridge-tam" / "channel" / "dist" / "server.js"
        assert deployed.is_file()
        assert result == str(deployed)
        assert deployed.read_text() == "// from default instance"

    def test_returns_none_when_both_bundled_and_default_missing(self, tmp_path):
        """Both bundled and default missing → returns None."""
        from claude_bridge.cli import _deploy_channel_server

        second_home = str(tmp_path / ".claude-bridge-tam")
        with patch("claude_bridge.get_channel_server_path", return_value=str(tmp_path / "nonexistent.js")), \
             patch("os.path.expanduser", side_effect=lambda p: p.replace("~", str(tmp_path / "home"))):
            result = _deploy_channel_server(second_home)

        assert result is None

    def test_does_not_copy_default_to_itself(self, tmp_path):
        """When bridge_home IS the default location, no self-copy occurs."""
        from claude_bridge.cli import _deploy_channel_server

        home_dir = tmp_path / "home"
        default_dir = home_dir / ".claude-bridge" / "channel" / "dist"
        default_dir.mkdir(parents=True)
        default_server = default_dir / "server.js"
        default_server.write_text("// server")

        default_bridge_home = str(home_dir / ".claude-bridge")

        with patch("claude_bridge.get_channel_server_path", return_value=str(tmp_path / "nonexistent.js")), \
             patch("os.path.expanduser", side_effect=lambda p: p.replace("~", str(home_dir))):
            # Deploy to default location — should find existing and return it without error
            result = _deploy_channel_server(default_bridge_home)

        # Already deployed path returns early (first check)
        assert result == str(default_dir / "server.js")


class TestGenerateMcpJsonFallback:
    """generate_mcp_json uses CLAUDE_BRIDGE_HOME path even when server not yet built."""

    def test_fallback_uses_bridge_home_not_source_ts(self, tmp_path, monkeypatch):
        """When neither deployed nor bundled exists, path is CLAUDE_BRIDGE_HOME/channel/dist/server.js."""
        from claude_bridge.cli import generate_mcp_json

        bridge_home = tmp_path / ".claude-bridge-tam"
        bridge_home.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(bridge_home))

        with patch("shutil.which", return_value="/usr/bin/bun"), \
             patch("claude_bridge.get_channel_server_path", return_value=str(tmp_path / "nonexistent.js")), \
             patch("claude_bridge.cli._get_bot_token", return_value="test:TOKEN"):
            result = generate_mcp_json(mode="channel")

        mcp = json.loads(result)
        channel_path = mcp["mcpServers"]["bridge"]["args"][1]
        expected = str(bridge_home / "channel" / "dist" / "server.js")
        assert channel_path == expected
        assert "server.ts" not in channel_path
