"""Tests for loop_orchestrator — goal loop lifecycle management."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from claude_bridge.db import BridgeDB
from claude_bridge.loop_orchestrator import (
    _build_iteration_prompt,
    _generate_feedback,
    cancel_loop,
    get_loop_status,
    on_task_complete,
    start_loop,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BridgeDB(db_path)
    yield database
    database.close()


@pytest.fixture
def agent(db, tmp_path):
    """Create a test agent and return the agent record dict."""
    project_dir = str(tmp_path / "project")
    import os
    os.makedirs(project_dir, exist_ok=True)
    db.create_agent(
        "backend",
        project_dir,
        "backend--project",
        "/path/to/agent.md",
        "API development",
        model="sonnet",
    )
    return db.get_agent("backend")


def _mock_spawn_task(monkeypatch, pid: int = 12345):
    """Monkeypatch spawn_task to return a fake PID without calling claude."""
    mock = MagicMock(return_value=pid)
    # spawn_task is lazily imported inside _dispatch_iteration from .dispatcher
    monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", mock)
    return mock


def _mock_get_result_file(monkeypatch, path: str = "/tmp/result.json"):
    """Monkeypatch get_result_file."""
    mock = MagicMock(return_value=path)
    monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", mock)
    return mock


# ── _build_iteration_prompt ────────────────────────────────────────────────────

class TestBuildIterationPrompt:
    def test_bridge_first_iteration_no_feedback(self):
        prompt = _build_iteration_prompt(
            goal="Fix all failing tests",
            iteration_num=1,
            feedback="",
            loop_type="bridge",
            done_when="command:pytest tests/",
        )
        assert "Fix all failing tests" in prompt
        # No feedback section for first iteration
        assert "Previous Iteration" not in prompt

    def test_bridge_second_iteration_with_feedback(self):
        prompt = _build_iteration_prompt(
            goal="Fix all failing tests",
            iteration_num=2,
            feedback="Iteration 1: fixed 3 tests",
            loop_type="bridge",
            done_when="command:pytest tests/",
        )
        assert "Fix all failing tests" in prompt
        assert "Iteration 1: fixed 3 tests" in prompt
        assert "iteration 2" in prompt.lower()

    def test_agent_loop_type_includes_instructions(self):
        prompt = _build_iteration_prompt(
            goal="Fix all failing tests",
            iteration_num=1,
            feedback="",
            loop_type="agent",
            done_when="command:pytest tests/",
        )
        assert "Internal Loop Instructions" in prompt
        assert "pytest tests/" in prompt
        assert "AGENT_LOOP_RESULT" in prompt

    def test_agent_loop_type_with_feedback(self):
        prompt = _build_iteration_prompt(
            goal="Fix tests",
            iteration_num=2,
            feedback="Previous attempt failed on auth tests",
            loop_type="agent",
            done_when="command:pytest",
        )
        assert "Previous attempt failed on auth tests" in prompt
        assert "Context from Previous Attempts" in prompt


# ── _generate_feedback ─────────────────────────────────────────────────────────

class TestGenerateFeedback:
    def test_empty_iterations(self):
        result = _generate_feedback([])
        assert result == ""

    def test_single_iteration(self):
        iterations = [
            {
                "iteration_num": 1,
                "status": "done",
                "result_summary": "Fixed 3 bugs",
                "done_check_passed": 0,
            }
        ]
        result = _generate_feedback(iterations)
        assert "Iteration 1" in result
        assert "Fixed 3 bugs" in result
        assert "not met" in result

    def test_takes_last_two_only(self):
        iterations = [
            {"iteration_num": 1, "status": "done", "result_summary": "Iter 1", "done_check_passed": 0},
            {"iteration_num": 2, "status": "done", "result_summary": "Iter 2", "done_check_passed": 0},
            {"iteration_num": 3, "status": "done", "result_summary": "Iter 3", "done_check_passed": 0},
        ]
        result = _generate_feedback(iterations)
        assert "Iter 3" in result
        assert "Iter 2" in result
        assert "Iter 1" not in result  # Only last 2

    def test_done_condition_passed(self):
        iterations = [
            {"iteration_num": 1, "status": "done", "result_summary": "Done!", "done_check_passed": 1},
        ]
        result = _generate_feedback(iterations)
        assert "PASSED" in result

    def test_long_summary_truncated(self):
        long_summary = "x" * 600
        iterations = [
            {"iteration_num": 1, "status": "done", "result_summary": long_summary, "done_check_passed": 0},
        ]
        result = _generate_feedback(iterations)
        assert "truncated" in result
        assert len(result) < len(long_summary) + 200  # Significant truncation


# ── start_loop ─────────────────────────────────────────────────────────────────

class TestStartLoop:
    def test_happy_path(self, db, agent, monkeypatch, tmp_path):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix all tests",
            done_when="command:pytest tests/",
        )
        assert loop_id is not None
        assert "--loop--" in loop_id

        loop = db.get_loop(loop_id)
        assert loop is not None
        assert loop["status"] == "running"
        assert loop["agent"] == "backend"
        assert loop["current_iteration"] == 1

    def test_first_iteration_created(self, db, agent, monkeypatch, tmp_path):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="file_exists:done.txt",
        )

        iterations = db.get_loop_iterations(loop_id)
        assert len(iterations) == 1
        assert iterations[0]["iteration_num"] == 1
        assert iterations[0]["status"] == "running"

    def test_invalid_done_when_raises(self, db, agent, monkeypatch):
        with pytest.raises(ValueError, match="Invalid done_when"):
            start_loop(
                db=db,
                agent="backend",
                project=agent["project_dir"],
                goal="Fix tests",
                done_when="invalid_condition",
            )

    def test_concurrent_loop_rejected(self, db, agent, monkeypatch, tmp_path):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        # Start first loop
        start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )

        # Second loop should be rejected
        with pytest.raises(RuntimeError, match="already has an active loop"):
            start_loop(
                db=db,
                agent="backend",
                project=agent["project_dir"],
                goal="Another goal",
                done_when="command:make test",
            )

    def test_nonexistent_agent_raises(self, db, tmp_path):
        with pytest.raises(RuntimeError, match="not found"):
            start_loop(
                db=db,
                agent="nonexistent",
                project=str(tmp_path),
                goal="Fix tests",
                done_when="command:pytest",
            )

    def test_loop_type_bridge_default(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Goal",
            done_when="command:true",
        )
        loop = db.get_loop(loop_id)
        assert loop["loop_type"] == "bridge"

    def test_loop_type_agent(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Goal",
            done_when="command:true",
            loop_type="agent",
        )
        loop = db.get_loop(loop_id)
        assert loop["loop_type"] == "agent"

    def test_spawn_task_called_once(self, db, agent, monkeypatch):
        mock = _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        mock.assert_called_once()


# ── on_task_complete ───────────────────────────────────────────────────────────

class TestOnTaskComplete:
    def _start_loop_and_get_task_id(self, db, agent, monkeypatch) -> tuple[str, str]:
        """Helper to start a loop and return (loop_id, task_id)."""
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix all tests",
            done_when="command:pytest tests/",
        )
        loop = db.get_loop(loop_id)
        task_id = loop["current_task_id"]
        return loop_id, task_id

    def test_done_condition_met_marks_loop_done(self, db, agent, monkeypatch, tmp_path):
        loop_id, task_id = self._start_loop_and_get_task_id(db, agent, monkeypatch)

        # Make done condition pass
        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(True, "All good")):
            on_task_complete(db, loop_id, task_id, "Tests all pass", cost_usd=0.05)

        loop = db.get_loop(loop_id)
        assert loop["status"] == "done"
        assert loop["finish_reason"] == "done_condition_met"
        assert loop["total_cost_usd"] == pytest.approx(0.05)

    def test_done_condition_not_met_dispatches_next(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
            max_iterations=5,
        )
        loop = db.get_loop(loop_id)
        task_id = loop["current_task_id"]

        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(False, "not yet")):
            on_task_complete(db, loop_id, task_id, "Fixed 1 test", cost_usd=0.02)

        loop = db.get_loop(loop_id)
        assert loop["status"] == "running"
        assert loop["current_iteration"] == 2

    def test_max_iterations_stops_loop(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
            max_iterations=1,
        )
        loop = db.get_loop(loop_id)
        task_id = loop["current_task_id"]

        # current_iteration == max_iterations == 1
        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(False, "not yet")):
            on_task_complete(db, loop_id, task_id, "Fixed some", cost_usd=0.01)

        loop = db.get_loop(loop_id)
        assert loop["status"] == "done"
        assert loop["finish_reason"] == "max_iterations"

    def test_consecutive_failures_stops_loop(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
            max_consecutive_failures=2,
            max_iterations=10,
        )
        loop = db.get_loop(loop_id)
        task_id = loop["current_task_id"]

        # Simulate task_id task as "failed"
        int_task_id = int(task_id)
        db.update_task(int_task_id, status="failed", error_message="some error")

        # First failure
        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(False, "n/a")):
            on_task_complete(db, loop_id, task_id, "", cost_usd=0.0)

        loop = db.get_loop(loop_id)
        assert loop["status"] == "running"
        assert loop["consecutive_failures"] == 1

        # Get new task_id for second iteration
        new_task_id = loop["current_task_id"]
        int_new_task_id = int(new_task_id)
        db.update_task(int_new_task_id, status="failed", error_message="still broken")

        # Second failure — should trigger max_consecutive_failures
        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(False, "n/a")):
            on_task_complete(db, loop_id, new_task_id, "", cost_usd=0.0)

        loop = db.get_loop(loop_id)
        assert loop["status"] == "failed"
        assert loop["finish_reason"] == "max_consecutive_failures"

    def test_cost_accumulates(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
            max_iterations=5,
        )
        loop = db.get_loop(loop_id)
        task_id = loop["current_task_id"]

        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(False, "not yet")):
            on_task_complete(db, loop_id, task_id, "Done iter 1", cost_usd=0.10)

        loop = db.get_loop(loop_id)
        assert loop["total_cost_usd"] == pytest.approx(0.10)

        task_id2 = loop["current_task_id"]
        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(True, "done!")):
            on_task_complete(db, loop_id, task_id2, "All fixed", cost_usd=0.15)

        loop = db.get_loop(loop_id)
        assert loop["total_cost_usd"] == pytest.approx(0.25)

    def test_result_truncated_to_1000_chars(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        loop = db.get_loop(loop_id)
        task_id = loop["current_task_id"]

        long_result = "A" * 2000
        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition", return_value=(True, "done")):
            on_task_complete(db, loop_id, task_id, long_result, cost_usd=0.0)

        iterations = db.get_loop_iterations(loop_id)
        assert len(iterations[0]["result_summary"]) <= 1020  # 1000 + "[...truncated]" padding

    def test_nonexistent_loop_silently_returns(self, db, agent, monkeypatch):
        # Should not raise
        on_task_complete(db, "nonexistent--loop--0", "123", "result", 0.0)

    def test_cancelled_loop_not_advanced(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        loop = db.get_loop(loop_id)
        task_id = loop["current_task_id"]

        # Cancel first
        cancel_loop(db, loop_id)

        # Now complete the task — should be ignored
        with patch("claude_bridge.loop_orchestrator.evaluate_done_condition") as mock_eval:
            on_task_complete(db, loop_id, task_id, "result", 0.0)
            mock_eval.assert_not_called()  # Evaluation skipped for non-running loop

        loop = db.get_loop(loop_id)
        assert loop["status"] == "cancelled"


# ── cancel_loop ────────────────────────────────────────────────────────────────

class TestCancelLoop:
    def test_cancel_running_loop(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        result = cancel_loop(db, loop_id)
        assert result is True

        loop = db.get_loop(loop_id)
        assert loop["status"] == "cancelled"
        assert loop["finish_reason"] == "user_cancelled"
        assert loop["finished_at"] is not None

    def test_cancel_nonexistent_loop(self, db):
        result = cancel_loop(db, "does-not-exist")
        assert result is False

    def test_cancel_already_done_loop(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        # Mark as done
        db.update_loop(loop_id, status="done")

        result = cancel_loop(db, loop_id)
        assert result is False  # Already done, can't cancel


# ── get_loop_status ────────────────────────────────────────────────────────────

class TestGetLoopStatus:
    def test_returns_loop_with_iterations(self, db, agent, monkeypatch):
        _mock_spawn_task(monkeypatch)
        _mock_get_result_file(monkeypatch)

        loop_id = start_loop(
            db=db,
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )

        status = get_loop_status(db, loop_id)
        assert status is not None
        assert status["loop_id"] == loop_id
        assert "iterations" in status
        assert len(status["iterations"]) == 1

    def test_returns_none_for_missing_loop(self, db):
        status = get_loop_status(db, "missing-loop-id")
        assert status is None


# ── DB loop operations ─────────────────────────────────────────────────────────

class TestDBLoopOperations:
    def test_create_and_get_loop(self, db, agent, tmp_path):
        loop_id = db.create_loop(
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        loop = db.get_loop(loop_id)
        assert loop is not None
        assert loop["agent"] == "backend"
        assert loop["status"] == "running"
        assert loop["max_iterations"] == 10

    def test_get_active_loop_for_agent(self, db, agent, tmp_path):
        loop_id = db.create_loop(
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        active = db.get_active_loop_for_agent("backend")
        assert active is not None
        assert active["loop_id"] == loop_id

    def test_no_active_loop_after_done(self, db, agent):
        loop_id = db.create_loop(
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        db.update_loop(loop_id, status="done")
        active = db.get_active_loop_for_agent("backend")
        assert active is None

    def test_get_loop_by_task_id(self, db, agent, tmp_path):
        loop_id = db.create_loop(
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        db.update_loop(loop_id, current_task_id="42")
        loop = db.get_loop_by_task_id("42")
        assert loop is not None
        assert loop["loop_id"] == loop_id

    def test_get_last_n_iterations(self, db, agent, tmp_path):
        loop_id = db.create_loop(
            agent="backend",
            project=agent["project_dir"],
            goal="Fix tests",
            done_when="command:pytest",
        )
        for i in range(1, 6):
            db.create_loop_iteration(loop_id, i, f"prompt {i}")

        last2 = db.get_last_n_iterations(loop_id, 2)
        assert len(last2) == 2
        assert last2[0]["iteration_num"] == 4
        assert last2[1]["iteration_num"] == 5

    def test_update_loop_invalid_column_raises(self, db, agent, tmp_path):
        loop_id = db.create_loop(
            agent="backend",
            project=agent["project_dir"],
            goal="g",
            done_when="command:true",
        )
        with pytest.raises(ValueError, match="invalid column"):
            db.update_loop(loop_id, nonexistent_column="value")

    def test_list_loops(self, db, agent, tmp_path):
        for i in range(3):
            db.create_loop(
                agent="backend",
                project=agent["project_dir"],
                goal=f"Goal {i}",
                done_when="command:true",
            )
        loops = db.list_loops(agent="backend")
        assert len(loops) == 3

    def test_list_loops_no_agent_filter(self, db, agent, tmp_path):
        db.create_loop(
            agent="backend",
            project=agent["project_dir"],
            goal="Goal",
            done_when="command:true",
        )
        loops = db.list_loops()
        assert len(loops) == 1
