#!/usr/bin/env python3
"""Fallback PID watcher — catches tasks where the Stop hook didn't fire.

Run via cron: * * * * * PYTHONPATH=/path/to/claude-bridge/src python3 -m claude_bridge.watcher
"""

import os
import sys
from datetime import datetime

from .db import BridgeDB
from .dispatcher import pid_alive, kill_process


DEFAULT_TIMEOUT_MINUTES = 30


def watch(timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES, db: BridgeDB | None = None):
    """Check running tasks and handle completions/timeouts."""
    own_db = db is None
    if own_db:
        db = BridgeDB()

    try:
        running_tasks = db.get_running_tasks()

        for task in running_tasks:
            task_id = task["id"]
            pid = task["pid"]
            session_id = task["session_id"]
            started_at = task["started_at"]

            if not pid:
                # No PID recorded — mark as failed
                db.update_task(
                    task_id,
                    status="failed",
                    error_message="No PID recorded",
                    completed_at=datetime.now().isoformat(),
                )
                db.update_agent_state(session_id, "idle")
                continue

            if not pid_alive(pid):
                # Process is dead but hook didn't fire — parse result if available
                from .on_complete import parse_result_file

                result_file = task["result_file"]
                result = parse_result_file(result_file) if result_file else None

                if result and not result.get("is_error"):
                    db.update_task(
                        task_id,
                        status="done",
                        result_summary=str(result.get("result", ""))[:500],
                        cost_usd=result.get("cost_usd", 0),
                        duration_ms=result.get("duration_ms", 0),
                        num_turns=result.get("num_turns", 0),
                        exit_code=0,
                        completed_at=datetime.now().isoformat(),
                    )
                    db.update_agent_state(session_id, "idle")
                    db.increment_agent_tasks(session_id)
                    print(f"[watcher] Task #{task_id} ({session_id}) completed (hook missed)")
                else:
                    error = str(result.get("result", "Process exited"))[:500] if result else "Process exited unexpectedly"
                    db.update_task(
                        task_id,
                        status="failed",
                        error_message=error,
                        exit_code=-1,
                        completed_at=datetime.now().isoformat(),
                    )
                    db.update_agent_state(session_id, "idle")
                    db.increment_agent_tasks(session_id)
                    print(f"[watcher] Task #{task_id} ({session_id}) failed (hook missed)")

            elif started_at:
                # Check timeout
                started = datetime.fromisoformat(started_at)
                elapsed = (datetime.now() - started).total_seconds()
                if elapsed > timeout_minutes * 60:
                    kill_process(pid)
                    db.update_task(
                        task_id,
                        status="timeout",
                        error_message=f"Timed out after {timeout_minutes} minutes",
                        completed_at=datetime.now().isoformat(),
                    )
                    db.update_agent_state(session_id, "idle")
                    print(f"[watcher] Task #{task_id} ({session_id}) timed out after {timeout_minutes}m")

        # Report unreported completions + send notifications
        from .notify import format_completion_message, deliver_notification

        unreported = db.get_unreported_tasks()
        for task in unreported:
            if task["status"] == "done":
                print(f"✓ Task #{task['id']} ({task['session_id']}) — done")
                if task["result_summary"]:
                    print(f"  {task['result_summary'][:200]}")
            elif task["status"] == "failed":
                print(f"✗ Task #{task['id']} ({task['session_id']}) — failed")
                if task["error_message"]:
                    print(f"  {task['error_message'][:200]}")
            elif task["status"] == "timeout":
                print(f"⏱ Task #{task['id']} ({task['session_id']}) — timed out")

            # Send notification if task has a channel + chat_id
            if task["channel"] != "cli" and task["channel_chat_id"]:
                agent = db.get_agent_by_session(task["session_id"])
                agent_name = agent["name"] if agent else task["session_id"]
                message = format_completion_message(task, agent_name)
                nid = db.create_notification(
                    task["id"], task["channel"],
                    task["channel_chat_id"], message,
                )
                deliver_notification(db, nid)

            db.mark_task_reported(task["id"])

        # Retry any pending notifications (from previous failed deliveries)
        pending = db.get_pending_notifications()
        for notif in pending:
            deliver_notification(db, notif["id"])

    finally:
        if own_db:
            db.close()


def main():
    watch()


if __name__ == "__main__":
    main()
