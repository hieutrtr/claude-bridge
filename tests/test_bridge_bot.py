"""Tests for Bridge Bot CLAUDE.md generation."""

from __future__ import annotations

import os

from claude_bridge.bridge_bot_claude_md import (
    generate_bridge_bot_claude_md,
    write_bridge_bot_claude_md,
)


class TestMCPMode:
    def test_contains_bridge_tools(self):
        content = generate_bridge_bot_claude_md(use_mcp=True)
        tools = [
            "bridge_get_messages", "bridge_acknowledge", "bridge_reply",
            "bridge_dispatch", "bridge_status", "bridge_agents",
            "bridge_kill", "bridge_history", "bridge_get_notifications",
            "bridge_create_agent",
        ]
        for tool in tools:
            assert tool in content, f"Missing tool: {tool}"

    def test_contains_core_loop(self):
        content = generate_bridge_bot_claude_md(use_mcp=True)
        assert "bridge_get_messages()" in content
        assert "bridge_acknowledge" in content
        assert "bridge_get_notifications()" in content

    def test_contains_natural_language(self):
        content = generate_bridge_bot_claude_md(use_mcp=True)
        assert "Natural Language" in content

    def test_contains_onboarding(self):
        content = generate_bridge_bot_claude_md(use_mcp=True)
        assert "Onboarding" in content
        assert "bridge_agents()" in content

    def test_contains_error_handling(self):
        content = generate_bridge_bot_claude_md(use_mcp=True)
        assert "Error" in content
        assert "not found" in content

    def test_contains_rules(self):
        content = generate_bridge_bot_claude_md(use_mcp=True)
        assert "Never modify project files" in content
        assert "SHORT" in content

    def test_default_is_mcp_mode(self):
        content = generate_bridge_bot_claude_md()
        assert "bridge_get_messages" in content


class TestShellMode:
    def test_contains_cli_invocations(self):
        content = generate_bridge_bot_claude_md(use_mcp=False)
        assert "python3 -m claude_bridge.cli" in content
        assert "PYTHONPATH=" in content

    def test_contains_commands(self):
        content = generate_bridge_bot_claude_md(use_mcp=False)
        assert "/dispatch" in content
        assert "/agents" in content
        assert "/status" in content

    def test_no_bridge_tools(self):
        content = generate_bridge_bot_claude_md(use_mcp=False)
        assert "bridge_get_messages" not in content


class TestWriteToFile:
    def test_write_mcp_mode(self, tmp_path):
        output = str(tmp_path / "bot" / "CLAUDE.md")
        result = write_bridge_bot_claude_md(output, use_mcp=True)
        assert os.path.isfile(result)
        with open(result) as f:
            content = f.read()
        assert "bridge_get_messages" in content

    def test_write_shell_mode(self, tmp_path):
        output = str(tmp_path / "bot" / "CLAUDE.md")
        result = write_bridge_bot_claude_md(output, use_mcp=False)
        with open(result) as f:
            content = f.read()
        assert "python3 -m claude_bridge.cli" in content
