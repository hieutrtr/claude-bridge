"""Tests for CLAUDE.md initialization — all subprocess calls mocked."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from claude_bridge.claude_md_init import init_claude_md, INIT_PROMPT_NEW, INIT_PROMPT_APPEND


@pytest.fixture
def project_dir(tmp_path):
    """A temporary project directory without CLAUDE.md."""
    p = tmp_path / "my-project"
    p.mkdir()
    return str(p)


@pytest.fixture
def project_dir_with_claude_md(tmp_path):
    """A temporary project directory with existing CLAUDE.md."""
    p = tmp_path / "my-project"
    p.mkdir()
    (p / "CLAUDE.md").write_text("# Existing Project\n\nSome content.\n")
    return str(p)


class TestNewProject:
    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_calls_claude_with_scan_prompt(self, mock_run, project_dir):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"cost_usd": 0.05, "is_error": False}),
            stderr="",
        )

        result = init_claude_md(project_dir, "backend", "API development")

        assert result["success"] is True
        mock_run.assert_called_once()

        call_args = mock_run.call_args[0][0]  # The command list
        assert call_args[0] == "claude"
        assert "-p" in call_args
        prompt_idx = call_args.index("-p") + 1
        prompt = call_args[prompt_idx]
        assert "API development" in prompt
        assert "PROJECT OVERVIEW" in prompt

    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_uses_correct_flags(self, mock_run, project_dir):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"cost_usd": 0.03}),
            stderr="",
        )

        init_claude_md(project_dir, "backend", "dev")

        call_args = mock_run.call_args[0][0]
        assert "--project-dir" in call_args
        assert "--allowedTools" in call_args
        assert "--output-format" in call_args

        tools_idx = call_args.index("--allowedTools") + 1
        assert call_args[tools_idx] == "Read,Grep,Glob,Write"

        fmt_idx = call_args.index("--output-format") + 1
        assert call_args[fmt_idx] == "json"

    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_returns_success_with_cost(self, mock_run, project_dir):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"cost_usd": 0.05}),
            stderr="",
        )

        result = init_claude_md(project_dir, "backend", "dev")

        assert result["success"] is True
        assert result["message"] == "CLAUDE.md initialized"
        assert result["cost_usd"] == 0.05

    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_uses_new_prompt_not_append(self, mock_run, project_dir):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="{}", stderr=""
        )

        init_claude_md(project_dir, "backend", "REST API")

        call_args = mock_run.call_args[0][0]
        prompt_idx = call_args.index("-p") + 1
        prompt = call_args[prompt_idx]
        # New project should use the full scan prompt
        assert "Analyze this codebase" in prompt
        assert "Agent Context" not in prompt or "Append" not in prompt


class TestExistingClaudeMd:
    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_uses_append_prompt(self, mock_run, project_dir_with_claude_md):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"cost_usd": 0.02}),
            stderr="",
        )

        init_claude_md(project_dir_with_claude_md, "backend", "API dev")

        call_args = mock_run.call_args[0][0]
        prompt_idx = call_args.index("-p") + 1
        prompt = call_args[prompt_idx]
        assert "Append" in prompt or "append" in prompt.lower() or "Agent Context" in prompt
        assert "backend" in prompt
        assert "API dev" in prompt

    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_returns_updated_message(self, mock_run, project_dir_with_claude_md):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"cost_usd": 0.01}),
            stderr="",
        )

        result = init_claude_md(project_dir_with_claude_md, "backend", "dev")

        assert result["success"] is True
        assert "updated" in result["message"].lower()


class TestErrorHandling:
    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_nonzero_exit_returns_error(self, mock_run, project_dir):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Something went wrong",
        )

        result = init_claude_md(project_dir, "backend", "dev")

        assert result["success"] is False
        assert "Something went wrong" in result["error"]

    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_nonzero_exit_no_stderr(self, mock_run, project_dir):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr=""
        )

        result = init_claude_md(project_dir, "backend", "dev")

        assert result["success"] is False
        assert "Unknown error" in result["error"]

    @patch("claude_bridge.claude_md_init.subprocess.run", side_effect=FileNotFoundError)
    def test_claude_not_found(self, mock_run, project_dir):
        result = init_claude_md(project_dir, "backend", "dev")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_timeout(self, mock_run, project_dir):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)

        result = init_claude_md(project_dir, "backend", "dev")

        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    @patch("claude_bridge.claude_md_init.subprocess.run")
    def test_invalid_json_stdout_still_succeeds(self, mock_run, project_dir):
        """If claude returns success but non-JSON stdout, still report success."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="not json", stderr=""
        )

        result = init_claude_md(project_dir, "backend", "dev")

        assert result["success"] is True
        assert "no JSON" in result["message"]

    def test_never_raises(self, project_dir):
        """init_claude_md should never raise — always returns dict."""
        # With no mock, FileNotFoundError is caught internally
        result = init_claude_md(project_dir, "backend", "dev")
        assert isinstance(result, dict)
        assert "success" in result


class TestPromptContent:
    def test_new_prompt_contains_purpose_placeholder(self):
        formatted = INIT_PROMPT_NEW.format(purpose="REST API development")
        assert "REST API development" in formatted
        assert "PROJECT OVERVIEW" in formatted
        assert "BUILD & TEST" in formatted
        assert "AGENT CONTEXT" in formatted

    def test_append_prompt_contains_agent_and_purpose(self):
        formatted = INIT_PROMPT_APPEND.format(agent_name="backend", purpose="API dev")
        assert "backend" in formatted
        assert "API dev" in formatted
        assert "Agent Context" in formatted
