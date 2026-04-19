# Claude Bridge Architecture

This document describes the current architecture of the `claude-bridge` project for
new contributors. It covers layering, data flow, and the background services that
keep multi-session Claude Code dispatch running.

## 1. Overview

Claude Bridge dispatches tasks to native Claude Code agents from messaging
channels (primarily Telegram). Each session is a pairing of an agent and a
project directory. The bridge runs as a long-lived process that owns an MCP
server (for Claude Code to call), an SQLite database, and a small number of
background loops.

- **Runtime:** [Bun](https://bun.sh) (uses `Bun.spawn`, `bun:sqlite`, Bun test
  runner). All source is TypeScript with strict mode.
- **Storage:** SQLite with WAL journaling (`bridge.db` and `messages.db`). WAL
  enables concurrent read/write between the bridge process and stop-hook
  sub-invocations.
- **IPC:** MCP (Model Context Protocol) over stdio JSON-RPC between Claude Code
  and the bridge's MCP server. Stop hooks re-enter the codebase through
  `bridge on-complete`.
- **Integration with Claude Code:** Relies on native Claude Code features —
  `--agent`, `--session-id`, `isolation: worktree`, Auto Memory, Stop hooks.
  The bridge never reimplements these; it only wires up the glue.

High-level flow:

```
  +----------+   +-----+   +-----+   +------------+   +-------------+
  | Bot/User |-->| MCP |-->| CLI |-->| Dispatcher |-->| Claude Code |
  +----------+   +-----+   +-----+   +------------+   +------+------+
                                                             |
                                                             v
                                                      +-------------+
                                                      | Stop hook   |
                                                      | (on-complete|
                                                      +------+------+
                                                             |
                                                             v
                                                      +-------------+
                                                      |  SQLite     |<--+
                                                      +------+------+   |
                                                             |          |
                                                             v          |
                                                      +-------------+   |
                                                      |  Notifier   +---+
                                                      | (5s loop)   |
                                                      +-------------+
```

## 2. Layered Architecture

Each layer has a single responsibility and exports a small, stable interface.
Layers import downwards only (higher layers may depend on lower ones, never the
reverse).

### `data/` — persistence & session identity

Owns both SQLite files and the session-id derivation rules.

- `BridgeDatabase` (`data/db.ts`) — the primary store. Manages agents, tasks,
  loops, loop iterations, schedules, permissions, notifications, and teams.
  Schema is created on construction; WAL and foreign keys are enabled.
  Notable method: `atomicCheckAndCreateTask()` wraps a busy-check + insert in
  an exclusive transaction to prevent races.
- `MessageDatabase` (`data/message-db.ts`) — a separate DB for channel I/O
  (inbound / outbound message queues + a key-value poller-state table). Keeps
  the message traffic isolated from the task schema.
- `SessionManager` (`data/session.ts`) — derives `session_id` (`agent--project`),
  agent-file names, worktree paths, and resolves bot/instance directories.
- `interfaces.ts` — `IDatabase`, `IMessageDatabase`, `ISessionManager`,
  `IConfigProvider` contracts used everywhere else.

### `execution/` — running tasks & reacting to completion

- `Dispatcher` (`execution/dispatcher.ts`) — spawns `claude` via `Bun.spawn`
  with a detached process group. Computes the deterministic session UUID
  (MD5 of `session_id[:task_id]`), sets `--agent`, `--session-id`,
  `--output-format json`, `--output-file <path>`, and opens the stderr file.
  Also implements `cancel()` (SIGTERM → wait → SIGKILL) and `isRunning()`.
- `CompletionHandler` (`execution/on-complete.ts`) — the stop-hook callback.
  Parses the result file, updates the task row, flips agent state back to
  `idle`, enqueues a notification if the task came from a channel, and
  auto-dequeues the next task for the same session.
- `ProcessWatcher` (`execution/watcher.ts`) — a 30s polling fallback. Marks
  dead processes as `failed` (stop hook missed) and tasks running longer than
  `DEFAULT_TIMEOUT_MINUTES` (360 = 6h) as `timeout`.
