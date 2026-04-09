"""Done condition evaluator for goal loops.

Supported condition types:
  command:<CMD>              — run CMD in project_dir, success = exit code 0
  file_exists:<PATH>         — check if file exists relative to project_dir
  file_contains:<PATH>:<PAT> — check if file contains pattern (substring match)
  llm_judge:<RUBRIC>         — call Claude CLI to judge result against rubric
  manual:<MSG>               — pause and ask user; always returns False until approved
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class DoneCondition:
    """Parsed done condition."""

    type: str
    args: list[str] = field(default_factory=list)

    def describe(self) -> str:
        """Return human-readable description for use in prompts."""
        if self.type == "command":
            cmd = self.args[0] if self.args else ""
            return f"command `{cmd}` exits with code 0"
        if self.type == "file_exists":
            path = self.args[0] if self.args else ""
            return f"file `{path}` exists"
        if self.type == "file_contains":
            path = self.args[0] if len(self.args) > 0 else ""
            pattern = self.args[1] if len(self.args) > 1 else ""
            return f"file `{path}` contains `{pattern}`"
        if self.type == "llm_judge":
            rubric = self.args[0] if self.args else ""
            return f"criteria met: {rubric}"
        if self.type == "manual":
            msg = self.args[0] if self.args else ""
            return f"manual user approval required: {msg}" if msg else "manual user approval required"
        return f"{self.type}: {' '.join(self.args)}"


def parse_done_condition(condition_str: str) -> DoneCondition:
    """Parse a done condition string into a DoneCondition dataclass.

    Raises ValueError for invalid format or unknown type.

    Valid formats:
      command:<CMD>
      file_exists:<PATH>
      file_contains:<PATH>:<PATTERN>
      llm_judge:<RUBRIC>
      manual:<MESSAGE>
    """
    if not condition_str or not condition_str.strip():
        raise ValueError("Done condition cannot be empty")

    condition_str = condition_str.strip()

    # Split on first colon to get type
    if ":" not in condition_str:
        raise ValueError(
            f"Invalid done condition format '{condition_str}': missing type prefix. "
            "Expected format: command:<CMD>, file_exists:<PATH>, file_contains:<PATH>:<PAT>, "
            "llm_judge:<RUBRIC>, or manual:<MSG>"
        )

    ctype, rest = condition_str.split(":", 1)
    ctype = ctype.strip().lower()

    if ctype == "command":
        if not rest.strip():
            raise ValueError("command type requires a non-empty command string")
        return DoneCondition(type="command", args=[rest])

    if ctype == "file_exists":
        if not rest.strip():
            raise ValueError("file_exists type requires a non-empty path")
        return DoneCondition(type="file_exists", args=[rest])

    if ctype == "file_contains":
        # Split on first colon to separate path from pattern
        if ":" not in rest:
            raise ValueError(
                "file_contains type requires format: file_contains:<PATH>:<PATTERN>"
            )
        path, pattern = rest.split(":", 1)
        if not path.strip():
            raise ValueError("file_contains type requires a non-empty path")
        if not pattern:
            raise ValueError("file_contains type requires a non-empty pattern")
        return DoneCondition(type="file_contains", args=[path, pattern])

    if ctype == "llm_judge":
        if not rest.strip():
            raise ValueError("llm_judge type requires a non-empty rubric")
        return DoneCondition(type="llm_judge", args=[rest])

    if ctype == "manual":
        # message is optional
        return DoneCondition(type="manual", args=[rest])

    raise ValueError(
        f"Unknown done condition type '{ctype}'. "
        "Valid types: command, file_exists, file_contains, llm_judge, manual"
    )


def validate_done_condition(condition_str: str) -> tuple[bool, str]:
    """Validate a done condition string.

    Returns:
        (True, "") if valid
        (False, error_message) if invalid
    """
    try:
        parse_done_condition(condition_str)
        return True, ""
    except ValueError as e:
        return False, str(e)


def evaluate_done_condition(
    condition: DoneCondition,
    project_dir: str,
    timeout: int = 30,
    result_summary: str = "",
) -> tuple[bool, str]:
    """Evaluate a done condition against the project directory.

    Args:
        condition: The parsed DoneCondition to evaluate.
        project_dir: The project directory to run commands/check files in.
        timeout: Timeout in seconds for command conditions (default 30).
        result_summary: Optional result text for llm_judge evaluation.

    Returns:
        (passed, reason) where passed is True if condition is met.
    """
    project_dir = os.path.expanduser(project_dir)

    if condition.type == "command":
        return _evaluate_command(condition.args[0], project_dir, timeout)

    if condition.type == "file_exists":
        return _evaluate_file_exists(condition.args[0], project_dir)

    if condition.type == "file_contains":
        path = condition.args[0]
        pattern = condition.args[1] if len(condition.args) > 1 else ""
        return _evaluate_file_contains(path, pattern, project_dir)

    if condition.type == "llm_judge":
        rubric = condition.args[0] if condition.args else ""
        return _evaluate_llm_judge(rubric, result_summary, project_dir, timeout)

    if condition.type == "manual":
        # Manual conditions always return False — must be approved via CLI/MCP
        return False, "manual: waiting for user approval via CLI or MCP"

    return False, f"Unknown condition type: {condition.type}"


def _evaluate_command(
    cmd: str,
    project_dir: str,
    timeout: int,
) -> tuple[bool, str]:
    """Run a shell command and return (exit_code==0, output)."""
    if not os.path.isdir(project_dir):
        return False, f"project_dir does not exist: {project_dir}"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return True, output or "Command exited with code 0"
        return False, f"Command exited with code {result.returncode}: {output[:500]}"
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {cmd}"
    except OSError as e:
        return False, f"Failed to run command: {e}"


def _evaluate_file_exists(path: str, project_dir: str) -> tuple[bool, str]:
    """Check if a file exists relative to (or absolute from) project_dir."""
    full_path = path if os.path.isabs(path) else os.path.join(project_dir, path)
    full_path = os.path.expanduser(full_path)
    if os.path.exists(full_path):
        return True, f"File exists: {full_path}"
    return False, f"File not found: {full_path}"


def _evaluate_file_contains(
    path: str,
    pattern: str,
    project_dir: str,
) -> tuple[bool, str]:
    """Check if a file contains the given pattern (substring match)."""
    full_path = path if os.path.isabs(path) else os.path.join(project_dir, path)
    full_path = os.path.expanduser(full_path)

    if not os.path.exists(full_path):
        return False, f"File not found: {full_path}"

    try:
        with open(full_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        return False, f"Cannot read file {full_path}: {e}"

    if pattern in content:
        return True, f"File '{path}' contains pattern '{pattern}'"
    return False, f"File '{path}' does not contain pattern '{pattern}'"


# ── LLM Judge evaluator ────────────────────────────────────────────────────────

_LLM_JUDGE_PROMPT_TEMPLATE = """\
You are evaluating whether a task result meets a quality rubric.

