"""Loop orchestrator — manages goal loop lifecycle.

A loop dispatches tasks in sequence until a done condition is met
or max_iterations/max_consecutive_failures is reached.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime

from .db import BridgeDB
from .loop_evaluator import (
    DoneCondition,
    parse_done_condition,
    validate_done_condition,
    evaluate_done_condition,
)

# ── Cost limit thresholds ──────────────────────────────────────────────────────

_COST_WARNING_THRESHOLD = 0.80  # warn at 80% of max_cost_usd


def start_loop(
    db: BridgeDB,
    agent: str,
    project: str,
    goal: str,
    done_when: str,
    max_iterations: int = 10,
    max_consecutive_failures: int = 3,
    loop_type: str = "bridge",
    max_cost_usd: float | None = None,
) -> str:
    """Start a goal loop and dispatch the first iteration.

    Args:
        db: BridgeDB instance.
        agent: Agent name (must exist in DB).
        project: Project directory path (agent's project_dir).
        goal: Human-readable description of what to achieve.
        done_when: Done condition string (e.g. 'command:pytest tests/').
        max_iterations: Maximum number of iterations (default 10).
        max_consecutive_failures: Stop after N consecutive task failures (default 3).
        loop_type: 'bridge' (default) or 'agent' or 'auto'.
        max_cost_usd: Optional cost ceiling in USD. Stops the loop when exceeded.

    Returns:
        loop_id string.

    Raises:
        ValueError: If done_when is invalid.
        RuntimeError: If the agent already has an active loop.
    """
    # Validate done_when
    valid, err = validate_done_condition(done_when)
    if not valid:
        raise ValueError(f"Invalid done_when condition: {err}")

    # Check for concurrent loop on same agent
    existing = db.get_active_loop_for_agent(agent)
    if existing:
        raise RuntimeError(
            f"Agent '{agent}' already has an active loop: {existing['loop_id']}. "
            "Cancel it before starting a new one."
        )

    # Resolve loop_type via branching heuristic when 'auto'
    resolved_loop_type = loop_type
    if loop_type == "auto":
        condition = parse_done_condition(done_when)
        use_agent = _should_use_agent_loop(
            goal=goal,
            done_condition=condition,
            max_iterations=max_iterations,
            loop_type_override=None,
            iteration_num=1,
        )
        resolved_loop_type = "agent" if use_agent else "bridge"

    # Create loop record
    loop_id = db.create_loop(
        agent=agent,
        project=project,
        goal=goal,
        done_when=done_when,
        loop_type=resolved_loop_type,
        max_iterations=max_iterations,
        max_consecutive_failures=max_consecutive_failures,
        max_cost_usd=max_cost_usd,
    )

    # Dispatch first iteration
    _dispatch_iteration(db, loop_id, db.get_loop(loop_id), iteration_num=1, feedback="")

    return loop_id


def _build_iteration_prompt(
    goal: str,
    iteration_num: int,
    feedback: str,
    loop_type: str,
    done_when: str,
) -> str:
    """Build the prompt for an iteration.

    For loop_type='bridge': clean task prompt with context from previous iterations.
    For loop_type='agent': add hint about being in a goal loop with internal loop instructions.
    """
    if loop_type == "agent":
        condition = parse_done_condition(done_when)
        condition_desc = condition.describe()

        prompt = f"""{goal}

## Internal Loop Instructions
Complete this task using an internal retry loop:

Step 1: Attempt the task as described above.
Step 2: Verify the result by: {condition_desc}
Step 3: If verification fails, diagnose what went wrong and retry.
Step 4: Repeat steps 1-3 as needed.
Step 5: Stop when either:
  (a) Verification passes — report SUCCESS
  (b) You've exhausted your attempts — report FAILURE with summary of what was tried

FINAL REPORT FORMAT (last thing you output):
---
AGENT_LOOP_RESULT: {{"attempts": N, "status": "success|failed",
                      "final_state": "<1-2 sentences>",
                      "remaining_issues": ["..."]}}
---

IMPORTANT:
- Do NOT stop after the first attempt unless verification passes.
- Do NOT ask for user input between attempts.
- Each attempt should build on lessons from the previous attempt."""

        if feedback and iteration_num > 1:
            prompt += f"\n\n## Context from Previous Attempts\n{feedback}"

        return prompt

    # bridge loop type — standard prompt
    prompt = goal
    if feedback and iteration_num > 1:
        prompt += f"\n\n## Previous Iteration Context\n{feedback}"
        prompt += f"\n\nThis is iteration {iteration_num}. Build on previous progress."

    return prompt


# ── Feedback helpers ───────────────────────────────────────────────────────────

def _parse_test_failures(output: str) -> list[str]:
    """Extract test failure lines from pytest/unittest output.

    Args:
        output: Raw test output string.

    Returns:
        List of failure description strings (max 10).
    """
    if not output:
        return []

    failures = []

    # Pytest style: "FAILED tests/test_x.py::TestX::test_y - ErrorType: message"
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("FAILED "):
            failures.append(stripped)
        elif stripped.startswith("FAIL: "):
            # unittest style: "FAIL: test_create (tests.test_model.TestModel)"
            failures.append(stripped)

    return failures[:10]


def _parse_stack_trace(output: str) -> str:
    """Extract the last Python traceback from output.

    Args:
        output: Raw output that may contain tracebacks.

    Returns:
        The last traceback as a string, truncated to 2000 chars. Empty if none found.
    """
    if not output:
        return ""

    # Find all traceback start positions
    pattern = re.compile(r"Traceback \(most recent call last\):", re.MULTILINE)
    matches = list(pattern.finditer(output))

    if not matches:
        return ""

    # Use the last traceback
    last_start = matches[-1].start()
    trace = output[last_start:]

    # Truncate if too long
    if len(trace) > 2000:
        trace = trace[:1997] + "..."

    return trace.strip()


def _truncate_feedback(text: str, max_chars: int = 2000) -> str:
    """Truncate feedback text to max_chars, adding marker if truncated.

    Args:
        text: Text to truncate.
        max_chars: Maximum character count.

    Returns:
        Possibly truncated string.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 15] + "...[truncated]"