- `Notifier` (`execution/notify.ts`) — posts task completion to Telegram via
  the Bot API. Reads the token from `config.json` or `TELEGRAM_BOT_TOKEN`.
  Also contains `formatMessage(task, agentName)` used for display.

### `orchestration/` — goal loops & recurring schedules

- `LoopOrchestrator` (`orchestration/loop.ts`) — state machine for iterative
  task execution. `startLoop` validates the done condition, records the loop,
  and dispatches iteration 1. `onTaskComplete` accumulates cost, evaluates the
  done condition, and either finishes the loop, fails it (cost ceiling,
  consecutive failures, max iterations), pauses for manual approval, or
  dispatches the next iteration with truncated feedback. Also decides loop
  type (`bridge` vs `agent`) and formats display output.
- `LoopEvaluator` (`orchestration/evaluator.ts`) — parses done-condition
  strings (`type:args`) and evaluates `command`, `file_exists`,
  `file_contains`, `llm_judge`, and `manual` condition types. `command` shells
  out with `Bun.spawn sh -c`; `llm_judge` shells out to `claude --print`.
- `Scheduler` (`orchestration/scheduler.ts`) — 60s poller. `runOnce` pulls due
  schedules and calls `dispatchForSchedule` (which calls
  `updateScheduleSuccess`). Errors flow through `db.updateScheduleError` for
  exponential backoff (the DB method contains the backoff math, not the
  scheduler).

### `cli/` — `bridge` command dispatcher

- `cli/index.ts` — manual arg parser and command registry. Handlers cover
  agent lifecycle (`create-agent`, `delete-agent`, `list-agents`, `status`),
  task ops (`dispatch`, `kill`, `history`, `cost`, `set-model`, `memory`),
  loops (`loop`, `loop-status`, `loop-cancel`, `loop-approve`, `loop-reject`,
  `loop-list`, `loop-history`), schedules (`schedule-add`, `-remove`, `-list`,
  `-pause`, `-resume`), bot lifecycle (`start`, `stop`, `restart`, `attach`,
  `daemon-status`, `logs`), daemon install (`install`, `uninstall`), the
  bot-dir scaffolder (`setup-bot`), diagnostics (`doctor`), and the stop-hook
  callback `on-complete`. `attach` drops the caller into the running tmux
  session; `doctor` shells out checks for the `bridge`/`claude`/`tmux`
  binaries, the bot-dir layout (`CLAUDE.md`, `.mcp.json`,
  `.claude/settings.local.json`), the Telegram token, and daemon /
  tmux-session state, returning non-zero if any check fails.
- `cli/setup-bot.ts` — scaffolds `{bot-dir}/CLAUDE.md`, `.mcp.json`,
  `.claude/agents/` and persists `bot_dir` / `telegram_token` to
  `{bridgeHome}/config.json`. Interactive by default; honors
  `--telegram-token`, `--no-prompt`, `--force`.
- `cli/agent-md.ts` — generates the native Claude Code agent `.md` (YAML
  frontmatter + markdown body) including the stop-hook wiring
  (`bridge on-complete --session-id ...`). Also installs
  `.claude/settings.local.json` hook entries via `installStopHook`.
- `cli/memory.ts` — reads Claude Code's Auto Memory directory for a project
  (`~/.claude/projects/{encoded}/memory/`) and formats a human-readable
  report.
- `cli/claude-md.ts` — shells out to `claude -p` to generate or append a
  project-level `CLAUDE.md`.

### `mcp/` — MCP server Claude Code talks to

- `mcp/server.ts` — creates a `Server` from `@modelcontextprotocol/sdk`,
  registers `ListTools` and `CallTool` handlers, and connects over stdio.
  When run directly, it delegates to `StartupOrchestrator` instead of starting
  bare — so spawning the MCP server also spins up background services.
- `mcp/tools.ts` — the authoritative tool registry: `TOOL_NAMES` and
  `TOOL_DEFINITIONS`, plus `buildCliArgs` (legacy Python-fallback helper) and
  `executeTool` (shells out to `bridge`, kept for compatibility).
