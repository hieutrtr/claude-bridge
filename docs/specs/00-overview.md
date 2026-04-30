# 00 — Claude Bridge Overview

A maintainer's map of the system. Read this first, then jump into the subsystem
docs (`01-data-layer.md` through `07-channels.md`). For the deeper dive into
layering rules, dependency direction, and the full data model, see
[`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) — this doc is the fast index, not
a replacement.

## 1. Executive summary

Claude Bridge dispatches Claude Code tasks from messaging channels (Telegram
today; Slack/Discord planned) and relays the results back. A long-lived bridge
process hosts an MCP server that a "bridge bot" (itself a Claude Code session)
calls into. Each tool call fans out to an isolated subprocess: `claude --agent
<name> --session-id <uuid> -p "<task>"`, spawned inside a git worktree with the
Stop hook wired back to `bridge on-complete`. Task state lives in SQLite (WAL)
so the subprocess, the stop hook, and the watcher loop can see each other
without coordination.

The project exists because running `claude` sessions per user/project/chat
combination is error-prone to do by hand — this is the smallest piece of glue
that makes it reliable.

## 2. End-to-end request lifecycle

A Telegram message becomes a dispatched task and a notification back, as
follows. File references are `path:line` and point to the function that owns
each step.

1. **Inbound webhook.** grammy long-polls Telegram inside the bridge process,
   started from
   [`src/mcp/server.ts:122`](../../src/mcp/server.ts) (auto-start block when
   run directly). Handlers live in
   [`src/mcp/telegram-inbound.ts:186`](../../src/mcp/telegram-inbound.ts) for
   text and `:202`, `:226`, `:252`, `:274` for photo/document/voice/audio. The
   allowlist check (`isAllowed`, `src/mcp/telegram-inbound.ts:58`) is
   fail-closed.

2. **Queue + push.** Each allowed message is persisted via
   `MessageDatabase.createInbound` and a JSON-RPC notification
   (`notifications/claude/channel`) is pushed to the MCP client. See
   `pushInbound` at
   [`src/mcp/telegram-inbound.ts:140`](../../src/mcp/telegram-inbound.ts).
   Emission goes through `queuedNotification` in
   [`src/mcp/server.ts:52`](../../src/mcp/server.ts) which defers writes while
   a tool response is in flight (MCP stdio multiplexes responses and
   notifications on one pipe; interleaving breaks the session).

3. **Bot agent reacts.** The bridge bot (a Claude Code instance running in the
   tmux session spawned by `bridge start`) receives the channel notification
   and calls back through MCP. The tool schema lives in
   [`src/mcp/tools.ts`](../../src/mcp/tools.ts); the dispatcher is
   `executeToolNative` at
   [`src/mcp/tool-handlers.ts:34`](../../src/mcp/tool-handlers.ts) → the big
   `switch` in `handleTool` at
   [`src/mcp/tool-handlers.ts:50`](../../src/mcp/tool-handlers.ts).

4. **`bridge_dispatch` tool.** See `case "bridge_dispatch"` at
   [`src/mcp/tool-handlers.ts:91`](../../src/mcp/tool-handlers.ts). It:
   - looks up the agent (`db.getAgent`),
   - calls `db.atomicCheckAndCreateTask` (exclusive SQLite txn — prevents two
     callers from both winning the "is session busy" check),
   - if busy: inserts a `queued` task and returns,
   - if free: calls `startTask` at
     [`src/execution/dispatcher.ts:163`](../../src/execution/dispatcher.ts).

5. **Spawn `claude`.** `startTask` flips the agent to `running`, marks the task
   `running` with `started_at`, then delegates to `Dispatcher.dispatch` at
   [`src/execution/dispatcher.ts:59`](../../src/execution/dispatcher.ts):
   - resolves `sessionUuid = sessionIdToUuid(session_id, task_id)` (MD5 of
     `session_id:task_id`, formatted UUID-style) —
     [`src/execution/dispatcher.ts:22`](../../src/execution/dispatcher.ts),
   - opens `workspaces/<session_id>/tasks/<task_id>.result.json` for stdout and
     `.stderr` for stderr,
   - `Bun.spawn` of `claude --agent <file> --session-id <uuid> --output-format
     json --dangerously-skip-permissions -p "<prompt>"` detached, inheriting
     `CLAUDE_BRIDGE_HOME`,
   - records pid via `db.updateTask(task.id, { pid })`.

6. **`claude` runs inside its worktree.** Worktree isolation is declared in
   the agent `.md` frontmatter (`isolation: worktree`); Claude Code handles
   the git-worktree checkout natively. The bridge never touches it.

7. **Stop hook fires.** When `claude` finishes it invokes the Stop hook
   registered in the project's `.claude/settings.local.json` (installed by
   `installStopHook` in
   [`src/cli/agent-md.ts`](../../src/cli/agent-md.ts)). The hook shells out
   to `bridge on-complete --session-id <sid>`, which lands in `cmdOnComplete`
   at [`src/cli/index.ts:621`](../../src/cli/index.ts). This is an
   **optimistic fast path only** — claude's stdout is block-buffered against
   the result file and often hasn't flushed yet when the hook runs (the hook
   blocks claude's exit). If `parseResultFile` returns `null`, `cmdOnComplete`
   no-ops and lets the watcher finalize.

8. **Watcher finalizes.** The primary completion path is `ProcessWatcher` at
   [`src/execution/watcher.ts:33`](../../src/execution/watcher.ts), polling
   every 5s (see `WATCHER_INTERVAL_MS` in
   [`src/infra/startup.ts:19`](../../src/infra/startup.ts)). When it detects
   the `claude` pid is gone it reads the now-flushed result file and calls
   `CompletionHandler.handleCompletion` at
   [`src/execution/on-complete.ts:57`](../../src/execution/on-complete.ts):
   - updates task row (`status`, `cost_usd`, `duration_ms`, `num_turns`,
     `completed_at`),
   - flips agent back to `idle`,
   - if `channel_chat_id` is set, inserts a row in `notifications` via
     `db.createNotification`
     ([`src/execution/on-complete.ts:89`](../../src/execution/on-complete.ts)),
   - if this task belongs to an active loop, delegates to
     `LoopOrchestrator.onTaskComplete`,
   - otherwise `db.dequeueNextTask(session_id)` and, if present, runs
     `startTask` again for the queued follow-up
     ([`src/execution/on-complete.ts:118`](../../src/execution/on-complete.ts)).

9. **Notify loop.** The 5s notification loop in `StartupOrchestrator` at
   [`src/infra/startup.ts:57`](../../src/infra/startup.ts) drains `pending`
   notifications and calls `Notifier.notify` at
   [`src/execution/notify.ts:73`](../../src/execution/notify.ts), which posts
   directly to `https://api.telegram.org/bot<token>/sendMessage` via `fetch`.
   On success the row is flipped to `sent`; on failure, `failed` (and retried
   next tick? — no, `getPendingNotifications` filters on `status='pending'`, so
   failed rows are terminal until an operator intervenes).

Two safety nets cover the unhappy paths: `ProcessWatcher` also marks dead
processes as `failed` if no result file exists, and any task running past 6h
(`DEFAULT_TIMEOUT_MINUTES = 360` in
[`src/execution/watcher.ts:16`](../../src/execution/watcher.ts)) gets
`status='timeout'` and a `SIGTERM`.

## 3. Module map

One line per top-level directory under `src/`. See sibling specs for depth.

| Path                | Role                                                        | See              |
| ------------------- | ----------------------------------------------------------- | ---------------- |
| `src/types.ts`      | Shared domain types (Agent, Task, Loop, Schedule, …)        | `08` in parent `specs/` |
| `src/config.ts`     | `ConfigProvider` — resolves `CLAUDE_BRIDGE_HOME`, loads `config.json` | `01-data-layer.md` |
| `src/data/`         | SQLite + session-id derivation (`db.ts`, `message-db.ts`, `session.ts`) | `01-data-layer.md` |
| `src/execution/`    | Task lifecycle: spawn (`dispatcher.ts`), stop-hook (`on-complete.ts`), liveness (`watcher.ts`), delivery (`notify.ts`) | `02-execution.md` |
| `src/orchestration/`| Goal loops (`loop.ts`), done-condition evaluators (`evaluator.ts`), cron-like `scheduler.ts` | `03-orchestration.md` |
| `src/cli/`          | `bridge` command dispatcher (`index.ts`), bot-dir scaffolder (`setup-bot.ts`), agent `.md` generator (`agent-md.ts`), diagnostics (`doctor.ts`) | `04-cli.md` |
| `src/mcp/`          | MCP stdio server (`server.ts`), tool registry (`tools.ts`), native tool dispatch (`tool-handlers.ts`), Telegram inbound (`telegram-inbound.ts`) | `05-mcp.md` |
| `src/infra/`        | Boot/shutdown (`startup.ts`), daemon installer (`daemon.ts`), tmux helpers (`bridge-cmd.ts`), permission relay (`permissions.ts`) | `06-infra.md` |
| `src/channel/`      | Platform adapters: `telegram/` (live formatter, adapter stubbed), `slack/` and `discord/` (stubs) | `07-channels.md` |
| `src/index.ts`      | Public API barrel — re-exports layer entry points           | —                |

The docs `01-…md` through `07-…md` are authored in parallel by sibling
agents; this overview intentionally does not describe their internals.

## 4. Runtime & dependency summary

- **Bun** — runtime + test runner. `Bun.spawn`, `bun:sqlite`, `bun test`. All
  source is strict-mode TypeScript (`tsc --noEmit` for the typecheck pass; Bun
  runs `.ts` directly).
- **SQLite (WAL)** — two files under `$CLAUDE_BRIDGE_HOME`: `bridge.db` for
  tasks/agents/loops/schedules/notifications/permissions,
  and `messages.db` for channel I/O queues. WAL is enabled so the main
  process, stop-hook subprocess, and watcher can read/write concurrently.
- **MCP over stdio** —
  [`@modelcontextprotocol/sdk`](https://github.com/modelcontextprotocol/typescript-sdk).
  `StdioServerTransport` is wired in
  [`src/mcp/server.ts:104`](../../src/mcp/server.ts). The server also
  advertises the experimental `claude/channel` capability so Claude Code will
  deliver `notifications/claude/channel` to the bot as user turns.
- **`claude` CLI subprocess** — must be on `PATH`. Spawned with
  `--dangerously-skip-permissions` because background subprocesses have no TTY
  to answer permission prompts (see comment at
  [`src/execution/dispatcher.ts:80`](../../src/execution/dispatcher.ts)).
- **grammy** — Telegram Bot API client used only by
  `src/mcp/telegram-inbound.ts`. Outbound delivery is direct `fetch` via
  `Notifier`, not grammy.
- **zod** — declared dependency (schema validation); used sparingly at MCP
  boundaries.

### Claude Code native features the bridge relies on

| Feature                        | Who provides it | How we use it                                                       |
| ------------------------------ | --------------- | ------------------------------------------------------------------- |
| `--agent <file>`               | Claude Code     | Points at `bridge--<session_id>.md` generated by `cli/agent-md.ts`  |
| `--session-id <uuid>`          | Claude Code     | Deterministic UUID from session_id + task_id — warms Claude's own session cache |
| `isolation: worktree` (agent frontmatter) | Claude Code | Concurrency-safe: each task gets its own git worktree; bridge does not manage it |
| Stop hook                      | Claude Code     | Registered via `.claude/settings.local.json`, calls `bridge on-complete` |
| Auto Memory                    | Claude Code     | Read via `bridge memory` (`src/cli/memory.ts`) — the bridge only displays it |
| Prompt caching                 | Claude Code     | Implicit; bridge keeps `--session-id` stable so Claude's cache hits |

## 5. Boot sequence (`bridge start`)

Triggered from [`src/cli/index.ts:676`](../../src/cli/index.ts) (`cmdStart`).

1. **Config validation.** `validateConfig` in
   [`src/infra/bridge-cmd.ts:149`](../../src/infra/bridge-cmd.ts) checks
   `bot_dir` and telegram token presence.
2. **Daemon-or-tmux fork.**
   - If `isDaemonInstalled(bridgeHome)` → `startDaemon` (launchd `launchctl
     bootstrap` on macOS, `systemctl --user start` on Linux). See
     [`src/infra/daemon.ts:276`](../../src/infra/daemon.ts).
   - Otherwise `startSession` in
     [`src/infra/bridge-cmd.ts:50`](../../src/infra/bridge-cmd.ts) spawns a
     tmux session whose command is `env CLAUDE_BRIDGE_HOME=… claude
     --dangerously-load-development-channels server:bridge
     --dangerously-skip-permissions`. The session cwd is `bot_dir`, so
     `claude` picks up the bot's `.mcp.json` and `CLAUDE.md`.
3. **Bot agent bootstraps.** `claude` in the tmux session spawns `bridge` as
   an MCP stdio server (via the `.mcp.json` in `bot_dir`, written by
   `cli/setup-bot.ts`). That re-enters our codebase at
   [`src/mcp/server.ts:115`](../../src/mcp/server.ts) (`if (import.meta.main)`).
4. **`StartupOrchestrator.start()`** —
   [`src/infra/startup.ts:30`](../../src/infra/startup.ts):
   - opens `BridgeDatabase` on `$CLAUDE_BRIDGE_HOME/bridge.db`,
   - constructs `Dispatcher` + `LoopOrchestrator` + `LoopEvaluator`,
   - `new ProcessWatcher(...).start(5_000)` (5s; unref'd so it doesn't pin
     the event loop),
   - `startNotificationLoop()` (5s; unref'd),
   - `startServer()` — connects MCP over stdio, **blocks** until the
     transport closes.
5. **Optional Telegram inbound.** If `TELEGRAM_BOT_TOKEN` is set, the
   auto-start block in
   [`src/mcp/server.ts:122`](../../src/mcp/server.ts) opens
   `MessageDatabase` and calls `startTelegramInbound`, attaching the grammy
   bot to the same process.
6. **Signal handlers.** `SIGTERM`/`SIGINT` →
   [`src/mcp/server.ts:144`](../../src/mcp/server.ts) (`shutdown`) → stops
   inbound, calls `orchestrator.stop()` (clears watcher, clears notify timer,
   closes DB), `process.exit(0)`.

`bridge stop` is symmetric: daemon path runs `launchctl bootout` / `systemctl
--user stop`; tmux path runs `stopSession`
([`src/infra/bridge-cmd.ts:88`](../../src/infra/bridge-cmd.ts)) which sends
`C-c` and falls back to `tmux kill-session` / `killBridgeProcesses`.

## 6. Glossary

Terms a newcomer will trip on, in rough order of impact:

- **Session** — `agent_name + project_path → session_id`. The session_id is
  literally `"<agent>--<basename(project)>"` (e.g. `backend--my-api`),
  derived in `SessionManager.deriveSessionId` (`src/data/session.ts`). It is
  the primary key for most agent lookups. Do not confuse with Claude Code's
  own session UUID — that's a deterministic hash we feed as `--session-id`.
- **Agent** — a row in the `agents` table: `{ name, project_dir, session_id,
  agent_file, purpose, state, model, … }`. Primary key is `(name,
  project_dir)`. `state ∈ {created, idle, running}`.
- **Agent `.md` file** — a native Claude Code agent spec with YAML
  frontmatter (`isolation: worktree`, Stop hook entry, model, tools) plus a
  markdown body. Generated by `generateAgentMd` in
  [`src/cli/agent-md.ts`](../../src/cli/agent-md.ts). Lives at
  `{bot_dir}/.claude/agents/bridge--<session_id>.md`. Claude Code reads it
  when given `--agent <file>`.
- **Bot dir** — the directory where the bridge-bot (itself a `claude`
  process) runs. Contains `CLAUDE.md`, `.mcp.json`, `.claude/agents/`, and
  `.claude/settings.local.json`. Scaffolded by `bridge setup-bot
  <dir>` — see [`src/cli/setup-bot.ts`](../../src/cli/setup-bot.ts). Its path
  is persisted to `$CLAUDE_BRIDGE_HOME/config.json` as `bot_dir`.
- **Stop hook** — a Claude Code hook type that fires when an agent's run
  ends. We register a `bridge on-complete --session-id <sid>` entry in
  `{project}/.claude/settings.local.json` via `installStopHook`
  ([`src/cli/agent-md.ts`](../../src/cli/agent-md.ts)). It's an optimistic
  fast-path (see
  [`src/cli/index.ts:634`](../../src/cli/index.ts) and
  [`src/execution/watcher.ts:1`](../../src/execution/watcher.ts) for why
  `ProcessWatcher` is the real completion path).
- **Worktree isolation** — declared via `isolation: worktree` in the agent
  `.md`. Claude Code runs each invocation in its own git worktree. The bridge
  does not create or manage these; see
  [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md#5-cross-cutting-concerns) for
  the full note.
- **`CLAUDE_BRIDGE_HOME`** — the env var that selects which instance you're
  talking to. Defaults to `~/.claude-bridge`. Everything state-shaped hangs
  off it: `bridge.db`, `messages.db`, `workspaces/<session_id>/tasks/`,
  `config.json`, `inbox/`, daemon service name. Resolved in every entry
  point (`getBridgeHome` in `src/cli/index.ts`, `getBridgeHome` in
  `src/mcp/tool-handlers.ts`, `ConfigProvider`, etc.).
- **Instance** — a single `CLAUDE_BRIDGE_HOME`. Multiple instances run side
  by side with independent daemons and databases
  (e.g. `~/.claude-bridge` and `~/.claude-bridge-tam`). The daemon service
  name is derived from `basename(bridgeHome)` in
  [`src/infra/daemon.ts:35`](../../src/infra/daemon.ts).
- **Task** — one unit of work (`prompt`, `session_id`, `status`). Status
  transitions: `pending` (just created) → `running` (spawned) → `done` /
  `failed` / `cancelled` / `timeout`. `queued` means the session was busy and
  the task waits in a positional queue, dequeued by `db.dequeueNextTask` in
  `on-complete`.
- **Loop** — iterated task execution with a done-condition. State machine
  lives in `LoopOrchestrator` (`src/orchestration/loop.ts`). Orthogonal to
  individual tasks: each iteration is a real task row with `task_type='loop'`.
  By default, iter 1 is a *planning iteration* (plan-first mode): the agent
  outputs a JSON plan of sub-tasks, then iters 2..N+1 execute one step each
  so the user sees per-step progress. Opt out with `--no-plan` (CLI) or
  `plan_first: false` (MCP). See `03-orchestration.md` §1.6.
- **Schedule** — a periodic task kicker. Polled every 60s by `Scheduler`
  (`src/orchestration/scheduler.ts`) which inserts new tasks on due windows
  and applies exponential backoff on errors (backoff math in
  `BridgeDatabase.updateScheduleError`, not the scheduler).
- **Workspace dir** — `$CLAUDE_BRIDGE_HOME/workspaces/<session_id>/tasks/`,
  where `<task_id>.result.json` (claude's JSON output) and `<task_id>.stderr`
  land. Not a git worktree — see worktree isolation above.
- **Channel** — messaging platform adapter under `src/channel/`. Today only
  Telegram is functional (formatter + inbound handler); Slack/Discord are
  skeletons. Outbound delivery is currently done by `Notifier` directly, not
  through the adapter contract.

---

If any of the above contradicts the code, the code wins — update this doc
rather than the other way around.
