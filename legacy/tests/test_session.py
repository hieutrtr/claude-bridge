"""Tests for session identity derivation, validation, and workspace management."""

import json
import os
import re

from claude_bridge.session import (
    derive_session_id,
    derive_agent_file_name,
    get_instance_prefix,
    validate_agent_name,
    validate_project_dir,
    get_workspace_dir,
    get_tasks_dir,
    get_agent_file_path,
    create_workspace,
    cleanup_workspace,
)


class TestDeriveSessionId:
    def test_basic(self):
        assert derive_session_id("backend", "/projects/my-api") == "backend--my-api"

    def test_nested_path(self):
        assert derive_session_id("frontend", "/Users/me/projects/my-web") == "frontend--my-web"

    def test_trailing_slash(self):
        assert derive_session_id("backend", "/projects/my-api/") == "backend--my-api"


class TestGetInstancePrefix:
    def test_default_home_returns_empty(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        assert get_instance_prefix() == ""

    def test_custom_home_with_bridge_prefix(self, tmp_path, monkeypatch):
        custom = tmp_path / ".claude-bridge-prod"
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        assert get_instance_prefix() == "prod"

    def test_custom_home_staging(self, tmp_path, monkeypatch):
        custom = tmp_path / ".claude-bridge-staging"
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        assert get_instance_prefix() == "staging"

    def test_custom_home_no_bridge_prefix(self, tmp_path, monkeypatch):
        custom = tmp_path / "my-instance"
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        assert get_instance_prefix() == "my-instance"

    def test_custom_home_special_chars_sanitized(self, tmp_path, monkeypatch):
        custom = tmp_path / "my_instance.2"
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        prefix = get_instance_prefix()
        assert re.match(r"^[a-zA-Z0-9-]+$", prefix)

    def test_prefix_max_20_chars(self, tmp_path, monkeypatch):
        custom = tmp_path / ("a" * 30)
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        assert len(get_instance_prefix()) <= 20


class TestDeriveAgentFileName:
    def test_basic_default_home(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        assert derive_agent_file_name("backend--my-api") == "bridge--backend--my-api"

    def test_no_instance_prefix_with_custom_home(self, tmp_path, monkeypatch):
        """derive_agent_file_name never adds instance prefix — isolation is via bot_dir."""
        custom = tmp_path / ".claude-bridge-prod"
        custom.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        assert derive_agent_file_name("backend--my-api") == "bridge--backend--my-api"

    def test_consistent_across_instances(self, tmp_path, monkeypatch):
        """Same session_id produces same file name regardless of CLAUDE_BRIDGE_HOME."""
        prod = tmp_path / ".claude-bridge-prod"
        prod.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(prod))
        name_prod = derive_agent_file_name("backend--api")

        staging = tmp_path / ".claude-bridge-staging"
        staging.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(staging))
        name_staging = derive_agent_file_name("backend--api")

        assert name_prod == name_staging == "bridge--backend--api"


class TestValidateAgentName:
    def test_valid(self):
        assert validate_agent_name("backend") is None
        assert validate_agent_name("my-agent") is None
        assert validate_agent_name("agent1") is None

    def test_empty(self):
        assert validate_agent_name("") is not None

    def test_too_long(self):
        assert validate_agent_name("a" * 31) is not None

    def test_double_dash(self):
        assert validate_agent_name("my--agent") is not None

    def test_invalid_chars(self):
        assert validate_agent_name("my agent") is not None
        assert validate_agent_name("my_agent") is not None


class TestValidateProjectDir:
    def test_existing_dir(self, tmp_path):
        assert validate_project_dir(str(tmp_path)) is None

    def test_missing_dir(self):
        assert validate_project_dir("/nonexistent/path") is not None


