"""Telegram integration for Goal Loop — notification formatting and approval parsing.

Handles:
- Formatting loop progress notifications for Telegram (batched, not per-iteration)
- Formatting loop completion / failure / approval-request messages
- Parsing user replies: 'approve', 'reject', 'reject: <feedback>'
- NLP parsing of natural language loop commands from Telegram
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple


# ── Notification formatters ────────────────────────────────────────────────────

def format_loop_progress(
    loop_id: str,
    agent: str,
    goal: str,
    iteration_num: int,
    max_iterations: int,
    result_summary: str,
    done: bool,
    cost_usd: float = 0.0,
) -> str:
    """Format a mid-loop iteration progress notification for Telegram.

    Args:
        loop_id: The loop ID.
        agent: Agent name.
        goal: Loop goal description.
        iteration_num: Completed iteration number (1-indexed).
        max_iterations: Maximum iterations.
        result_summary: Summary from the completed iteration.
        done: Whether the done condition was met in this iteration.
        cost_usd: Running total cost so far.

    Returns:
        Formatted Telegram message string.
    """
    goal_short = goal[:80] + "..." if len(goal) > 80 else goal
    summary_short = result_summary[:200] + "..." if len(result_summary) > 200 else result_summary

    if done:
        return (
            f"Loop '{goal_short}' iteration {iteration_num}/{max_iterations} done.\n"
            f"Status: goal achieved.\n"
            f"Cost so far: ${cost_usd:.3f}"
        )

    status_line = summary_short if summary_short else "No summary."

    return (
        f"Loop '{goal_short}' iteration {iteration_num}/{max_iterations} done.\n"
        f"Status: {status_line}\n"
        f"Cost so far: ${cost_usd:.3f}"
    )


def format_loop_done(
    loop_id: str,
    agent: str,
    goal: str,
    iterations_completed: int,
    total_cost_usd: float,
    duration_ms: int | None,
    finish_reason: str,
) -> str:
    """Format a loop completion notification for Telegram.

    Args:
        loop_id: The loop ID.
        agent: Agent name.
        goal: Loop goal description.
        iterations_completed: Number of iterations completed.
        total_cost_usd: Total cost accumulated.
        duration_ms: Total duration in milliseconds (optional).
        finish_reason: Reason the loop ended ('done_condition_met', 'max_iterations', etc.)

    Returns:
        Formatted Telegram message string.
    """
    goal_short = goal[:80] + "..." if len(goal) > 80 else goal

    # Humanize finish reason
    reason_map = {
        "done_condition_met": "Goal achieved",
        "max_iterations": "Max iterations reached",
        "max_consecutive_failures": "Too many consecutive failures",
        "cost_limit_exceeded": "Cost limit exceeded",
        "manual_approved": "Approved by user",
        "user_cancelled": "Cancelled by user",
    }

    # Handle cost_limit_exceeded with extra detail
    if finish_reason and finish_reason.startswith("cost_limit_exceeded:"):
        human_reason = "Cost limit exceeded"
    else:
        human_reason = reason_map.get(finish_reason or "", finish_reason or "completed")

    # Format duration
    duration_str = ""
    if duration_ms is not None and duration_ms > 0:
        total_secs = duration_ms // 1000
        mins = total_secs // 60
        secs = total_secs % 60
        duration_str = f" | Time: {mins}m {secs}s"

    iter_word = "iteration" if iterations_completed == 1 else "iterations"

    if finish_reason in ("done_condition_met", "manual_approved"):
        return (
            f"Loop done after {iterations_completed} {iter_word}. {human_reason}.\n"
            f"Goal: '{goal_short}'\n"
            f"Total cost: ${total_cost_usd:.3f}{duration_str}"
        )

    return (
        f"Loop stopped after {iterations_completed} {iter_word}. {human_reason}.\n"
        f"Goal: '{goal_short}'\n"
        f"Total cost: ${total_cost_usd:.3f}{duration_str}"
    )


def format_loop_approval_request(
    loop_id: str,
    agent: str,
    goal: str,
    iteration_num: int,
    result_summary: str,
) -> str:
    """Format a manual approval request notification for Telegram.

    Args:
        loop_id: The loop ID.
        agent: Agent name.
        goal: Loop goal description.
        iteration_num: The iteration that just completed.
        result_summary: Summary of the completed iteration.

    Returns:
        Formatted Telegram message string asking user to approve or reject.
    """
    goal_short = goal[:80] + "..." if len(goal) > 80 else goal
    summary_short = result_summary[:300] + "..." if len(result_summary) > 300 else result_summary

    return (
        f"Loop iteration {iteration_num} completed.\n"
        f"Goal: '{goal_short}'\n"
        f"Result: {summary_short}\n\n"
        f"Does this meet your goal?\n"
        f"Reply 'approve' to finish, or 'reject' (optionally with feedback) to continue.\n"
        f"Loop ID: {loop_id}"
    )


def format_loop_started(
    loop_id: str,
    agent: str,
    goal: str,
    done_when: str,
    max_iterations: int,
    loop_type: str,
) -> str:
    """Format a loop start confirmation notification for Telegram.

    Args:
        loop_id: The loop ID.
        agent: Agent name.
        goal: Loop goal description.
        done_when: Done condition string.
        max_iterations: Maximum iterations.
        loop_type: 'bridge' or 'agent'.

    Returns:
        Formatted Telegram message string.
    """
    goal_short = goal[:80] + "..." if len(goal) > 80 else goal

    return (
        f"Loop started for '{agent}'.\n"
        f"Goal: '{goal_short}'\n"
        f"Done when: {done_when}\n"
        f"Max iterations: {max_iterations} | Type: {loop_type}\n"
        f"Loop ID: {loop_id}"
    )


# ── Approval reply parser ──────────────────────────────────────────────────────

class ApprovalAction(NamedTuple):
    """Result of parsing a user's approval/rejection reply."""

    action: str            # 'approve', 'reject', 'unknown'
    feedback: str          # non-empty if user included rejection feedback
    loop_id: str | None    # extracted loop_id from message, if any


