"""Tests for on_complete.py — Stop hook handler."""

import json
import os
import sys
from unittest.mock import patch

import pytest

from claude_bridge.db import BridgeDB
from claude_bridge.on_complete import parse_result_file, main


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BridgeDB(db_path)
    yield database
    database.close()


@pytest.fixture
def setup_running_task(db, tmp_path):
    """Create an agent with a running task and result file dir."""
    db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
    tid = db.create_task("backend--api", "fix bug")
    result_file = str(tmp_path / f"task-{tid}-result.json")
    db.update_task(tid, status="running", pid=12345, result_file=result_file)
    db.update_agent_state("backend--api", "running")
    return {"task_id": tid, "result_file": result_file, "session_id": "backend--api"}


class TestParseResultFile:
    def test_valid_json(self, tmp_path):
        f = tmp_path / "result.json"
        f.write_text(json.dumps({"cost_usd": 0.05, "is_error": False, "result": "done"}))
        result = parse_result_file(str(f))
        assert result is not None
        assert result["cost_usd"] == 0.05

    def test_missing_file(self):
        result = parse_result_file("/nonexistent/file.json")
        assert result is None

    def test_empty_file(self, tmp_path):
        f = tmp_path / "result.json"
        f.write_text("")
        result = parse_result_file(str(f))
        assert result is None

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "result.json"
        f.write_text("not json {{{")
        result = parse_result_file(str(f))
        assert result is None


