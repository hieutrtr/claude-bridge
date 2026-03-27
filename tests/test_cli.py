"""Tests for CLI command handlers."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from claude_bridge.cli import cmd_create_agent, cmd_delete_agent, cmd_list_agents, build_parser
from claude_bridge.db import BridgeDB


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BridgeDB(db_path)
    yield database
    database.close()


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Set up isolated environment for CLI tests."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    # Create a fake project directory
    project = tmp_path / "project"
    project.mkdir()

    # Create agents dir
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)

    # Create bridge dir
    bridge_dir = home / ".claude-bridge"
    bridge_dir.mkdir(parents=True)

    return {
        "home": home,
        "project": project,
        "agents_dir": agents_dir,
        "bridge_dir": bridge_dir,
        "db": BridgeDB(str(bridge_dir / "bridge.db")),
    }


class _Args:
    """Simple namespace for argparse-like args."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestCreateAgent:
    @patch("claude_bridge.cli.init_claude_md")
    def test_creates_agent_in_db(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "initialized"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="API dev")

        result = cmd_create_agent(db, args)

        assert result == 0
        agent = db.get_agent("backend")
        assert agent is not None
        assert agent["name"] == "backend"
        assert agent["purpose"] == "API dev"
        assert agent["state"] == "created"

    @patch("claude_bridge.cli.init_claude_md")
    def test_creates_agent_md_file(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "initialized"}
        db = cli_env["db"]
        project_name = cli_env["project"].name
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="API dev")

        cmd_create_agent(db, args)

        agent_file = cli_env["agents_dir"] / f"bridge--backend--{project_name}.md"
        assert agent_file.is_file()

        content = agent_file.read_text()
        assert "isolation: worktree" in content
        assert "memory: project" in content
        assert "on-complete.py" in content
        assert "API dev" in content

    @patch("claude_bridge.cli.init_claude_md")
    def test_creates_workspace(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "initialized"}
        db = cli_env["db"]
        project_name = cli_env["project"].name
        session_id = f"backend--{project_name}"
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="API dev")

        cmd_create_agent(db, args)

        workspace = cli_env["bridge_dir"] / "workspaces" / session_id
        assert workspace.is_dir()
        assert (workspace / "tasks").is_dir()
        assert (workspace / "metadata.json").is_file()

    @patch("claude_bridge.cli.init_claude_md")
    def test_session_id_derived_correctly(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "initialized"}
        db = cli_env["db"]
        project_name = cli_env["project"].name
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="API dev")

        cmd_create_agent(db, args)

        agent = db.get_agent("backend")
        assert agent["session_id"] == f"backend--{project_name}"

    @patch("claude_bridge.cli.init_claude_md")
    def test_duplicate_name_returns_error(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "initialized"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="API dev")

        cmd_create_agent(db, args)
        result = cmd_create_agent(db, args)

        assert result == 1

    def test_invalid_name_returns_error(self, cli_env):
        db = cli_env["db"]
        args = _Args(name="my agent", path=str(cli_env["project"]), purpose="dev")

        result = cmd_create_agent(db, args)
        assert result == 1

    def test_nonexistent_project_returns_error(self, cli_env):
        db = cli_env["db"]
        args = _Args(name="backend", path="/nonexistent/path", purpose="dev")

        result = cmd_create_agent(db, args)
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    def test_claude_md_init_failure_still_creates_agent(self, mock_init, cli_env):
        """Agent should be created even if CLAUDE.md init fails."""
        mock_init.return_value = {"success": False, "error": "claude not found"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="API dev")

        result = cmd_create_agent(db, args)

        assert result == 0  # Still succeeds
        assert db.get_agent("backend") is not None

    @patch("claude_bridge.cli.init_claude_md")
    def test_calls_claude_md_init(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "initialized"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="API dev")

        cmd_create_agent(db, args)

        mock_init.assert_called_once()
        # init_claude_md(project_dir, agent_name, purpose)
        assert mock_init.call_args[0][2] == "API dev"


class TestBuildParser:
    def test_create_agent_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["create-agent", "backend", "/path", "--purpose", "dev"])
        assert args.command == "create-agent"
        assert args.name == "backend"
        assert args.path == "/path"
        assert args.purpose == "dev"

    def test_dispatch_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["dispatch", "backend", "fix the bug"])
        assert args.command == "dispatch"
        assert args.name == "backend"
        assert args.prompt == "fix the bug"

    def test_list_agents_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["list-agents"])
        assert args.command == "list-agents"

    def test_status_without_name(self):
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"
        assert args.name is None

    def test_status_with_name(self):
        parser = build_parser()
        args = parser.parse_args(["status", "backend"])
        assert args.name == "backend"