- `mcp/tool-handlers.ts` — `executeToolNative`: each tool routes directly into
  the TS layers (DB, `LoopOrchestrator`, `Dispatcher`, `Notifier`,
  `MessageDatabase`, etc.). This is the path used in production.
- `mcp/bridge-md.ts` — generates the bridge-bot `CLAUDE.md` that documents the
  tool surface to the bot agent.

### `infra/` — process & service lifecycle

- `infra/startup.ts` — `StartupOrchestrator` wires the three background
  pieces: `ProcessWatcher` (30s), a notification delivery loop (5s), and the
  MCP server (blocking on stdio). `stop()` tears everything down cleanly.
- `infra/daemon.ts` — generates and installs `launchd` plists (macOS) or
  systemd user units (Linux) that launch the bridge inside a tmux session
  with `CLAUDE_BRIDGE_HOME` set. Driven by `bridge install` /
  `bridge uninstall` / `bridge daemon-status`.
- `infra/bridge-cmd.ts` — tmux session helpers, config validation
  (`validateConfig`), and process cleanup (`killBridgeProcesses` using `pkill`
  against known patterns). Used by `bridge start` / `bridge stop` /
  `bridge restart` when no OS daemon is installed.
- `infra/permissions.ts` — `PreToolUse` hook handler. Records a permission
  request, polls the DB every 2s, returns exit code 0 (approved) / 2 (denied
  or timeout). Default timeout 300s.

### `channel/` — multi-platform adapters

- `channel/interface.ts` — `IChannelAdapter`, `IMessageFormatter`,
  `ChannelMessage`, `ChannelFile`, `SendOpts`. The adapter contract covers
  lifecycle, send/edit/delete, optional reactions, file download, and
  message/command event handlers.
- `channel/core.ts` — shared access-control helpers (`isAllowed`,
  `loadAllowlist`). Most of this is marked TODO / Phase 2.
- `channel/telegram/` — `TelegramAdapter` and `TelegramFormatter`. The
  formatter produces HTML for Telegram Bot API; the adapter is a skeleton
  (methods throw `Not implemented`) pending the Phase 2 extraction from the
  legacy Python bot. (stub)
- `channel/discord/` — `DiscordAdapter`, `DiscordFormatter`. (stub, Phase 3)
- `channel/slack/` — `SlackAdapter`, `SlackFormatter`. (stub, Phase 6)

The Telegram adapter is currently the only one with a functional formatter;
all three adapter classes are skeletons. Outbound Telegram delivery is
performed directly by `Notifier` via `fetch()`, not through the adapter.

### Layer dependency table

| Layer           | Imports from                                 | Exported to                 |
| --------------- | -------------------------------------------- | --------------------------- |
| `types.ts`      | —                                            | all layers                  |
| `config.ts`     | `types`, `data/interfaces`                   | `cli`, `mcp`, `infra`       |
| `data/`         | `types`                                      | `execution`, `orchestration`, `cli`, `mcp`, `infra` |
| `execution/`    | `types`, `data/interfaces`                   | `cli`, `mcp`, `infra`       |
| `orchestration/`| `types`, `data/interfaces`                   | `cli`, `mcp`                |
| `channel/`      | (self-contained; `data/message-db` planned)  | (future bot integration)    |
| `mcp/`          | `data`, `execution`, `orchestration`, `cli`, `infra` | top-level `index.ts` |
| `cli/`          | `data`, `execution`, `orchestration`         | bin entry point             |
| `infra/`        | `data`, `execution`, `mcp`                   | daemon entry, `mcp/server`  |

## 3. Core Domain Model

All types live in `src/types.ts`. Field names mirror the SQLite schema.

- **Agent** — `{ name, project_dir, session_id, agent_file, purpose, state,
  created_at, last_task_at, total_tasks, model }`. `state ∈ {created, idle,
  running}`. Primary key is `(name, project_dir)`; `session_id` is unique.
