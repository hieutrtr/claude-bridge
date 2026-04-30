# Data Layer

The data layer holds all durable state for a Claude Bridge instance. It is split
into two independent SQLite databases that live under `CLAUDE_BRIDGE_HOME` and a
stateless `SessionManager` that derives filesystem paths and identifiers. Every
long-lived process (the bridge daemon, the MCP server, the Stop-hook subprocess
spawned by the `claude` CLI, and short-lived `bridge` CLI invocations) attaches
to the same two files directly — there is no broker or shared in-memory cache.
That is why WAL mode and narrow, short-lived transactions are load-bearing, not
optional.

## Files in scope

- `src/data/db.ts` — `BridgeDatabase`, the primary store for agents, tasks,
  queues, loops, schedules, permissions, notifications, and teams.
- `src/data/message-db.ts` — `MessageDatabase`, a second store for the
  inbound/outbound channel message queues and poller state.
- `src/data/session.ts` — `SessionManager`, derives session IDs, agent file
  names, worktree paths, and the per-instance prefix used by the daemon.
- `src/data/interfaces.ts` — `IDatabase`, `IMessageDatabase`,
  `ISessionManager`, `IConfigProvider` — the contracts the rest of the codebase
  depends on.
- `src/data/index.ts` — barrel export for the data layer.

## Two databases, one instance

A running instance owns exactly two SQLite files, both sitting directly under
`CLAUDE_BRIDGE_HOME` (default `~/.claude-bridge`, overridden per multi-instance):

- `bridge.db` — opened by `BridgeDatabase` (`src/data/db.ts:49`).
- `messages.db` — opened by `MessageDatabase` (`src/data/message-db.ts:19`).

They are deliberately separate. `bridge.db` is written by the daemon, by every
`bridge` CLI invocation, and — critically — by the `bridge on-complete` process
that runs out-of-band as the `claude` CLI Stop hook. `messages.db` is written
almost exclusively by the channel poller and the notification loop. Keeping
channel I/O out of the agent/task DB keeps poller churn from contending with
stop-hook writes on the same WAL.

Both constructors follow the same pattern: open with `{ create: true }`, enable
WAL, enable foreign keys, call `initSchema()`. `BridgeDatabase` additionally
calls `runMigrations()` — see below.

### `bridge.db` — `BridgeDatabase`

All `CREATE TABLE` statements live in `initSchema()` at `src/data/db.ts:74`. Read
them there; the summaries below are not a substitute.

#### `agents` — `src/data/db.ts:76`

One row per agent, where an agent is bound to a single project directory.

| Column | Type | Notes |
| --- | --- | --- |
| `name` | TEXT NOT NULL | Part of composite PK. |
| `project_dir` | TEXT NOT NULL | Part of composite PK. |
| `session_id` | TEXT NOT NULL UNIQUE | `<agent>--<project-basename>` (see `SessionManager.deriveSessionId`). UNIQUE so tasks and loops can foreign-key onto it. |
| `agent_file` | TEXT NOT NULL | Absolute path to the generated agent `.md`. |
| `purpose` | TEXT | Free-form. |
| `state` | TEXT DEFAULT 'created' | Free-form string, updated via `updateAgentState` (`src/data/db.ts:260`). |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | SQLite `CURRENT_TIMESTAMP` (UTC, `YYYY-MM-DD HH:MM:SS`). |
| `last_task_at` | TIMESTAMP | Set by `incrementAgentTasks` (`src/data/db.ts:264`). |
| `total_tasks` | INTEGER DEFAULT 0 | Incremented by `incrementAgentTasks`. |
| `model` | TEXT DEFAULT 'sonnet' | Updated via `updateAgentModel`. |

Primary key is composite `(name, project_dir)`, but `session_id` is the real
foreign-key target for every other table. `getAgent(name)` looks up by name
only; if you ever introduce two agents with the same name across projects, the
query at `src/data/db.ts:243` will return only one.

#### `tasks` — `src/data/db.ts:90`

