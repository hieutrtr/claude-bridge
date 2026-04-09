"""Tests for agent .md file generation."""

import os
import sys
from claude_bridge.agent_md import generate_agent_md, write_agent_md, delete_agent_md


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

    def test_stop_hook_contains_bridge_home(self, tmp_path, monkeypatch):
        """install_stop_hook must include CLAUDE_BRIDGE_HOME in hook command."""
        import json
        from claude_bridge.agent_md import install_stop_hook
        custom_home = str(tmp_path / "custom-bridge-home")
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", custom_home)
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        path = install_stop_hook(project_dir, "backend--api")
        with open(path) as f:
            settings = json.load(f)
        hook_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert f"CLAUDE_BRIDGE_HOME={custom_home}" in hook_cmd

    def test_stop_hook_default_bridge_home(self, tmp_path, monkeypatch):
        """install_stop_hook is backward-compatible when CLAUDE_BRIDGE_HOME is not set."""
        import json
        from claude_bridge.agent_md import install_stop_hook
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        project_dir = str(tmp_path / "project")
        os.makedirs(project_dir)
        path = install_stop_hook(project_dir, "backend--api")
        with open(path) as f:
            settings = json.load(f)
        hook_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        # Default home contains ".claude-bridge"
        assert "CLAUDE_BRIDGE_HOME=" in hook_cmd
        assert ".claude-bridge" in hook_cmd


class TestBotDirAgentMd:
    def test_generate_no_instance_prefix(self, monkeypatch):
        """generate_agent_md always uses plain bridge-- prefix regardless of CLAUDE_BRIDGE_HOME."""
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        content = generate_agent_md("backend--api", "backend", "/projects/api", "API dev")
        assert "name: bridge--backend--api" in content

    def test_generate_no_prefix_with_custom_home(self, tmp_path, monkeypatch):
        """generate_agent_md does not embed instance prefix — isolation is via bot_dir."""
        custom = tmp_path / ".claude-bridge-prod"
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        content = generate_agent_md("backend--api", "backend", "/projects/api", "API dev")
        assert "name: bridge--backend--api" in content
        assert "bridge--prod" not in content

    def test_write_to_bot_dir(self, tmp_path):
        """write_agent_md writes to bot_dir/.claude/agents/ when bot_dir is provided."""
        bot_dir = str(tmp_path / "bridge-bot")
        content = generate_agent_md("backend--api", "backend", "/p/api", "API dev")
        path = write_agent_md("backend--api", content, bot_dir=bot_dir)
        expected = os.path.join(bot_dir, ".claude", "agents", "bridge--backend--api.md")
        assert path == expected
        assert os.path.isfile(path)

    def test_write_fallback_to_global(self, tmp_path, monkeypatch):
        """write_agent_md falls back to ~/.claude/agents/ when no bot_dir."""
        monkeypatch.setenv("HOME", str(tmp_path))
        content = generate_agent_md("backend--api", "backend", "/p/api", "API dev")
        path = write_agent_md("backend--api", content)
        assert path.endswith("bridge--backend--api.md")
        assert ".claude/agents/" in path
        assert os.path.isfile(path)

    def test_delete_from_bot_dir(self, tmp_path):
        """delete_agent_md removes file from bot_dir when provided."""
        bot_dir = str(tmp_path / "bridge-bot")
        content = generate_agent_md("backend--api", "backend", "/p/api", "API dev")
        write_agent_md("backend--api", content, bot_dir=bot_dir)
        assert delete_agent_md("backend--api", bot_dir=bot_dir) is True
        agents_dir = os.path.join(bot_dir, ".claude", "agents")
        assert not os.path.isfile(os.path.join(agents_dir, "bridge--backend--api.md"))

    def test_delete_fallback_to_global(self, tmp_path, monkeypatch):
        """delete_agent_md falls back to ~/.claude/agents/ when file not in bot_dir."""
        monkeypatch.setenv("HOME", str(tmp_path))
        bot_dir = str(tmp_path / "bridge-bot")
        content = generate_agent_md("backend--api", "backend", "/p/api", "API dev")
        # Write to global, not bot_dir
        write_agent_md("backend--api", content)
        # Delete with bot_dir set — should find file in global fallback
        assert delete_agent_md("backend--api", bot_dir=bot_dir) is True

    def test_two_instances_different_bot_dirs(self, tmp_path):
        """Two instances with different bot_dirs create isolated agent files."""
        bot_dir1 = str(tmp_path / "bridge-bot-1")
        bot_dir2 = str(tmp_path / "bridge-bot-2")
        content = generate_agent_md("backend--api", "backend", "/p/api", "API dev")
        path1 = write_agent_md("backend--api", content, bot_dir=bot_dir1)
        path2 = write_agent_md("backend--api", content, bot_dir=bot_dir2)
        assert path1 != path2
        assert os.path.isfile(path1)
        assert os.path.isfile(path2)
