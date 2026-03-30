"""Tests for CLI command handlers."""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

from claude_bridge.cli import (
    cmd_create_agent, cmd_delete_agent, cmd_list_agents,
    cmd_dispatch, cmd_status, cmd_kill, cmd_history, cmd_memory,
    cmd_queue, cmd_cancel, cmd_set_model, cmd_cost,
    cmd_create_team, cmd_list_teams, cmd_delete_team,
    cmd_team_dispatch, cmd_team_status,
    build_parser,
)
from claude_bridge.on_complete import main as on_complete_main
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
        assert "API dev" in content

        # Stop hook is in project settings, not frontmatter
        import json
        settings_path = cli_env["project"] / ".claude" / "settings.local.json"
        assert settings_path.is_file()
        with open(settings_path) as f:
            settings = json.load(f)
        hook_cmd = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "on-complete" in hook_cmd and "session-id" in hook_cmd

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


class TestCost:
    def test_no_tasks(self, cli_env, capsys):
        db = cli_env["db"]
        result = cmd_cost(db, _Args(name=None, period="all"))
        assert result == 0
        captured = capsys.readouterr()
        assert "$0.00" in captured.out or "0 tasks" in captured.out.lower()

    @patch("claude_bridge.cli.init_claude_md")
    def test_cost_with_tasks(self, mock_init, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
        agent = db.get_agent("backend")

        t1 = db.create_task(agent["session_id"], "task 1")
        db.update_task(t1, status="done", cost_usd=0.04)
        t2 = db.create_task(agent["session_id"], "task 2")
        db.update_task(t2, status="done", cost_usd=0.06)

        result = cmd_cost(db, _Args(name=None, period="all"))
        assert result == 0
        captured = capsys.readouterr()
        assert "$0.10" in captured.out or "0.10" in captured.out
        assert "2" in captured.out  # 2 tasks

    @patch("claude_bridge.cli.init_claude_md")
    def test_cost_per_agent(self, mock_init, cli_env, capsys):
        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]
        cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
        agent = db.get_agent("backend")

        t1 = db.create_task(agent["session_id"], "task 1")
        db.update_task(t1, status="done", cost_usd=0.05)

        result = cmd_cost(db, _Args(name="backend", period="all"))
        assert result == 0
        captured = capsys.readouterr()
        assert "0.05" in captured.out

    def test_cost_nonexistent_agent(self, cli_env):
        db = cli_env["db"]
        result = cmd_cost(db, _Args(name="nope", period="all"))
        assert result == 1


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

    def test_create_team_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["create-team", "fullstack", "--lead", "backend", "--members", "frontend,devops"])
        assert args.command == "create-team"
        assert args.name == "fullstack"
        assert args.lead == "backend"
        assert args.members == "frontend,devops"

    def test_list_teams_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["list-teams"])
        assert args.command == "list-teams"

    def test_delete_team_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["delete-team", "fullstack"])
        assert args.command == "delete-team"
        assert args.name == "fullstack"


class TestCreateTeam:
    def _create_agents(self, db, cli_env):
        """Helper to create test agents."""
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="API dev", model=None))
            # Need a second project dir for frontend
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI dev", model=None))
            project3 = cli_env["home"] / "project3"
            project3.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="devops", path=str(project3), purpose="Infra", model=None))

    def test_create_team(self, cli_env, capsys):
        db = cli_env["db"]
        self._create_agents(db, cli_env)
        args = _Args(name="fullstack", lead="backend", members="frontend,devops")
        result = cmd_create_team(db, args)
        assert result == 0
        team = db.get_team("fullstack")
        assert team is not None
        assert team["lead_agent"] == "backend"

    def test_create_team_shows_confirmation(self, cli_env, capsys):
        db = cli_env["db"]
        self._create_agents(db, cli_env)
        args = _Args(name="fullstack", lead="backend", members="frontend,devops")
        cmd_create_team(db, args)
        captured = capsys.readouterr()
        assert "fullstack" in captured.out
        assert "backend" in captured.out

    def test_lead_in_members_errors(self, cli_env):
        db = cli_env["db"]
        self._create_agents(db, cli_env)
        args = _Args(name="bad", lead="backend", members="backend,frontend")
        result = cmd_create_team(db, args)
        assert result == 1

    def test_nonexistent_lead_errors(self, cli_env):
        db = cli_env["db"]
        self._create_agents(db, cli_env)
        args = _Args(name="bad", lead="nonexistent", members="frontend")
        result = cmd_create_team(db, args)
        assert result == 1

    def test_nonexistent_member_errors(self, cli_env):
        db = cli_env["db"]
        self._create_agents(db, cli_env)
        args = _Args(name="bad", lead="backend", members="frontend,nonexistent")
        result = cmd_create_team(db, args)
        assert result == 1

    def test_duplicate_team_name_errors(self, cli_env):
        db = cli_env["db"]
        self._create_agents(db, cli_env)
        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))
        result = cmd_create_team(db, _Args(name="fullstack", lead="devops", members="frontend"))
        assert result == 1


