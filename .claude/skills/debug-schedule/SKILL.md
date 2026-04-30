---
name: debug-schedule
description: Use this skill when a scheduled task in claude-bridge is not firing, fires but does not run, runs but does not notify, or when the user reports that a `bridge schedule-add` row "doesn't do anything" or "no notification came". Trigger on phrases like "schedule không chạy", "schedule không fire", "không thấy notification", "schedule pending mãi", "scheduled task missing", "không nhận được tin từ schedule", or any debugging question that mentions both `schedule`/`schedule-add` and a missing outcome (task, notification, run_count). Skip for general scheduler feature development (use `develop-scheduler`), for non-schedule notification issues, or for loop orchestrator problems.
---

# Debugging the schedule → task → notification chain

A scheduled run goes through 4 stages. Pinpoint which stage broke, then fix.

```
schedules row  →  Scheduler.runOnce  →  task row dispatched  →  on-complete  →  notification delivered
   (1)              (2)                   (3)                     (4)            (5)
```

## Stage 0 — establish the baseline

```bash
date -u +"%Y-%m-%dT%H:%M:%SZ"      # current UTC, all timestamps in DB are UTC
ls -la ~/.claude-bridge/            # confirm $CLAUDE_BRIDGE_HOME (override with env var)
bridge daemon-status                # session running? PID? uptime?
```

If the user runs a non-default instance (e.g. `CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam`), all queries below must target that DB. **Each instance has its own DB and its own daemon.**

## Stage 1 — schedule row exists and is enabled

```bash
sqlite3 ~/.claude-bridge/bridge.db \
  "SELECT id,name,agent_name,interval_minutes,enabled,run_count,consecutive_errors,
          last_run_at,next_run_at,last_error,channel,channel_chat_id,user_id,created_at
     FROM schedules ORDER BY id;" -header -column
```

Verdict table:

| Symptom | Likely cause |
|---|---|
| `enabled=0` and `consecutive_errors>=5` | Auto-paused after 5 consecutive failures. Inspect `last_error`. |
| `enabled=0`, errors=0 | User ran `schedule-pause` manually. |
| `next_run_at` empty | `addSchedule` failed or schema was edited mid-flight. |
| `next_run_at` ≪ now and `run_count=0` | **Stage 2 problem — scheduler is not running.** Most common case. |
| `channel_chat_id` NULL | `dispatchForSchedule` will create a task with no chat. Notification stage fails silently. |
| `cron_expr` set but `interval_minutes` NULL | Trap. `cron_expr` is a schema stub; **the code only reads `interval_minutes`**. Treat as misconfigured. |
| `run_once=1` set | Trap. `run_once` is a schema stub; the schedule re-fires regardless. Pause manually after first run. |

## Stage 2 — Scheduler is actually running

**This is the most common failure mode.** The `Scheduler` class
([src/orchestration/scheduler.ts:15](src/orchestration/scheduler.ts:15)) is correct
and tested but **historically not wired into the daemon**. Verify:

```bash
grep -n "new Scheduler\|scheduler\.start" src/infra/startup.ts
grep -rn "new Scheduler" src/ --exclude-dir=node_modules
```

If zero hits in `src/infra/startup.ts`, the scheduler **never runs in production**, no matter how many rows are in `schedules`. This is the boring cause; check it before anything else.

If wired but you still see no firing:

```bash
# Is the MCP/daemon process alive and recently started?
ps -ef | grep -E "src/mcp/server\.ts|claude-bridge" | grep -v grep

# Is the source newer than the running process? Old in-memory code won't see fixes.
stat -f "%Sm %N" src/orchestration/scheduler.ts src/infra/startup.ts
ps -p <pid> -o lstart=
```

If source mtime > process start time ⇒ `bridge restart` (kills tmux session
`claude-bridge`, ~few seconds downtime).

Manual fire (bypass timer) for diagnostics:

```bash
bun run -e "
import { Database } from './src/data/db.js';
import { Scheduler } from './src/orchestration/scheduler.js';
const db = new Database(process.env.CLAUDE_BRIDGE_HOME ?? require('os').homedir()+'/.claude-bridge');
const s = new Scheduler(process.env.CLAUDE_BRIDGE_HOME ?? require('os').homedir()+'/.claude-bridge', db);
await s.runOnce();
console.log('runOnce done');
"
```

After a manual `runOnce`, re-query schedules: `next_run_at` should advance,
`run_count` should increment, and a new row in `tasks` should exist with
`session_id={agent}--scheduled`.

## Stage 3 — task row was dispatched (not just inserted)

```bash
sqlite3 ~/.claude-bridge/bridge.db "
  SELECT id,session_id,task_type,status,pid,started_at,completed_at,exit_code,
         channel,channel_chat_id,error_message
    FROM tasks
   WHERE session_id LIKE '%--scheduled' OR session_id LIKE '<agent>--%'
   ORDER BY id DESC LIMIT 10;" -header -column
```

