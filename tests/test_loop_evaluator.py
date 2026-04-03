"""Tests for loop_evaluator — done condition parsing and evaluation."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from claude_bridge.loop_evaluator import (
    DoneCondition,
    evaluate_done_condition,
    parse_done_condition,
    validate_done_condition,
)


# ── parse_done_condition ───────────────────────────────────────────────────────

class TestParseDoneCondition:
    def test_parse_command(self):
        cond = parse_done_condition("command:pytest tests/")
        assert cond.type == "command"
        assert cond.args == ["pytest tests/"]

    def test_parse_command_with_flags(self):
        cond = parse_done_condition("command:make test -- --verbose")
        assert cond.type == "command"
        assert cond.args == ["make test -- --verbose"]

    def test_parse_file_exists(self):
        cond = parse_done_condition("file_exists:output/report.txt")
        assert cond.type == "file_exists"
        assert cond.args == ["output/report.txt"]

    def test_parse_file_contains(self):
        cond = parse_done_condition("file_contains:result.txt:ALL PASSED")
        assert cond.type == "file_contains"
        assert cond.args == ["result.txt", "ALL PASSED"]

    def test_parse_file_contains_pattern_with_colon(self):
        # Pattern itself may contain a colon — only first colon after type separates path
        cond = parse_done_condition("file_contains:output.log:status: ok")
        assert cond.type == "file_contains"
        assert cond.args == ["output.log", "status: ok"]

    def test_parse_empty_string_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_done_condition("")

    def test_parse_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            parse_done_condition("   ")

    def test_parse_no_colon_raises(self):
        with pytest.raises(ValueError, match="missing type prefix"):
            parse_done_condition("file_exists")

    def test_parse_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown done condition type"):
            parse_done_condition("unknown_type:whatever")

    def test_parse_command_empty_cmd_raises(self):
        with pytest.raises(ValueError, match="non-empty command"):
            parse_done_condition("command:")

    def test_parse_file_exists_empty_path_raises(self):
        with pytest.raises(ValueError, match="non-empty path"):
            parse_done_condition("file_exists:")

    def test_parse_file_contains_missing_pattern_raises(self):
        with pytest.raises(ValueError, match="file_contains type requires format"):
            parse_done_condition("file_contains:path_only")

    def test_parse_file_contains_empty_path_raises(self):
        with pytest.raises(ValueError, match="non-empty path"):
            parse_done_condition("file_contains::pattern")

    def test_parse_case_insensitive_type(self):
        cond = parse_done_condition("COMMAND:pytest")
        assert cond.type == "command"

    def test_describe_command(self):
        cond = parse_done_condition("command:pytest tests/")
        assert "pytest tests/" in cond.describe()
        assert "code 0" in cond.describe()

    def test_describe_file_exists(self):
        cond = parse_done_condition("file_exists:output.txt")
        assert "output.txt" in cond.describe()
        assert "exists" in cond.describe()

    def test_describe_file_contains(self):
        cond = parse_done_condition("file_contains:result.txt:ALL PASSED")
        assert "result.txt" in cond.describe()
        assert "ALL PASSED" in cond.describe()


# ── validate_done_condition ────────────────────────────────────────────────────

class TestValidateDoneCondition:
    def test_valid_command(self):
        ok, err = validate_done_condition("command:pytest")
        assert ok is True
        assert err == ""

    def test_valid_file_exists(self):
        ok, err = validate_done_condition("file_exists:output.txt")
        assert ok is True
        assert err == ""

    def test_valid_file_contains(self):
        ok, err = validate_done_condition("file_contains:log.txt:SUCCESS")
        assert ok is True
        assert err == ""

    def test_invalid_empty(self):
        ok, err = validate_done_condition("")
        assert ok is False
        assert err != ""

    def test_invalid_unknown_type(self):
        ok, err = validate_done_condition("badtype:something")
        assert ok is False
        assert "Unknown" in err


# ── evaluate_done_condition ────────────────────────────────────────────────────

class TestEvaluateDoneConditionCommand:
    def test_successful_command(self, tmp_path):
        cond = DoneCondition(type="command", args=["true"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True

    def test_failing_command(self, tmp_path):
        cond = DoneCondition(type="command", args=["false"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "code 1" in reason

    def test_nonexistent_project_dir(self):
        cond = DoneCondition(type="command", args=["true"])
        passed, reason = evaluate_done_condition(cond, "/nonexistent/path/xyz")
        assert passed is False
        assert "does not exist" in reason

    def test_command_output_in_reason(self, tmp_path):
        cond = DoneCondition(type="command", args=["echo hello"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True
        assert "hello" in reason

    def test_command_timeout(self, tmp_path):
        cond = DoneCondition(type="command", args=["sleep 100"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path), timeout=1)
        assert passed is False
        assert "timed out" in reason.lower()

    def test_command_runs_in_project_dir(self, tmp_path):
        # Create a sentinel file and use pwd to check cwd
        sentinel = tmp_path / "sentinel.txt"
        sentinel.write_text("exists")
        cond = DoneCondition(type="command", args=["test -f sentinel.txt"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True

    def test_mock_subprocess_success(self, tmp_path):
        """Verify mocking works for subprocess calls."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "All tests passed"
        mock_result.stderr = ""
        with patch("claude_bridge.loop_evaluator.subprocess.run", return_value=mock_result):
            cond = DoneCondition(type="command", args=["pytest"])
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True

    def test_mock_subprocess_failure(self, tmp_path):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "3 tests failed"
        with patch("claude_bridge.loop_evaluator.subprocess.run", return_value=mock_result):
            cond = DoneCondition(type="command", args=["pytest"])
            passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "3 tests failed" in reason