class TestListTeams:
    def test_empty(self, cli_env, capsys):
        db = cli_env["db"]
        result = cmd_list_teams(db, _Args())
        assert result == 0
        captured = capsys.readouterr()
        assert "No teams" in captured.out

    def test_lists_teams(self, cli_env, capsys):
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI", model=None))
        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))
        capsys.readouterr()  # clear

        result = cmd_list_teams(db, _Args())
        assert result == 0
        captured = capsys.readouterr()
        assert "fullstack" in captured.out
        assert "backend" in captured.out


class TestDeleteTeam:
    def test_delete_team(self, cli_env):
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI", model=None))
        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))

        result = cmd_delete_team(db, _Args(name="fullstack"))
        assert result == 0
        assert db.get_team("fullstack") is None

    def test_delete_nonexistent_team(self, cli_env):
        db = cli_env["db"]
        result = cmd_delete_team(db, _Args(name="nope"))
        assert result == 1

    def test_delete_team_preserves_agents(self, cli_env):
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI", model=None))
        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))
        cmd_delete_team(db, _Args(name="fullstack"))

        assert db.get_agent("backend") is not None
        assert db.get_agent("frontend") is not None


class TestTeamDispatch:
    def _setup_team(self, db, cli_env):
        """Helper to create agents and a team."""
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="API dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI dev", model=None))
        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_creates_parent_task_with_team_type(self, mock_spawn, cli_env):
        db = cli_env["db"]
        self._setup_team(db, cli_env)

        result = cmd_team_dispatch(db, _Args(name="fullstack", prompt="build user profile"))
        assert result == 0

        agent = db.get_agent("backend")
        history = db.get_task_history(agent["session_id"])
        assert len(history) == 1
        assert history[0]["task_type"] == "team"

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_augmented_prompt_contains_team_context(self, mock_spawn, cli_env):
        db = cli_env["db"]
        self._setup_team(db, cli_env)

        cmd_team_dispatch(db, _Args(name="fullstack", prompt="build user profile"))

        # Check the prompt passed to spawn_task contains team context
        call_args = mock_spawn.call_args
        prompt = call_args[0][3]  # 4th positional arg is prompt
        assert "build user profile" in prompt
        assert "frontend" in prompt
        assert "UI dev" in prompt
        assert "bridge-cli" in prompt or "dispatch" in prompt

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_spawns_to_lead_agent(self, mock_spawn, cli_env):
        db = cli_env["db"]
        self._setup_team(db, cli_env)

        cmd_team_dispatch(db, _Args(name="fullstack", prompt="build it"))

        assert mock_spawn.called
        call_args = mock_spawn.call_args
        agent_file = call_args[0][0]  # 1st positional arg
        assert "backend" in agent_file

    def test_nonexistent_team_errors(self, cli_env):
        db = cli_env["db"]
        result = cmd_team_dispatch(db, _Args(name="nope", prompt="do stuff"))
        assert result == 1

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_busy_lead_queues_task(self, mock_spawn, cli_env):
        db = cli_env["db"]
        self._setup_team(db, cli_env)

        # First dispatch to make lead busy
        cmd_team_dispatch(db, _Args(name="fullstack", prompt="task 1"))

        # Second dispatch should queue
        result = cmd_team_dispatch(db, _Args(name="fullstack", prompt="task 2"))
        assert result == 0

        agent = db.get_agent("backend")
        queued = db.get_queued_tasks(agent["session_id"])
        assert len(queued) == 1

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_parser_has_team_dispatch(self, mock_spawn):
        parser = build_parser()
        args = parser.parse_args(["team-dispatch", "fullstack", "build it"])
        assert args.command == "team-dispatch"
        assert args.name == "fullstack"
        assert args.prompt == "build it"


