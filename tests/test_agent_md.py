"""Tests for agent .md file generation."""

from claude_bridge.agent_md import generate_agent_md


class TestGenerateAgentMd:
    def test_contains_frontmatter(self):
        content = generate_agent_md("backend--api", "backend", "/projects/api", "API dev")
        assert "---" in content
        assert "name: bridge--backend--api" in content
        assert "isolation: worktree" in content
        assert "memory: project" in content

    def test_contains_purpose(self):
        content = generate_agent_md("backend--api", "backend", "/projects/api", "REST endpoints")
        assert "REST endpoints" in content

    def test_contains_stop_hook(self):
        content = generate_agent_md("backend--api", "backend", "/projects/api", "API dev")
        assert "on-complete.py" in content
        assert "--session-id backend--api" in content

    def test_contains_tools(self):
        content = generate_agent_md("backend--api", "backend", "/projects/api", "API dev")
        assert "tools: Read, Edit, Write, Bash, Grep, Glob" in content
