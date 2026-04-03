#!/usr/bin/env python3
"""Stop hook handler — called by Claude Code when an agent task completes.

This script is referenced in agent .md frontmatter:
  hooks:
    Stop:
      - hooks:
          - type: command
            command: "python3 ~/.claude-bridge/on-complete.py --session-id <id>"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

# Add parent to path so we can import from the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from claude_bridge.db import BridgeDB


def parse_result_file(result_file: str) -> dict | None:
    """Parse the JSON result file from claude --output-format json."""
    try:
        expanded = os.path.expanduser(result_file)
        if not os.path.isfile(expanded):
            return None
        with open(expanded) as f:
            content = f.read().strip()
            if not content:
                return None
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return None


def _check_team_aggregation(db: BridgeDB, parent_task_id: int):
    """Check if all sub-tasks for a parent are done. If so, mark parent done."""
    parent = db.get_task(parent_task_id)
    if not parent or parent["status"] not in ("running", "pending"):
        return

    subtasks = db.get_subtasks(parent_task_id)
    if not subtasks:
        return

    # Check if all sub-tasks are in a terminal state
    terminal = {"done", "failed", "killed", "timeout", "cancelled"}
    if not all(s["status"] in terminal for s in subtasks):
        return

    # All sub-tasks complete — aggregate
    total_cost = sum((s["cost_usd"] or 0) for s in subtasks)
    total_cost += parent["cost_usd"] or 0

    summaries = []
    for s in subtasks:
        agent = db.get_agent_by_session(s["session_id"])
        name = agent["name"] if agent else s["session_id"]
        status = s["status"]
        summary = s["result_summary"] or s["error_message"] or ""
        summaries.append(f"[{name}] {status}: {summary[:100]}")

    aggregated_summary = "\n".join(summaries)

    db.update_task(
        parent_task_id,
        status="done",
        cost_usd=total_cost,
        result_summary=aggregated_summary[:500],
        completed_at=datetime.now().isoformat(),
    )

    done_count = sum(1 for s in subtasks if s["status"] == "done")
    total_count = len(subtasks)
    print(f"🏁 Team task #{parent_task_id} complete — {done_count}/{total_count} sub-tasks succeeded, total cost: ${total_cost:.3f}")


def main(db: BridgeDB | None = None, msg_db_path: str | None = None):
    parser = argparse.ArgumentParser(description="Claude Bridge stop hook handler")
    parser.add_argument("--session-id", required=True, help="Session ID of the completed task")
    args = parser.parse_args()

    own_db = db is None
    if own_db:
        db = BridgeDB()

    try:
        # Find the running task for this session
        task = db.get_running_task(args.session_id)
        if not task:
            return

        task_id = task["id"]
        result_file = task["result_file"]

        # Parse result
        status = "done"
        summary = ""
        cost = 0.0
        duration = 0
        turns = 0
        exit_code = 0
        error = None

        result = parse_result_file(result_file) if result_file else None

        if result:
            if result.get("is_error"):
                status = "failed"
                error = str(result.get("result", "Unknown error"))[:500]
            else:
                summary = str(result.get("result", ""))[:500]
            cost = result.get("cost_usd", 0) or 0
            duration = result.get("duration_ms", 0) or 0
            turns = result.get("num_turns", 0) or 0
        else:
            # No result file — check stderr
            if result_file:
                stderr_file = result_file.replace("-result.json", "-stderr.log")
                stderr_path = os.path.expanduser(stderr_file)
                if os.path.isfile(stderr_path):
                    with open(stderr_path) as f:
                        stderr_content = f.read().strip()
                    if stderr_content:
                        status = "failed"
                        error = stderr_content[:500]
                        exit_code = -1

        # Update task
        db.update_task(
            task_id,
            status=status,
            result_summary=summary if summary else None,
            cost_usd=cost,
            duration_ms=duration,
            num_turns=turns,
            exit_code=exit_code,
            error_message=error,
            completed_at=datetime.now().isoformat(),
        )

        # Check if this is a sub-task — aggregate parent if all siblings done
        if task["parent_task_id"]:
            _check_team_aggregation(db, task["parent_task_id"])

        # Check if this task belongs to a loop — if so, hand off to orchestrator
        loop = db.get_loop_by_task_id(str(task_id))
        if loop:
            from .loop_orchestrator import on_task_complete as loop_on_task_complete
            result_for_loop = summary if summary else (error or "")
            loop_on_task_complete(
                db,
                loop["loop_id"],
                str(task_id),
                result_for_loop,
                cost,
            )
            # Loop orchestrator handles next dispatch — skip normal queue processing
            db.increment_agent_tasks(args.session_id)
            db.mark_task_reported(task_id)
            return

        # Update agent and check queue
        db.increment_agent_tasks(args.session_id)

        # Auto-dequeue next task if any
        next_task = db.dequeue_next_task(args.session_id)
        if next_task:
            from .dispatcher import spawn_task, get_result_file
            from .session import derive_agent_file_name

            agent = db.get_agent_by_session(args.session_id)
            agent_file_name = derive_agent_file_name(args.session_id)
            next_task_id = next_task["id"]
            next_result_file = get_result_file(args.session_id, next_task_id)

            pid = spawn_task(
                agent_file_name, args.session_id,
                agent["project_dir"], next_task["prompt"], next_task_id,
            )
            db.update_task(
                next_task_id,
                status="running", pid=pid,
                result_file=next_result_file,
                started_at=datetime.now().isoformat(),
            )
            # Agent stays running
        else:
            db.update_agent_state(args.session_id, "idle")

        # Print report (Bridge Bot picks this up)
        if duration:
            mins = duration // 60000
            secs = (duration % 60000) // 1000
            duration_str = f"{mins}m {secs}s"
        else:
            duration_str = "unknown"

        if status == "done":
            print(f"✓ Task #{task_id} ({args.session_id}) — done in {duration_str}")
            if summary:
                print(f"  {summary[:200]}")
            print(f"  Cost: ${cost:.3f} | Turns: {turns}")
        else:
            print(f"✗ Task #{task_id} ({args.session_id}) — failed after {duration_str}")
            if error:
                print(f"  Error: {error[:200]}")

        # Queue notification for delivery (Bridge MCP poller sends it)
        updated_task = db.get_task(task_id)
        if updated_task["channel"] != "cli" and updated_task["channel_chat_id"]:
            agent = db.get_agent_by_session(args.session_id)
            agent_name = agent["name"] if agent else args.session_id

            from .notify import format_completion_message
            from .message_db import MessageDB
            message = format_completion_message(updated_task, agent_name)

            _msg_db = MessageDB(msg_db_path) if msg_db_path else MessageDB()
            try:
                _msg_db.create_outbound(
                    updated_task["channel"],
                    updated_task["channel_chat_id"],
                    message,
                    source="notification",
                )
            finally:
                _msg_db.close()

        # Mark as reported so watcher doesn't send again
        db.mark_task_reported(task_id)

    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    main()
