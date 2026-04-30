---
name: develop-scheduler
description: Use this skill when working on the schedule/scheduler feature in claude-bridge — adding, fixing, or extending recurring task dispatch. Trigger when the user mentions `schedule`, `scheduler`, `cron`, `recurring task`, `schedule-add/list/remove/pause/resume`, or when editing `src/orchestration/scheduler.ts`, the `schedules` table in `src/data/db.ts`, or schedule-related CLI handlers in `src/cli/index.ts`. Skip for `loop` orchestrator, generic `tasks` table work, permission relay, or notification queue — those are separate concerns.
---

# Developing the scheduler feature

## What the feature is

A polling-based recurring task dispatcher. Each row in the `schedules` table fires its `prompt` against `agent_name` every `interval_minutes`. Not a real cron engine — `cron_expr` and `run_once` columns exist in the schema but are unread by code.

## Code map (don't re-discover)

- **Class**: [src/orchestration/scheduler.ts:15](src/orchestration/scheduler.ts:15) — `Scheduler` with `start/stop/runOnce/computeNextRun/dispatchForSchedule`.
- **Schema + index**: [src/data/db.ts:200](src/data/db.ts:200), index `idx_schedules_next_run` at [:222](src/data/db.ts:222).
- **DB ops** ([src/data/db.ts:634](src/data/db.ts:634)+): `addSchedule`, `getScheduleByName/Id`, `getDueSchedules`, `updateScheduleSuccess`, `updateScheduleError`, `listSchedules`, `removeSchedule`, `pauseSchedule`, `resumeSchedule`.
- **CLI handlers**: [src/cli/index.ts:554-619](src/cli/index.ts:554) (`cmdScheduleAdd/Remove/List/Pause/Resume`).
- **Tests**: `tests/wave4/scheduler.test.ts`, `tests/coverage/evaluator-scheduler-extra.test.ts`.
- **Spec (current state, authoritative)**: [docs/specs/03-orchestration.md:382](docs/specs/03-orchestration.md:382).
- **Daemon entry**: [src/infra/startup.ts](src/infra/startup.ts) — `StartupOrchestrator` (where wiring belongs).

## Known gaps — DO NOT re-discover, fix or note them

1. **Scheduler is not wired into the daemon.** No `new Scheduler(` outside tests. CLI imports it ([src/cli/index.ts:19](src/cli/index.ts:19)) but never uses the symbol. ⇒ `bridge schedule-add` writes the row, nothing fires it.
2. **`dispatchForSchedule` only inserts a `tasks` row in `pending` state** — never calls `Dispatcher.startTask`. Even with the poller running, scheduled prompts won't actually execute. The watcher and MCP `bridge_dispatch` don't claim `pending` rows from schedules either.
3. **`cron_expr` and `run_once` columns are stubs** — `addSchedule` accepts them, no read site honors them. Don't claim they work.
4. **Backoff logic is duplicated.** `Scheduler.computeNextRun(_, _, isError=true)` AND `db.updateScheduleError` both compute `2^errors × interval` (cap 8×). Changing one without the other creates drift. Consolidate or document.
5. **Belt-and-suspenders check.** `runOnce` skips schedules with `consecutive_errors >= 5`, but `db.updateScheduleError` already sets `enabled=0` at that threshold so they wouldn't be returned by `getDueSchedules` anyway.

## Integration recipe (for fixing gaps #1 + #2)

**Wire into daemon** ([src/infra/startup.ts](src/infra/startup.ts)):
- Construct `new Scheduler(this.homeDir, this.db)` in `StartupOrchestrator.start`.
- Call `.start()` alongside the watcher; `.stop()` in shutdown path.
- Default poll interval is 60s; accept override via env or config if user asks, otherwise leave default.

**Make dispatch real** ([src/orchestration/scheduler.ts:66](src/orchestration/scheduler.ts:66)):
- `dispatchForSchedule` must invoke the same path `bridge dispatch` uses — i.e. `Dispatcher.startTask` from [src/execution/dispatcher.ts](src/execution/dispatcher.ts), not a bare `db.createTask`.
- Watch the `session_id` convention: bridge sessions are `agent--project`, but scheduler currently writes `agent--scheduled`. Decide deliberately — either resolve the agent's project (preferred, keeps Auto Memory and worktree paths consistent) or document the `--scheduled` virtual project.
- Update `last_run_at`/`run_count`/`next_run_at` only **after** dispatch succeeds. On thrown error, route through `updateScheduleError` so backoff applies.

**If user asks for cron expressions**: that's a real dependency add (e.g. `cron-parser`). Flag it before adding — current code is interval-only. Don't half-implement.

## Conventions (CLAUDE.md, must follow)

- **Never invoke real `claude` CLI in tests** — mock subprocess.
- All state in SQLite at `~/.claude-bridge/bridge.db` (or `$CLAUDE_BRIDGE_HOME/bridge.db`).
- TypeScript strict mode, Bun runtime + test runner.
- Errors → stderr, output → stdout, exit 0 = success.
- Single responsibility per module; don't merge scheduler concerns into dispatcher.

## Validation checklist (run before declaring done)

```bash
bun test tests/wave4/scheduler.test.ts tests/coverage/evaluator-scheduler-extra.test.ts
bun run typecheck

# end-to-end smoke (requires a real agent already created):
bridge schedule-add <agent> "echo from scheduler" --every 1
bridge schedule-list
# wait ~70s
bridge history     # new task row should be present and have moved past `pending`
bridge schedule-pause <name>
bridge doctor
```

If you wire scheduler into daemon, also restart instances: `bridge restart`.

## Pitfalls / boring causes

- **Tests must not run real timers.** Use long intervals (`scheduler.start(100_000)`) or call `runOnce()` directly. A short `setInterval` will fire during the test suite and pollute state.
- `next_run_at` is stored as ISO string. Compare via `new Date(...).getTime()`, not lexicographically across timezones.
- **Multi-instance:** `CLAUDE_BRIDGE_HOME` switches the DB path. Schedules are per-instance — never assume cross-instance visibility. Each daemon must run its own `Scheduler`.
- The `setInterval` handle is `.unref()`'d ([scheduler.ts:30](src/orchestration/scheduler.ts:30)) so it won't block process exit. Preserve that when refactoring.
- `UNIQUE(name, agent_name)` on `schedules` — duplicate add throws; surface a clean error in CLI, don't crash.

## Out of scope

- Loop orchestrator ([src/orchestration/loop.ts](src/orchestration/loop.ts)) — separate skill territory.
- Permission relay, notification queue, channel adapters.
- Migrating existing scheduled rows on schema change — there are none in production yet.