One row per dispatched task. Task status values observed in the code:
`pending`, `queued`, `running`, `done`, `failed`, `timeout`, `cancelled`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | Referenced by `notifications.task_id`, `outbound_messages.task_id`. |
| `session_id` | TEXT NOT NULL, FK `agents(session_id)` ON DELETE CASCADE | Deleting an agent removes its tasks. |
| `prompt` | TEXT NOT NULL | Raw user prompt. |
| `status` | TEXT DEFAULT 'pending' | Drives every queue and notification query. |
| `position` | INTEGER | FIFO slot when `status='queued'`; nulled on dequeue (`src/data/db.ts:386`). |
| `pid` | INTEGER | OS PID of the spawned `claude` process, for the fallback watcher. |
| `result_file` / `result_summary` | TEXT | Populated by `on-complete`. |
| `cost_usd`, `duration_ms`, `num_turns`, `exit_code` | numeric/INTEGER | All nullable; set by `on-complete`. |
| `error_message` | TEXT | Set on failure. |
| `model` | TEXT | Resolved model at dispatch time. |
| `task_type` | TEXT DEFAULT 'standard' | Also: loop-iteration tasks use other values. |
| `parent_task_id` | INTEGER FK `tasks(id)` | For sub-tasks; indexed. |
| `channel`, `channel_chat_id`, `channel_message_id` | TEXT | Origin channel metadata (`telegram`, `slack`, `cli`, ...). Default channel is `cli`. |
| `user_id` | TEXT | Channel user identifier. |
| `created_at`, `started_at`, `completed_at` | TIMESTAMP | `created_at` defaults to `CURRENT_TIMESTAMP`; the other two are set explicitly via `utcnow()` strings. |
| `reported` | INTEGER DEFAULT 0 | Boolean flag; notification loop sets it via `markTaskReported` (`src/data/db.ts:335`). |

Indexes: `idx_tasks_status`, `idx_tasks_session`, `idx_tasks_parent`
(`src/data/db.ts:219`). The hot queries — `getRunningTasks`,
`getUnreportedTasks`, `getQueuedTasks`, `getTaskHistory`, `getSubtasks` — all
use one of these indexes.

Writers go through `updateTask` (`src/data/db.ts:321`), which only accepts keys
in the `TASK_UPDATABLE` whitelist at `src/data/db.ts:24`. Adding a new column
that should be writable by `updateTask` means editing that set as well as the
`CREATE TABLE`.

#### `permissions` — `src/data/db.ts:117`

One row per permission prompt relayed to a channel. Status lifecycle:
`pending` → `approved` | `denied` | `timeout`. The timeout is expressed as a
`timeout_seconds` column (default 300) and resolved with SQLite datetime math in
`timeoutPermissions` (`src/data/db.ts:454`). `id` is a caller-supplied string
(the request ID issued by the permission relay), not an autoincrement.

#### `teams` and `team_members` — `src/data/db.ts:130`, `src/data/db.ts:136`

`teams` holds the lead agent; `team_members` is a join table with PK
`(team_name, agent_name)` and `ON DELETE CASCADE` back to `teams`. Only
`agent_name` is stored for members — there is no FK into `agents`, because team
composition is expected to be authored before the agents exist.

#### `notifications` — `src/data/db.ts:142`

Notifications produced by the completion pipeline. Distinct from
`outbound_messages` in `messages.db`: this table holds the *intent* to notify
(`task_id`, `channel`, `chat_id`, `message`), while `messages.db` is the
per-platform send queue with retries. Status values: `pending`, `sent`,
`failed`. Indexed on `status`.

#### `loops` — `src/data/db.ts:153`

One row per orchestration loop. `loop_id` is an 8-char UUID slice
(`src/data/db.ts:540`). Note the timestamps here are `TEXT NOT NULL`, not
`TIMESTAMP` — loop timestamps are always written with `utcnow()` (see gotchas).
Status values include `running`, `done`, `failed`, `cancelled`, `awaiting_approval`.
`current_task_id` is `TEXT` because it can hold either a task row id or a
synthetic id; `getLoopByTaskId` (`src/data/db.ts:621`) looks up by it.
`max_cost_usd` and `pending_approval` are gated by the orchestrator.

