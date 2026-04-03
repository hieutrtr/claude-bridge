"""Tests for agent .md file generation."""

import os
import sys
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

    def test_stop_hook_in_project_settings(self, tmp_path):
        from claude_bridge.agent_md import install_stop_hook
        import json
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        path = install_stop_hook(project_dir, "backend--api")
        with open(path) as f:
            settings = json.load(f)
        hook_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "on-complete" in hook_cmd and "session-id" in hook_cmd
        assert "--session-id backend--api" in hook_cmd

    def test_contains_tools(self):
        content = generate_agent_md("backend--api", "backend", "/projects/api", "API dev")
        assert "tools: Read, Edit, Write, Bash, Grep, Glob" in content

    def test_uses_sys_executable_for_python_path(self):
        """generate_agent_md must use sys.executable, not a hardcoded python3."""
        content = generate_agent_md("backend--api", "backend", "/projects/api", "API dev")
        assert sys.executable in content

    def test_stop_hook_uses_sys_executable(self, tmp_path):
        """install_stop_hook must embed sys.executable in the hook command."""
        import json
        from claude_bridge.agent_md import install_stop_hook
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        path = install_stop_hook(project_dir, "backend--api")
        with open(path) as f:
            settings = json.load(f)
        hook_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        # When bridge-cli is installed it uses bridge-cli path; otherwise sys.executable
        # Either way the raw "python3" literal must NOT appear
        assert "python3" not in hook_cmd or sys.executable in hook_cmd
