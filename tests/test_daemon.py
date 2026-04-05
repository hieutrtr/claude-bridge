"""Tests for daemon.py — service name derivation and path generation."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_bridge.daemon import (
    get_service_name,
    get_launchd_label,
    _systemd_unit_path,
    _launchd_plist_path,
)


class TestGetServiceName:
    """Derive service name from CLAUDE_BRIDGE_HOME."""

    def test_default_home_returns_claude_bridge(self):
        """~/.claude-bridge → claude-bridge (backward compat)."""
        name = get_service_name("~/.claude-bridge")
        assert name == "claude-bridge"

    def test_alice_suffix_returns_claude_bridge_alice(self):
        """~/.claude-bridge-alice → claude-bridge-alice."""
        name = get_service_name("~/.claude-bridge-alice")
        assert name == "claude-bridge-alice"

    def test_bob_suffix_returns_claude_bridge_bob(self):
        """~/.claude-bridge-bob → claude-bridge-bob."""
        name = get_service_name("~/.claude-bridge-bob")
        assert name == "claude-bridge-bob"

    def test_absolute_path_with_dot_prefix(self, tmp_path):
        """Absolute path like /home/user/.claude-bridge → claude-bridge."""
        home = str(tmp_path / ".claude-bridge")
        name = get_service_name(home)
        assert name == "claude-bridge"

    def test_absolute_path_with_suffix(self, tmp_path):
        """Absolute path like /home/user/.claude-bridge-prod → claude-bridge-prod."""
        home = str(tmp_path / ".claude-bridge-prod")
        name = get_service_name(home)
        assert name == "claude-bridge-prod"

    def test_reads_env_when_no_arg(self):
        """No arg → reads CLAUDE_BRIDGE_HOME from environment."""
        with patch.dict(os.environ, {"CLAUDE_BRIDGE_HOME": "~/.claude-bridge-env"}):
            name = get_service_name()
        assert name == "claude-bridge-env"

    def test_falls_back_to_default_when_no_arg_no_env(self):
        """No arg, no env → falls back to default ~/.claude-bridge → claude-bridge."""
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_BRIDGE_HOME"}
        with patch.dict(os.environ, env, clear=True):
            name = get_service_name()
        assert name == "claude-bridge"

    def test_explicit_arg_overrides_env(self):
        """Explicit bridge_home arg takes precedence over env."""
        with patch.dict(os.environ, {"CLAUDE_BRIDGE_HOME": "~/.claude-bridge-env"}):
            name = get_service_name("~/.claude-bridge-explicit")
        assert name == "claude-bridge-explicit"

    def test_no_dot_prefix_in_name(self):
        """Returned name never starts with a dot."""
        name = get_service_name("~/.claude-bridge-test")
        assert not name.startswith(".")

    def test_path_without_dot_prefix(self, tmp_path):
        """Non-dotted basename like claude-bridge-ci → claude-bridge-ci."""
        home = str(tmp_path / "claude-bridge-ci")
        name = get_service_name(home)
        assert name == "claude-bridge-ci"


class TestGetLaunchdLabel:
    """Derive launchd label from CLAUDE_BRIDGE_HOME."""

    def test_default_returns_ai_claude_bridge(self):
        """~/.claude-bridge → ai.claude-bridge."""
        label = get_launchd_label("~/.claude-bridge")
        assert label == "ai.claude-bridge"

    def test_alice_returns_ai_claude_bridge_alice(self):
        """~/.claude-bridge-alice → ai.claude-bridge-alice."""
        label = get_launchd_label("~/.claude-bridge-alice")
        assert label == "ai.claude-bridge-alice"

    def test_bob_returns_ai_claude_bridge_bob(self):
        """~/.claude-bridge-bob → ai.claude-bridge-bob."""
        label = get_launchd_label("~/.claude-bridge-bob")
        assert label == "ai.claude-bridge-bob"

    def test_reads_env_when_no_arg(self):
        """No arg → reads CLAUDE_BRIDGE_HOME from environment."""
        with patch.dict(os.environ, {"CLAUDE_BRIDGE_HOME": "~/.claude-bridge-env"}):
            label = get_launchd_label()
        assert label == "ai.claude-bridge-env"

    def test_label_always_starts_with_ai_dot(self):
        """Label always starts with 'ai.'."""
        assert get_launchd_label("~/.claude-bridge").startswith("ai.")
        assert get_launchd_label("~/.claude-bridge-x").startswith("ai.")


class TestSystemdUnitPath:
    """_systemd_unit_path uses derived service name."""

    def test_default_path_is_claude_bridge_service(self):
        """Default path ends with claude-bridge.service."""
        p = _systemd_unit_path("~/.claude-bridge")
        assert p.name == "claude-bridge.service"
        assert "systemd/user" in str(p)

    def test_alice_path_ends_with_alice_service(self):
        """Alice instance path ends with claude-bridge-alice.service."""
        p = _systemd_unit_path("~/.claude-bridge-alice")
        assert p.name == "claude-bridge-alice.service"

    def test_bob_path_ends_with_bob_service(self):
        """Bob instance path ends with claude-bridge-bob.service."""
        p = _systemd_unit_path("~/.claude-bridge-bob")
        assert p.name == "claude-bridge-bob.service"

    def test_two_instances_have_different_paths(self):
        """Two different CLAUDE_BRIDGE_HOMEs → two different service file paths."""
        p1 = _systemd_unit_path("~/.claude-bridge-alice")
        p2 = _systemd_unit_path("~/.claude-bridge-bob")
        assert p1 != p2

    def test_reads_env_when_no_arg(self):
        """No arg → reads CLAUDE_BRIDGE_HOME from environment."""
        with patch.dict(os.environ, {"CLAUDE_BRIDGE_HOME": "~/.claude-bridge-env"}):
            p = _systemd_unit_path()
        assert p.name == "claude-bridge-env.service"


class TestLaunchdPlistPath:
    """_launchd_plist_path uses derived label."""

    def test_default_path_is_ai_claude_bridge_plist(self):
        """Default path ends with ai.claude-bridge.plist."""
        p = _launchd_plist_path("~/.claude-bridge")
        assert p.name == "ai.claude-bridge.plist"
        assert "LaunchAgents" in str(p)

    def test_alice_path_ends_with_alice_plist(self):
        """Alice instance path ends with ai.claude-bridge-alice.plist."""
        p = _launchd_plist_path("~/.claude-bridge-alice")
        assert p.name == "ai.claude-bridge-alice.plist"

    def test_two_instances_have_different_paths(self):
        """Two different CLAUDE_BRIDGE_HOMEs → two different plist paths."""
        p1 = _launchd_plist_path("~/.claude-bridge-alice")
        p2 = _launchd_plist_path("~/.claude-bridge-bob")
        assert p1 != p2

    def test_reads_env_when_no_arg(self):
        """No arg → reads CLAUDE_BRIDGE_HOME from environment."""
        with patch.dict(os.environ, {"CLAUDE_BRIDGE_HOME": "~/.claude-bridge-env"}):
            p = _launchd_plist_path()
        assert p.name == "ai.claude-bridge-env.plist"


class TestMultiInstanceUniqueness:
    """End-to-end: two instances must not collide on service names or file paths."""

    def test_alice_and_bob_service_names_differ(self):
        assert get_service_name("~/.claude-bridge-alice") != get_service_name("~/.claude-bridge-bob")

    def test_alice_and_bob_launchd_labels_differ(self):
        assert get_launchd_label("~/.claude-bridge-alice") != get_launchd_label("~/.claude-bridge-bob")

    def test_alice_and_bob_systemd_paths_differ(self):
        assert _systemd_unit_path("~/.claude-bridge-alice") != _systemd_unit_path("~/.claude-bridge-bob")

    def test_alice_and_bob_launchd_paths_differ(self):
        assert _launchd_plist_path("~/.claude-bridge-alice") != _launchd_plist_path("~/.claude-bridge-bob")

    def test_default_vs_custom_differ(self):
        """Default instance and a named instance must not collide."""
        assert get_service_name("~/.claude-bridge") != get_service_name("~/.claude-bridge-alice")
        assert _systemd_unit_path("~/.claude-bridge") != _systemd_unit_path("~/.claude-bridge-alice")
