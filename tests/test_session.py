"""Tests for session identity derivation and validation."""

from claude_bridge.session import (
    derive_session_id,
    derive_agent_file_name,
    validate_agent_name,
    validate_project_dir,
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
