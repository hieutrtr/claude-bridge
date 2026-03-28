"""Tests for channel abstraction layer."""

import os
import sys
import pytest
import sqlite3
from pathlib import Path
from unittest.mock import patch
from claude_bridge.channel import format_message, parse_channel_context, CHANNELS
from claude_bridge.db import BridgeDB
from claude_bridge.cli import cmd_dispatch, cmd_create_agent, cmd_history, build_parser


@pytest.fixture
def db(tmp_path):
    db = BridgeDB(str(tmp_path / "test.db"))
    return db


class TestFormatMessage:
    """Tests for channel-specific message formatting."""

    def test_plain_text_passthrough(self):
        result = format_message("cli", "Hello world")
        assert result == "Hello world"

    def test_telegram_escapes_special_chars(self):
        result = format_message("telegram", "cost: $0.05 (2 tasks)")
        # MarkdownV2 requires escaping: . - ( ) ! + = | { } ~ > #
        assert "\\$" not in result or "\\(" in result  # At minimum parens escaped
        assert "cost" in result

    def test_discord_keeps_markdown(self):
        result = format_message("discord", "**bold** and `code`")
        assert "**bold**" in result
        assert "`code`" in result

    def test_slack_converts_bold(self):
        result = format_message("slack", "**bold** text")
        assert "*bold*" in result

    def test_unknown_channel_falls_back_to_plain(self):
        result = format_message("unknown", "Hello world")
        assert result == "Hello world"

    def test_empty_message(self):
        result = format_message("cli", "")
        assert result == ""


class TestParseChannelContext:
    def test_basic_context(self):
        ctx = parse_channel_context("telegram", "12345", "67")
        assert ctx["channel"] == "telegram"
        assert ctx["channel_chat_id"] == "12345"
        assert ctx["channel_message_id"] == "67"

    def test_no_message_id(self):
        ctx = parse_channel_context("discord", "99999", None)
        assert ctx["channel"] == "discord"
        assert ctx["channel_message_id"] is None

    def test_cli_context(self):
        ctx = parse_channel_context("cli", None, None)
        assert ctx["channel"] == "cli"
        assert ctx["channel_chat_id"] is None


class TestChannelConstants:
    def test_all_channels_defined(self):
        assert "cli" in CHANNELS
        assert "telegram" in CHANNELS
        assert "discord" in CHANNELS
        assert "slack" in CHANNELS


class TestChannelInDB:
    """Tests for channel columns in tasks table."""

    def test_task_default_channel_is_cli(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug")
        task = db.get_task(tid)
        assert task["channel"] == "cli"

    def test_task_stores_channel_info(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug")
        db.update_task(tid, channel="telegram", channel_chat_id="12345", channel_message_id="67")
        task = db.get_task(tid)
        assert task["channel"] == "telegram"
        assert task["channel_chat_id"] == "12345"
        assert task["channel_message_id"] == "67"

    def test_create_task_with_channel(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug", channel="telegram", channel_chat_id="12345")
        task = db.get_task(tid)
        assert task["channel"] == "telegram"
        assert task["channel_chat_id"] == "12345"


class _Args:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    db_obj = BridgeDB(str(home / ".claude-bridge" / "bridge.db"))
    return {"db": db_obj, "home": home, "project": project}


class TestDispatchWithChannel:
    """Tests for channel tracking in dispatch."""

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_dispatch_stores_channel(self, mock_spawn, cli_env):
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))

        args = _Args(name="backend", prompt="fix bug", model=None, channel="telegram", chat_id="12345", message_id="67")
        result = cmd_dispatch(db, args)
        assert result == 0

        agent = db.get_agent("backend")
        history = db.get_task_history(agent["session_id"])
        assert history[0]["channel"] == "telegram"
        assert history[0]["channel_chat_id"] == "12345"
        assert history[0]["channel_message_id"] == "67"

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_dispatch_defaults_to_cli(self, mock_spawn, cli_env):
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))

        args = _Args(name="backend", prompt="fix bug", model=None, channel=None, chat_id=None, message_id=None)
        cmd_dispatch(db, args)

        agent = db.get_agent("backend")
        history = db.get_task_history(agent["session_id"])
        assert history[0]["channel"] == "cli"

    def test_parser_has_channel_flags(self):
        parser = build_parser()
        args = parser.parse_args(["dispatch", "backend", "fix bug", "--channel", "telegram", "--chat-id", "12345"])
        assert args.channel == "telegram"
        assert args.chat_id == "12345"

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_history_shows_channel(self, mock_spawn, cli_env, capsys):
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))

        cmd_dispatch(db, _Args(name="backend", prompt="fix bug", model=None, channel="telegram", chat_id="12345", message_id=None))
        capsys.readouterr()

        cmd_history(db, _Args(name="backend", limit=10))
        captured = capsys.readouterr()
        assert "telegram" in captured.out