class TestOnCompleteIntegration:
    def test_successful_task(self, db, setup_running_task, tmp_path, monkeypatch):
        info = setup_running_task
        with open(info["result_file"], "w") as f:
            json.dump({
                "type": "result",
                "is_error": False,
                "result": "Added pagination to /users",
                "cost_usd": 0.04,
                "duration_ms": 135000,
                "num_turns": 5,
            }, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", info["session_id"]])
        main(db=db)

        task = db.get_task(info["task_id"])
        assert task["status"] == "done"
        assert task["cost_usd"] == 0.04
        assert task["duration_ms"] == 135000
        assert task["num_turns"] == 5
        assert "pagination" in task["result_summary"]
        assert task["completed_at"] is not None

        agent = db.get_agent("backend")
        assert agent["state"] == "idle"
        assert agent["total_tasks"] == 1

    def test_failed_task(self, db, setup_running_task, tmp_path, monkeypatch):
        info = setup_running_task
        with open(info["result_file"], "w") as f:
            json.dump({
                "type": "result",
                "is_error": True,
                "result": "npm test failed with exit code 1",
                "cost_usd": 0.02,
                "duration_ms": 45000,
                "num_turns": 3,
            }, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", info["session_id"]])
        main(db=db)

        task = db.get_task(info["task_id"])
        assert task["status"] == "failed"
        assert "npm test" in task["error_message"]

        agent = db.get_agent("backend")
        assert agent["state"] == "idle"

    def test_missing_result_file(self, db, setup_running_task, monkeypatch):
        info = setup_running_task

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", info["session_id"]])
        main(db=db)

        task = db.get_task(info["task_id"])
        assert task["status"] in ("done", "failed")

    def test_no_running_task(self, db, monkeypatch):
        """If no running task for session, exit silently."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])
        main(db=db)  # Should not raise

    @patch("claude_bridge.dispatcher.spawn_task", return_value=99999)
    def test_auto_dequeues_next_task(self, mock_spawn, db, setup_running_task, monkeypatch):
        """After task completes, next queued task should auto-dispatch."""
        info = setup_running_task
        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "done", "cost_usd": 0.01, "duration_ms": 5000, "num_turns": 1}, f)

        # Queue a task
        t2 = db.create_task(info["session_id"], "queued task")
        db.update_task(t2, status="queued", position=1)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", info["session_id"]])
        main(db=db)

        # Queued task should now be running
        task2 = db.get_task(t2)
        assert task2["status"] == "running"
        assert task2["pid"] == 99999

        # Agent should still be running (not idle)
        agent = db.get_agent("backend")
        assert agent["state"] == "running"

    def test_no_queue_sets_idle(self, db, setup_running_task, monkeypatch):
        """No queued tasks → agent goes idle."""
        info = setup_running_task
        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "done", "cost_usd": 0.01, "duration_ms": 5000, "num_turns": 1}, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", info["session_id"]])
        main(db=db)

        agent = db.get_agent("backend")
        assert agent["state"] == "idle"

    def test_malformed_json_result(self, db, setup_running_task, monkeypatch):
        info = setup_running_task
        with open(info["result_file"], "w") as f:
            f.write("not valid json {{{")

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", info["session_id"]])
        main(db=db)

        task = db.get_task(info["task_id"])
        assert task["status"] in ("done", "failed")
        assert task["completed_at"] is not None


class TestTeamAggregation:
    """Tests for sub-task completion triggering parent task aggregation."""

    def _setup_team_tasks(self, db, tmp_path):
        """Create lead + member agents, parent team task, and a running sub-task."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "API dev")
        db.create_agent("frontend", "/p/web", "frontend--web", "/b.md", "UI dev")

        # Parent team task (already completed by lead)
        parent_id = db.create_task("backend--api", "build profile", task_type="team")
        db.update_task(parent_id, status="running", pid=111)

        # Sub-task for frontend (running)
        sub_id = db.create_task("frontend--web", "build UI", parent_task_id=parent_id)
        result_file = str(tmp_path / f"task-{sub_id}-result.json")
        db.update_task(sub_id, status="running", pid=222, result_file=result_file)
        db.update_agent_state("frontend--web", "running")

        return {"parent_id": parent_id, "sub_id": sub_id, "result_file": result_file}

    def test_last_subtask_completes_parent(self, db, tmp_path, monkeypatch):
        info = self._setup_team_tasks(db, tmp_path)

        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "UI built", "cost_usd": 0.03, "duration_ms": 60000, "num_turns": 4}, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "frontend--web"])
        main(db=db)

        # Sub-task should be done
        sub = db.get_task(info["sub_id"])
        assert sub["status"] == "done"

        # Parent should be done (all sub-tasks complete)
        parent = db.get_task(info["parent_id"])
        assert parent["status"] == "done"
        assert parent["completed_at"] is not None

    def test_not_last_subtask_leaves_parent_running(self, db, tmp_path, monkeypatch):
        info = self._setup_team_tasks(db, tmp_path)

        # Add another sub-task that's still running
        sub2_id = db.create_task("backend--api", "build API", parent_task_id=info["parent_id"])
        db.update_task(sub2_id, status="running", pid=333)

        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "UI built", "cost_usd": 0.03, "duration_ms": 60000, "num_turns": 4}, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "frontend--web"])
        main(db=db)

        # Parent should still be running
        parent = db.get_task(info["parent_id"])
        assert parent["status"] == "running"

    def test_aggregated_cost(self, db, tmp_path, monkeypatch):
        info = self._setup_team_tasks(db, tmp_path)

        # Complete the parent task's own cost first
        db.update_task(info["parent_id"], cost_usd=0.05)

        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "UI built", "cost_usd": 0.03, "duration_ms": 60000, "num_turns": 4}, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "frontend--web"])
        main(db=db)

        parent = db.get_task(info["parent_id"])
        # Parent cost should include sub-task costs
        assert parent["cost_usd"] >= 0.03  # At least the sub-task cost

    def test_standalone_task_no_aggregation(self, db, setup_running_task, monkeypatch):
        """A task with no parent_task_id should not trigger aggregation."""
        info = setup_running_task
        with open(info["result_file"], "w") as f:
            json.dump({"is_error": False, "result": "done", "cost_usd": 0.01, "duration_ms": 5000, "num_turns": 1}, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", info["session_id"]])
        main(db=db)

        # Should complete normally without errors
        task = db.get_task(info["task_id"])
        assert task["status"] == "done"

    def test_subtask_failed_still_aggregates(self, db, tmp_path, monkeypatch):
        """Even if a sub-task fails, parent should complete when all sub-tasks are done."""
        info = self._setup_team_tasks(db, tmp_path)

        with open(info["result_file"], "w") as f:
            json.dump({"is_error": True, "result": "build failed", "cost_usd": 0.02, "duration_ms": 30000, "num_turns": 2}, f)

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "frontend--web"])
        main(db=db)

        parent = db.get_task(info["parent_id"])
        assert parent["status"] == "done"  # Still done, even though sub-task failed