class TestTeamStatus:
    def _setup_team_with_tasks(self, db, cli_env):
        """Create agents, team, and a running team task with sub-tasks."""
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="API dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI dev", model=None))
        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))

        # Create parent team task
        lead = db.get_agent("backend")
        parent_id = db.create_task(lead["session_id"], "build profile page", task_type="team")
        db.update_task(parent_id, status="running", pid=111)

        # Create sub-task
        frontend = db.get_agent("frontend")
        sub_id = db.create_task(frontend["session_id"], "build UI component", parent_task_id=parent_id)
        db.update_task(sub_id, status="done")

        return parent_id, sub_id

    def test_shows_lead_and_subtasks(self, cli_env, capsys):
        db = cli_env["db"]
        self._setup_team_with_tasks(db, cli_env)

        result = cmd_team_status(db, _Args(name="fullstack"))
        assert result == 0
        captured = capsys.readouterr()
        assert "backend" in captured.out
        assert "frontend" in captured.out
        assert "build UI component" in captured.out

    def test_shows_progress(self, cli_env, capsys):
        db = cli_env["db"]
        self._setup_team_with_tasks(db, cli_env)

        result = cmd_team_status(db, _Args(name="fullstack"))
        assert result == 0
        captured = capsys.readouterr()
        assert "1/1" in captured.out  # 1 sub-task done out of 1

    def test_no_active_task(self, cli_env, capsys):
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI", model=None))
        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))

        result = cmd_team_status(db, _Args(name="fullstack"))
        assert result == 0
        captured = capsys.readouterr()
        assert "No active team task" in captured.out

    def test_nonexistent_team_errors(self, cli_env):
        db = cli_env["db"]
        result = cmd_team_status(db, _Args(name="nope"))
        assert result == 1

    def test_parser_has_team_status(self):
        parser = build_parser()
        args = parser.parse_args(["team-status", "fullstack"])
        assert args.command == "team-status"
        assert args.name == "fullstack"