Channel-routing columns (`channel`, `channel_chat_id`, `user_id`) carry the
originating chat info so per-iteration and end-of-loop notifications can be
sent back to the right user (`src/orchestration/loop.ts:219 emitLoopNotification`).

Plan-first columns (see `03-orchestration.md` §1.6):
- `plan_enabled` (INTEGER 0/1) — locked when the loop is created. `1` means
  iter 1 is a planning iteration that produces a JSON plan; iters 2..N+1
  each execute one sub-task. Flipped to `0` on plan parse failure (fallback
  to legacy single-shot execution).
- `plan` (TEXT JSON) — populated once after the planning iter parses
  successfully. Shape matches `LoopPlan` in `src/types.ts`:
  `{ steps: [{ id, title, description, verification? }], truncated? }`.
  `truncated: true` means the agent's plan had more steps than
  `max_iterations - 1` allowed.

Consecutive-PASS columns (see `03-orchestration.md` §1.7):
- `pass_threshold` (INTEGER, default 1) — how many consecutive PASS verdicts
  the done condition must produce before the loop terminates. Default 1
  preserves "first PASS wins". `LoopOrchestrator.startLoop` clamps to ≥ 1.
- `consecutive_passes` (INTEGER, default 0) — live counter incremented on
  every PASS verdict and reset to 0 on any non-PASS. The loop finalizes as
  `done` when this counter first hits `pass_threshold`.

Writes go through `updateLoop` (`src/data/db.ts:563`) using the `LOOP_UPDATABLE`
whitelist at `src/data/db.ts:31` (which includes `plan` and `plan_enabled`).

Indexes: `idx_loops_status`, `idx_loops_agent` (`src/data/db.ts:218`).

#### `loop_iterations` — `src/data/db.ts:177`

One row per iteration of a loop. `done_check_passed` is stored as INTEGER (0/1).
`cost_usd` defaults to 0.0 and is summed into `loops.total_cost_usd` by the
orchestrator, not by a trigger — the DB does not maintain that invariant for
you. Writes go through `updateLoopIteration` (`src/data/db.ts:591`) with the
`LOOP_ITER_UPDATABLE` whitelist at `src/data/db.ts:37`. Indexed on `loop_id`.

#### `schedules` — `src/data/db.ts:191`

Recurring or run-once prompts. Unique key is `(name, agent_name)`. `enabled`,
`run_once` are INTEGER booleans. The scheduler computes `next_run_at` in
application code: on success, `updateScheduleSuccess` (`src/data/db.ts:662`) adds
`interval_minutes` to `now`; on failure, `updateScheduleError`
(`src/data/db.ts:675`) applies exponential backoff capped at 8x, then disables
the schedule after 5 consecutive errors. Index: `idx_schedules_next_run` on
`(next_run_at, enabled)` — this is the index the scheduler's
`getDueSchedules(now)` query (`src/data/db.ts:655`) relies on.

### `messages.db` — `MessageDatabase`

Schema lives at `src/data/message-db.ts:26`.

#### `inbound_messages` — `src/data/message-db.ts:28`

One row per message received from a channel. Status lifecycle:
`pending` → `delivered` → `acknowledged`, with `failed` as a terminal error
state. `getUnacknowledgedInbound(timeoutSeconds)` (`src/data/message-db.ts:97`)
re-surfaces stuck-in-`delivered` rows using a datetime comparison against
`delivered_at`. `retry_count` is bumped by `incrementInboundRetry`, which also
resets status to `pending` and clears `delivered_at` — that's the replay path
when the MCP consumer crashes between delivery and ack.

#### `outbound_messages` — `src/data/message-db.ts:44`

