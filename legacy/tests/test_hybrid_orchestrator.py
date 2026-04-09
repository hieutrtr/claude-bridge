"""Tests for hybrid orchestrator: decide_loop_type, format_loop_list, format_loop_history."""

from __future__ import annotations

import pytest

from claude_bridge.loop_orchestrator import (
    decide_loop_type,
    format_loop_list,
    format_loop_history,
)


# ── decide_loop_type ──────────────────────────────────────────────────────────

class TestDecideLoopType:
    """Tests for the public decide_loop_type() function."""

    def test_explicit_bridge_preference(self):
        result = decide_loop_type("fix tests", "command:pytest", user_preference="bridge")
        assert result == "bridge"

    def test_explicit_agent_preference(self):
        result = decide_loop_type("fix tests", "command:pytest", user_preference="agent")
        assert result == "agent"

    def test_auto_preference_command_short_returns_agent(self):
        # command + max_iterations conservative (<=5) → agent
        result = decide_loop_type("fix tests", "command:pytest", user_preference="auto")
        assert result == "agent"

    def test_none_preference_same_as_auto(self):
        # None should behave like auto
        result = decide_loop_type("fix tests", "command:pytest", user_preference=None)
        assert result == "agent"

    def test_manual_condition_returns_bridge(self):
        result = decide_loop_type("review code", "manual:check output", user_preference=None)
        assert result == "bridge"

    def test_llm_judge_condition_returns_bridge(self):
        result = decide_loop_type("refactor auth", "llm_judge:code is clean", user_preference=None)
        assert result == "bridge"

    def test_file_exists_condition_returns_agent(self):
        result = decide_loop_type("generate report", "file_exists:output/report.md", user_preference=None)
        assert result == "agent"

    def test_file_contains_condition_returns_agent(self):
        result = decide_loop_type("write output", "file_contains:out.txt:SUCCESS", user_preference=None)
        assert result == "agent"

    def test_invalid_done_when_returns_bridge(self):
        result = decide_loop_type("goal", "not_valid_condition", user_preference=None)
        assert result == "bridge"

    def test_bridge_override_beats_heuristic(self):
        # Even though command:pytest would normally → agent, bridge override wins
        result = decide_loop_type("fix tests", "command:pytest", user_preference="bridge")
        assert result == "bridge"

    def test_agent_override_beats_manual_condition(self):
        # Even though manual → bridge, agent override wins
        result = decide_loop_type("check code", "manual:check it", user_preference="agent")
        assert result == "agent"

    def test_auto_string_same_as_none(self):
        r_auto = decide_loop_type("fix tests", "command:pytest", user_preference="auto")
        r_none = decide_loop_type("fix tests", "command:pytest", user_preference=None)
        assert r_auto == r_none


# ── format_loop_list ──────────────────────────────────────────────────────────

class TestFormatLoopList:
    """Tests for format_loop_list() display formatter."""

    def _make_loop(self, loop_id, agent, status, current, max_iter, cost, goal):
        return {
            "loop_id": loop_id,
            "agent": agent,
            "status": status,
            "current_iteration": current,
            "max_iterations": max_iter,
            "total_cost_usd": cost,
            "goal": goal,
        }

    def test_empty_list(self):
        result = format_loop_list([])
        assert "No loops" in result

    def test_single_loop(self):
        loop = self._make_loop("42", "backend", "running", 2, 5, 0.021, "Fix all tests")
        result = format_loop_list([loop])
        assert "42" in result
        assert "backend" in result
        assert "running" in result
        assert "2/5" in result
        assert "$0.021" in result
        assert "Fix all tests" in result

    def test_multiple_loops(self):
        loops = [
            self._make_loop("1", "backend", "done", 3, 5, 0.10, "Goal A"),
            self._make_loop("2", "frontend", "running", 1, 10, 0.01, "Goal B"),
        ]
        result = format_loop_list(loops)
        assert "backend" in result
        assert "frontend" in result
        assert "Goal A" in result
        assert "Goal B" in result

    def test_long_goal_truncated(self):
        long_goal = "A" * 100
        loop = self._make_loop("1", "a", "running", 1, 5, 0.0, long_goal)
        result = format_loop_list([loop])
        assert "..." in result

    def test_none_cost_shows_zero(self):
        loop = self._make_loop("1", "a", "running", 1, 5, None, "goal")
        result = format_loop_list([loop])
        assert "$0.000" in result


# ── format_loop_history ───────────────────────────────────────────────────────