| Symptom | Likely cause |
|---|---|
| Row exists, `status=pending`, `pid=NULL`, `started_at=NULL` | **Second known gap.** `Scheduler.dispatchForSchedule` only `INSERT`s into `tasks` — it does **not** call `Dispatcher.startTask`, and the watcher does not claim `pending` rows. The task will sit forever. ([src/orchestration/scheduler.ts:66](src/orchestration/scheduler.ts:66)) |
| Row missing entirely after `runOnce` | `dispatchForSchedule` threw — check `last_error` on the schedule (`updateScheduleError` was called). |
| `status=running`, `pid` present, but never finishes | Process zombie or `claude` CLI hang. `ps -p <pid>` and `bridge kill <id>`. |
| `status=failed`, `error_message` set | Task ran, `claude` exited non-zero. Inspect agent .md for issues; this is no longer a *scheduling* bug. |
| `channel_chat_id` NULL on the task row | `dispatchForSchedule` propagates `schedule.channel_chat_id` directly. If the schedule was added without channel info (missing CLI flag), the task has no destination. |

## Stage 4 — completion handler ran

```bash
# For a specific task id:
sqlite3 ~/.claude-bridge/bridge.db \
  "SELECT id,status,exit_code,duration_ms,num_turns,cost_usd,reported,
          length(result_summary), substr(result_summary,1,200)
     FROM tasks WHERE id=<task_id>;" -header -column
```

`completed_at` populated + `status` in (`done`,`failed`,`timeout`) means the Stop hook
fired and `bridge on-complete` ran successfully. If `status=running` long after process exit:
- Stop hook didn't fire (check agent .md frontmatter for the hook section).
- Or the `ProcessWatcher` fallback hasn't caught it yet (interval ~10s).

## Stage 5 — notification delivered

```bash
sqlite3 ~/.claude-bridge/bridge.db "
  SELECT id,task_id,status,length(message),created_at,sent_at,
         substr(message,1,80)
    FROM notifications
   ORDER BY id DESC LIMIT 10;" -header -column
```

| Symptom | Likely cause |
|---|---|
| No row exists for the task | `on-complete.ts` skipped because `task.channel_chat_id` was null. Trace back to Stage 3. |
| Row `pending` for >1 minute | Notify loop not running. Check `StartupOrchestrator.startNotificationLoop` is called and MCP server is alive. Loop interval is 5s. |
| Row `failed` | Telegram rejected. Look at stderr — after the recent fix, the log line is `[notify] Telegram http=... ok=... code=... description=...`. Common: `MESSAGE_TOO_LONG` (>4096 UTF-16 units) or `can't parse entities` (from `parse_mode` mismatch — should be plain text now). |
| Row `sent` but user never received | Old code (pre-fix) trusted `resp.ok` without parsing the JSON `{ok:true}` body. Telegram occasionally returns 200 with `{ok:false, description:"..."}` — the message is silently lost. Restart with the patched `notify.ts` ([src/execution/notify.ts](src/execution/notify.ts)) and re-queue: `UPDATE notifications SET status='pending', sent_at=NULL WHERE id=<n>;` |
| `length(message) > 4000` | The summary was inlined whole at [on-complete.ts:88](src/execution/on-complete.ts:88). The new Notifier chunks; verify the running daemon picked up the patched build (mtime check). |

## Quick re-queue helper

After a code fix that requires the notify loop to retry:

```bash
sqlite3 ~/.claude-bridge/bridge.db \
  "UPDATE notifications SET status='pending', sent_at=NULL WHERE id IN (<ids>);"
bridge restart   # so MCP server reloads notify.ts
```

## Manual end-to-end smoke (after fixing wiring)

```bash
bridge schedule-add <agent> "echo schedule smoke" --every 1
sleep 70
sqlite3 ~/.claude-bridge/bridge.db \
  "SELECT id,run_count,last_run_at,next_run_at FROM schedules WHERE agent_name='<agent>';"
bridge history | head -5     # new task should appear
# Pause to stop the loop:
bridge schedule-pause <name>
```

If `run_count` stays at 0 after >1 interval → Stage 2 broken (scheduler not running).
If `run_count` advances but no task in `bridge history` → Stage 3 broken (`dispatchForSchedule` not calling `startTask`).

## Pitfalls / boring causes

- **Wrong DB**: User dispatched on the main instance, scheduled on `tam` instance, then queries the wrong DB. Always confirm `CLAUDE_BRIDGE_HOME`.
- **Daemon was restarted but tmux session was already attached to a stale subprocess** — `bridge daemon-status` shows session uptime; if it predates the source change, restart again.
- **Schedule added with no channel info** when the CLI lacked support. Inspect `channel_chat_id`/`user_id` on the schedule row; fix by deleting and re-adding via the bot (which sets channel context) instead of bare CLI.
- **Clock drift**: VM/container time vs host time. `getDueSchedules` compares to `now` from app code; if `next_run_at` is stored from one clock and queried with another, schedules slip. Compare `date -u` to a `SELECT datetime('now')`.
- **`run_count=0` with `last_run_at` set** — only `updateScheduleSuccess` increments count. If `last_run_at` is populated but count is 0, something wrote the row with `addSchedule` (which sets `next_run_at`, not `last_run_at`) — re-read the row, it's likely `next_run_at` you're looking at.
- **Old in-memory code**: Bun runs TS directly; restarting the source file alone does nothing. The MCP server process (`bun run src/mcp/server.ts`) holds the old module graph until killed. Always check process start time vs source mtime.

## Scope

- In: schedules, tasks coming from schedules, the notify chain for those tasks.
- Out: standalone `bridge dispatch` failures, loop orchestrator, permission relay, agent creation.
