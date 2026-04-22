# Task Execution Pipeline

Reference for how a task goes from `bridge dispatch` to a delivered Telegram
notification. Debugging "task spawned but never completed" or "notification
never fired"? Start here. Each step names the file that owns it, the DB rows
involved, and the failure modes that wedge the system in each state.

**Files in scope**: `src/execution/dispatcher.ts` (spawn),
`src/execution/on-complete.ts` (`bridge on-complete` stop-hook callback and
shared completion finaliser), `src/execution/watcher.ts` (`ProcessWatcher`,
primary completion path), `src/execution/notify.ts` (`Notifier`, Telegram
delivery), `src/execution/interfaces.ts` (four interfaces tying the layer
together), `src/cli/agent-md.ts` (generates agent `.md` and writes the Stop
hook into `{project_dir}/.claude/settings.local.json`), and
`src/infra/startup.ts` (long-lived process that boots the watcher and
notification loops).

**Callers that exercise the pipeline** (orientation only): `bridge dispatch`
in `src/cli/index.ts:225`, the `bridge_dispatch` MCP tool in
`src/mcp/tool-handlers.ts`, and `LoopOrchestrator` in
`src/orchestration/loop.ts`.

## 1. End-to-end shape

```
  bridge dispatch                                  bridge on-complete
      v                                                    ^
  atomicCheckAndCreateTask -> tasks row (pending)          | optimistic,
      v                                                    | usually no-op
  startTask (dispatcher.ts:163)                            |
      - agents.state=running, tasks.status=running         |
      - Dispatcher.dispatch -> Bun.spawn("claude", ...)    |
      - stdout/stderr -> workspace files; proc.unref()     |
      - tasks.pid = proc.pid                               |
                                                           |
  [claude runs; minutes to hours]                          |
                                                           |
  claude finishes -> Stop hook fires ----------------------+
      stdout still buffered, .result.json empty => no-op
      v
  claude exits; stdout flushes to .result.json
      v
  ProcessWatcher.checkOnce (every 5s, watcher.ts:54)
      isAlive(pid) == false
      v
  parseResultFile + handleCompletion (on-complete.ts:33,57)
      - tasks: status=done|failed, cost/duration/summary
      - agents.state=idle
      - dequeueNextTask (maybe startTask again)
      - notifications row created (if channel_chat_id set)
      v
  Notification loop (startup.ts:63, every 5s)
      getPendingNotifications -> Notifier.notify -> Telegram
      markNotificationSent | markNotificationFailed
```

## 2. Dispatch

Owner: `src/execution/dispatcher.ts`. Callers (`bridge dispatch`, the
`bridge_dispatch` MCP tool, and the auto-dequeue path on completion) all
funnel through `startTask` (`src/execution/dispatcher.ts:163`) so bookkeeping
is identical.

### 2.1 Atomic task creation

Before dispatch, the caller holds a transactional gate.
`IDatabase.atomicCheckAndCreateTask` (`src/data/db.ts:339`) opens a `BEGIN
EXCLUSIVE` transaction that (a) checks for any existing row with
`status='running'` for the session and (b) inserts a new row only when none
exists. If the session is already running a task the caller instead inserts a
`status='queued'` row with a position (`src/cli/index.ts:254`). This is the
single serialisation point for concurrent dispatches — see section 8.

### 2.2 startTask

`startTask` (`src/execution/dispatcher.ts:163`) performs four writes in this
order:

1. `agents.state = 'running'` via `updateAgentState`.
2. `tasks.status = 'running'`, `started_at = now().toISOString()`.
3. `Dispatcher.dispatch` spawns the subprocess and returns a PID.
4. `tasks.pid` set to the returned PID.

If `Dispatcher.dispatch` throws (e.g. `claude` missing from PATH), step 4 is
replaced with `status='failed'`, `error_message='Dispatch failed: ...'`,
`completed_at=now`, and `agents.state='idle'`
(`src/execution/dispatcher.ts:183`). No partially-running row survives a spawn
failure.

### 2.3 What `claude` is invoked with

`Dispatcher.dispatch` (`src/execution/dispatcher.ts:59`) builds:

```
claude --agent <agent_file>
       --session-id <uuid(session_id, task_id)>
       --output-format json
       --dangerously-skip-permissions
       [--model <model>]
       -p "<task prompt>"
```