class TestEvaluateDoneConditionFileExists:
    def test_file_exists(self, tmp_path):
        f = tmp_path / "output.txt"
        f.write_text("done")
        cond = DoneCondition(type="file_exists", args=["output.txt"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True
        assert "exists" in reason

    def test_file_not_exists(self, tmp_path):
        cond = DoneCondition(type="file_exists", args=["missing.txt"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "not found" in reason

    def test_absolute_path_file_exists(self, tmp_path):
        f = tmp_path / "abs.txt"
        f.write_text("hi")
        cond = DoneCondition(type="file_exists", args=[str(f)])
        passed, reason = evaluate_done_condition(cond, "/some/other/dir")
        assert passed is True

    def test_nested_path(self, tmp_path):
        nested = tmp_path / "sub" / "dir" / "result.txt"
        nested.parent.mkdir(parents=True)
        nested.write_text("result")
        cond = DoneCondition(type="file_exists", args=["sub/dir/result.txt"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True


class TestEvaluateDoneConditionFileContains:
    def test_file_contains_pattern(self, tmp_path):
        f = tmp_path / "result.txt"
        f.write_text("ALL TESTS PASSED\nDone.")
        cond = DoneCondition(type="file_contains", args=["result.txt", "ALL TESTS PASSED"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True

    def test_file_does_not_contain_pattern(self, tmp_path):
        f = tmp_path / "result.txt"
        f.write_text("3 tests failed")
        cond = DoneCondition(type="file_contains", args=["result.txt", "ALL PASSED"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "does not contain" in reason

    def test_file_not_found(self, tmp_path):
        cond = DoneCondition(type="file_contains", args=["missing.txt", "pattern"])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "not found" in reason

    def test_empty_pattern_substring(self, tmp_path):
        # Empty string is always a substring of any content
        f = tmp_path / "f.txt"
        f.write_text("anything")
        cond = DoneCondition(type="file_contains", args=["f.txt", ""])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is True

    def test_unknown_condition_type(self, tmp_path):
        cond = DoneCondition(type="unknown_type", args=[])
        passed, reason = evaluate_done_condition(cond, str(tmp_path))
        assert passed is False
        assert "Unknown" in reason