- **Session** — the derived `{ session_id, agent_name, project_path }` view.
  Not persisted on its own; reconstructed from `Agent`.
- **Task** — `{ id, session_id, prompt, status, position, pid, result_file,
  result_summary, cost_usd, duration_ms, num_turns, exit_code, error_message,
  model, task_type, parent_task_id, channel, channel_chat_id,
  channel_message_id, user_id, created_at, started_at, completed_at,
  reported }`. `status ∈ {pending, running, done, failed, cancelled, timeout,
  queued}`. `task_type ∈ {standard, loop, schedule}`. `position` is the queue
  slot when status is `queued`.
- **Loop** — `{ loop_id, agent, project, goal, done_when, loop_type, status,
  max_iterations, max_consecutive_failures, current_iteration,
  consecutive_failures, total_cost_usd, max_cost_usd, pending_approval,
  started_at, finished_at, finish_reason, current_task_id }`.
  `status ∈ {running, paused, done, failed, timeout, cancelled}`. `loop_id`
  is an 8-char UUID slice.
- **LoopIteration** — per-iteration record with `task_id`, `prompt`,
  `result_summary`, `done_check_passed`, `cost_usd`, timestamps, `status`.
- **Schedule** — `{ id, name, agent_name, prompt, interval_minutes, cron_expr,
  run_once, enabled, run_count, consecutive_errors, last_run_at, next_run_at,
  last_error, channel, channel_chat_id, user_id, created_at, updated_at }`.
  `cron_expr` exists in the schema but the current scheduler only uses
  `interval_minutes`.
- **Permission** — `{ id, session_id, tool_name, command, description,
  status, response, created_at, responded_at, timeout_seconds }`.
  `status ∈ {pending, approved, denied, timeout}`.
- **Notification** — `{ id, task_id, channel, chat_id, message, status,
  created_at, sent_at }`. `status ∈ {pending, sent, failed}`. Used by the
  startup notification loop in `bridge.db`.
- **InboundMessage / OutboundMessage** — channel I/O in `messages.db`.
  `InboundMessage.status ∈ {pending, delivered, acknowledged, failed}`.
  `OutboundMessage.status ∈ {pending, sent, failed, notified}`.
- **Team** — `{ name, lead_agent, created_at }` with an auxiliary
  `team_members(team_name, agent_name)` table.
- **ChannelMessage** (runtime, non-persisted) — platform-neutral message
  shape used by channel adapters: `{ id, text, senderId, senderName, chatId,
  threadId?, replyToMessageId?, files?, timestamp }`.

## 4. Runtime Flows

### 4a. Task dispatch

```
 CLI/MCP          BridgeDatabase           Dispatcher         Claude Code
   |                    |                       |                   |
   |--atomicCheckAnd--->|  (exclusive txn)      |                   |
   |    CreateTask      |                       |                   |
   |<--isBusy / taskId--|                       |                   |
   |                    |                       |                   |
   | if !busy:          |                       |                   |
   |----dispatch(task,  |---------------------->|                   |
   |   agent, project)  |                       |--spawn(claude)--->|
   |                    |                       |<---pid------------|
   |<--------------pid--|                       |                   |
   |                    |--updateTask(pid)      |                   |
   | if busy:           |                       |                   |
   |  createTask status=queued, position=N      |                   |
```

`atomicCheckAndCreateTask` runs an exclusive SQLite transaction: if a task is
already `running` for that `session_id`, nothing is inserted and `isBusy=true`
is returned; the caller then creates a `queued` task with a tail `position`.
Otherwise a `pending` task is inserted inside the same transaction, ensuring
two concurrent callers cannot both create a running task.

### 4b. Stop hook / on-complete

```
 Claude Code exits
   |
   v
 stop hook:  bridge on-complete --session-id <sid>
   |
   v
 cmdOnComplete:
   - find running task for session
   - resultFile = homeDir/workspaces/<sid>/tasks/<taskId>.result.json
   - parseResultFile -> { exitCode, summary, costUsd, durationMs, numTurns }
   - CompletionHandler.handleCompletion(sid, taskId, result)
       - db.updateTask(status=done|failed, metrics, completed_at)
       - db.updateAgentState(sid, "idle")
       - if channel_chat_id: db.createNotification(...)
       - next = db.dequeueNextTask(sid)
       - if next: dispatcher.dispatch(next) + updateTask(pid)
```

