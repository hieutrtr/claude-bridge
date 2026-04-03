"""Tests for branching decision logic + agent loop prompt injection + result extraction."""

from __future__ import annotations

import json
import pytest

from claude_bridge.loop_evaluator import DoneCondition, parse_done_condition
from claude_bridge.loop_orchestrator import (
    _should_use_agent_loop,
    _inject_agent_loop_prompt,
    _extract_agent_loop_result,
)


# ── _should_use_agent_loop ─────────────────────────────────────────────────────

class TestShouldUseAgentLoop:
    def test_bridge_override_always_returns_false(self):
        cond = parse_done_condition("command:pytest tests/")
        assert _should_use_agent_loop(
            goal="Fix tests",
            done_condition=cond,
            max_iterations=3,
            loop_type_override="bridge",
            iteration_num=1,
        ) is False

    def test_agent_override_always_returns_true(self):
        cond = parse_done_condition("command:pytest tests/")
        assert _should_use_agent_loop(
            goal="Fix tests",
            done_condition=cond,
            max_iterations=3,
            loop_type_override="agent",
            iteration_num=1,
        ) is True

    def test_manual_condition_always_bridge(self):
        cond = parse_done_condition("manual:check it")
        result = _should_use_agent_loop(
            goal="Fix tests",
            done_condition=cond,
            max_iterations=3,
            loop_type_override=None,
            iteration_num=1,
        )
        assert result is False

    def test_llm_judge_condition_always_bridge(self):
        cond = parse_done_condition("llm_judge:Code is production-ready")
        result = _should_use_agent_loop(
            goal="Write production code",
            done_condition=cond,
            max_iterations=3,
            loop_type_override=None,
            iteration_num=1,
        )
        assert result is False

    def test_many_iterations_uses_bridge(self):
        """max_iterations > 5 forces bridge loop for visibility."""
        cond = parse_done_condition("command:pytest tests/")
        result = _should_use_agent_loop(
            goal="Fix all tests",
            done_condition=cond,
            max_iterations=6,
            loop_type_override=None,
            iteration_num=1,
        )
        assert result is False

    def test_command_few_iterations_uses_agent(self):
        """command type + max_iterations <= 5 → agent loop."""
        cond = parse_done_condition("command:pytest tests/")
        result = _should_use_agent_loop(
            goal="Fix tests",
            done_condition=cond,
            max_iterations=3,
            loop_type_override=None,
            iteration_num=1,
        )
        assert result is True

    def test_file_exists_few_iterations_uses_agent(self):
        """file_exists type + max_iterations <= 5 → agent loop."""
        cond = parse_done_condition("file_exists:output.txt")
        result = _should_use_agent_loop(
            goal="Generate output",
            done_condition=cond,
            max_iterations=5,
            loop_type_override=None,
            iteration_num=1,
        )
        assert result is True

    def test_file_contains_few_iterations_uses_agent(self):
        """file_contains type + max_iterations <= 5 → agent loop."""
        cond = parse_done_condition("file_contains:result.txt:DONE")
        result = _should_use_agent_loop(
            goal="Complete task",
            done_condition=cond,
            max_iterations=4,
            loop_type_override=None,
            iteration_num=1,
        )
        assert result is True

    def test_default_is_bridge(self):
        """Unknown/edge cases default to bridge loop."""
        cond = DoneCondition(type="unknown_type", args=["something"])
        result = _should_use_agent_loop(
            goal="Do something",
            done_condition=cond,
            max_iterations=3,
            loop_type_override=None,
            iteration_num=1,
        )
        assert result is False

    def test_auto_type_resolves_to_bridge_or_agent(self):
        """auto type (None override) follows heuristics, not stuck."""
        cond = parse_done_condition("command:make test")
        result = _should_use_agent_loop(
            goal="Run build",
            done_condition=cond,
            max_iterations=3,
            loop_type_override=None,
            iteration_num=1,
        )
        # Should return bool (not raise)
        assert isinstance(result, bool)


# ── _inject_agent_loop_prompt ──────────────────────────────────────────────────