def _generate_feedback(iterations: list[dict]) -> str:
    """Generate feedback string from the last 2 iterations.

    Enhanced in Phase 2: parses test failures and stack traces from result summaries.

    Args:
        iterations: List of iteration dicts (in order).

    Returns:
        Formatted feedback string (max 2000 chars total).
    """
    if not iterations:
        return ""

    # Take last 2 iterations only
    recent = iterations[-2:] if len(iterations) >= 2 else iterations

    parts = []
    for it in recent:
        num = it["iteration_num"]
        status = it.get("status", "unknown")
        summary = it.get("result_summary") or ""
        if len(summary) > 500:
            summary = summary[:500] + "...[truncated]"
        passed = it.get("done_check_passed", 0)
        check_str = "PASSED" if passed else "not met"

        # Enhanced: extract failures and stack traces
        failures = _parse_test_failures(summary)
        trace = _parse_stack_trace(summary)

        entry = (
            f"Iteration {num} ({status}): {summary}\n"
            f"  Done condition: {check_str}"
        )

        if failures:
            failures_str = "\n    ".join(failures[:5])
            entry += f"\n  Test failures:\n    {failures_str}"

        if trace and not failures:
            # Only include trace if no failures extracted (avoid duplication)
            trace_short = trace[:300] + "..." if len(trace) > 300 else trace
            entry += f"\n  Error trace:\n    {trace_short}"

        parts.append(entry)

    combined = "\n\n".join(parts)

    # Apply total 2000-char cap
    return _truncate_feedback(combined, max_chars=2000)


# ── Branching decision engine ──────────────────────────────────────────────────