- `--session-id` is a deterministic MD5-derived UUID of `session_id:task_id`
  (`src/execution/dispatcher.ts:22`). Claude Code uses it to bucket session
  state including Auto Memory.
- `--dangerously-skip-permissions` is mandatory: subprocess mode has no TTY,
  so any interactive permission prompt would hang on the first tool call.
- No `--output-file` flag exists. `--output-format json` writes to stdout;
  dispatcher redirects stdout to
  `{home}/workspaces/{session_id}/tasks/{task_id}.result.json` via
  `openSync` (`src/execution/dispatcher.ts:103`). `parseResultFile` reads it.
- Stderr redirects to `{task_id}.stderr` in the same directory.
- `cwd` is `projectDir`, **not** an isolated worktree — Claude Code handles
  isolation (section 7).
- `CLAUDE_BRIDGE_HOME` is forwarded so the stop-hook subprocess finds the
  correct DB.

### 2.4 PID tracking and liveness

`Bun.spawn` returns a `Subprocess`; `.pid` is written to `tasks.pid`. The
dispatcher calls `proc.unref()` (`src/execution/dispatcher.ts:115`) so the
child does not keep the daemon alive — the daemon may restart while `claude`
keeps running; on restart only the DB row and PID survive, and the watcher
reconciles.

Liveness uses `process.kill(pid, 0)` in both `Dispatcher.isRunning`
(`src/execution/dispatcher.ts:46`) and `ProcessWatcher.isAlive`
(`src/execution/watcher.ts:106`) — the null signal throws if the process is
gone or not owned. It does not distinguish zombie from running and returns
true for a recycled PID. Recycled-PID risk is low in practice (`claude`
runs for minutes-to-hours) but not zero.

### 2.5 Cancellation

`Dispatcher.cancel` (`src/execution/dispatcher.ts:125`): `SIGTERM`, poll
`isRunning` every 100ms up to `timeout` seconds (default 10), then `SIGKILL`
if still alive. `bridge kill` uses this. The watcher's timeout branch sends
`SIGTERM` only (no escalation); the next cycle will reap the PID.

## 3. Stop-hook wiring (agent-md.ts)

Easy to get wrong and has historically stranded tasks.

### 3.1 Where the hook lives

`generateAgentMd` (`src/cli/agent-md.ts:53`) produces the agent `.md` at
`{bot_dir}/.claude/agents/bridge--{session_id}.md`. The frontmatter's
`hooks.stop` block is **ignored by Claude Code** — documentation only. The
real wiring is `installStopHook` (`src/cli/agent-md.ts:134`), which writes
(or merges into) the **project's** `{project_dir}/.claude/settings.local.json`
with the schema Claude Code actually honours:

```
{ "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": "<cmd>" } ] } ] } }
```

Gotchas: event name is capitalised `Stop` (legacy lowercase migrated at
`src/cli/agent-md.ts:160`); each group nests a `hooks: [{ type, command }]`
array (legacy flat `{ command }` rewritten at `src/cli/agent-md.ts:169`);
session-scoped entries are removed and re-added so legacy commands pointing
at the removed Python `bridge-cli` get replaced (`src/cli/agent-md.ts:180`).

The command written is literally:

```
CLAUDE_BRIDGE_HOME={home} bridge on-complete --session-id {session_id}
```

If any detail is wrong (lowercase event, flat shape, wrong home), Claude
Code silently ignores the hook and tasks stay `running` until
`ProcessWatcher` finalises via the PID-death fallback. Most common "hook not
firing" bug — check `settings.local.json` shape first.

### 3.2 Runtime path

When `claude` finishes, it invokes the Stop command as a short-lived
subprocess — a fresh `bridge` invocation that enters `main`
(`src/cli/index.ts:999`), opens its own `BridgeDatabase`
(`src/cli/index.ts:1017`), and closes it on return. SQLite runs in WAL mode
(`PRAGMA journal_mode=WAL` at `src/data/db.ts:51`), so the hook process and
the long-lived daemon read/write `bridge.db` concurrently without
corruption. **Do not** change to default rollback journal mode.

`cmdOnComplete` (`src/cli/index.ts:621`) looks up the single
`status='running'` row via `getRunningTask` (returning 0 silently if none —
watcher already finalised or task was killed), constructs `Dispatcher`,
`LoopOrchestrator`, and `CompletionHandler`, then calls `parseResultFile`.
If it returns a parsed result, `handleCompletion` runs; if `null`, the hook
is a no-op.