Per-platform send queue. Status lifecycle: `pending` → `sent` | `failed`. A
`notified` status is tolerated by `updatePendingOutboundForTask`
(`src/data/message-db.ts:156`) for backward compatibility with older writers.
`task_id` is an INTEGER that joins back to `bridge.db:tasks.id` — but it is *not*
a SQL foreign key, because the two databases are separate files; maintain the
relationship in application code. `hasNotificationForTask`
(`src/data/message-db.ts:149`) is the dedupe check used by the notification
loop. `cleanupOldOutbound` (`src/data/message-db.ts:192`) garbage-collects
terminal rows older than `maxAgeHours` (default 24).

#### `poller_state` — `src/data/message-db.ts:59`

Trivial key/value store for the channel poller (for example, the Telegram
`update_id` offset). Accessed via `getState` / `setState`
(`src/data/message-db.ts:203`, `src/data/message-db.ts:208`).

## WAL mode

Both databases enable WAL on construction:

- `src/data/db.ts:51` — `this.db.exec("PRAGMA journal_mode=WAL")`
- `src/data/message-db.ts:21` — same.

WAL is mandatory, not a tuning knob. The write pattern looks like this:

1. The bridge daemon holds `bridge.db` open for the poller, dispatcher, watcher,
   and notification loop.
2. Every `bridge` CLI command opens its own short-lived connection.
3. Every spawned `claude` subprocess fires a `bridge on-complete` handler that
   opens `bridge.db` and writes task completion fields, cost, and result
   summary — while the daemon is still reading from `tasks`.

Without WAL, the rollback journal serialises readers and writers, so the
stop-hook subprocess would regularly collide with the daemon's task-watching
queries and one of them would see `SQLITE_BUSY`. With WAL, readers use the
snapshot and writers append to the log, so the hook can commit cleanly while
the daemon is iterating. `PRAGMA foreign_keys=ON` is also set on both
databases — it is per-connection in SQLite, so this line must remain in the
constructor, not moved to a one-shot script.

Never downgrade either of these to `DELETE` or `TRUNCATE` journal mode, and
never hold a write transaction open across I/O. The stop-hook subprocess is
hot-path.

## Session ID derivation

`SessionManager` at `src/data/session.ts:13` is stateless apart from `homeDir`.

### `deriveSessionId(agentName, projectPath)` — `src/data/session.ts:16`

Rule: `` `${agentName}--${basename(normalize(projectPath))}` ``. The
project-path half is reduced to its `basename` after `normalize`, so
`/Users/x/projects/my-api` and `/Users/x/projects/my-api/` both produce
`my-api`. Trailing slashes are fine. Two projects with the same basename under
different parents collide — this is accepted because `agents` has `UNIQUE`
on `session_id`, so the second `createAgent` will throw at the DB layer.

### `deriveAgentFileName(sessionId)` — `src/data/session.ts:21`

Always `bridge--<sessionId>`, i.e. the generated `.md` is
`bridge--backend--my-api.md`. The leading `bridge--` namespace is what lets
`bridge delete-agent` prune only agent files it owns.

### `validateAgentName(name)` — `src/data/session.ts:25`

Rules, checked in order:

1. Non-empty.
2. <= 30 characters.
3. Matches `^[a-zA-Z0-9][a-zA-Z0-9-]*$` — alphanumeric plus hyphen, starting
   with a letter or digit.
4. Must not contain `--` (double-dash is the session-ID separator).

Returns an error message or `null`. Callers treat `null` as "valid".

### `validateProjectDir(path)` — `src/data/session.ts:41`

Expands a leading `~` to `homedir()`, then `existsSync`. This is the only place
`~` is expanded by the data layer — every other path passes through unchanged.

### `getInstancePrefix()` — `src/data/session.ts:65`

Used by the daemon to name per-instance launchd/systemd units. If `homeDir`
normalises to `~/.claude-bridge`, the prefix is empty (main instance).
Otherwise it takes `basename(homeDir)`, strips one of the prefixes
`.claude-bridge-`, `claude-bridge-`, `.bridge-`, `bridge-`, sanitises to
`[a-zA-Z0-9-]`, trims leading/trailing hyphens, falls back to `custom` when
empty, and truncates to 20 chars. Changing this is a breaking change for
existing installs — unit filenames are derived from it.

