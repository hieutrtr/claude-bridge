"""Scheduler runner — reads due schedules and dispatches tasks.

Called by cron every minute: bridge-cli scheduler
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from .db import BridgeDB


def compute_next_run(schedule: dict, now: datetime, error: bool = False) -> datetime:
    """Compute next_run_at for a schedule.

    Success: anchor-based (last_run_at + interval), prevents drift.
    Error:   exponential backoff, capped at 8x interval.

    Args:
        schedule: Schedule dict with last_run_at, interval_minutes, consecutive_errors.
        now: Current UTC time (used as anchor when last_run_at is None).
        error: If True, apply backoff based on consecutive_errors.
    """
    interval = schedule["interval_minutes"] or 60
    anchor_str = schedule["last_run_at"]
    if anchor_str:
        try:
            anchor = datetime.fromisoformat(anchor_str)
        except ValueError:
            anchor = now
    else:
        anchor = now

    if error:
        errors = (schedule["consecutive_errors"] or 0)
        backoff = min(2 ** errors, 8)
        return anchor + timedelta(minutes=interval * backoff)
    else:
        return anchor + timedelta(minutes=interval)


def dispatch_for_schedule(db: BridgeDB, schedule: dict, agent: dict) -> int:
    """Dispatch a task for the given schedule. Returns task_id.

    Reuses the same logic as cmd_dispatch: atomic check, spawn, update.
    """
    from .dispatcher import spawn_task, get_result_file
    from .session import derive_agent_file_name

    session_id = agent["session_id"]
    channel = schedule.get("channel") or "cli"
    channel_chat_id = schedule.get("channel_chat_id")
    user_id = schedule.get("user_id")
    prompt = schedule["prompt"]

    task_id, is_busy = db.atomic_check_and_create_task(
        session_id, prompt,
        channel=channel,
        channel_chat_id=channel_chat_id,
    )

    if is_busy:
        # Queue the task — existing queue mechanism handles ordering
        queued_id = db.create_task(
            session_id, prompt,
            channel=channel,
            channel_chat_id=channel_chat_id,
            user_id=user_id,
        )
        position = db.get_next_queue_position(session_id)
        db.update_task(queued_id, status="queued", position=position)
        return queued_id

    result_file = get_result_file(session_id, task_id)
    agent_file_name = derive_agent_file_name(session_id)
    model = agent["model"]

    pid = spawn_task(agent_file_name, session_id, agent["project_dir"], prompt, task_id, model=model)

    db.update_task(
        task_id,
        pid=pid,
        result_file=result_file,
        model=model,
        started_at=datetime.now(timezone.utc).isoformat(),
        user_id=user_id,
    )
    db.update_agent_state(session_id, "running")
    return task_id


def run_scheduler(db: BridgeDB) -> None:
    """Read all due schedules and dispatch each one.

    Called by cron every minute. Always exits cleanly (cron jobs must not fail).
    Logs errors to stderr for visibility in scheduler.log.
    """
    now = datetime.now(timezone.utc)
    due = db.get_due_schedules(now)

    for schedule in due:
        sid = schedule["id"]
        name = schedule["name"]
        agent_name = schedule["agent_name"]

        # Skip if too many consecutive errors (schedule should already be auto-paused)
        if (schedule["consecutive_errors"] or 0) >= 5:
            print(f"[scheduler] skipping '{name}': too many consecutive errors", file=sys.stderr)
            continue

        agent = db.get_agent(agent_name)
        if not agent:
            print(f"[scheduler] error: agent '{agent_name}' not found for schedule '{name}'", file=sys.stderr)
            db.update_schedule_error(sid, f"Agent '{agent_name}' not found")
            continue

        try:
            task_id = dispatch_for_schedule(db, schedule, agent)
            db.update_schedule_success(sid, now)
            print(f"[scheduler] dispatched '{name}' → task #{task_id}", file=sys.stderr)
        except Exception as exc:
            msg = str(exc)
            print(f"[scheduler] error dispatching '{name}': {msg}", file=sys.stderr)
            db.update_schedule_error(sid, msg)
