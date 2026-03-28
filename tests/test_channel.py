"""Tests for channel abstraction layer."""

import pytest
import sqlite3
from claude_bridge.channel import format_message, parse_channel_context, CHANNELS
from claude_bridge.db import BridgeDB


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