def _should_use_agent_loop(
    goal: str,
    done_condition: DoneCondition,
    max_iterations: int,
    loop_type_override: str | None,
    iteration_num: int,
) -> bool:
    """Decide whether to use an agent-internal loop for this iteration.

    Returns True if agent should loop internally (1 task, agent retries).
    Returns False if bridge should control the loop (1 task per bridge iteration).

    Args:
        goal: The loop goal description.
        done_condition: The parsed done condition.
        max_iterations: Total max iterations configured.
        loop_type_override: Explicit 'bridge', 'agent', or None for auto.
        iteration_num: Current iteration number (1-indexed).
    """
    # 1. Explicit overrides always win
    if loop_type_override == "bridge":
        return False
    if loop_type_override == "agent":
        return True

    # 2. manual condition requires Bridge (must send Telegram/ask user)
    if done_condition.type == "manual":
        return False

    # 3. llm_judge condition requires Bridge to call claude evaluate
    if done_condition.type == "llm_judge":
        return False

    # 4. Many iterations → Bridge Loop for visibility and cost tracking
    if max_iterations > 5:
        return False

    # 5. command/file conditions with few iterations → agent loop
    #    (agent can verify and retry faster, avoiding Bridge overhead)
    if done_condition.type in ("command", "file_exists", "file_contains"):
        if max_iterations <= 5:
            return True

    # Default: bridge loop (safe, observable)
    return False


def _inject_agent_loop_prompt(
    original_task: str,
    done_condition: DoneCondition,
    max_internal_iterations: int,
) -> str:
    """Augment an original task prompt with agent-internal loop instructions.

    Args:
        original_task: The original task/goal prompt.
        done_condition: Parsed done condition (used to describe verification step).
        max_internal_iterations: How many internal attempts the agent should make.

    Returns:
        Full augmented prompt string.
    """
    condition_desc = done_condition.describe()

    return f"""{original_task}

## Internal Loop Instructions
Complete this task using an internal retry loop:

Step 1: Attempt the task as described above.
Step 2: Verify the result by: {condition_desc}
Step 3: If verification fails, diagnose what went wrong and retry.
Step 4: Repeat steps 1-3, up to {max_internal_iterations} total attempts.
Step 5: Stop when either:
  (a) Verification passes — report SUCCESS
  (b) You've exhausted {max_internal_iterations} attempts — report FAILURE
      with summary of what was tried and what still fails

Use TodoWrite/TodoRead to track your attempts:
  - Before each attempt: update todo with "Attempt N: [plan]"
  - After each attempt: update todo with "Attempt N: [result]"

FINAL REPORT FORMAT (last thing you output):
---
AGENT_LOOP_RESULT: {{"attempts": N, "status": "success|failed",
                      "final_state": "<1-2 sentences>",
                      "remaining_issues": ["..."] }}
---

IMPORTANT:
- Do NOT stop after the first attempt unless verification passes.
- Do NOT ask for user input between attempts.
- Each attempt should build on lessons from the previous attempt."""