### Workspace helpers

`getWorktreePath`, `getTasksDir`, `getAgentMdPath` are pure path joins.
`createWorkspace` (`src/data/session.ts:83`) creates the tasks dir and drops
`metadata.json` with ISO-8601 `created_at`. `cleanupWorkspace`
(`src/data/session.ts:98`) recursively removes it — it's safe against a missing
directory.

## Public interfaces

From `src/data/interfaces.ts`:

- `IDatabase` (`src/data/interfaces.ts:26`) — contract implemented by
  `BridgeDatabase`; groups methods by concern (agent, task, queue, permission,
  notification, team, sub-task, loop, schedule, cost, lifecycle). Injectable for
  testing.
- `IMessageDatabase` (`src/data/interfaces.ts:154`) — contract implemented by
  `MessageDatabase`; inbound queue, outbound queue, poller state, lifecycle.
- `ISessionManager` (`src/data/interfaces.ts:200`) — contract implemented by
  `SessionManager`; ID/path derivation plus `createWorkspace` /
  `cleanupWorkspace`.
- `IConfigProvider` (`src/data/interfaces.ts:215`) — minimal config reader
  surface: `load()`, `homeDir`, `dbPath`. The implementation lives outside the
  data layer.

## Migrations

There is no `schema_version` table. Migrations are additive and idempotent,
run on every connection.

- `BridgeDatabase.initSchema` (`src/data/db.ts:74`) uses
  `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` — safe on
  subsequent opens, but note it will not modify an existing table.
- `BridgeDatabase.runMigrations` (`src/data/db.ts:62`) is the only place that
  retrofits columns onto pre-existing tables. It currently adds to `loops`:
  `channel`, `channel_chat_id`, and `user_id` (channel-aware loops);
  `plan` (TEXT) and `plan_enabled` (INTEGER DEFAULT 0) for plan-first mode;
  `pass_threshold` (INTEGER DEFAULT 1) and `consecutive_passes` (INTEGER
  DEFAULT 0) for the consecutive-PASS gate. It does so by calling
  `addColumnIfMissing` (`src/data/db.ts:68`), which reads
  `PRAGMA table_info(<table>)` and only issues `ALTER TABLE ... ADD COLUMN`
  when the column is absent.
- `MessageDatabase` has no migration runner — the `messages.db` schema has been
  stable since introduction.

To add a column to an existing table on live installs: add it to the
`CREATE TABLE` in `initSchema` so fresh installs get it, then add an
`addColumnIfMissing` line to `runMigrations` so existing installs pick it up on
the next `BridgeDatabase` construction. If the column should be writable via
`updateTask`/`updateLoop`/`updateLoopIteration`, add it to the matching
whitelist (`TASK_UPDATABLE` at `src/data/db.ts:24`, `LOOP_UPDATABLE` at
`src/data/db.ts:31`, `LOOP_ITER_UPDATABLE` at `src/data/db.ts:37`). To add a
whole new table, put `CREATE TABLE IF NOT EXISTS` in `initSchema` — no
migration hook needed, since it's idempotent for tables.

There is no down-migration. Drop-column or type changes require a manual
SQLite dump-and-reload.

## Query conventions

All callers go through `Database.prepare`-equivalent APIs from `bun:sqlite`:

- `this.db.query(sql).get(...)`, `.all(...)`, or `.run(...)` for parameter
  binding. Never interpolate user input into SQL strings.
- `this.db.run(sql, params)` for INSERT/UPDATE/DELETE.
- Whitelists gate dynamic UPDATE column lists
  (`src/data/db.ts:24`, `src/data/db.ts:31`, `src/data/db.ts:37`). When you
  extend them, the keys must exactly match DB column names because the code
  does `` `${key} = ?` ``.

Transactions use `db.transaction(() => { ... })`:

- `atomicCheckAndCreateTask` (`src/data/db.ts:339`) — the canonical example.
  It uses `.exclusive()` to take an `IMMEDIATE` write lock, checking for a
  running task and inserting a new one in one atomic step so two concurrent
  dispatches cannot both pass the busy check.