def parse_approval_reply(text: str) -> ApprovalAction:
    """Parse a user's Telegram reply into an approval action.

    Handles:
        "approve"                         → approve, no feedback
        "approve loop 42"                 → approve, loop_id="42"
        "reject"                          → reject, no feedback
        "reject: tests are still failing" → reject with feedback
        "reject tests are still failing"  → reject with feedback
        "/approve-loop 42"                → approve, loop_id="42"
        "/deny-loop 42"                   → reject, loop_id="42"
        anything else                     → unknown

    Args:
        text: The raw Telegram message text.

    Returns:
        ApprovalAction namedtuple.
    """
    if not text:
        return ApprovalAction("unknown", "", None)

    stripped = text.strip()
    lower = stripped.lower()

    # /approve-loop <id> or /deny-loop <id>
    slash_approve = re.match(r'^/approve[-_]loop\s+(\S+)', stripped, re.IGNORECASE)
    if slash_approve:
        return ApprovalAction("approve", "", slash_approve.group(1))

    slash_deny = re.match(r'^/deny[-_]loop\s+(\S+)', stripped, re.IGNORECASE)
    if slash_deny:
        return ApprovalAction("reject", "", slash_deny.group(1))

    # "approve [loop <id>]"
    if re.match(r'^approve\b', lower):
        loop_match = re.search(r'loop\s+(\S+)', lower)
        loop_id = loop_match.group(1) if loop_match else None
        return ApprovalAction("approve", "", loop_id)

    # "reject [: <feedback>]" or "deny [: <feedback>]"
    reject_match = re.match(r'^(?:reject|deny)\b[:\s]*(.*)', stripped, re.IGNORECASE)
    if reject_match:
        feedback = reject_match.group(1).strip()
        # Try to find a loop_id embedded
        loop_match = re.search(r'loop\s+(\S+)', feedback, re.IGNORECASE)
        loop_id = None
        if loop_match:
            loop_id = loop_match.group(1)
            # Remove "loop <id>" from feedback
            feedback = re.sub(r'loop\s+\S+', '', feedback, flags=re.IGNORECASE).strip()

        return ApprovalAction("reject", feedback, loop_id)

    return ApprovalAction("unknown", "", None)


# ── Natural language loop command parser ───────────────────────────────────────

class LoopCommand(NamedTuple):
    """Result of parsing a natural language loop command from Telegram."""

    command: str            # 'start', 'stop', 'status', 'list', 'unknown'
    agent: str | None       # agent name extracted
    goal: str | None        # goal description extracted
    done_when: str | None   # done condition extracted
    loop_id: str | None     # loop_id for stop/status commands
    max_iterations: int     # default 10


