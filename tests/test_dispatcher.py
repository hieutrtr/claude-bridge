"""Tests for task dispatcher — subprocess spawning and PID management."""

import os
import signal
from unittest.mock import patch, MagicMock, mock_open

import pytest

from claude_bridge.dispatcher import (
    spawn_task,
    get_result_file,
    get_stderr_file,
    pid_alive,
    kill_process,
)


class TestSpawnTask:
    @patch("claude_bridge.dispatcher.subprocess.Popen")
    def test_calls_popen_with_correct_command(self, mock_popen, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "claude_bridge.dispatcher.get_tasks_dir",
            lambda sid: str(tmp_path / "tasks"),
        )
        mock_process = MagicMock()
        mock_process.pid = 42
        mock_popen.return_value = mock_process

        pid = spawn_task(
            "bridge--backend--api",
            "backend--api",
            "/projects/api",
            "fix the bug",
            1,
        )

        assert pid == 42
        mock_popen.assert_called_once()

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "claude"
        assert "--agent" in cmd
        assert "bridge--backend--api" in cmd
        assert "--session-id" in cmd
        assert "backend--api" in cmd
        assert "--output-format" in cmd
        # project dir passed as cwd, not --project-dir
        assert "--project-dir" not in cmd
        assert "json" in cmd
        assert "-p" in cmd
        assert "fix the bug" in cmd

    @patch("claude_bridge.dispatcher.subprocess.Popen")
    def test_detaches_from_parent(self, mock_popen, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "claude_bridge.dispatcher.get_tasks_dir",
            lambda sid: str(tmp_path / "tasks"),
        )
        mock_popen.return_value = MagicMock(pid=1)

        spawn_task("agent", "sid", "/p", "prompt", 1)

        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get("start_new_session") is True

    @patch("claude_bridge.dispatcher.subprocess.Popen")
    def test_creates_tasks_directory(self, mock_popen, tmp_path, monkeypatch):
        tasks_dir = tmp_path / "tasks"
        monkeypatch.setattr(
            "claude_bridge.dispatcher.get_tasks_dir",
            lambda sid: str(tasks_dir),
        )
        mock_popen.return_value = MagicMock(pid=1)

        spawn_task("agent", "sid", "/p", "prompt", 1)

        assert tasks_dir.is_dir()

    @patch("claude_bridge.dispatcher.subprocess.Popen")
    def test_redirects_stdout_to_result_file(self, mock_popen, tmp_path, monkeypatch):
        tasks_dir = tmp_path / "tasks"
        monkeypatch.setattr(
            "claude_bridge.dispatcher.get_tasks_dir",
            lambda sid: str(tasks_dir),
        )
        mock_popen.return_value = MagicMock(pid=1)

        spawn_task("agent", "sid", "/p", "prompt", 42)

        # Verify result file was opened for writing
        call_kwargs = mock_popen.call_args[1]
        stdout_file = call_kwargs["stdout"]
        assert stdout_file.name == str(tasks_dir / "task-42-result.json")


class TestPathHelpers:
    def test_get_result_file(self):
        path = get_result_file("backend--api", 5)
        assert "task-5-result.json" in path
        assert "backend--api" in path

    def test_get_stderr_file(self):
        path = get_stderr_file("backend--api", 5)
        assert "task-5-stderr.log" in path
        assert "backend--api" in path


class TestPidAlive:
    @patch("claude_bridge.dispatcher.os.kill")
    def test_alive(self, mock_kill):
        mock_kill.return_value = None  # No error = alive
        assert pid_alive(123) is True
        mock_kill.assert_called_with(123, 0)

    @patch("claude_bridge.dispatcher.os.kill", side_effect=ProcessLookupError)
    def test_dead(self, mock_kill):
        assert pid_alive(123) is False

    @patch("claude_bridge.dispatcher.os.kill", side_effect=PermissionError)
    def test_permission_error_means_alive(self, mock_kill):
        assert pid_alive(123) is True


class TestKillProcess:
    @patch("claude_bridge.dispatcher.pid_alive", return_value=False)
    @patch("claude_bridge.dispatcher.os.kill")
    def test_sigterm_then_dead(self, mock_kill, mock_alive):
        result = kill_process(999)
        assert result is True
        mock_kill.assert_called_with(999, signal.SIGTERM)

    @patch("claude_bridge.dispatcher.os.kill", side_effect=ProcessLookupError)
    def test_already_dead(self, mock_kill):
        result = kill_process(999)
        assert result is False

    @patch("claude_bridge.dispatcher.pid_alive", return_value=True)
    @patch("claude_bridge.dispatcher.time.sleep")
    @patch("claude_bridge.dispatcher.os.kill")
    def test_sigterm_then_sigkill(self, mock_kill, mock_sleep, mock_alive):
        """If SIGTERM doesn't work after 10 checks, escalate to SIGKILL."""
        result = kill_process(999)
        assert result is True
        # Should have called SIGTERM first, then SIGKILL
        calls = [c[0] for c in mock_kill.call_args_list]
        assert (999, signal.SIGTERM) in calls
        assert (999, signal.SIGKILL) in calls


class TestDispatchCommand:
    @patch("claude_bridge.cli.spawn_task", return_value=12345)
    @patch("claude_bridge.cli.init_claude_md")
    def test_dispatch_creates_task_and_spawns(self, mock_init, mock_spawn, cli_env):
        from claude_bridge.cli import cmd_create_agent, cmd_dispatch

        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]

        # Create agent first
        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        # Dispatch
        args_dispatch = _Args(name="backend", prompt="fix the bug")
        result = cmd_dispatch(db, args_dispatch)

        assert result == 0
        mock_spawn.assert_called_once()
        agent = db.get_agent("backend")
        assert agent["state"] == "running"

    @patch("claude_bridge.cli.init_claude_md")
    def test_dispatch_nonexistent_agent(self, mock_init, cli_env):
        from claude_bridge.cli import cmd_dispatch

        db = cli_env["db"]
        args = _Args(name="nope", prompt="fix")
        result = cmd_dispatch(db, args)
        assert result == 1

    @patch("claude_bridge.cli.spawn_task", return_value=111)
    @patch("claude_bridge.cli.init_claude_md")
    def test_dispatch_busy_agent(self, mock_init, mock_spawn, cli_env):
        from claude_bridge.cli import cmd_create_agent, cmd_dispatch

        mock_init.return_value = {"success": True, "message": "ok"}
        db = cli_env["db"]

        args_create = _Args(name="backend", path=str(cli_env["project"]), purpose="dev")
        cmd_create_agent(db, args_create)

        # First dispatch
        args_dispatch = _Args(name="backend", prompt="task 1")
        cmd_dispatch(db, args_dispatch)

        # Second dispatch should queue (not fail)
        args_dispatch2 = _Args(name="backend", prompt="task 2")
        result = cmd_dispatch(db, args_dispatch2)
        assert result == 0  # Queued successfully


# Reuse _Args and cli_env from test_cli.py
class _Args:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    project = tmp_path / "project"
    project.mkdir()

    (home / ".claude" / "agents").mkdir(parents=True)
    bridge_dir = home / ".claude-bridge"
    bridge_dir.mkdir(parents=True)

    from claude_bridge.db import BridgeDB
    return {
        "home": home,
        "project": project,
        "agents_dir": home / ".claude" / "agents",
        "bridge_dir": bridge_dir,
        "db": BridgeDB(str(bridge_dir / "bridge.db")),
    }
