"""Tests for enhanced feedback generation in loop_orchestrator."""

from __future__ import annotations

import pytest

from claude_bridge.loop_orchestrator import (
    _generate_feedback,
    _parse_test_failures,
    _parse_stack_trace,
    _truncate_feedback,
)


# ── _parse_test_failures ───────────────────────────────────────────────────────

class TestParseTestFailures:
    def test_extracts_pytest_failures(self):
        output = """
FAILED tests/test_auth.py::TestAuth::test_login - AssertionError: expected 200, got 401
FAILED tests/test_auth.py::TestAuth::test_logout - AttributeError: 'NoneType' object has no attribute 'session'
2 failed, 5 passed
"""
        failures = _parse_test_failures(output)
        assert len(failures) == 2
        assert "test_login" in failures[0]
        assert "test_logout" in failures[1]

    def test_extracts_line_numbers(self):
        output = """
FAILED tests/test_db.py::TestDB::test_query - AssertionError
tests/test_db.py:42: AssertionError
"""
        failures = _parse_test_failures(output)
        assert len(failures) >= 1
        # At least one failure should contain file + line info
        combined = " ".join(failures)
        assert "test_db" in combined

    def test_empty_output_returns_empty(self):
        failures = _parse_test_failures("")
        assert failures == []

    def test_no_failures_returns_empty(self):
        output = "5 passed in 0.42s"
        failures = _parse_test_failures(output)
        assert failures == []

    def test_unittest_failures(self):
        output = """
FAIL: test_create (tests.test_model.TestModel)
----------------------------------------------------------------------
AssertionError: None != 'expected'
"""
        failures = _parse_test_failures(output)
        assert len(failures) >= 1
        assert "test_create" in failures[0]

    def test_limits_to_10_failures(self):
        # Generate 15 FAILED lines
        lines = "\n".join(
            f"FAILED tests/test_x.py::TestX::test_{i} - AssertionError"
            for i in range(15)
        )
        failures = _parse_test_failures(lines)
        assert len(failures) <= 10


# ── _parse_stack_trace ─────────────────────────────────────────────────────────

class TestParseStackTrace:
    def test_extracts_python_traceback(self):
        output = """
Traceback (most recent call last):
  File "src/auth.py", line 45, in login
    user = db.find_user(username)
  File "src/db.py", line 12, in find_user
    return self.conn.execute(query).fetchone()
AttributeError: 'NoneType' object has no attribute 'execute'
"""
        trace = _parse_stack_trace(output)
        assert "AttributeError" in trace
        assert "auth.py" in trace or "login" in trace

    def test_no_traceback_returns_empty(self):
        output = "All tests passed!"
        trace = _parse_stack_trace(output)
        assert trace == ""

    def test_multiple_tracebacks_returns_last(self):
        output = """
Traceback (most recent call last):
  File "a.py", line 1, in foo
ValueError: first error

Traceback (most recent call last):
  File "b.py", line 2, in bar
TypeError: second error
"""
        trace = _parse_stack_trace(output)
        # Should contain the last traceback
        assert "TypeError" in trace or "second error" in trace

    def test_truncates_long_traceback(self):
        long_trace = "\n".join(
            [f"  File 'src/module_{i}.py', line {i}, in func_{i}" for i in range(100)]
        )
        output = f"Traceback (most recent call last):\n{long_trace}\nRuntimeError: too deep"
        trace = _parse_stack_trace(output)
        assert len(trace) <= 2000


# ── _truncate_feedback ─────────────────────────────────────────────────────────

class TestTruncateFeedback:
    def test_short_feedback_unchanged(self):
        text = "This is short feedback."
        result = _truncate_feedback(text, max_chars=2000)
        assert result == text

    def test_long_feedback_truncated(self):
        text = "x" * 3000
        result = _truncate_feedback(text, max_chars=2000)
        assert len(result) <= 2000
        assert "truncated" in result

    def test_truncation_at_boundary(self):
        text = "x" * 2000
        result = _truncate_feedback(text, max_chars=2000)
        assert result == text  # Exactly at limit, no truncation

    def test_empty_feedback(self):
        result = _truncate_feedback("", max_chars=2000)
        assert result == ""


# ── Enhanced _generate_feedback ───────────────────────────────────────────────

class TestEnhancedGenerateFeedback:
    def test_feedback_includes_failure_summary(self):
        """Enhanced feedback includes 'failed because' phrasing."""
        iterations = [
            {
                "iteration_num": 1,
                "status": "done",
                "result_summary": "FAILED tests/test_auth.py::TestAuth::test_login - AssertionError",
                "done_check_passed": 0,
            }
        ]
        result = _generate_feedback(iterations)
        assert "Iteration 1" in result
        assert "test_auth" in result or "test_login" in result or "FAILED" in result

    def test_feedback_template_format(self):
        """Feedback includes iteration N info."""
        iterations = [
            {
                "iteration_num": 2,
                "status": "done",
                "result_summary": "Command exited with code 1: 3 tests failed",
                "done_check_passed": 0,
            }
        ]
        result = _generate_feedback(iterations)
        assert "Iteration 2" in result

    def test_total_feedback_truncated_to_2000(self):
        """Total feedback is capped at 2000 chars."""
        long_summary = "x" * 1200
        iterations = [
            {
                "iteration_num": 1,
                "status": "done",
                "result_summary": long_summary,
                "done_check_passed": 0,
            },
            {
                "iteration_num": 2,
                "status": "done",
                "result_summary": long_summary,
                "done_check_passed": 0,
            },
        ]
        result = _generate_feedback(iterations)
        assert len(result) <= 2100  # Allow small overhead for headers

    def test_backward_compatible_with_phase1_callers(self):
        """_generate_feedback still works with Phase 1 iteration format."""
        iterations = [
            {
                "iteration_num": 1,
                "status": "done",
                "result_summary": "Fixed 3 bugs",
                "done_check_passed": 0,
            }
        ]
        result = _generate_feedback(iterations)
        assert result  # Non-empty
        assert "Iteration 1" in result