def _extract_agent_loop_result(task_output: str) -> dict | None:
    """Parse AGENT_LOOP_RESULT JSON marker from task output.

    Args:
        task_output: The raw text output from a completed task.

    Returns:
        Dict with keys: attempts, status, final_state, remaining_issues.
        Returns None if no valid marker found.
    """
    if not task_output:
        return None

    # Find all occurrences of AGENT_LOOP_RESULT
    pattern = re.compile(
        r"AGENT_LOOP_RESULT:\s*(\{.*?\})",
        re.DOTALL,
    )
    matches = list(pattern.finditer(task_output))

    if not matches:
        return None

    # Use the last match (most recent attempt)
    last_match = matches[-1]
    try:
        return json.loads(last_match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


# ── Cost limit helpers ─────────────────────────────────────────────────────────

def _check_cost_limit(loop: dict, new_total: float) -> tuple[bool, str]:
    """Check if cost limit is exceeded or approaching.

    Returns:
        (should_stop, reason_or_warning)
        If should_stop is True, the loop should be halted.
    """
    max_cost = loop.get("max_cost_usd")
    if max_cost is None or max_cost <= 0:
        return False, ""

    if new_total >= max_cost:
        return True, f"Cost limit reached: ${new_total:.4f} >= ${max_cost:.4f}"

    # Warn at 80%
    ratio = new_total / max_cost
    if ratio >= _COST_WARNING_THRESHOLD:
        print(
            f"Warning: loop {loop['loop_id']}: cost ${new_total:.4f} is "
            f"{ratio*100:.0f}% of limit ${max_cost:.4f}",
            file=sys.stderr,
        )

    return False, ""


# ── Pending approval notification ─────────────────────────────────────────

def _notify_pending_approval(db: BridgeDB, loop: dict, iteration_num: int) -> None:
    """Send a Telegram notification when a manual loop enters pending_approval.

    Looks up the chat_id from the current task's channel_chat_id.
    If no chat_id is available, silently skips (CLI-only usage).
    """
    loop_id = loop["loop_id"]
    agent = loop["agent"]
    current_task_id = loop.get("current_task_id")
    if not current_task_id:
        return

    task = db.get_task(int(current_task_id))
    if not task:
        return

    chat_id = task.get("channel_chat_id")
    if not chat_id:
        return

    message = (
        f"⏸ Loop {loop_id} ({agent}) iteration {iteration_num} done "
        f"— waiting for your approval.\n"
        f"Use /loop-approve or /loop-reject to continue."
    )

    try:
        from .message_db import MessageDB
        msg_db = MessageDB()
        try:
            msg_db.create_outbound("telegram", chat_id, message, source="loop")
        finally:
            msg_db.close()
    except Exception:
        # Best-effort notification — don't break the loop flow
        print(f"[loop] Failed to send pending_approval notification for {loop_id}", file=sys.stderr)


# ── Dispatch ───────────────────────────────────────────────────────────────────

def _dispatch_iteration(
    db: BridgeDB,
    loop_id: str,
    loop: dict,
    iteration_num: int,
    feedback: str,
) -> str:
    """Build and dispatch a single loop iteration.

    Returns the task_id (as string) of the spawned task.
    """
    from .dispatcher import spawn_task, get_result_file
    from .session import derive_agent_file_name, derive_session_id

    agent_name = loop["agent"]
    project_dir = loop["project"]
    goal = loop["goal"]
    loop_type = loop["loop_type"]
    done_when = loop["done_when"]

    prompt = _build_iteration_prompt(goal, iteration_num, feedback, loop_type, done_when)

    # Get agent record for model info
    agent_record = db.get_agent(agent_name)
    if agent_record is None:
        raise RuntimeError(f"Agent '{agent_name}' not found in database")

    session_id = agent_record["session_id"]
    agent_file_name = derive_agent_file_name(session_id)
    model = agent_record["model"] or "sonnet"

    # Create task record
    task_id = db.create_task(
        session_id=session_id,
        prompt=prompt,
        task_type="loop",
    )
    result_file = get_result_file(session_id, task_id)

    # Spawn
    pid = spawn_task(
        agent_file_name,
        session_id,
        project_dir,
        prompt,
        task_id,
        model=model,
    )

    db.update_task(
        task_id,
        status="running",
        pid=pid,
        result_file=result_file,
        model=model,
        started_at=datetime.now().isoformat(),
    )
    db.update_agent_state(session_id, "running")

    # Create iteration record
    iteration_id = db.create_loop_iteration(
        loop_id=loop_id,
        iteration_num=iteration_num,
        prompt=prompt,
    )
    db.update_loop_iteration(iteration_id, task_id=str(task_id))

    # Update loop state
    db.update_loop(
        loop_id,
        current_iteration=iteration_num,
        current_task_id=str(task_id),
    )

    return str(task_id)


def on_task_complete(
    db: BridgeDB,
    loop_id: str,
    task_id: str,
    result_summary: str,
    cost_usd: float = 0.0,
) -> None:
    """Handle task completion for a loop iteration.

    Called by on_complete.py when a task belonging to a loop finishes.

    Args:
        db: BridgeDB instance.
        loop_id: The loop ID this task belongs to.
        task_id: The completed task ID (as string).
        result_summary: The task's result summary (will be truncated to 1000 chars).
        cost_usd: Cost of this task in USD.
    """
    loop = db.get_loop(loop_id)
    if loop is None:
        return

    # Guard: only act on running loops
    if loop["status"] != "running":
        return

    # Truncate result_summary to 1000 chars
    if len(result_summary) > 1000:
        result_summary = result_summary[:1000] + "...[truncated]"

    # Find the iteration record for this task
    iterations = db.get_loop_iterations(loop_id)
    iteration_record = None
    for it in iterations:
        if it.get("task_id") == str(task_id):
            iteration_record = it
            break

    finished_at = datetime.now().isoformat()

    # Determine if the task itself failed
    task = db.get_task(int(task_id))
    task_failed = task is not None and task["status"] == "failed"

    # Check agent loop result extraction for agent-type loops
    agent_result = None
    if not task_failed and loop.get("loop_type") == "agent":
        task_output = (task.get("result_summary") or "") if task else ""
        agent_result = _extract_agent_loop_result(task_output or result_summary)

    # Evaluate done condition
    done = False
    done_reason = ""
    if not task_failed:
        # If agent self-reported success, trust it
        if agent_result and agent_result.get("status") == "success":
            done = True
            done_reason = agent_result.get("final_state", "Agent self-reported success")
        else:
            try:
                condition = parse_done_condition(loop["done_when"])
                project_dir = loop["project"]
                done, done_reason = evaluate_done_condition(
                    condition, project_dir, result_summary=result_summary
                )
            except Exception as e:
                done_reason = f"Evaluation error: {e}"

    # Update iteration record
    if iteration_record:
        db.update_loop_iteration(
            iteration_record["id"],
            result_summary=result_summary,
            done_check_passed=1 if done else 0,
            cost_usd=cost_usd,
            finished_at=finished_at,
            status="failed" if task_failed else "done",
        )

    # Update loop total cost
    new_total_cost = (loop.get("total_cost_usd") or 0.0) + cost_usd
    db.update_loop(loop_id, total_cost_usd=new_total_cost)

    # Check cost limit
    cost_exceeded, cost_reason = _check_cost_limit(loop, new_total_cost)
    if cost_exceeded:
        db.update_loop(
            loop_id,
            status="failed",
            finished_at=finished_at,
            finish_reason=f"cost_limit_exceeded: {cost_reason}",
        )
        return

    current_iteration = loop["current_iteration"]

    if done:
        db.update_loop(
            loop_id,
            status="done",
            finished_at=finished_at,
            finish_reason="done_condition_met",
        )
        return

    # Update consecutive failures
    consecutive_failures = loop.get("consecutive_failures", 0)
    if task_failed:
        consecutive_failures += 1
    else:
        consecutive_failures = 0
    db.update_loop(loop_id, consecutive_failures=consecutive_failures)

    # Check max_consecutive_failures
    if consecutive_failures >= loop["max_consecutive_failures"]:
        db.update_loop(
            loop_id,
            status="failed",
            finished_at=finished_at,
            finish_reason="max_consecutive_failures",
        )
        return

    # Check max_iterations
    if current_iteration >= loop["max_iterations"]:
        db.update_loop(
            loop_id,
            status="done",
            finished_at=finished_at,
            finish_reason="max_iterations",
        )
        return

    # Manual done condition: set pending_approval and notify user
    try:
        condition = parse_done_condition(loop["done_when"])
        if condition.type == "manual":
            db.update_loop(loop_id, pending_approval=1)
            _notify_pending_approval(db, loop, current_iteration)
            return
    except ValueError:
        pass

    # Dispatch next iteration with feedback
    all_iterations = db.get_loop_iterations(loop_id)
    feedback = _generate_feedback(all_iterations)
    next_iteration_num = current_iteration + 1

    try:
        _dispatch_iteration(
            db, loop_id, db.get_loop(loop_id), next_iteration_num, feedback
        )
    except Exception as e:
        # If dispatch fails, mark loop as failed
        db.update_loop(
            loop_id,
            status="failed",
            finished_at=datetime.now().isoformat(),
            finish_reason=f"dispatch_error: {str(e)[:200]}",
        )


def cancel_loop(db: BridgeDB, loop_id: str) -> bool:
    """Cancel a running loop.

    Returns:
        True if the loop was found and cancelled.
        False if not found or already in a terminal state.
    """
    loop = db.get_loop(loop_id)
    if loop is None:
        return False
    if loop["status"] != "running":
        return False

    db.update_loop(
        loop_id,
        status="cancelled",
        finished_at=datetime.now().isoformat(),
        finish_reason="user_cancelled",
    )
    return True


def approve_loop(db: BridgeDB, loop_id: str) -> bool:
    """Approve a loop that is waiting for manual done condition.

    Marks the loop as done (condition met by user approval).

    Returns:
        True if approved. False if loop not found, not running, or not pending approval.
    """
    loop = db.get_loop(loop_id)
    if loop is None:
        return False
    if loop["status"] != "running":
        return False
    if not loop.get("pending_approval"):
        return False

    db.update_loop(
        loop_id,
        status="done",
        pending_approval=0,
        finished_at=datetime.now().isoformat(),
        finish_reason="manual_approved",
    )
    return True


def reject_loop(db: BridgeDB, loop_id: str, feedback: str = "") -> bool:
    """Reject a loop waiting for manual approval — continue to next iteration.

    Args:
        db: BridgeDB instance.
        loop_id: The loop to resume.
        feedback: Optional feedback to inject into the next iteration.

    Returns:
        True if rejected and next iteration dispatched.
        False if loop not found, not running, or not pending approval.
    """
    loop = db.get_loop(loop_id)
    if loop is None:
        return False
    if loop["status"] != "running":
        return False
    if not loop.get("pending_approval"):
        return False

    current_iteration = loop["current_iteration"]

    # Check max_iterations
    if current_iteration >= loop["max_iterations"]:
        db.update_loop(
            loop_id,
            status="done",
            pending_approval=0,
            finished_at=datetime.now().isoformat(),
            finish_reason="max_iterations",
        )
        return True

    db.update_loop(loop_id, pending_approval=0)

    # Dispatch next iteration with user feedback injected
    all_iterations = db.get_loop_iterations(loop_id)
    auto_feedback = _generate_feedback(all_iterations)
    combined_feedback = feedback + ("\n\n" + auto_feedback if auto_feedback else "") if feedback else auto_feedback
    next_iteration_num = current_iteration + 1

    try:
        _dispatch_iteration(
            db, loop_id, db.get_loop(loop_id), next_iteration_num, combined_feedback
        )
    except Exception as e:
        db.update_loop(
            loop_id,
            status="failed",
            finished_at=datetime.now().isoformat(),
            finish_reason=f"dispatch_error: {str(e)[:200]}",
        )
        return False

    return True


def get_loop_status(db: BridgeDB, loop_id: str) -> dict | None:
    """Get loop status with full iteration list.

    Returns:
        Dict with loop fields plus 'iterations' key, or None if not found.
    """
    loop = db.get_loop(loop_id)
    if loop is None:
        return None

    iterations = db.get_loop_iterations(loop_id)
    loop["iterations"] = iterations
    return loop


# ── Public hybrid orchestrator API ────────────────────────────────────────────

def decide_loop_type(
    goal: str,
    done_when: str,
    user_preference: str | None = None,
    max_iterations: int = 5,
) -> str:
    """Decide whether to use 'bridge' or 'agent' loop type.

    This is the public API for the hybrid orchestrator decision engine.
    It accepts a raw done_when string (not a pre-parsed DoneCondition).

    Args:
        goal: The loop goal description string.
        done_when: Done condition string (e.g. 'command:pytest', 'manual:msg').
        user_preference: Explicit preference — 'bridge', 'agent', 'auto', or None.
                         None and 'auto' both trigger the heuristic.
        max_iterations: Expected max iterations (used in heuristic). Default 5.
                        Pass the actual loop max_iterations for best results.
                        Values > 5 will bias toward 'bridge' for observability.

    Returns:
        'bridge' or 'agent'.
    """
    # 'auto' and None both trigger heuristic
    override = user_preference if user_preference not in (None, "auto") else None

    try:
        condition = parse_done_condition(done_when)
    except ValueError:
        # Invalid condition — default to bridge (safe)
        return "bridge"

    use_agent = _should_use_agent_loop(
        goal=goal,
        done_condition=condition,
        max_iterations=max_iterations,
        loop_type_override=override,
        iteration_num=1,
    )
    return "agent" if use_agent else "bridge"


# ── Loop dashboard formatters ──────────────────────────────────────────────────

def format_loop_list(loops: list[dict]) -> str:
    """Format a list of loops for CLI or Telegram dashboard display.

    Args:
        loops: List of loop dicts (from db.list_loops).

    Returns:
        Formatted multi-line string.
    """
    if not loops:
        return "No loops found."

    lines = []
    for loop in loops:
        loop_id = loop.get("loop_id", "?")
        agent = loop.get("agent", "?")
        status = loop.get("status", "?")
        current = loop.get("current_iteration", 0)
        max_iter = loop.get("max_iterations", "?")
        cost = loop.get("total_cost_usd") or 0.0
        goal = loop.get("goal", "")
        goal_short = goal[:60] + "..." if len(goal) > 60 else goal
        lines.append(
            f"Loop {loop_id} — {agent} [{status}]\n"
            f"  Goal: {goal_short}\n"
            f"  Progress: {current}/{max_iter}  Cost: ${cost:.3f}"
        )

    return "\n\n".join(lines)


def format_loop_history(loop: dict) -> str:
    """Format a single loop's full iteration history for CLI or Telegram.

    Args:
        loop: Loop dict with 'iterations' list (from get_loop_status).

    Returns:
        Formatted multi-line string.
    """
    if not loop:
        return "Loop not found."

    loop_id = loop.get("loop_id", "?")
    agent = loop.get("agent", "?")
    status = loop.get("status", "?")
    goal = loop.get("goal", "")
    goal_short = goal[:80] + "..." if len(goal) > 80 else goal
    cost = loop.get("total_cost_usd") or 0.0
    finish_reason = loop.get("finish_reason") or ""
    iterations = loop.get("iterations", [])

    header = (
        f"Loop {loop_id} — {agent} [{status}]\n"
        f"  Goal: {goal_short}\n"
        f"  Total cost: ${cost:.3f}"
    )
    if finish_reason:
        header += f"\n  Finish reason: {finish_reason}"

    if not iterations:
        return header + "\n  No iterations recorded."

    iter_lines = []
    for it in iterations:
        num = it.get("iteration_num", "?")
        it_status = it.get("status", "?")
        done_passed = it.get("done_check_passed", 0)
        done_str = "PASS" if done_passed else "fail"
        cost_it = it.get("cost_usd") or 0.0
        duration_ms = it.get("duration_ms")
        duration_str = ""
        if duration_ms:
            secs = duration_ms // 1000
            duration_str = f" {secs}s"
        summary = (it.get("result_summary") or "")[:100]
        if len(it.get("result_summary") or "") > 100:
            summary += "..."

        iter_lines.append(
            f"  [{num}] {it_status:<8} done={done_str}  ${cost_it:.3f}{duration_str}"
            + (f"\n      {summary}" if summary else "")
        )

    return header + "\n  Iterations:\n" + "\n".join(iter_lines)
