"""Tests for telegram_loop.py — notification formatting and approval parsing."""

from __future__ import annotations

import pytest

from claude_bridge.telegram_loop import (
    format_loop_progress,
    format_loop_done,
    format_loop_approval_request,
    format_loop_started,
    parse_approval_reply,
    parse_loop_command,
    _infer_done_when,
    ApprovalAction,
    LoopCommand,
)


# ── format_loop_progress ───────────────────────────────────────────────────────

class TestFormatLoopProgress:
    def test_not_done_includes_iteration_counts(self):
        msg = format_loop_progress(
            loop_id="42",
            agent="backend",
            goal="Fix all failing tests",
            iteration_num=3,
            max_iterations=5,
            result_summary="2 tests still failing",
            done=False,
            cost_usd=0.021,
        )
        assert "3/5" in msg
        assert "2 tests still failing" in msg
        assert "$0.021" in msg

    def test_done_says_goal_achieved(self):
        msg = format_loop_progress(
            loop_id="42",
            agent="backend",
            goal="Fix all failing tests",
            iteration_num=2,
            max_iterations=5,
            result_summary="All tests pass",
            done=True,
            cost_usd=0.05,
        )
        assert "goal achieved" in msg.lower()
        assert "2/5" in msg

    def test_long_goal_truncated(self):
        long_goal = "A" * 100
        msg = format_loop_progress("1", "agent", long_goal, 1, 5, "ok", False)
        assert "..." in msg
        assert len(msg) < 500  # Reasonable max

    def test_long_summary_truncated(self):
        long_summary = "B" * 300
        msg = format_loop_progress("1", "agent", "goal", 1, 5, long_summary, False)
        assert "..." in msg

    def test_zero_cost(self):
        msg = format_loop_progress("1", "agent", "goal", 1, 5, "done", False, cost_usd=0.0)
        assert "$0.000" in msg


# ── format_loop_done ──────────────────────────────────────────────────────────

class TestFormatLoopDone:
    def test_done_condition_met(self):
        msg = format_loop_done(
            loop_id="42",
            agent="backend",
            goal="Fix all tests",
            iterations_completed=3,
            total_cost_usd=0.063,
            duration_ms=272000,
            finish_reason="done_condition_met",
        )
        assert "3 iteration" in msg
        assert "Goal achieved" in msg or "done" in msg.lower()
        assert "$0.063" in msg
        assert "4m 32s" in msg

    def test_max_iterations_reached(self):
        msg = format_loop_done(
            loop_id="42",
            agent="backend",
            goal="Fix all tests",
            iterations_completed=10,
            total_cost_usd=1.23,
            duration_ms=None,
            finish_reason="max_iterations",
        )
        assert "Max iterations" in msg or "stopped" in msg.lower()
        assert "10 iteration" in msg

    def test_cost_limit_exceeded(self):
        msg = format_loop_done(
            loop_id="42",
            agent="backend",
            goal="Fix all tests",
            iterations_completed=5,
            total_cost_usd=2.50,
            duration_ms=None,
            finish_reason="cost_limit_exceeded: $2.50 >= $2.00",
        )
        assert "Cost limit" in msg or "exceeded" in msg.lower()

    def test_manual_approved(self):
        msg = format_loop_done(
            loop_id="1",
            agent="backend",
            goal="Review code",
            iterations_completed=1,
            total_cost_usd=0.01,
            duration_ms=None,
            finish_reason="manual_approved",
        )
        assert "Approved" in msg or "approved" in msg.lower()

    def test_no_duration(self):
        msg = format_loop_done("1", "a", "g", 1, 0.0, None, "done_condition_met")
        # Should not crash, no duration info
        assert "iteration" in msg

    def test_plural_iterations(self):
        msg = format_loop_done("1", "a", "goal", 3, 0.0, None, "done_condition_met")
        assert "iterations" in msg

    def test_singular_iteration(self):
        msg = format_loop_done("1", "a", "goal", 1, 0.0, None, "done_condition_met")
        assert "1 iteration" in msg


# ── format_loop_approval_request ──────────────────────────────────────────────

class TestFormatLoopApprovalRequest:
    def test_contains_approve_reject_instructions(self):
        msg = format_loop_approval_request(
            loop_id="42",
            agent="backend",
            goal="Generate report",
            iteration_num=3,
            result_summary="Report generated at output/report.md",
        )
        assert "approve" in msg.lower()
        assert "reject" in msg.lower()
        assert "42" in msg  # loop_id

    def test_includes_iteration_and_summary(self):
        msg = format_loop_approval_request("1", "a", "goal", 2, "some result")
        assert "iteration 2" in msg.lower() or "2 completed" in msg.lower()
        assert "some result" in msg

    def test_long_summary_truncated(self):
        long_summary = "X" * 400
        msg = format_loop_approval_request("1", "a", "goal", 1, long_summary)
        assert "..." in msg


# ── format_loop_started ───────────────────────────────────────────────────────

class TestFormatLoopStarted:
    def test_basic_format(self):
        msg = format_loop_started(
            loop_id="99",
            agent="backend",
            goal="Fix all tests",
            done_when="command:pytest",
            max_iterations=5,
            loop_type="bridge",
        )
        assert "backend" in msg
        assert "command:pytest" in msg
        assert "5" in msg
        assert "bridge" in msg
        assert "99" in msg