class TestInjectAgentLoopPrompt:
    def test_includes_original_task(self):
        cond = parse_done_condition("command:pytest tests/")
        prompt = _inject_agent_loop_prompt(
            original_task="Fix the authentication module",
            done_condition=cond,
            max_internal_iterations=3,
        )
        assert "Fix the authentication module" in prompt

    def test_includes_internal_loop_instructions(self):
        cond = parse_done_condition("command:pytest tests/")
        prompt = _inject_agent_loop_prompt(
            original_task="Fix tests",
            done_condition=cond,
            max_internal_iterations=3,
        )
        assert "Internal Loop Instructions" in prompt

    def test_includes_max_iterations(self):
        cond = parse_done_condition("command:pytest tests/")
        prompt = _inject_agent_loop_prompt(
            original_task="Fix tests",
            done_condition=cond,
            max_internal_iterations=5,
        )
        assert "5" in prompt

    def test_includes_done_condition_description(self):
        cond = parse_done_condition("command:pytest tests/")
        prompt = _inject_agent_loop_prompt(
            original_task="Fix tests",
            done_condition=cond,
            max_internal_iterations=3,
        )
        assert "pytest tests/" in prompt

    def test_includes_agent_loop_result_template(self):
        cond = parse_done_condition("command:pytest tests/")
        prompt = _inject_agent_loop_prompt(
            original_task="Fix tests",
            done_condition=cond,
            max_internal_iterations=3,
        )
        assert "AGENT_LOOP_RESULT" in prompt

    def test_includes_attempt_instructions(self):
        cond = parse_done_condition("command:pytest tests/")
        prompt = _inject_agent_loop_prompt(
            original_task="Fix tests",
            done_condition=cond,
            max_internal_iterations=3,
        )
        assert "Attempt" in prompt or "attempt" in prompt

    def test_file_exists_condition(self):
        cond = parse_done_condition("file_exists:output/report.txt")
        prompt = _inject_agent_loop_prompt(
            original_task="Generate report",
            done_condition=cond,
            max_internal_iterations=2,
        )
        assert "output/report.txt" in prompt
        assert "AGENT_LOOP_RESULT" in prompt

    def test_no_user_input_instruction(self):
        """Prompt must instruct agent not to ask for user input."""
        cond = parse_done_condition("command:make test")
        prompt = _inject_agent_loop_prompt(
            original_task="Run make",
            done_condition=cond,
            max_internal_iterations=3,
        )
        lower = prompt.lower()
        assert "do not ask" in lower or "don't ask" in lower or "no user input" in lower


# ── _extract_agent_loop_result ─────────────────────────────────────────────────

class TestExtractAgentLoopResult:
    def test_extract_success_result(self):
        output = """
I've fixed all the failing tests. Here's what I did:
1. Fixed null pointer in auth.py line 45
2. Added missing import in db.py

AGENT_LOOP_RESULT: {"attempts": 2, "status": "success", "final_state": "All 12 tests pass.", "remaining_issues": []}
"""
        result = _extract_agent_loop_result(output)
        assert result is not None
        assert result["status"] == "success"
        assert result["attempts"] == 2
        assert result["final_state"] == "All 12 tests pass."
        assert result["remaining_issues"] == []

    def test_extract_failed_result(self):
        output = """
AGENT_LOOP_RESULT: {"attempts": 3, "status": "failed", "final_state": "Still failing on test_edge_case.", "remaining_issues": ["test_edge_case still fails"]}
"""
        result = _extract_agent_loop_result(output)
        assert result is not None
        assert result["status"] == "failed"
        assert result["attempts"] == 3
        assert len(result["remaining_issues"]) == 1

    def test_returns_none_if_not_found(self):
        output = "I completed the task. Everything looks good."
        result = _extract_agent_loop_result(output)
        assert result is None

    def test_returns_none_for_empty_output(self):
        result = _extract_agent_loop_result("")
        assert result is None

    def test_returns_none_for_malformed_json(self):
        output = 'AGENT_LOOP_RESULT: {attempts: 1, "status": "success"'
        result = _extract_agent_loop_result(output)
        assert result is None

    def test_extracts_from_middle_of_output(self):
        """AGENT_LOOP_RESULT can appear anywhere in output."""
        output = """
Starting iteration 1...
Made changes to auth.py

AGENT_LOOP_RESULT: {"attempts": 1, "status": "success", "final_state": "Done.", "remaining_issues": []}

Some trailing text after the result.
"""
        result = _extract_agent_loop_result(output)
        assert result is not None
        assert result["status"] == "success"

    def test_extracts_multiline_json(self):
        """AGENT_LOOP_RESULT JSON can span multiple lines."""
        output = """
AGENT_LOOP_RESULT: {
  "attempts": 2,
  "status": "success",
  "final_state": "All tests pass.",
  "remaining_issues": []
}
"""
        result = _extract_agent_loop_result(output)
        assert result is not None
        assert result["status"] == "success"

    def test_uses_last_result_if_multiple(self):
        """If AGENT_LOOP_RESULT appears multiple times, use the last one."""
        output = """
AGENT_LOOP_RESULT: {"attempts": 1, "status": "failed", "final_state": "First attempt.", "remaining_issues": ["still failing"]}
More work...
AGENT_LOOP_RESULT: {"attempts": 2, "status": "success", "final_state": "Done!", "remaining_issues": []}
"""
        result = _extract_agent_loop_result(output)
        assert result is not None
        assert result["status"] == "success"
        assert result["attempts"] == 2


# ── Cost limit enforcement ─────────────────────────────────────────────────────

class TestCostLimitEnforcement:
    """Tests for cost limit in loop orchestrator."""

    def test_cost_tracking_import(self):
        """on_task_complete is importable (smoke test)."""
        from claude_bridge.loop_orchestrator import on_task_complete
        assert callable(on_task_complete)

    def test_loop_db_has_max_cost_column(self):
        """loops table should have max_cost_usd column."""
        import sqlite3
        import tempfile
        import os
        from claude_bridge.db import BridgeDB
        with tempfile.TemporaryDirectory() as td:
            db = BridgeDB(os.path.join(td, "test.db"))
            cursor = db.conn.execute("PRAGMA table_info(loops)")
            cols = [row[1] for row in cursor.fetchall()]
            db.close()
        assert "max_cost_usd" in cols, f"loops table columns: {cols}"