class TestPathHelpers:
    def test_get_workspace_dir(self):
        path = get_workspace_dir("backend--my-api")
        assert "workspaces/backend--my-api" in path
        assert path.startswith("/")  # expanded, not ~

    def test_get_tasks_dir(self):
        path = get_tasks_dir("backend--my-api")
        assert path.endswith("workspaces/backend--my-api/tasks")

    def test_get_agent_file_path(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        path = get_agent_file_path("backend--my-api")
        assert "agents/bridge--backend--my-api.md" in path
        assert path.startswith("/")

    def test_get_agent_file_path_with_bot_dir(self, tmp_path):
        """get_agent_file_path uses bot_dir/.claude/agents/ when bot_dir is provided."""
        bot_dir = str(tmp_path / "bridge-bot")
        path = get_agent_file_path("backend--my-api", bot_dir=bot_dir)
        import os
        expected = os.path.join(bot_dir, ".claude", "agents", "bridge--backend--my-api.md")
        assert path == expected


class TestCreateWorkspace:
    def test_creates_directories(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_id = "backend--my-api"
        bridge_dir = tmp_path / ".claude-bridge" / "workspaces" / session_id
        tasks_dir = bridge_dir / "tasks"

        # Monkeypatch the helper to use tmp_path
        monkeypatch.setattr(
            "claude_bridge.session.get_workspace_dir",
            lambda sid: str(tmp_path / ".claude-bridge" / "workspaces" / sid),
        )
        monkeypatch.setattr(
            "claude_bridge.session.get_tasks_dir",
            lambda sid: str(tmp_path / ".claude-bridge" / "workspaces" / sid / "tasks"),
        )

        create_workspace(session_id, "backend", "/projects/api", "API dev")

        assert bridge_dir.is_dir()
        assert tasks_dir.is_dir()

    def test_creates_metadata_json(self, tmp_path, monkeypatch):
        session_id = "backend--my-api"
        workspace = tmp_path / ".claude-bridge" / "workspaces" / session_id

        monkeypatch.setattr(
            "claude_bridge.session.get_workspace_dir",
            lambda sid: str(workspace),
        )
        monkeypatch.setattr(
            "claude_bridge.session.get_tasks_dir",
            lambda sid: str(workspace / "tasks"),
        )

        create_workspace(session_id, "backend", "/projects/api", "API dev")

        metadata_path = workspace / "metadata.json"
        assert metadata_path.is_file()

        with open(metadata_path) as f:
            meta = json.load(f)
        assert meta["agent_name"] == "backend"
        assert meta["project_dir"] == "/projects/api"
        assert meta["session_id"] == session_id
        assert meta["purpose"] == "API dev"
        assert "created_at" in meta

    def test_idempotent(self, tmp_path, monkeypatch):
        session_id = "backend--my-api"
        workspace = tmp_path / "ws" / session_id

        monkeypatch.setattr(
            "claude_bridge.session.get_workspace_dir",
            lambda sid: str(workspace),
        )
        monkeypatch.setattr(
            "claude_bridge.session.get_tasks_dir",
            lambda sid: str(workspace / "tasks"),
        )

        # Calling twice should not error
        create_workspace(session_id, "backend", "/p/api", "dev")
        create_workspace(session_id, "backend", "/p/api", "dev")
        assert workspace.is_dir()


class TestCleanupWorkspace:
    def test_removes_directory(self, tmp_path, monkeypatch):
        session_id = "backend--my-api"
        workspace = tmp_path / "ws" / session_id
        workspace.mkdir(parents=True)
        (workspace / "tasks").mkdir()
        (workspace / "metadata.json").write_text("{}")

        monkeypatch.setattr(
            "claude_bridge.session.get_workspace_dir",
            lambda sid: str(workspace),
        )

        cleanup_workspace(session_id)
        assert not workspace.exists()

    def test_missing_directory_no_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "claude_bridge.session.get_workspace_dir",
            lambda sid: str(tmp_path / "nonexistent"),
        )
        # Should not raise
        cleanup_workspace("nonexistent--session")


class TestPackageImport:
    def test_version_defined(self):
        import claude_bridge
        assert hasattr(claude_bridge, "__version__")
        assert claude_bridge.__version__