### 3.3 Why the hook is usually a no-op

Most counter-intuitive part of the pipeline. Claude Code runs the Stop hook
**inside the `claude` process**, blocking exit until the hook returns.
`claude`'s stdout is block-buffered when redirected to a file, so the result
JSON is not flushed until process exit. Therefore at hook time `.result.json`
is empty/partial, `parseResultFile` returns `null`, `handleCompletion` is not
called, and the hook exits 0. Then `claude` exits, stdout flushes, and the
file becomes readable. Documented at `src/execution/on-complete.ts:33` and
`src/execution/watcher.ts:1`. The hook is retained as an optimistic fast
path only; the real completion path is the watcher.

## 4. `handleCompletion` — shared finaliser

`CompletionHandler.handleCompletion` (`src/execution/on-complete.ts:57`) is
the single function that finalises a task. Called by the watcher (usual path)
and the stop hook (rare fast path); both funnel here so DB transitions are
identical.

1. Load the task row. If gone, return.
2. `isSuccess = result.exitCode === 0`.
3. `updateTask`: `status = 'done' | 'failed'`, `result_summary` (success) or
   `error_message` (failure), `cost_usd`, `duration_ms`, `num_turns`,
   `exit_code`, `completed_at`.
4. `updateAgentState(session_id, 'idle')`.
5. If `task.channel_chat_id` is set, `createNotification` inserts a
   `status='pending'` row. Does **not** call Telegram; the notification loop
   picks it up (section 6).
6. If the task belongs to an active goal loop
   (`getActiveLoopForAgent(agent.name).current_task_id === String(taskId)`),
   invoke `onLoopTaskComplete` and set `loopHandled=true`. This replaces
   auto-dequeue because the orchestrator may dispatch its own follow-up;
   double-dispatch would break the running-task invariant.
7. If `!loopHandled`, `dequeueNextTask(session_id)`. If it returns a queued
   task and a dispatcher is available, `startTask` promotes it. This is how
   queued tasks run serially without external polling.

### 4.1 parseResultFile tolerances

`parseResultFile` (`src/execution/on-complete.ts:33`) extracts `cost_usd`
from `total_cost_usd` (current key) or `cost_usd` (legacy), plus `summary`
(`result`), `duration_ms`, `num_turns`, and `exitCode = is_error ? 1 : 0`.
JSON parse errors or missing file return `null`; callers must handle it.

## 5. ProcessWatcher — primary completion path

Owner: `src/execution/watcher.ts`. Started by `StartupOrchestrator`
(`src/infra/startup.ts:41`) at boot with a 5-second interval
(`WATCHER_INTERVAL_MS` at `src/infra/startup.ts:19`). Timer is `unref`'d
(`src/execution/watcher.ts:41`).

### 5.1 Why it exists

The stop hook cannot see the result file (section 3.3). `ProcessWatcher` is
what actually promotes tasks from `running` to `done`/`failed`/`timeout`. It
also reconciles state after a daemon restart: the daemon can restart while
spawned `claude` processes keep running, and on boot the watcher sees stale
`running` rows with valid PIDs and does the right thing.

### 5.2 checkOnce

`checkOnce` (`src/execution/watcher.ts:54`) iterates every
`status='running'` row (`getRunningTasks` at `src/data/db.ts:305`):

1. Skip if `task.pid` is null (spawn in flight between `startTask` step 2 and
   step 4).
2. `isAlive(pid)` via `kill(pid, 0)`.
3. **Alive** + elapsed from `started_at` > `DEFAULT_TIMEOUT_MINUTES`
   (default 360 = 6h): `status='timeout'`, `error_message`, `completed_at`,
   agent idle, best-effort `SIGTERM`. No `SIGKILL` escalation — next cycle
   reaps.
4. **Dead**: `parseResultFile` on `{id}.result.json`. If it parses, delegate
   to `handleCompletion` (handles DB, notifications, loop callback, queue
   dequeue in one shot — section 4). Otherwise `status='failed'`,
   `error_message = "Process {pid} died without writing a result"`, agent
   idle.

### 5.3 Latency

Expected delay between `claude` exit and DB showing `done` is 0–5 seconds.
Longer means the watcher is not running (check `bridge logs`) or the event
loop is blocked.

## 6. Notifier and the notification loop

