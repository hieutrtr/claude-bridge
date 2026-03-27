"""Tests for Bridge Bot CLAUDE.md generation."""

import os

from claude_bridge.bridge_bot_claude_md import (
    generate_bridge_bot_claude_md,
    write_bridge_bot_claude_md,
)


class TestBridgeBotClaudeMd:
    def test_contains_all_commands(self):
        content = generate_bridge_bot_claude_md()
        commands = [
            "/create-agent", "/delete-agent", "/task", "/agents",
            "/status", "/kill", "/history", "/memory", "/help",
        ]
        for cmd in commands:
            assert cmd in content, f"Missing command: {cmd}"

    def test_contains_cli_invocations(self):
        content = generate_bridge_bot_claude_md()
        assert "python3 -m claude_bridge.cli" in content
        assert "PYTHONPATH=" in content

    def test_contains_natural_language_rules(self):
        content = generate_bridge_bot_claude_md()
        assert "Natural Language" in content
        assert "ask backend" in content.lower() or "ask" in content.lower()

    def test_contains_completion_check(self):
        content = generate_bridge_bot_claude_md()
        assert "claude_bridge.watcher" in content

    def test_contains_rules(self):
        content = generate_bridge_bot_claude_md()
        assert "Relay output verbatim" in content
        assert "Never modify projects directly" in content

    def test_write_to_file(self, tmp_path):
        output = str(tmp_path / "bot" / "CLAUDE.md")
        result = write_bridge_bot_claude_md(output)
        assert os.path.isfile(result)
        with open(result) as f:
            content = f.read()
        assert "Bridge Bot" in content

    def test_no_empty_sections(self):
        content = generate_bridge_bot_claude_md()
        lines = content.split("\n")
        # No two consecutive blank lines (no empty sections)
        for i in range(len(lines) - 2):
            assert not (lines[i].strip() == "" and lines[i+1].strip() == "" and lines[i+2].strip() == ""), \
                f"Empty section near line {i}"