The deterministic UUID from `Dispatcher.sessionIdToUuid(sessionId, taskId)`
(MD5 of `session_id:task_id`, formatted as `8-4-4-4-12`) is what Claude Code
sees as `--session-id`. Subsequent tasks for the same pair get the same UUID
so Claude Code's own session continuity applies.

### 4c. Loop iteration

```
 startLoop(agent, goal, done_when, opts)
   |
   |--validate done condition
   |--check for active loop (one-per-agent)
   |--db.createLoop(...)                 -> loop_id
   |--dispatchIteration(loop_id, 1, null)
          |--createTask, createLoopIteration
          |--updateLoop(current_iteration=1, current_task_id=taskId)

 on task complete (called by CompletionHandler via the stop path):
   onTaskComplete(loop_id, task_id, summary, cost)
     - record iteration summary & cost
     - accumulate total_cost_usd
     - if max_cost_usd exceeded          -> status=failed
     - if task failed:
         consecutive_failures++
         if >= max_consecutive_failures  -> status=failed
     - condition = parseDoneCondition(done_when)
     - if condition.type == "manual"     -> pending_approval=1
     - else: evaluator.evaluate(...)
         - if passed                     -> status=done
         - else if current_iteration >= max_iterations -> status=failed
         - else dispatchIteration(loop_id, current+1, feedback)
```

Feedback is generated from the last 2 iterations' summaries, each truncated to
half of `MAX_FEEDBACK_CHARS` (2000). Manual/rejected loops rely on the
caller invoking `approveLoop` / `rejectLoop` (CLI or MCP).

### 4d. Schedule execution

```
 Scheduler.start(60_000) sets an interval that calls runOnce():
   |
   v
 runOnce():
   now = new Date()
   for s in db.getDueSchedules(now):
     if s.consecutive_errors >= 5: continue
     try:   dispatchForSchedule(s)    -> creates task, updateScheduleSuccess(next_run = now + interval)
     catch: db.updateScheduleError(s.id, err)
              - errors++ (stored)
              - if errors >= 5: disable schedule
              - else: next_run = now + interval * min(2^errors, 8)
```

Note that `dispatchForSchedule` inserts a `<agent>--scheduled` session_id, not
the agent's real session. The scheduler's job is to produce tasks; the
dispatch engine picks them up through the normal task flow. Backoff math
lives in `BridgeDatabase.updateScheduleError`, not in `Scheduler`.

### 4e. MCP tool call

```
 Claude Code --->  stdio JSON-RPC  ---> StdioServerTransport
                                              |
                                              v
                                 server.setRequestHandler(CallTool, ...)
                                              |
                                              v
                                 executeToolNative(name, args)
                                     - open BridgeDatabase
                                     - route to handler (switch on name)
                                     - close DB in finally
                                              |
                                              v
                                   ToolResult { content: [...] }
```

Every tool call opens and closes the `BridgeDatabase` — cheap because WAL
makes this a file open, not a schema init. `handleTool` may additionally open
`MessageDatabase` for message-related tools.

### 4f. Startup

```
 bun run src/mcp/server.ts   (or launchd / systemd unit)
   |
   v
 StartupOrchestrator.start()
   |--new BridgeDatabase(homeDir/bridge.db)
   |--ProcessWatcher.start(30_000)       <-- sweeps dead PIDs, 6h timeouts
   |--startNotificationLoop(5_000)       <-- drains pending notifications via Notifier
   |--startServer()                      <-- connects MCP over stdio (blocking)
```

Both background timers are `unref`-ed so they don't keep the event loop alive
if the MCP transport closes. Stop is symmetric (`ProcessWatcher.stop` +
`clearInterval` + `db.close`).

## 5. Cross-Cutting Concerns