Owner: `src/execution/notify.ts`. Driver: `startNotificationLoop`
(`src/infra/startup.ts:57`), also 5-second interval.

### 6.1 Separation of concerns

`handleCompletion` does **not** send messages. It inserts a
`notifications.status='pending'` row via `createNotification`
(`src/data/db.ts:466`). The notification loop is the only code that talks to
Telegram. This split means the Telegram transport being slow or down does not
stall the completion path, and failed sends are observable as
`status='failed'` rows rather than lost in stderr.

### 6.2 The loop

Every 5 seconds:

1. `getPendingNotifications` (`src/data/db.ts:478`) returns rows with
   `status='pending'` ordered by `created_at`.
2. `Notifier.notify` (`src/execution/notify.ts:73`) `POST`s to
   `https://api.telegram.org/bot<token>/sendMessage`.
3. On HTTP `ok`, `markNotificationSent` (sets `status='sent'`,
   `sent_at=now`). Otherwise `markNotificationFailed` (`status='failed'`).

### 6.3 Deduplication

The `status` column **is** the dedup key. The loop only selects
`status='pending'`; once transitioned to `sent` or `failed`, the row is
excluded from future passes. There is no separate `notified` flag — do not
add one. To re-send, flip `status` back to `'pending'` directly.
`Notifier.retryFailed` is a stub (`src/execution/notify.ts:96`); implement
it by flipping status, not by bypassing the table.

### 6.4 Message format and token resolution

`formatMessage` (`src/execution/notify.ts:16`) is the canonical shape used by
ad-hoc call sites. The `createNotification` path in `handleCompletion`
builds a simpler message inline (`src/execution/on-complete.ts:86`); the
two are not identical — intentional, since the channel adapter eventually
picks the right one. Do not unify without checking the Telegram adapter.

`Notifier.getBotToken` (`src/execution/notify.ts:58`) reads
`config.json#telegram_token` first, then falls back to
`TELEGRAM_BOT_TOKEN` env. If neither is set, `notify` returns `false` and
the row is marked `failed`.

## 7. Worktree isolation

The bridge **does not** create git worktrees itself. The agent `.md`
frontmatter contains `isolation: worktree` (`src/cli/agent-md.ts:26`), which
tells Claude Code to allocate an isolated worktree per session. The dispatcher
passes `cwd: projectDir` to `Bun.spawn` (`src/execution/dispatcher.ts:108`);
Claude Code checks out into its own worktree under its own control.

Bridge-owned: `{home}/workspaces/{session_id}/` (per-session scratch,
`src/data/session.ts:49`) containing `metadata.json` (from `createWorkspace`
at `src/data/session.ts:83`), `tasks/{task_id}.result.json` (`claude`
stdout), and `tasks/{task_id}.stderr`.

Not bridge-owned: the actual git worktree — Claude Code's lifetime and
cleanup. `SessionManager.cleanupWorkspace` (`src/data/session.ts:98`) removes
only `{home}/workspaces/{session_id}`, not any Claude-Code-managed worktree.
Result files accumulate indefinitely; there is no retention policy — a known
gap.

## 8. Concurrency model

**One running task per session.** Invariant: at most one
`tasks.status='running'` row per `session_id`. Enforced by
`atomicCheckAndCreateTask` (`src/data/db.ts:339`, exclusive transaction),
`handleCompletion` (flips `running` → `done`/`failed` before dequeuing), and
`ProcessWatcher.checkOnce` (same, for the dead-PID path). Concurrent
`bridge dispatch` calls to the same session: first wins the transaction and
runs; the rest get `isBusy=true` and insert `status='queued'` rows
(`src/cli/index.ts:254`).

**Multiple sessions** run in parallel. No global concurrency cap. WAL mode
(`src/data/db.ts:51`) tolerates many concurrent writers; contention is
per-row.

**Daemon + stop-hook concurrency.** The daemon holds a long-lived
`BridgeDatabase` (`src/infra/startup.ts:32`). Every `bridge on-complete` is
a **separate** short-lived process with its own `BridgeDatabase`
(`src/cli/index.ts:1017`). Both share `bridge.db`. WAL mode is what makes
this safe. "Database is locked" errors from the stop hook mean
`PRAGMA journal_mode=WAL` was lost.

