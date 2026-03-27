# Milestone 11: Agent Teams — Report

**Date:** 2026-03-28
**Status:** COMPLETE

## Task Summary

| Task | Status | Tests | Gaps Fixed | Notes |
|------|--------|-------|------------|-------|
| M11.T1 | done | 16/16 | Schema: teams, team_members, task_type, parent_task_id | Greenfield |
| M11.T2 | done | 14/14 | CLI: create-team, list-teams, delete-team | Also fixed test_dispatcher for UUID change |
| M11.T3 | done | 6/6 | CLI: team-dispatch with augmented prompt | Lead gets PYTHONPATH-based dispatch commands |
| M11.T4 | done | 5/5 | CLI: team-status with progress tracking | Shows sub-task breakdown |
| M11.T5 | done | 5/5 | on_complete: team aggregation | sqlite3.Row .get() not supported |
| M11.T6 | done | 3/3 | E2E: full lifecycle + partial failure | Sub-tasks must use different sessions |

## Gaps Discovered and Fixed
- **sqlite3.Row has no .get()**: Used direct key access with fallback chain instead
- **Sub-tasks on same session as parent**: `get_running_task` returns parent instead of sub-task. Design constraint: sub-tasks should go to different agent sessions (teammates), not back to the lead. This is architecturally correct since the lead coordinates, teammates execute.
- **UUID session-id**: Claude Code requires UUID for `--session-id`. Fixed in dispatcher with deterministic uuid5. Updated test_dispatcher.py.
- **DB schema drift**: Live DB missing columns added in Phase 2 code. Need migration strategy for existing installs.

## Blockers
- None for the team feature itself
- Operational: stop hook (`on-complete.py`) path needs to be correct for real usage
- Operational: `--dangerously-skip-permissions` added for non-interactive use

## Architecture Deviations
- **Augmented prompt uses PYTHONPATH**: Instead of `bridge-cli` binary, the team prompt uses `PYTHONPATH=... python3 -m claude_bridge.cli` since the package isn't pip-installed. This works but is fragile — should be replaced with proper package install in production.
- **No separate aggregation dispatch to lead**: The plan suggested dispatching an aggregation prompt back to the lead. Instead, we mark the parent done immediately with aggregated summaries. Simpler and avoids an extra Claude Code invocation.

## Next Milestone Readiness
M11 is complete. Ready to proceed to M12 (Multi-Channel), M13 (Cost Dashboard), M14 (Workspace Cleanup), or M15 (Session Management).
