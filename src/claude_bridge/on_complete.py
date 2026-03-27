#!/usr/bin/env python3
"""Stop hook handler — called by Claude Code when an agent task completes.

This script is referenced in agent .md frontmatter:
  hooks:
    Stop:
      - hooks:
          - type: command
            command: "python3 ~/.claude-bridge/on-complete.py --session-id <id>"
"""

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


def main(db: BridgeDB | None = None):
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

        # Update agent state
        db.update_agent_state(args.session_id, "idle")
        db.increment_agent_tasks(args.session_id)

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

    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    main()