RUBRIC:
{rubric}

TASK RESULT:
{result_summary}

Respond with EXACTLY one of:
  PASS — if the result clearly meets all rubric criteria
  FAIL — if the result does not meet the rubric criteria

Follow your verdict with a one-sentence explanation.
Example: "PASS\\nAll edge cases are covered and error handling is present."
"""


def _evaluate_llm_judge(
    rubric: str,
    result_summary: str,
    project_dir: str,
    timeout: int = 60,
) -> tuple[bool, str]:
    """Call Claude CLI to evaluate result against rubric.

    Falls back gracefully if claude CLI is unavailable — returns (False, warning).

    Args:
        rubric: The evaluation criteria from the llm_judge condition.
        result_summary: The task output to evaluate.
        project_dir: Used as cwd for claude invocation.
        timeout: Timeout in seconds for the claude call.

    Returns:
        (passed, reason)
    """
    prompt = _LLM_JUDGE_PROMPT_TEMPLATE.format(
        rubric=rubric,
        result_summary=result_summary[:3000] if result_summary else "(no result provided)",
    )

    try:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=project_dir,
        )
    except FileNotFoundError:
        print(
            "Warning: llm_judge: claude CLI not found — skipping LLM judge evaluation",
            file=sys.stderr,
        )
        return False, "LLM judge unavailable: claude CLI not found"
    except subprocess.TimeoutExpired:
        print(
            f"Warning: llm_judge: claude CLI timed out after {timeout}s",
            file=sys.stderr,
        )
        return False, f"LLM judge timed out after {timeout}s"
    except OSError as e:
        print(f"Warning: llm_judge: failed to run claude CLI: {e}", file=sys.stderr)
        return False, f"LLM judge failed: {e}"

    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()
        return False, f"LLM judge failed (exit {result.returncode}): {output[:200]}"

    output = result.stdout.strip()
    upper = output.upper()

    if upper.startswith("PASS"):
        return True, f"LLM judge PASS: {output}"
    if upper.startswith("FAIL"):
        return False, f"LLM judge FAIL: {output}"

    # Ambiguous output — default to False with explanation
    print(
        f"Warning: llm_judge: ambiguous output (neither PASS nor FAIL): {output[:100]}",
        file=sys.stderr,
    )
    return False, f"LLM judge ambiguous output — defaulting to not-done: {output[:200]}"