- `dequeueNextTask` (`src/data/db.ts:380`) — picks the lowest-position queued
  task, flips it to `pending`, and shifts the other queued rows' positions down
  in the same transaction.
- `createTeam` (`src/data/db.ts:494`) — inserts the team row and all member
  rows atomically.

New queries should follow the same pattern: parameter-bind, wrap multi-statement
state transitions in a transaction, keep the critical section short, do no
I/O inside it. For hot paths that race with `bridge on-complete`, prefer
`exclusive()` over the default immediate-but-non-blocking transaction.

## Gotchas

### Timestamps — two conventions

Two conventions coexist:

- Columns with `DEFAULT CURRENT_TIMESTAMP` (e.g. `agents.created_at`,
  `tasks.created_at`, `permissions.created_at`, `notifications.created_at`,
  most of `schedules`, `inbound_messages.created_at`) use SQLite's
  `YYYY-MM-DD HH:MM:SS` UTC format produced by the engine.
- Columns written from application code use `utcnow()`
  (`src/data/db.ts:42`, `src/data/message-db.ts:12`), which formats
  `new Date().toISOString()` the same way: T replaced with space, Z stripped.
  This is deliberate — it keeps `datetime(col, '+N seconds')` comparisons in
  `timeoutPermissions` (`src/data/db.ts:454`) and `getUnacknowledgedInbound`
  (`src/data/message-db.ts:97`) working against both kinds of row.

Do not write raw `toISOString()` output to a timestamp column — the `T` and
trailing `Z` will break `datetime()` math. Use `utcnow()` or a bare
`CURRENT_TIMESTAMP` default.

Epoch millis do not appear anywhere in these schemas.

### Booleans as INTEGER

SQLite has no boolean type. `tasks.reported`, `loops.pending_approval`,
`loop_iterations.done_check_passed`, `schedules.enabled`, `schedules.run_once`,
`inbound_messages.retry_count` parity checks — all are INTEGER. Writers coerce
with the ternary `? 1 : 0` form (see `addSchedule` at `src/data/db.ts:642`).

### No JSON columns

None of the current tables store JSON. `metadata.json` next to the worktree
(`src/data/session.ts:88`) is the one JSON payload in the data layer, and it
lives on disk, not in SQLite.

### Cross-database joins are not real

`outbound_messages.task_id` joins logically to `bridge.db:tasks.id`, but
SQLite cannot enforce the FK across files. The notification loop keeps them
consistent in application code; bulk operations that delete tasks will leave
orphaned outbound rows unless they also clean up `messages.db`.

### FK cascade is narrow

Only two cascades exist: `tasks.session_id` → `agents.session_id` ON DELETE
CASCADE, and `team_members.team_name` → `teams.name` ON DELETE CASCADE. Deleting
an agent removes its tasks; it does *not* remove related loops, schedules,
permissions, notifications, or outbound messages. Callers that want that must
issue the deletes themselves.

### `updateTask` / `updateLoop` silently drop unknown keys

If `updates` contains no whitelisted keys, `updateTask` (`src/data/db.ts:321`)
returns without running any SQL and reports no error. This is by design — it
keeps callers free to pass broad `Partial<Task>` objects — but it means a typo
in a key name is a silent no-op. When adding new updatable columns, always
extend the whitelist.

### `session_id` uniqueness is load-bearing

`agents.session_id UNIQUE` plus the FK from `tasks.session_id` is what lets the
rest of the code treat a session ID as the primary agent identifier. If you ever
drop the UNIQUE constraint, `getAgentBySession` and every task query stop being
well-defined.

### Agent name lookup collides across projects

The composite PK on `agents` is `(name, project_dir)`, but `getAgent(name)`
(`src/data/db.ts:243`) looks up by name alone. Re-using an agent name across
projects will cause ambiguous lookups in any caller that only has a name;
prefer `getAgentBySession` when a session ID is available.
