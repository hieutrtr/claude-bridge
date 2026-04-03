"""Tests for LLM judge done condition type."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_bridge.loop_evaluator import (
    DoneCondition,
    evaluate_done_condition,
    parse_done_condition,
    validate_done_condition,
)


# ── Parse llm_judge ────────────────────────────────────────────────────────────

class TestParseLlmJudge:
    def test_parse_llm_judge(self):
        cond = parse_done_condition("llm_judge:Code is production-ready with error handling")
        assert cond.type == "llm_judge"
        assert cond.args == ["Code is production-ready with error handling"]

    def test_parse_llm_judge_empty_rubric_raises(self):
        with pytest.raises(ValueError, match="non-empty rubric"):
            parse_done_condition("llm_judge:")

    def test_parse_llm_judge_with_colons_in_rubric(self):
        cond = parse_done_condition("llm_judge:Code quality: high, tests: passing")
        assert cond.type == "llm_judge"
        assert cond.args == ["Code quality: high, tests: passing"]

    def test_validate_llm_judge_valid(self):
        ok, err = validate_done_condition("llm_judge:Code is production-ready")
        assert ok is True
        assert err == ""

    def test_validate_llm_judge_empty_rubric(self):
        ok, err = validate_done_condition("llm_judge:")
        assert ok is False
        assert "rubric" in err


# ── describe() for llm_judge ───────────────────────────────────────────────────

class TestLlmJudgeDescribe:
    def test_describe_llm_judge(self):
        cond = DoneCondition(type="llm_judge", args=["Code is production-ready"])
        desc = cond.describe()
        assert "production-ready" in desc
        assert "criteria met" in desc.lower() or "Code is production-ready" in desc


# ── evaluate llm_judge ─────────────────────────────────────────────────────────

class TestEvaluateLlmJudge:
    def test_llm_judge_pass_when_claude_says_yes(self, tmp_path):
        """When claude outputs PASS, condition is met."""
        cond = parse_done_condition("llm_judge:Code is production-ready")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="PASS\nThe code looks good.",
                stderr="",
            )
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True
        assert "PASS" in reason or "pass" in reason.lower()

    def test_llm_judge_fail_when_claude_says_fail(self, tmp_path):
        """When claude outputs FAIL, condition is not met."""
        cond = parse_done_condition("llm_judge:Code is production-ready")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="FAIL\nMissing error handling in auth module.",
                stderr="",
            )
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "FAIL" in reason or "fail" in reason.lower()

    def test_llm_judge_fail_gracefully_when_api_unavailable(self, tmp_path):
        """When claude CLI is unavailable (subprocess fails), return False with warning."""
        cond = parse_done_condition("llm_judge:Code is production-ready")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("claude not found")
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "unavailable" in reason.lower() or "warning" in reason.lower() or "failed" in reason.lower()

    def test_llm_judge_fail_when_timeout(self, tmp_path):
        """When claude CLI times out, return False with warning."""
        cond = parse_done_condition("llm_judge:Code is production-ready")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=30)
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "timeout" in reason.lower() or "timed out" in reason.lower()

    def test_llm_judge_fail_when_returncode_nonzero(self, tmp_path):
        """When claude exits with non-zero but no PASS/FAIL, return False."""
        cond = parse_done_condition("llm_judge:Code is production-ready")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="Error: something went wrong",
                stderr="fatal error",
            )
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False

    def test_llm_judge_fallback_on_ambiguous_output(self, tmp_path):
        """When claude output has neither PASS nor FAIL, default to False."""
        cond = parse_done_condition("llm_judge:Code is production-ready")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="The code looks interesting.",
                stderr="",
            )
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "ambiguous" in reason.lower() or "unclear" in reason.lower() or "pass" in reason.lower()

    def test_llm_judge_uses_rubric_in_prompt(self, tmp_path):
        """The rubric from done condition is passed to claude."""
        cond = parse_done_condition("llm_judge:All edge cases covered with 100% branch coverage")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="PASS", stderr="")
            evaluate_done_condition(cond, str(tmp_path))
        # The rubric must appear in the prompt sent to claude
        call_args = mock_run.call_args
        prompt_arg = str(call_args)
        assert "edge cases" in prompt_arg or "branch coverage" in prompt_arg


# ── Manual done condition (parse only — eval is loop-level) ───────────────────

class TestParseManual:
    def test_parse_manual(self):
        cond = parse_done_condition("manual:waiting for user approval")
        assert cond.type == "manual"
        assert cond.args == ["waiting for user approval"]

    def test_parse_manual_no_message(self):
        cond = parse_done_condition("manual:")
        assert cond.type == "manual"
        assert cond.args == [""]

    def test_validate_manual(self):
        ok, err = validate_done_condition("manual:check it")
        assert ok is True

    def test_describe_manual(self):
        cond = DoneCondition(type="manual", args=["Looks good to you"])
        desc = cond.describe()
        assert "manual" in desc.lower() or "user" in desc.lower()