**Session ID derivation.** `SessionManager.deriveSessionId(agentName, path)`
produces `"<agent>--<basename(path)>"` (e.g. `backend--my-api`). That string
is the DB primary key for session lookups. Before spawning Claude Code,
`Dispatcher.sessionIdToUuid(sessionId[, taskId])` hashes it with MD5 and
formats the hex as a UUID. Feeding this UUID to `claude --session-id` keeps
Claude Code's own session cache warm across related task invocations.

**Worktree isolation.** Not implemented by the bridge — the agent `.md` file
declares `isolation: worktree` in its YAML frontmatter and Claude Code handles
it natively. `SessionManager.getWorktreePath()` only reports where a
workspace's metadata/tasks directory lives (`homeDir/workspaces/<sid>`); the
real git worktree is Claude Code's business.

**Race prevention.** Concurrent dispatches for the same session go through
`atomicCheckAndCreateTask`, which executes the busy-check and insert inside a
`db.transaction(...).exclusive()`. Queue dequeue uses a similar pattern in
`dequeueNextTask` so position shifts are atomic.

**Reliability.** Two safety nets cover missed stop hooks:

1. `ProcessWatcher` (30s interval). If the spawned `claude` process is gone
   but the task is still `running`, the task is marked `failed` with
   `"Process <pid> died unexpectedly"` and the agent flips to `idle`.
2. A 6h task timeout. Tasks whose `started_at` is older than
   `DEFAULT_TIMEOUT_MINUTES` (360) get status `timeout` and a `SIGTERM`.

Notifications use the same pattern: the 5s loop retries any row with
`status='pending'`, flipping it to `sent` or `failed`.

**Multi-instance via `CLAUDE_BRIDGE_HOME`.** `ConfigProvider` (and all other
entry points) read `process.env.CLAUDE_BRIDGE_HOME`, defaulting to
`~/.claude-bridge`. Each instance gets its own `bridge.db`, `messages.db`,
`workspaces/`, `config.json`, and daemon service name (derived from
`basename(home)`). `SessionManager.getInstancePrefix()` strips common
prefixes so agent file names stay readable.

## 6. Extension Points

**Add a new channel.** Implement `IChannelAdapter` and `IMessageFormatter`
for the platform in `src/channel/<platform>/`, export both from
`channel/index.ts`, and add platform-specific outbound delivery to `Notifier`
(or refactor `Notifier` to delegate to adapters when the migration lands).
The abstract contract already covers send/edit/delete, threads, reactions,
and file upload capability flags. See `TelegramAdapter` for the reference
skeleton.

**Add a new MCP tool.** Append the tool to `TOOL_NAMES` and add a matching
entry to `TOOL_DEFINITIONS` in `src/mcp/tools.ts`, then extend the `switch`
in `handleTool` (`src/mcp/tool-handlers.ts`) to route the arguments into the
appropriate layer (DB, orchestration, etc.). Tools may open `MessageDatabase`
on demand; remember to `close()` in `finally`. The legacy `buildCliArgs` /
`executeTool` path is only relevant if you still need Python fallback.

**Add a new done-condition type.** Extend the `VALID_TYPES` set in
`src/orchestration/evaluator.ts`, widen `DoneCondition["type"]` in
`orchestration/interfaces.ts`, handle the type in `parseDoneCondition`
(argument split), and add a branch to the `switch` in `evaluate`. If the
type should not emit a pass/fail by itself (like `manual`), also update
`LoopOrchestrator.onTaskComplete` so the loop state machine handles it.

## 7. File Map

