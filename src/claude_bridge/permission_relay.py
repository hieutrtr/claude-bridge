#!/usr/bin/env python3
"""Permission relay hook — called by Claude Code PreToolUse hook.

Blocks execution, creates a permission request in SQLite, polls until
approved/denied/timed out, then returns exit code.

Exit codes:
  0 = approved (allow the action)
  2 = denied (block the action)

Usage in agent .md frontmatter:
  hooks:
    PreToolUse:
      - matcher: "Bash(git push *)"
        hooks:
          - type: command
            command: "python3 -m claude_bridge.permission_relay --session-id <id>"
"""

import argparse
import json
import os
import sys
import time
import uuid

from .db import BridgeDB

DEFAULT_TIMEOUT = 300  # 5 minutes
POLL_INTERVAL = 2  # seconds


def main(db: BridgeDB | None = None):
    parser = argparse.ArgumentParser(description="Claude Bridge permission relay hook")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--tool", default="unknown")
    parser.add_argument("--command", default="")
    parser.add_argument("--description", default="")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    own_db = db is None
    if own_db:
        db = BridgeDB()

    try:
        request_id = str(uuid.uuid4())[:8]

        db.create_permission(
            request_id=request_id,
            session_id=args.session_id,
            tool_name=args.tool,
            command=args.command,
            description=args.description,
            timeout_seconds=args.timeout,
        )

        print(f"🔒 Permission requested ({args.session_id}): {args.tool} {args.command}")
        print(f"   Request ID: {request_id}")
        print(f"   Waiting for approval (timeout: {args.timeout}s)...")

        # Poll for response
        elapsed = 0
        while elapsed < args.timeout:
            perm = db.get_permission(request_id)
            if perm and perm["status"] != "pending":
                if perm["status"] == "approved":
                    print(f"   ✓ Approved")
                    return 0
                else:
                    print(f"   ✗ Denied ({perm['response']})")
                    return 2
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

        # Timeout — auto-deny
        db.respond_permission(request_id, approved=False)
        print(f"   ⏱ Timed out after {args.timeout}s — auto-denied")
        return 2

    finally:
        if own_db:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
