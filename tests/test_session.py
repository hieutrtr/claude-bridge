"""Tests for session identity derivation, validation, and workspace management."""

import json
import os

from claude_bridge.session import (
    derive_session_id,
    derive_agent_file_name,
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


class TestDeriveAgentFileName:
    def test_basic(self):
        assert derive_agent_file_name("backend--my-api") == "bridge--backend--my-api"


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

    def test_get_agent_file_path(self):
        path = get_agent_file_path("backend--my-api")
        assert "agents/bridge--backend--my-api.md" in path
        assert path.startswith("/")


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