# ── parse_approval_reply ──────────────────────────────────────────────────────

class TestParseApprovalReply:
    def test_approve(self):
        result = parse_approval_reply("approve")
        assert result.action == "approve"
        assert result.feedback == ""
        assert result.loop_id is None

    def test_approve_with_loop_id(self):
        result = parse_approval_reply("approve loop 42")
        assert result.action == "approve"
        assert result.loop_id == "42"

    def test_reject_no_feedback(self):
        result = parse_approval_reply("reject")
        assert result.action == "reject"
        assert result.feedback == ""

    def test_reject_with_feedback_colon(self):
        result = parse_approval_reply("reject: tests are still failing")
        assert result.action == "reject"
        assert "tests are still failing" in result.feedback

    def test_reject_with_feedback_space(self):
        result = parse_approval_reply("reject tests still failing")
        assert result.action == "reject"
        assert "tests still failing" in result.feedback

    def test_deny_synonym(self):
        result = parse_approval_reply("deny")
        assert result.action == "reject"

    def test_deny_with_feedback(self):
        result = parse_approval_reply("deny: not good enough")
        assert result.action == "reject"
        assert "not good enough" in result.feedback

    def test_slash_approve_loop(self):
        result = parse_approval_reply("/approve-loop 42")
        assert result.action == "approve"
        assert result.loop_id == "42"

    def test_slash_deny_loop(self):
        result = parse_approval_reply("/deny-loop 42")
        assert result.action == "reject"
        assert result.loop_id == "42"

    def test_unknown(self):
        result = parse_approval_reply("hello world")
        assert result.action == "unknown"

    def test_empty_string(self):
        result = parse_approval_reply("")
        assert result.action == "unknown"

    def test_case_insensitive_approve(self):
        result = parse_approval_reply("APPROVE")
        assert result.action == "approve"

    def test_case_insensitive_reject(self):
        result = parse_approval_reply("REJECT")
        assert result.action == "reject"


# ── parse_loop_command ────────────────────────────────────────────────────────

class TestParseLoopCommand:
    def test_basic_start(self):
        cmd = parse_loop_command("loop backend fix all tests")
        assert cmd.command == "start"
        assert cmd.agent == "backend"
        assert "fix all tests" in (cmd.goal or "")

    def test_start_with_until_done_when(self):
        cmd = parse_loop_command("loop vn-trader generate brief until file output/brief.md exists")
        assert cmd.command == "start"
        assert cmd.agent == "vn-trader"
        assert cmd.done_when is not None
        assert "file_exists" in (cmd.done_when or "")
        assert "output/brief.md" in (cmd.done_when or "")

    def test_start_with_max(self):
        cmd = parse_loop_command("loop backend fix tests until pytest passes max 3")
        assert cmd.command == "start"
        assert cmd.max_iterations == 3

    def test_start_with_pytest_until(self):
        cmd = parse_loop_command("loop backend fix tests until pytest passes")
        assert cmd.command == "start"
        assert cmd.done_when is not None
        assert "command:pytest" in (cmd.done_when or "")

    def test_stop_loop(self):
        cmd = parse_loop_command("stop loop 42")
        assert cmd.command == "stop"
        assert cmd.loop_id == "42"

    def test_cancel_loop(self):
        cmd = parse_loop_command("cancel loop 99")
        assert cmd.command == "stop"
        assert cmd.loop_id == "99"

    def test_loop_status(self):
        cmd = parse_loop_command("loop status")
        assert cmd.command == "status"

    def test_loop_status_with_id(self):
        cmd = parse_loop_command("loop status 42")
        assert cmd.command == "status"
        assert cmd.loop_id == "42"

    def test_list_loops(self):
        cmd = parse_loop_command("list loops")
        assert cmd.command == "list"

    def test_loops_shorthand(self):
        cmd = parse_loop_command("loops")
        assert cmd.command == "list"

    def test_unknown(self):
        cmd = parse_loop_command("hello world")
        assert cmd.command == "unknown"

    def test_empty_string(self):
        cmd = parse_loop_command("")
        assert cmd.command == "unknown"


# ── _infer_done_when ──────────────────────────────────────────────────────────

class TestInferDoneWhen:
    def test_structured_pass_through(self):
        assert _infer_done_when("command:pytest") == "command:pytest"
        assert _infer_done_when("file_exists:output.txt") == "file_exists:output.txt"

    def test_pytest_passes(self):
        result = _infer_done_when("pytest passes")
        assert "command:pytest" in result

    def test_file_exists(self):
        result = _infer_done_when("file output/brief.md exists")
        assert "file_exists:output/brief.md" in result

    def test_file_contains(self):
        result = _infer_done_when("file result.txt contains SUCCESS")
        assert "file_contains:result.txt:SUCCESS" in result

    def test_unrecognized_returns_as_is(self):
        text = "some unusual condition text"
        result = _infer_done_when(text)
        assert result == text

    def test_empty(self):
        assert _infer_done_when("") == ""