| Path                                   | Responsibility                                              |
| -------------------------------------- | ----------------------------------------------------------- |
| `src/index.ts`                         | Public API barrel — re-exports all layer entry points       |
| `src/types.ts`                         | Shared domain types (Agent, Task, Loop, Schedule, ...)      |
| `src/config.ts`                        | `ConfigProvider` — resolves `CLAUDE_BRIDGE_HOME`, loads `config.json` |
| `src/data/db.ts`                       | `BridgeDatabase` — SQLite primary store + atomic ops        |
| `src/data/message-db.ts`               | `MessageDatabase` — inbound/outbound queue + poller state   |
| `src/data/session.ts`                  | `SessionManager` — session-id derivation, workspace paths   |
| `src/data/interfaces.ts`               | Data-layer contracts                                        |
| `src/data/index.ts`                    | Data-layer barrel                                           |
| `src/execution/dispatcher.ts`          | `Dispatcher` — `Bun.spawn` of `claude`, cancel, UUIDs       |
| `src/execution/on-complete.ts`         | `CompletionHandler` — stop-hook callback & auto-dequeue     |
| `src/execution/watcher.ts`             | `ProcessWatcher` — 30s dead-process / timeout sweeper       |
| `src/execution/notify.ts`              | `Notifier` — Telegram API delivery + message formatting     |
| `src/execution/interfaces.ts`          | Execution-layer contracts                                   |
| `src/execution/index.ts`               | Execution-layer barrel                                      |
| `src/orchestration/loop.ts`            | `LoopOrchestrator` — iterative task state machine           |
| `src/orchestration/evaluator.ts`       | `LoopEvaluator` — done-condition parser + evaluators        |
| `src/orchestration/scheduler.ts`       | `Scheduler` — 60s poll for due schedules                    |
| `src/orchestration/interfaces.ts`      | Orchestration-layer contracts                               |
| `src/orchestration/index.ts`           | Orchestration-layer barrel                                  |
| `src/cli/index.ts`                     | `bridge` command dispatcher + `on-complete` entry + lifecycle commands |
| `src/cli/setup-bot.ts`                 | `bridge setup-bot` — scaffolds bot dir (CLAUDE.md, .mcp.json, agents, settings.local.json) + config.json |
| `src/cli/doctor.ts`                    | `bridge doctor` — `[ok]` / `[warn]` / `[fail]` diagnostics for the bot-dir layout, daemon, and tmux session |
| `src/cli/agent-md.ts`                  | Agent `.md` generator + `.claude/settings.local.json` hook installer |
| `src/cli/memory.ts`                    | Claude Code Auto Memory reader                              |
| `src/cli/claude-md.ts`                 | Project `CLAUDE.md` initializer (shells out to `claude`)    |
| `src/mcp/server.ts`                    | MCP stdio server setup                                      |
| `src/mcp/tools.ts`                     | Tool name registry, definitions, CLI-fallback helpers       |
| `src/mcp/tool-handlers.ts`             | `executeToolNative` — native TS tool dispatch               |
| `src/mcp/bridge-md.ts`                 | Bridge-bot `CLAUDE.md` generator                            |
| `src/mcp/index.ts`                     | MCP-layer barrel                                            |
| `src/infra/startup.ts`                 | `StartupOrchestrator` — wires watcher, notify loop, MCP     |
| `src/infra/daemon.ts`                  | launchd / systemd install / uninstall / status              |
| `src/infra/bridge-cmd.ts`              | tmux session helpers, config validation, process cleanup    |
| `src/infra/permissions.ts`             | `PreToolUse` permission relay (exit 0 / 2)                  |
| `src/infra/index.ts`                   | Infra-layer barrel                                          |
| `src/channel/interface.ts`             | `IChannelAdapter`, `IMessageFormatter`, `ChannelMessage`    |
| `src/channel/core.ts`                  | Shared access-control helpers (mostly stubs)                |
| `src/channel/telegram/adapter.ts`      | Telegram adapter (stub — methods throw)                     |
| `src/channel/telegram/format.ts`       | Telegram HTML formatter                                     |
| `src/channel/discord/adapter.ts`       | Discord adapter (stub)                                      |
| `src/channel/discord/format.ts`        | Discord Markdown formatter (stub)                           |
| `src/channel/slack/adapter.ts`         | Slack adapter (stub)                                        |
| `src/channel/slack/format.ts`          | Slack mrkdwn formatter (stub)                               |
| `src/channel/index.ts`                 | Channel-layer barrel                                        |
