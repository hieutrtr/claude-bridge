"""Shared pytest configuration and fixtures."""

import pytest


@pytest.fixture(autouse=True)
def isolate_bridge_home(tmp_path, monkeypatch):
    """Prevent tests from writing to real ~/.claude-bridge* directories.

    Sets CLAUDE_BRIDGE_HOME to an isolated tmp_path for every test so that
    get_bridge_home() never resolves to the user's real data directory.
    Tests that need a specific path override this with monkeypatch.setenv().
    Tests that need the env var absent use monkeypatch.delenv().
    """
    safe_home = tmp_path / ".claude-bridge-test"
    safe_home.mkdir()
    monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(safe_home))
