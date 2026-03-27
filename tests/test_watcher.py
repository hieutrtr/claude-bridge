"""Tests for watcher.py — fallback PID checker."""

import json
from unittest.mock import patch
from datetime import datetime, timedelta

import pytest

from claude_bridge.db import BridgeDB
from claude_bridge.watcher import watch


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BridgeDB(db_path)
    yield database
    database.close()


@pytest.fixture
def agent_with_running_task(db, tmp_path):
    """Create an agent with a running task."""
    db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
    tid = db.create_task("backend--api", "fix bug")
    result_file = str(tmp_path / f"task-{tid}-result.json")
    db.update_task(
        tid,
        status="running",
        pid=99999,
        result_file=result_file,
        started_at=datetime.now().isoformat(),
    )
    db.update_agent_state("backend--api", "running")
    return {"task_id": tid, "result_file": result_file, "session_id": "backend--api"}


class TestWatcherDeadPid:
    @patch("claude_bridge.watcher.pid_alive", return_value=False)
    def test_dead_pid_with_result_marks_done(self, mock_alive, db, agent_with_running_task):
        """Dead PID + successful result → task done, agent idle."""
        info = agent_with_running_task
        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "done", "cost_usd": 0.03, "duration_ms": 60000, "num_turns": 3}, f)

        watch.__wrapped__(db) if hasattr(watch, '__wrapped__') else _run_watch(db)

        task = db.get_task(info["task_id"])
        assert task["status"] == "done"

        agent = db.get_agent("backend")
        assert agent["state"] == "idle"  # Agent MUST be idle, not "failed"

    @patch("claude_bridge.watcher.pid_alive", return_value=False)
    def test_dead_pid_no_result_marks_failed(self, mock_alive, db, agent_with_running_task):
        """Dead PID + no result file → task failed, agent idle."""
        info = agent_with_running_task
        # Don't write result file

        _run_watch(db)

        task = db.get_task(info["task_id"])
        assert task["status"] == "failed"

        agent = db.get_agent("backend")
        assert agent["state"] == "idle"  # Agent MUST be idle, not "failed"


class TestWatcherTimeout:
    @patch("claude_bridge.watcher.kill_process")
    @patch("claude_bridge.watcher.pid_alive", return_value=True)
    def test_timeout_kills_and_marks(self, mock_alive, mock_kill, db, tmp_path):
        """Running > timeout → kill + mark timeout, agent idle."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "long task")
        # Set started_at to 40 minutes ago
        started = (datetime.now() - timedelta(minutes=40)).isoformat()
        db.update_task(tid, status="running", pid=88888, started_at=started)
        db.update_agent_state("backend--api", "running")

        _run_watch(db, timeout_minutes=30)

        task = db.get_task(tid)
        assert task["status"] == "timeout"

        agent = db.get_agent("backend")
        assert agent["state"] == "idle"  # Agent MUST be idle, not "timeout"

        mock_kill.assert_called_once_with(88888)


class TestWatcherNoOp:
    def test_no_running_tasks(self, db):
        """No running tasks → exits silently."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        _run_watch(db)  # Should not raise


class TestWatcherReporting:
    @patch("claude_bridge.watcher.pid_alive", return_value=False)
    def test_reports_unreported_tasks(self, mock_alive, db, agent_with_running_task, capsys):
        info = agent_with_running_task
        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "fixed it", "cost_usd": 0.01}, f)

        _run_watch(db)

        captured = capsys.readouterr()
        assert "Task #" in captured.out

        # Task should be marked as reported
        unreported = db.get_unreported_tasks()
        assert len(unreported) == 0


def _run_watch(db: BridgeDB, timeout_minutes: int = 30):
    """Run the watch function with an injected db."""
    watch(timeout_minutes=timeout_minutes, db=db)