def parse_loop_command(text: str) -> LoopCommand:
    """Parse a natural language Telegram message into a loop command.

    Handles phrases like:
        "loop vn-trader morning brief until 3pm"
            → start, agent='vn-trader', goal='morning brief until 3pm', done_when=None
        "loop backend fix tests, done when pytest passes"
            → start, agent='backend', goal='fix tests', done_when='command:pytest'
        "loop backend 'generate report' until file output/report.md exists, max 5"
            → start, agent='backend', goal='generate report',
              done_when='file_exists:output/report.md', max_iterations=5
        "stop loop 42"  /  "cancel loop 42"
            → stop, loop_id='42'
        "loop status"  /  "loop status 42"
            → status, loop_id=None or '42'
        "list loops"  /  "loops"
            → list

    Args:
        text: Raw Telegram message text.

    Returns:
        LoopCommand namedtuple.
    """
    if not text:
        return LoopCommand("unknown", None, None, None, None, 10)

    stripped = text.strip()
    lower = stripped.lower()

    # "stop loop <id>" / "cancel loop <id>"
    stop_match = re.match(r'^(?:stop|cancel)\s+loop\s+(\S+)', lower)
    if stop_match:
        return LoopCommand("stop", None, None, None, stop_match.group(1), 10)

    # "loop status [<id>]"
    status_match = re.match(r'^loop\s+status\s*(\S+)?', lower)
    if status_match:
        loop_id = status_match.group(1)
        return LoopCommand("status", None, None, None, loop_id, 10)

    # "list loops" / "loops"
    if re.match(r'^(?:list\s+)?loops?$', lower):
        return LoopCommand("list", None, None, None, None, 10)

    # "loop <agent> <goal> [until/done-when/when <condition>] [max <N>]"
    # The agent is the first word after "loop"
    loop_start = re.match(r'^loop\s+(\S+)\s+(.*)', stripped, re.IGNORECASE)
    if loop_start:
        agent = loop_start.group(1)
        rest = loop_start.group(2).strip()

        # Extract max_iterations: "max N" or "max-iterations N" (case-insensitive)
        max_iterations = 10
        max_match = re.search(r'\bmax(?:-iterations?)?\s+(\d+)', rest, re.IGNORECASE)
        if max_match:
            try:
                max_iterations = int(max_match.group(1))
            except ValueError:
                pass
            rest = rest[:max_match.start()].rstrip() + rest[max_match.end():]
            rest = rest.strip()

        # Extract done_when from "until <condition>", "done when <condition>",
        # "when <condition>", "check <condition>"
        done_when = None
        done_patterns = [
            r'\buntil\s+(.+)$',
            r'\bdone\s+when\s+(.+)$',
            r'\bwhen\s+(.+)$',
            r'\bcheck\s+(.+)$',
        ]
        for pat in done_patterns:
            m = re.search(pat, rest, re.IGNORECASE)
            if m:
                cond_text = m.group(1).strip()
                done_when = _infer_done_when(cond_text)
                rest = rest[:m.start()].strip()
                break

        # What remains is the goal
        goal = rest.strip() if rest.strip() else None

        return LoopCommand("start", agent, goal, done_when, None, max_iterations)

    return LoopCommand("unknown", None, None, None, None, 10)


def _infer_done_when(cond_text: str) -> str:
    """Infer a done_when condition string from natural language condition text.

    Examples:
        "pytest passes"          → "command:pytest"
        "file output/brief.md exists" → "file_exists:output/brief.md"
        "file result.txt contains SUCCESS" → "file_contains:result.txt:SUCCESS"
        "3pm"                    → None (time-based, not supported)
        "command:pytest"         → "command:pytest" (pass-through)

    Args:
        cond_text: Natural language or structured condition.

    Returns:
        Structured done_when string or the original text as-is.
    """
    if not cond_text:
        return cond_text

    # Already structured
    if re.match(r'^(command|file_exists|file_contains|llm_judge|manual):', cond_text):
        return cond_text

    # "pytest passes" / "pytest exits 0" / "pytest succeeds"
    pytest_match = re.search(r'\bpytest\b([^,]*)', cond_text, re.IGNORECASE)
    if pytest_match:
        pytest_args = pytest_match.group(1).strip()
        if pytest_args and not re.search(r'\b(pass|exit|succeed)\b', pytest_args, re.IGNORECASE):
            return f"command:pytest {pytest_args}"
        return "command:pytest"

    # Generic "command X passes/succeeds/exits 0"
    cmd_match = re.search(r'\bcommand\s+(.+?)(?:\s+(?:pass|exit|succeed))', cond_text, re.IGNORECASE)
    if cmd_match:
        return f"command:{cmd_match.group(1).strip()}"

    # "file <path> exists" / "file <path> is ready"
    file_exists_match = re.search(r'\bfile\s+(\S+)\s+(?:exists|is\s+ready|appears)', cond_text, re.IGNORECASE)
    if file_exists_match:
        return f"file_exists:{file_exists_match.group(1)}"

    # "file <path> contains <text>"
    file_contains_match = re.search(r'\bfile\s+(\S+)\s+contains\s+(.+)', cond_text, re.IGNORECASE)
    if file_contains_match:
        path = file_contains_match.group(1)
        content = file_contains_match.group(2).strip().strip("'\"")
        return f"file_contains:{path}:{content}"

    # Return as-is if we can't infer
    return cond_text