class TestFormatLoopHistory:
    """Tests for format_loop_history() iteration history formatter."""

    def _make_loop_with_iters(self, status="done", finish_reason="done_condition_met"):
        return {
            "loop_id": "42",
            "agent": "backend",
            "status": status,
            "goal": "Fix all tests",
            "total_cost_usd": 0.063,
            "finish_reason": finish_reason,
            "iterations": [
                {
                    "iteration_num": 1,
                    "status": "done",
                    "done_check_passed": 0,
                    "cost_usd": 0.021,
                    "duration_ms": 15000,
                    "result_summary": "3 tests still failing",
                    "created_at": "2026-04-03T10:00:00",
                    "finished_at": "2026-04-03T10:00:15",
                },
                {
                    "iteration_num": 2,
                    "status": "done",
                    "done_check_passed": 1,
                    "cost_usd": 0.042,
                    "duration_ms": 30000,
                    "result_summary": "All tests pass",
                    "created_at": "2026-04-03T10:00:20",
                    "finished_at": "2026-04-03T10:00:50",
                },
            ],
        }

    def test_none_loop_returns_not_found(self):
        result = format_loop_history(None)
        assert "not found" in result.lower() or "Loop not found" in result

    def test_empty_loop_dict(self):
        result = format_loop_history({})
        assert "not found" in result.lower() or result  # doesn't crash

    def test_basic_structure(self):
        loop = self._make_loop_with_iters()
        result = format_loop_history(loop)
        assert "42" in result
        assert "backend" in result
        assert "Fix all tests" in result
        assert "$0.063" in result

    def test_shows_iterations(self):
        loop = self._make_loop_with_iters()
        result = format_loop_history(loop)
        assert "[1]" in result
        assert "[2]" in result
        assert "PASS" in result  # iteration 2 passed
        assert "fail" in result  # iteration 1 failed

    def test_shows_finish_reason(self):
        loop = self._make_loop_with_iters()
        result = format_loop_history(loop)
        assert "done_condition_met" in result

    def test_no_iterations(self):
        loop = {
            "loop_id": "1",
            "agent": "a",
            "status": "running",
            "goal": "goal",
            "total_cost_usd": 0.0,
            "finish_reason": None,
            "iterations": [],
        }
        result = format_loop_history(loop)
        assert "No iterations" in result

    def test_long_goal_truncated(self):
        long_goal = "A" * 100
        loop = self._make_loop_with_iters()
        loop["goal"] = long_goal
        result = format_loop_history(loop)
        assert "..." in result

    def test_duration_formatting(self):
        loop = self._make_loop_with_iters()
        result = format_loop_history(loop)
        # duration_ms=15000 → "15s"
        assert "15s" in result

    def test_none_cost_iteration(self):
        loop = self._make_loop_with_iters()
        loop["iterations"][0]["cost_usd"] = None
        result = format_loop_history(loop)
        assert "$0.000" in result

    def test_long_result_summary_truncated(self):
        loop = self._make_loop_with_iters()
        loop["iterations"][0]["result_summary"] = "X" * 200
        result = format_loop_history(loop)
        assert "..." in result


# ── Integration: decide → format pipeline ────────────────────────────────────

class TestHybridOrchestratorIntegration:
    """Integration tests: decide_loop_type feeds into formatting logic."""

    def test_agent_loop_for_simple_command(self):
        """Short command loops should be auto-selected as agent."""
        loop_type = decide_loop_type(
            goal="Fix failing tests",
            done_when="command:pytest tests/",
            user_preference=None,
        )
        assert loop_type == "agent"

    def test_bridge_loop_for_manual(self):
        """Manual approval loops always use bridge."""
        loop_type = decide_loop_type(
            goal="Review and approve code",
            done_when="manual",
            user_preference=None,
        )
        assert loop_type == "bridge"

    def test_bridge_loop_for_llm_judge(self):
        """LLM judge loops always use bridge."""
        loop_type = decide_loop_type(
            goal="Refactor to production quality",
            done_when="llm_judge:Code has full test coverage and error handling",
            user_preference=None,
        )
        assert loop_type == "bridge"

    def test_format_list_after_decide(self):
        """format_loop_list should render correctly regardless of loop_type."""
        loop_type = decide_loop_type("fix tests", "command:pytest", user_preference="auto")
        loops = [
            {
                "loop_id": "10",
                "agent": "backend",
                "status": "running",
                "current_iteration": 1,
                "max_iterations": 5,
                "total_cost_usd": 0.0,
                "goal": "Fix tests",
                "loop_type": loop_type,
            }
        ]
        formatted = format_loop_list(loops)
        assert "backend" in formatted
        assert "running" in formatted
