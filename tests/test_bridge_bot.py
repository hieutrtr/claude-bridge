"""Tests for Bridge Bot CLAUDE.md generation."""

from __future__ import annotations

import os

from claude_bridge.bridge_bot_claude_md import (
    generate_bridge_bot_claude_md,
    write_bridge_bot_claude_md,
)


class TestChannelMode:
    def test_contains_channel_tag_instructions(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "<channel" in content
        assert 'source="bridge"' in content

    def test_contains_reply_tool(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "reply(chat_id" in content or "reply(" in content

    def test_no_bridge_get_messages(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "bridge_get_messages" not in content

    def test_contains_bridge_dispatch(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "bridge_dispatch" in content

    def test_contains_notifications(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "task_completion" in content

    def test_contains_onboarding(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "Onboarding" in content

    def test_contains_error_handling(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "not found" in content

    def test_contains_rules(self):
        content = generate_bridge_bot_claude_md(mode="channel")
        assert "Never modify project files" in content

    def test_default_is_channel_mode(self):
        content = generate_bridge_bot_claude_md()
        assert "<channel" in content


class TestMCPMode:
    def test_contains_bridge_get_messages(self):
        content = generate_bridge_bot_claude_md(mode="mcp")
        assert "bridge_get_messages" in content
        assert "bridge_acknowledge" in content

    def test_contains_core_loop(self):
        content = generate_bridge_bot_claude_md(mode="mcp")
        assert "bridge_get_notifications()" in content


class TestShellMode:
    def test_contains_cli_invocations(self):
        content = generate_bridge_bot_claude_md(mode="shell")
        assert "python3 -m claude_bridge.cli" in content
        assert "PYTHONPATH=" in content

    def test_no_bridge_tools(self):
        content = generate_bridge_bot_claude_md(mode="shell")
        assert "bridge_get_messages" not in content


class TestWriteToFile:
    def test_write_channel_mode(self, tmp_path):
        output = str(tmp_path / "bot" / "CLAUDE.md")
        result = write_bridge_bot_claude_md(output, mode="channel")
        assert os.path.isfile(result)
        with open(result) as f:
            content = f.read()
        assert "<channel" in content

    def test_write_shell_mode(self, tmp_path):
        output = str(tmp_path / "bot" / "CLAUDE.md")
        result = write_bridge_bot_claude_md(output, mode="shell")
        with open(result) as f:
            content = f.read()
        assert "python3 -m claude_bridge.cli" in content
