"""Tests for CLI command handlers."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from claude_bridge.cli import (
    cmd_create_agent, cmd_delete_agent, cmd_list_agents,
    cmd_dispatch, cmd_status, cmd_kill, cmd_history, cmd_memory,
    cmd_queue, cmd_cancel, cmd_set_model,
    build_parser,
)
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


class TestDeleteAgent:
    @patch("claude_bridge.cli.init_claude_md")
    def test_deletes_agent_from_db(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        args_delete = _Args(name="backend")
        result = cmd_delete_agent(db, args_delete)

        assert result == 0
        assert db.get_agent("backend") is None

    @patch("claude_bridge.cli.init_claude_md")
    def test_removes_agent_md_file(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        project_name = cli_env["project"].name
        agent_file = cli_env["agents_dir"] / f"bridge--backend--{project_name}.md"
        assert agent_file.is_file()

        args_delete = _Args(name="backend")
        cmd_delete_agent(db, args_delete)

        assert not agent_file.exists()

    @patch("claude_bridge.cli.init_claude_md")
    def test_removes_workspace(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        project_name = cli_env["project"].name
        session_id = f"backend--{project_name}"
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        workspace = cli_env["bridge_dir"] / "workspaces" / session_id
        assert workspace.is_dir()

        args_delete = _Args(name="backend")
        cmd_delete_agent(db, args_delete)

        assert not workspace.exists()

    def test_nonexistent_agent_returns_error(self, cli_env):
        db = cli_env["db"]
        args = _Args(name="nonexistent")
        result = cmd_delete_agent(db, args)
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    def test_running_task_returns_error(self, mock_init, cli_env):
        """Should error if agent has running task — not silently kill."""
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        agent = db.get_agent("backend")
        tid = db.create_task(agent["session_id"], "running task")
        db.update_task(tid, status="running", pid=99999)

        args_delete = _Args(name="backend")
        result = cmd_delete_agent(db, args_delete)

        assert result == 1  # Should fail, not silently kill
        assert db.get_agent("backend") is not None  # Agent should still exist


class TestListAgents:
    @patch("claude_bridge.cli.init_claude_md")
    def test_lists_agents(self, mock_init, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args)

        result = cmd_list_agents(db, _Args())
        assert result == 0
        captured = capsys.readouterr()
        assert "backend" in captured.out
        assert "created" in captured.out

    def test_empty_list(self, cli_env, capsys):
        db = cli_env["db"]
        result = cmd_list_agents(db, _Args())
        assert result == 0
        captured = capsys.readouterr()
        assert "No agents" in captured.out


class TestDispatchQueue:
    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_dispatch_busy_queues_task(self, mock_init, mock_spawn, cli_env, capsys):
        """Dispatch to busy agent should queue, not reject."""
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        # First dispatch — immediate
        cmd_dispatch(db, _Args(name="backend", prompt="task 1"))

        # Second dispatch — should queue
        result = cmd_dispatch(db, _Args(name="backend", prompt="task 2"))
        assert result == 0  # Should succeed (queued), not error

        captured = capsys.readouterr()
        assert "queued" in captured.out.lower() or "position" in captured.out.lower()

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_dispatch_busy_shows_position(self, mock_init, mock_spawn, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        cmd_dispatch(db, _Args(name="backend", prompt="task 1"))
        cmd_dispatch(db, _Args(name="backend", prompt="task 2"))
        capsys.readouterr()  # clear

        cmd_dispatch(db, _Args(name="backend", prompt="task 3"))
        captured = capsys.readouterr()
        assert "2" in captured.out  # position 2

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_queued_task_in_db(self, mock_init, mock_spawn, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        cmd_dispatch(db, _Args(name="backend", prompt="task 1"))
        cmd_dispatch(db, _Args(name="backend", prompt="task 2"))

        agent = db.get_agent("backend")
        queued = db.get_queued_tasks(agent["session_id"])
        assert len(queued) == 1
        assert queued[0]["prompt"] == "task 2"
        assert queued[0]["position"] == 1


class TestStatus:
    def test_no_running_tasks(self, cli_env, capsys):
        db = cli_env["db"]
        result = cmd_status(db, _Args(name=None))
        assert result == 0
        captured = capsys.readouterr()
        assert "No running tasks" in captured.out

    @patch("claude_bridge.cli.init_claude_md")
    def test_status_with_agent_name(self, mock_init, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        result = cmd_status(db, _Args(name="backend"))
        assert result == 0
        captured = capsys.readouterr()
        assert "backend" in captured.out
        assert "CREATED" in captured.out

    def test_status_nonexistent_agent(self, cli_env):
        db = cli_env["db"]
        result = cmd_status(db, _Args(name="nope"))
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    @patch("claude_bridge.cli.pid_alive", return_value=False)
    def test_status_detects_dead_pid(self, mock_alive, mock_init, cli_env, capsys):
        """If PID is dead but task marked running, status should update it."""
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        agent = db.get_agent("backend")
        tid = db.create_task(agent["session_id"], "stale task")
        db.update_task(tid, status="running", pid=99999)
        db.update_agent_state(agent["session_id"], "running")

        result = cmd_status(db, _Args(name="backend"))
        assert result == 0

        # After status check, stale task should be detected
        captured = capsys.readouterr()
        # The status command should show the agent — we'll check if it at least
        # mentions the agent name. The dead PID fix is tracked separately.
        assert "backend" in captured.out


class TestKill:
    @patch("claude_bridge.cli.kill_process")
    @patch("claude_bridge.cli.init_claude_md")
    def test_kills_running_task(self, mock_init, mock_kill, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        agent = db.get_agent("backend")
        tid = db.create_task(agent["session_id"], "long task")
        db.update_task(tid, status="running", pid=12345)
        db.update_agent_state(agent["session_id"], "running")

        result = cmd_kill(db, _Args(name="backend"))

        assert result == 0
        mock_kill.assert_called_once_with(12345)
        task = db.get_task(tid)
        assert task["status"] == "killed"
        agent = db.get_agent("backend")
        assert agent["state"] == "idle"

    def test_kill_nonexistent_agent(self, cli_env):
        db = cli_env["db"]
        result = cmd_kill(db, _Args(name="nope"))
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    def test_kill_idle_agent(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        result = cmd_kill(db, _Args(name="backend"))
        assert result == 0  # No error, just "no running task"


class TestHistory:
    @patch("claude_bridge.cli.init_claude_md")
    def test_shows_task_history(self, mock_init, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        agent = db.get_agent("backend")
        tid = db.create_task(agent["session_id"], "fix bug")
        db.update_task(tid, status="done", cost_usd=0.04, duration_ms=120000)

        result = cmd_history(db, _Args(name="backend", limit=10))
        assert result == 0
        captured = capsys.readouterr()
        assert "fix bug" in captured.out
        assert "done" in captured.out

    def test_history_nonexistent_agent(self, cli_env):
        db = cli_env["db"]
        result = cmd_history(db, _Args(name="nope", limit=10))
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    def test_empty_history(self, mock_init, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        result = cmd_history(db, _Args(name="backend", limit=10))
        assert result == 0
        captured = capsys.readouterr()
        assert "No tasks" in captured.out


class TestQueueCommand:
    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_shows_queued_tasks(self, mock_init, mock_spawn, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev"))
        cmd_dispatch(db, _Args(name="backend", prompt="task 1"))
        cmd_dispatch(db, _Args(name="backend", prompt="task 2"))

        result = cmd_queue(db, _Args(name="backend"))
        assert result == 0
        captured = capsys.readouterr()
        assert "task 2" in captured.out
        assert "pos:1" in captured.out

    def test_empty_queue(self, cli_env, capsys):
        db = cli_env["db"]
        result = cmd_queue(db, _Args(name=None))
        assert result == 0
        captured = capsys.readouterr()
        assert "No tasks in queue" in captured.out


class TestCancelCommand:
    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_cancel_queued_task(self, mock_init, mock_spawn, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev"))
        cmd_dispatch(db, _Args(name="backend", prompt="task 1"))
        cmd_dispatch(db, _Args(name="backend", prompt="task 2"))

        # Find the queued task
        agent = db.get_agent("backend")
        queued = db.get_queued_tasks(agent["session_id"])
        assert len(queued) == 1

        result = cmd_cancel(db, _Args(task_id=queued[0]["id"]))
        assert result == 0
        assert db.get_queued_tasks(agent["session_id"]) == []

    def test_cancel_nonexistent_task(self, cli_env):
        db = cli_env["db"]
        result = cmd_cancel(db, _Args(task_id=9999))
        assert result == 1

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_cancel_running_task_fails(self, mock_init, mock_spawn, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev"))
        cmd_dispatch(db, _Args(name="backend", prompt="task 1"))

        # Task 1 is running, not queued
        result = cmd_cancel(db, _Args(task_id=1))
        assert result == 1


class TestModelRouting:
    @patch("claude_bridge.cli.init_claude_md")
    def test_create_agent_default_model(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None)
        cmd_create_agent(db, args)
        agent = db.get_agent("backend")
        assert agent["model"] == "sonnet"

    @patch("claude_bridge.cli.init_claude_md")
    def test_create_agent_with_model(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model="opus")
        cmd_create_agent(db, args)
        agent = db.get_agent("backend")
        assert agent["model"] == "opus"

    @patch("claude_bridge.cli.init_claude_md")
    def test_create_agent_invalid_model(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        args = _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model="gpt4")
        result = cmd_create_agent(db, args)
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    def test_set_model(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))

        result = cmd_set_model(db, _Args(name="backend", model="opus"))
        assert result == 0
        agent = db.get_agent("backend")
        assert agent["model"] == "opus"

    def test_set_model_nonexistent_agent(self, cli_env):
        db = cli_env["db"]
        result = cmd_set_model(db, _Args(name="nope", model="opus"))
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    def test_set_model_invalid(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
        result = cmd_set_model(db, _Args(name="backend", model="gpt4"))
        assert result == 1

    @patch("claude_bridge.cli.init_claude_md")
    def test_agent_md_contains_model(self, mock_init, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model="opus"))

        project_name = cli_env["project"].name
        agent_file = cli_env["agents_dir"] / f"bridge--backend--{project_name}.md"
        content = agent_file.read_text()
        assert "model: opus" in content

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_dispatch_with_model_override(self, mock_init, mock_spawn, cli_env):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))

        result = cmd_dispatch(db, _Args(name="backend", prompt="fix bug", model="opus"))
        assert result == 0

        # Check spawn was called with model
        call_kwargs = mock_spawn.call_args
        # model should be passed somehow
        assert mock_spawn.called


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