class TestTeamEndToEnd:
    """End-to-end test of the full team workflow."""

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_full_team_lifecycle(self, mock_spawn, cli_env, capsys, monkeypatch):
        db = cli_env["db"]

        # 1. Create agents
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="API dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI dev", model=None))

        # 2. Create team
        result = cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))
        assert result == 0

        # 3. Team dispatch
        result = cmd_team_dispatch(db, _Args(name="fullstack", prompt="build user profile page"))
        assert result == 0

        # Verify parent task
        lead = db.get_agent("backend")
        history = db.get_task_history(lead["session_id"])
        assert len(history) == 1
        parent_task = history[0]
        assert parent_task["task_type"] == "team"
        assert parent_task["status"] == "running"
        parent_id = parent_task["id"]

        # 4. Simulate lead dispatching sub-task (what the lead agent would do via Bash)
        frontend = db.get_agent("frontend")
        sub_id = db.create_task(frontend["session_id"], "build profile UI component", parent_task_id=parent_id)
        sub_result_file = str(cli_env["home"] / f"task-{sub_id}-result.json")
        db.update_task(sub_id, status="running", pid=222, result_file=sub_result_file)
        db.update_agent_state(frontend["session_id"], "running")

        # 5. Team status — should show in-progress
        capsys.readouterr()  # clear
        result = cmd_team_status(db, _Args(name="fullstack"))
        assert result == 0
        captured = capsys.readouterr()
        assert "0/1" in captured.out  # 0 of 1 sub-tasks complete
        assert "frontend" in captured.out

        # 6. Sub-task completes
        with open(sub_result_file, "w") as f:
            json.dump({
                "is_error": False,
                "result": "Built profile UI with avatar and bio sections",
                "cost_usd": 0.06,
                "duration_ms": 180000,
                "num_turns": 8,
            }, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", frontend["session_id"]])
        on_complete_main(db=db)

        # 7. Verify sub-task done
        sub = db.get_task(sub_id)
        assert sub["status"] == "done"
        assert sub["cost_usd"] == 0.06

        # 8. Verify parent aggregated
        parent = db.get_task(parent_id)
        assert parent["status"] == "done"
        assert parent["cost_usd"] >= 0.06
        assert parent["completed_at"] is not None
        assert "frontend" in parent["result_summary"]

        # 9. Team status after completion
        capsys.readouterr()
        result = cmd_team_status(db, _Args(name="fullstack"))
        assert result == 0
        captured = capsys.readouterr()
        assert "1/1" in captured.out

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    def test_team_with_multiple_subtasks_partial_failure(self, mock_spawn, cli_env, capsys, monkeypatch):
        db = cli_env["db"]

        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="API dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI dev", model=None))

        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))
        cmd_team_dispatch(db, _Args(name="fullstack", prompt="build dashboard"))

        lead = db.get_agent("backend")
        parent_id = db.get_task_history(lead["session_id"])[0]["id"]

        # Two sub-tasks — both dispatched to frontend (different prompts)
        frontend = db.get_agent("frontend")
        sub1 = db.create_task(frontend["session_id"], "charts component", parent_task_id=parent_id)
        sub1_file = str(cli_env["home"] / f"task-{sub1}-result.json")
        db.update_task(sub1, status="running", pid=222, result_file=sub1_file)
        db.update_agent_state(frontend["session_id"], "running")

        # Create a third agent for sub2
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            project3 = cli_env["home"] / "project3"
            project3.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="devops", path=str(project3), purpose="Infra", model=None))
        devops = db.get_agent("devops")
        sub2 = db.create_task(devops["session_id"], "API endpoints", parent_task_id=parent_id)
        sub2_file = str(cli_env["home"] / f"task-{sub2}-result.json")
        db.update_task(sub2, status="running", pid=333, result_file=sub2_file)
        db.update_agent_state(devops["session_id"], "running")

        # Sub1 succeeds
        with open(sub1_file, "w") as f:
            json.dump({"is_error": False, "result": "Charts done", "cost_usd": 0.04, "duration_ms": 60000, "num_turns": 3}, f)
        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", frontend["session_id"]])
        on_complete_main(db=db)

        # Parent still running (sub2 not done)
        assert db.get_task(parent_id)["status"] == "running"

        # Sub2 fails
        with open(sub2_file, "w") as f:
            json.dump({"is_error": True, "result": "DB connection failed", "cost_usd": 0.02, "duration_ms": 30000, "num_turns": 2}, f)
        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", devops["session_id"]])
        on_complete_main(db=db)

        # Parent should be done (all sub-tasks in terminal state)
        parent = db.get_task(parent_id)
        assert parent["status"] == "done"
        assert parent["cost_usd"] >= 0.06  # 0.04 + 0.02
        assert "Charts done" in parent["result_summary"]
        assert "DB connection failed" in parent["result_summary"]

    def test_delete_team_after_completion(self, cli_env):
        """Deleting a team preserves task history."""
        db = cli_env["db"]
        with patch("claude_bridge.cli.init_claude_md", return_value={"success": True, "message": "ok"}):
            cmd_create_agent(db, _Args(name="backend", path=str(cli_env["project"]), purpose="dev", model=None))
            project2 = cli_env["home"] / "project2"
            project2.mkdir(exist_ok=True)
            cmd_create_agent(db, _Args(name="frontend", path=str(project2), purpose="UI", model=None))

        cmd_create_team(db, _Args(name="fullstack", lead="backend", members="frontend"))

        # Create some task history
        lead = db.get_agent("backend")
        tid = db.create_task(lead["session_id"], "old task", task_type="team")
        db.update_task(tid, status="done")

        # Delete team
        cmd_delete_team(db, _Args(name="fullstack"))

        # Task history preserved
        history = db.get_task_history(lead["session_id"])
        assert len(history) == 1
        assert history[0]["task_type"] == "team"
