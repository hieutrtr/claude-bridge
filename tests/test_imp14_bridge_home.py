"""Tests for IMP-14: CLAUDE_BRIDGE_HOME env var support."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_bridge import get_bridge_home


class TestGetBridgeHome:
    def test_default_is_dot_claude_bridge(self, tmp_path, monkeypatch):
        """Default path is ~/.claude-bridge when env var not set."""
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        result = get_bridge_home()
        assert result == tmp_path / ".claude-bridge"

    def test_env_var_overrides_home(self, tmp_path, monkeypatch):
        """CLAUDE_BRIDGE_HOME overrides the default."""
        custom = tmp_path / "custom-bridge"
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        result = get_bridge_home()
        assert result == custom

    def test_returns_path_object(self, monkeypatch):
        """get_bridge_home() returns a Path, not a string."""
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        result = get_bridge_home()
        assert isinstance(result, Path)

    def test_env_var_empty_uses_default(self, tmp_path, monkeypatch):
        """Empty CLAUDE_BRIDGE_HOME env var falls back to default."""
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        result = get_bridge_home()
        assert ".claude-bridge" in str(result)


class TestBridgeDBUsesEnvVar:
    def test_custom_home_affects_default_db_path(self, tmp_path, monkeypatch):
        """BridgeDB() without explicit path respects CLAUDE_BRIDGE_HOME."""
        custom_home = tmp_path / "my-bridge"
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom_home))
        from claude_bridge.db import BridgeDB
        db = BridgeDB()
        expected = str(custom_home / "bridge.db")
        assert db.db_path == expected
        db.close()

    def test_explicit_path_ignores_env_var(self, tmp_path, monkeypatch):
        """Explicit db_path argument is always respected."""
        custom_home = tmp_path / "my-bridge"
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom_home))
        explicit = str(tmp_path / "explicit.db")
        from claude_bridge.db import BridgeDB
        db = BridgeDB(explicit)
        assert db.db_path == explicit
        db.close()


class TestSessionWorkspacePath:
    def test_workspace_respects_env_var(self, tmp_path, monkeypatch):
        """Workspace dir is under CLAUDE_BRIDGE_HOME when env var is set."""
        custom_home = tmp_path / "custom"
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom_home))
        from claude_bridge.session import get_workspace_dir
        result = get_workspace_dir("backend--myproject")
        assert str(custom_home) in result
        assert "backend--myproject" in result

    def test_workspace_default_path(self, tmp_path, monkeypatch):
        """Workspace dir defaults to ~/.claude-bridge/workspaces/ when no env var."""
        monkeypatch.delenv("CLAUDE_BRIDGE_HOME", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        from claude_bridge.session import get_workspace_dir
        result = get_workspace_dir("backend--myproject")
        assert ".claude-bridge" in result
        assert "workspaces" in result
        assert "backend--myproject" in result