**Backpressure: none explicit.** 50 dispatches at a busy agent produce one
`running` row and 49 `queued` rows; the queue drains serially via
`handleCompletion`'s dequeue. No length cap. An overwhelmed agent shows up
as a growing `getQueuedTasks` count; `bridge status` surfaces it.

## 9. State machine

Task `status` transitions. Parentheses name the owning file.

```
  (nothing) --atomicCheckAndCreateTask (data/db.ts:339)--> pending
                                                             |
                                                             | startTask
                                                             v
                                                          running
                                                          /  |  \
   handleCompletion,                       watcher.ts:67 /   |   \ startTask spawn
   exitCode == 0                           elapsed > 6h /    |    \ throws
                                           pid alive   /     |     \ (dispatcher.ts:183)
                                                      v      v      v
                                                   timeout  done   failed
                                                                    ^
                                                                    | handleCompletion,
                                                                    | exitCode != 0 OR
                                                                    | parseResultFile null

  (nothing) --> queued --dequeueNextTask--> pending
                  |
                  | cancelQueuedTask
                  v
                cancelled
```

- No explicit `killed` status. `bridge kill` calls `Dispatcher.cancel`;
  after the PID dies, `ProcessWatcher` marks the row `failed` next cycle
  with `error_message = "Process {pid} died without writing a result"`.
- `cancelled` is reachable only from `queued`, never from `running`.
- `pending` is short-lived: between `atomicCheckAndCreateTask` insert and
  `startTask`'s first `updateTask`. On queued → pending, `startTask`
  immediately flips pending → running. A row stuck in `pending` means
  `startTask` crashed between the insert and its first write — check for
  spawn failures in logs.

## 10. Known failure modes

### 10.1 Task spawned but never completed

`tasks.status='running'` for a long time, PID no longer alive.

1. Daemon running? `bridge daemon-status`. If no, watcher is not polling.
2. Watcher started? `bridge logs` should show `[startup] ProcessWatcher
   started (5s interval)` (`src/infra/startup.ts:47`).
3. PID dead? `kill -0 <pid>`. If dead, watcher should reap within 5s.
4. `{home}/workspaces/{session_id}/tasks/{task_id}.result.json` exists? If
   yes, watcher should have called `handleCompletion`. If no, expect
   `status='failed'` with "died without writing a result" — check `.stderr`
   to see why `claude` crashed before flushing.

### 10.2 Stop hook not firing

Usually irrelevant — the watcher is the primary path (section 3.3). But if
the optimistic fast path matters:

1. `{project_dir}/.claude/settings.local.json` `hooks` block must use
   capitalised `Stop` and nested `{ hooks: [{ type, command }] }`. Flat
   `{ command }` is ignored.
2. Command must be `bridge on-complete --session-id <session_id>`; legacy
   `bridge-cli` targets mean re-run `bridge create-agent` to rewrite
   (`src/cli/agent-md.ts:180`).
3. `CLAUDE_BRIDGE_HOME` in the hook command must match the daemon's home
   (relevant for multi-instance setups).

### 10.3 Notification never fired

1. `notifications` row exists? `SELECT * FROM notifications WHERE task_id =
   ?`. If missing, `task.channel_chat_id` was null at `handleCompletion` —
   check the `dispatch` call.
2. Row `status='pending'`? Notification loop is not running — check
   `[startup] Notification loop started` in `bridge logs`.
3. Row `status='failed'`? Token resolution (`src/execution/notify.ts:58`):
   `config.json#telegram_token` or `TELEGRAM_BOT_TOKEN`. Wrong token → every
   row fails on first try.
4. Row `status='sent'` but user did not see it? Verify `chat_id`.

### 10.4 Stale PID after daemon restart

On restart the watcher inherits all `running` rows. Live PIDs → left alone
(finalise on exit). Dead PIDs → `failed` within 5s. **Recycled** PIDs (rare)
→ watcher sees a live unrelated process and waits up to 6h for timeout;
inspect `ps -p <pid> -o command=` manually before trusting the watcher.

### 10.5 Double-dispatch after loop iteration

If both the loop callback and auto-dequeue fire, you get two `running` rows
and the invariant breaks. Prevented by `loopHandled` in `handleCompletion`
(`src/execution/on-complete.ts:108`): a successful loop callback skips
`dequeueNextTask`. Callback failures log at
`src/execution/on-complete.ts:110` but do **not** set `loopHandled=true`, so
the queue still advances — intentional.
