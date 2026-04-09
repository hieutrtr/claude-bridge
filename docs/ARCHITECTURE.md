# Claude Bridge TypeScript Migration — Architecture Document

> **Version:** 0.1.0 | **Last updated:** 2026-04-09
> **Scope:** Complete architecture for migrating Claude Bridge from Python to TypeScript/Bun,
> targeting distribution as a Claude Code plugin.

---

## Table of Contents

1. [Context & Scope](#1-context--scope)
2. [Stakeholder Concerns & Quality Attributes](#2-stakeholder-concerns--quality-attributes)
3. [Functional Requirements Mapping](#3-functional-requirements-mapping)
4. [Component Design](#4-component-design)
5. [Data Architecture](#5-data-architecture)
6. [Integration Points](#6-integration-points)
7. [Deployment Model](#7-deployment-model)
8. [Architecture Decision Records](#8-architecture-decision-records)
9. [Migration Strategy](#9-migration-strategy)
10. [Risk Assessment](#10-risk-assessment)

---

## 1. Context & Scope

### 1.1 Problem Statement

Claude Bridge is a multi-session Claude Code dispatcher that accepts tasks from messaging
platforms (Telegram, Discord, Slack), routes them to isolated Claude Code agent sessions,
and delivers results back. The current implementation is Python 3.11+ (stdlib-only core +
optional `mcp` dependency). The migration to TypeScript/Bun targets:

1. **Plugin distribution** — Claude Code's official plugin ecosystem is TypeScript/Bun-native
2. **Runtime unification** — the existing channel server (`channel/server.ts`) is already TypeScript;
   merging eliminates the Python↔TS boundary
3. **Performance** — Bun's native SQLite (`bun:sqlite`) and fast startup reduce overhead for
   daemon and hook processes

### 1.2 What Claude Bridge Is

A **dispatch orchestrator** — not an AI agent itself. It:

- Manages named agents (e.g., `backend`, `frontend`) bound to project directories
- Dispatches tasks to Claude Code via `claude -p --agent --session-id`
- Tracks task lifecycle: pending → running → completed/failed
- Provides goal loops (iterate until done condition), schedules (cron), and queuing
- Relays results back to messaging channels
- Handles permission requests for dangerous operations (git push, rm -rf)

### 1.3 What Claude Bridge Is NOT

- Not a Claude API wrapper (it orchestrates the `claude` CLI binary)
- Not a chatbot (the Bridge Bot session is a Claude Code instance that uses Bridge as a tool)
- Not a replacement for Claude Code features (it leverages `--agent`, `--session-id`,
  `isolation: worktree`, Auto Memory, Stop hooks)

### 1.4 System Boundaries

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          EXTERNAL ACTORS                                │
│                                                                         │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐   │
│   │ Telegram  │   │ Discord  │   │  Slack   │   │  Claude Code CLI │   │
│   │ Bot API   │   │ Gateway  │   │ Socket   │   │  (claude binary) │   │
│   └─────┬─────┘   └─────┬────┘   └────┬─────┘   └────────┬─────────┘   │
│         │               │              │                  │             │
└─────────┼───────────────┼──────────────┼──────────────────┼─────────────┘
          │               │              │                  │
          ▼               ▼              ▼                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│                        CLAUDE BRIDGE (TS/Bun)                           │
│                                                                         │
│  ┌─────────────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ Channel Layer    │  │  MCP Server  │  │  Core (Data + Execution   │  │
│  │ (Telegram,       │  │  (tools for  │  │   + Orchestration)        │  │
│  │  Discord, Slack) │  │  Bridge Bot) │  │                           │  │
│  └────────┬─────────┘  └──────┬───────┘  └─────────────┬─────────────┘  │
│           │                   │                        │               │
│           └───────────────────┴────────────────────────┘               │
│                               │                                        │
│                        ┌──────▼──────┐                                 │
│                        │   SQLite    │                                 │
│                        │  (WAL mode) │                                 │
│                        └─────────────┘                                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.5 C4 Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              C4 — CONTEXT                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│                          ┌────────────┐                                     │
│                          │   User     │                                     │
│                          │ (Developer)│                                     │
│                          └─────┬──────┘                                     │
│                                │                                            │
│                    sends commands / receives results                        │
│                                │                                            │
│               ┌────────────────┼───────────────────┐                       │
│               ▼                ▼                    ▼                       │
│        ┌───────────┐   ┌───────────┐        ┌───────────┐                  │
│        │ Telegram   │   │ Discord   │        │  Slack    │                  │
│        │ [External] │   │ [External]│        │ [External]│                  │
│        └─────┬──────┘   └─────┬─────┘        └─────┬─────┘                  │
│              │                │                     │                       │
│              └────────────────┼─────────────────────┘                       │
│                               │                                             │
│                     Bot API / WebSocket / Socket Mode                       │
│                               │                                             │
│                        ┌──────▼──────┐                                      │
│                        │             │                                      │
│                        │   CLAUDE    │                                      │
│                        │   BRIDGE    │                                      │
│                        │  [System]   │                                      │
│                        │             │                                      │
│                        └──┬───────┬──┘                                      │
│                           │       │                                         │
│              spawns tasks │       │ reads/writes                            │
│              via CLI      │       │ state                                   │
│                           │       │                                         │
│                    ┌──────▼──┐  ┌─▼──────────┐                              │
│                    │ Claude  │  │  SQLite DB  │                              │
│                    │ Code    │  │  [Datastore]│                              │
│                    │ CLI     │  │             │                              │
│                    │[External│  └─────────────┘                              │
│                    │ System] │                                               │
│                    └─────────┘                                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.6 Actors & Interactions

| Actor | Type | Interaction with Bridge |
|-------|------|------------------------|
| **User (Developer)** | Human | Sends commands via messaging app, receives task results |
| **Telegram Bot API** | External | HTTP polling (getUpdates) + push (sendMessage) via grammy SDK |
| **Discord Gateway** | External | WebSocket connection via discord.js SDK (Phase 3) |
| **Slack Socket Mode** | External | WebSocket via @slack/bolt SDK (Phase 6) |
| **Claude Code CLI** | External | Subprocess spawn (`claude -p --agent ...`), JSON result output |
| **SQLite** | Datastore | Agents, tasks, loops, schedules, messages, permissions |
| **Bridge Bot** | Internal | Claude Code session that uses Bridge MCP tools to process user requests |
| **File System** | Internal | Agent .md files, worktree directories, result JSON files, config |

### 1.7 Scope of This Migration

**In scope:**
- All Python modules in `src/claude_bridge/` → TypeScript in `ts-src/src/`
- Channel server (`channel/server.ts`) absorbed into the unified TS codebase
- CLI (`bridge-cli`), daemon management, MCP server
- Plugin packaging for Claude Code plugin marketplace

**Out of scope:**
- Claude Code internals (we treat `claude` binary as opaque)
- Telegram/Discord/Slack API changes
- Bridge Bot's CLAUDE.md prompt (it stays as-is, just references TS tools)

### 1.8 Key References

| Artifact | Path |
|----------|------|
| Python source | `src/claude_bridge/` (18 modules, ~4,500 LOC) |
| TS scaffold | `ts-src/src/` (6 layers, types + interfaces + scaffolds) |
| Existing channel server | `channel/server.ts` + `channel/lib.ts` (~3,500 LOC) |
| Core types | `ts-src/src/types.ts` (Agent, Task, Loop, Schedule, Notification) |
| Channel interfaces | `ts-src/src/channel/interface.ts` (IChannelAdapter, IMessageFormatter) |
| Data interfaces | `ts-src/src/data/interfaces.ts` (IDatabase, ISessionManager, IConfigProvider) |
| Execution interfaces | `ts-src/src/execution/interfaces.ts` (IDispatcher, ICompletionHandler, INotifier) |
| Orchestration interfaces | `ts-src/src/orchestration/interfaces.ts` (ILoopOrchestrator, IScheduler) |
| Plugin migration plan | `plan/plugin-migration-plan.md` (7-wave strategy) |
| Architecture decision | `research/ARCHITECTURE_DECISION.md` (Channels vs RemoteTrigger) |
| MVP specification | `specs/MVP.md` |

---

## 2. Stakeholder Concerns & Quality Attributes

### 2.1 Stakeholders

| Stakeholder | Role | Primary Concern |
|-------------|------|-----------------|
| **Developer (User)** | Dispatches tasks from mobile/desktop | Reliability — tasks must not silently drop; results must arrive |
| **Bridge Operator** | Installs, configures, maintains Bridge | Operability — easy setup, clear logs, daemon management |
| **Plugin Ecosystem** | Claude Code plugin marketplace | Compatibility — must follow plugin conventions (TS/Bun, MCP) |
| **Bridge Bot** | Claude Code session consuming MCP tools | API stability — MCP tool signatures must not break between versions |
| **Agent Sessions** | Spawned Claude Code processes | Isolation — worktree safety, no cross-session state corruption |

### 2.2 Quality Attributes

#### QA-1: Reliability (Critical)

**Concern:** A dispatched task must complete and report results. Silent failures are unacceptable.

**Mechanisms:**
- **Stop hook** as primary completion signal (`on-complete.ts` invoked by Claude Code)
- **Process watcher** as fallback (polls PIDs every 5 min, catches crashed/timed-out tasks)
- **Atomic task creation** (`BEGIN EXCLUSIVE` transaction in SQLite prevents duplicate dispatches)
- **Notification queue** with retry logic (exponential backoff, max 3 retries)

**Measurable:** Zero silent task drops over 24h of continuous use.

#### QA-2: Data Integrity (Critical)

**Concern:** SQLite must handle concurrent access from Bridge Bot, on-complete hooks,
watcher cron, and channel server without corruption.

**Mechanisms:**
- **WAL mode** (Write-Ahead Logging) — concurrent readers don't block writer
- **`BEGIN EXCLUSIVE`** for critical state transitions (task dispatch, queue dequeue)
- **Foreign keys ON** with `CASCADE` delete (agent deletion cascades to tasks)
- **Separate message DB** (`messages.db`) isolates high-frequency channel I/O from core state

**Constraint from Python:** `db.py:22` — `PRAGMA journal_mode=WAL` set on every connection.
TS must replicate: `bun:sqlite` Database constructor with `WAL` pragma.

#### QA-3: Process Isolation (Critical)

**Concern:** Agent sessions must not interfere with each other or leave zombie processes.

**Mechanisms:**
- **`start_new_session=True`** (Python) → `detached: true` (Bun) — spawned process gets
  its own process group, preventing Bridge's death from killing agents
- **Session-scoped worktrees** — Claude Code `isolation: worktree` in agent .md frontmatter
- **PID tracking** in SQLite — every running task has a known PID
- **Graceful kill**: SIGTERM → 10s wait → SIGKILL (never SIGKILL directly)

**Constraint from Python:** `dispatcher.py:50` uses `start_new_session=True`.
TS equivalent: `Bun.spawn({ detached: true })` or `child_process.spawn` with `detached`.

#### QA-4: Startup Performance (Important)

**Concern:** Stop hooks and CLI commands must start fast. Python's ~200ms import overhead
is noticeable for hooks that fire on every task completion.

**Mechanisms:**
- **Bun runtime** — ~10ms cold start vs Python's ~200ms
- **No heavy imports** — on-complete handler imports only data layer, not full orchestration
- **Lazy loading** — channel adapters loaded only when needed

**Measurable:** Stop hook (on-complete) completes in <100ms for simple task updates.

#### QA-5: Extensibility (Important)

**Concern:** Adding new channels (Discord, Slack) or orchestration modes (teams) must not
require modifying existing code.

**Mechanisms:**
- **`IChannelAdapter` interface** (`ts-src/src/channel/interface.ts`) — each platform
  implements the same contract: `start()`, `stop()`, `sendMessage()`, `onMessage()`
- **`IMessageFormatter` interface** — platform-specific formatting (HTML for Telegram,
  mrkdwn for Slack, standard Markdown for Discord)
- **Plugin architecture** — each layer is independently testable and replaceable

**Evidence:** Adding Discord requires only `DiscordAdapter` + `DiscordFormatter`,
no changes to orchestration, data, or MCP layers.

#### QA-6: Operability (Important)

**Concern:** The operator must be able to start, stop, monitor, and troubleshoot Bridge
without deep system knowledge.

**Mechanisms:**
- **Single binary** — `bun run ts-src/src/cli/index.ts` replaces `python -m claude_bridge.cli`
- **Daemon management** — launchd (macOS) / systemd (Linux) integration
- **Structured logging** — errors to stderr, structured output to stdout
- **Health checks** — `bridge status` shows running agents, active tasks, daemon state

#### QA-7: Backward Compatibility (During Migration)

**Concern:** Existing Python installations must continue working during the migration period.
The TS version must read existing SQLite databases without requiring migration.

**Mechanisms:**
- **Same SQLite schema** — TS reads/writes identical tables and columns
- **Same file layout** — `~/.claude-bridge/` directory structure preserved
- **Same MCP tool names** — Bridge Bot's CLAUDE.md doesn't need to change
- **Coexistence mode** — TS can shell out to `bridge-cli` (Python) for unimplemented features

### 2.3 Quality Attribute Priority Matrix

```
                    ┌─────────────┬─────────────┐
                    │  Negotiable │    Fixed     │
  ┌─────────────┬───┼─────────────┼─────────────┤
  │ Must Have   │   │             │ QA-1 Reliab. │
  │             │   │             │ QA-2 Data Int.│
  │             │   │             │ QA-3 Proc Iso.│
  ├─────────────┼───┼─────────────┼─────────────┤
  │ Should Have │   │ QA-6 Ops    │ QA-4 Startup │
  │             │   │ QA-7 Compat │ QA-5 Extensib│
  └─────────────┴───┴─────────────┴─────────────┘
```

### 2.4 Constraints (Non-Negotiable)

| ID | Constraint | Source |
|----|-----------|--------|
| C-1 | Bun runtime (not Node.js) | Plugin ecosystem requirement |
| C-2 | SQLite with WAL mode | Architecture rule (`.claude/rules/architecture.md`) |
| C-3 | `session_id = "{agent}--{project}"` | Session model identity (cannot change without breaking existing DBs) |
| C-4 | `start_new_session` / `detached` for spawned processes | Architecture rule (subprocess management) |
| C-5 | Agent .md files in `{bot_dir}/.claude/agents/bridge--{session_id}.md` | Claude Code native convention |
| C-6 | `CLAUDE_BRIDGE_HOME` env var for multi-instance support | Multi-instance architecture |
| C-7 | Timestamps as ISO8601 strings in SQLite | Architecture rule |
| C-8 | Graceful kill: SIGTERM → 10s → SIGKILL | Architecture rule |

---

## 3. Functional Requirements Mapping

### 3.1 Python Feature Audit → TS Interface Coverage

This section maps every Python public function to its TS interface equivalent. Status
indicates whether the TS interface covers the Python functionality.

#### Legend

- **Covered** — TS interface has a matching method
- **Partial** — TS interface exists but is missing parameters or return type details
- **Gap** — No corresponding TS interface method exists
- **N/A** — Feature intentionally excluded from TS migration

### 3.2 Data Layer

#### Python `db.py` (BridgeDB) → TS `IDatabase`

| Python Method | TS Interface Method | Status | Gap Notes |
|--------------|---------------------|--------|-----------|
| `create_agent(name, project_dir, session_id, agent_file, purpose, model)` | `createAgent(name, projectPath, purpose, sessionId)` | **Partial** | Missing: `agent_file`, `model` params |
| `get_agent(name)` | `getAgent(name)` | Covered | |
| `get_agent_by_session(session_id)` | — | **Gap** | Needed for on-complete (looks up agent by session) |
| `list_agents()` | `listAgents()` | Covered | |
| `delete_agent(name)` | `deleteAgent(name)` | Covered | |
| `update_agent_state(session_id, state)` | — | **Gap** | State transitions: created→idle→running |
| `increment_agent_tasks(session_id)` | — | **Gap** | Counter for total_tasks |
| `update_agent_model(session_id, model)` | — | **Gap** | Model override per agent |
| `atomic_check_and_create_task(...)` | `createTask(input)` | **Partial** | Missing atomicity guarantee, channel/user params |
| `get_task(task_id)` | `getTask(id)` | Covered | |
| `get_running_task(session_id)` | — | **Gap** | Single running task per session |
| `get_running_tasks()` | `getRunningTasks()` | Covered | |
| `get_unreported_tasks()` | — | **Gap** | Notification delivery tracking |
| `get_task_history(session_id, limit)` | `getTasksByAgent(agentName, limit)` | Covered | Keyed by agentName vs session_id |
| `update_task(task_id, **kwargs)` | `updateTaskStatus(id, status, updates?)` | Covered | |
| `mark_task_reported(task_id)` | — | **Gap** | Notification flag |
| `get_cost_summary(session_id, period)` | — | **Gap** | Cost analytics |
| `create_permission(...)` | — | **Gap** | Permission relay system (6 methods) |
| `get_queued_tasks(session_id)` | — | **Gap** | Task queue (4 methods) |
| `dequeue_next_task(session_id)` | — | **Gap** | Auto-dequeue on completion |
| `create_team(...)` | — | **Gap** | Team coordination (5 methods) |
| `create_notification(...)` | — | **Gap** | Notification queue (5 methods) |
| Loop methods (10) | `createLoop`, `getLoop`, `updateLoop`, `getActiveLoops` | **Partial** | Missing: iterations, loop-by-task lookup |
| Schedule methods (7) | `createSchedule` through `deleteSchedule` | **Partial** | Missing: `get_due_schedules`, `pause/resume` |

**Summary:** IDatabase covers 10/61 Python methods. 51 methods have no TS interface equivalent.

#### Python `session.py` → TS `ISessionManager`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `derive_session_id(agent_name, project_dir)` | `deriveSessionId(agentName, projectPath)` | Covered |
| `get_workspace_dir(session_id)` | `getWorktreePath(sessionId)` | Covered |
| `get_agent_file_path(session_id, bot_dir)` | `getAgentMdPath(sessionId)` | **Partial** (missing bot_dir param) |
| `validate_agent_name(name)` | — | **Gap** |
| `validate_project_dir(path)` | — | **Gap** |
| `get_tasks_dir(session_id)` | — | **Gap** |
| `create_workspace(session_id, ...)` | — | **Gap** |
| `cleanup_workspace(session_id)` | — | **Gap** |
| `derive_agent_file_name(session_id)` | — | **Gap** |
| `get_instance_prefix()` | — | **Gap** |

**Summary:** 2/10 covered, 1 partial, 7 gaps.

### 3.3 Execution Layer

#### Python `dispatcher.py` → TS `IDispatcher`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `spawn_task(agent_file, session_id, project_dir, prompt, task_id, model)` | `dispatch(task, options?)` | **Partial** — Task object doesn't carry agent_file or model |
| `pid_alive(pid)` | `isRunning(pid)` | Covered |
| `kill_process(pid, graceful, timeout)` | `cancel(task)` | **Partial** — no graceful/timeout params |
| `session_id_to_uuid(session_id, task_id)` | — | **Gap** |
| `get_result_file(session_id, task_id)` | — | **Gap** |
| `get_stderr_file(session_id, task_id)` | — | **Gap** |

#### Python `on_complete.py` → TS `ICompletionHandler`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `parse_result_file(result_file)` | — | **Gap** (internal to handleCompletion) |
| `main(db, msg_db_path)` | `handleCompletion(sessionId, taskId, result)` | **Partial** — Python parses CLI args + result file; TS takes pre-parsed result |

#### Python `watcher.py` → TS `IProcessWatcher`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `watch(timeout_minutes, db)` | `start(intervalMs?)` | Covered |
| `main()` | — | N/A (CLI entry point) |

#### Python `notify.py` → TS `INotifier`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `format_completion_message(task, agent_name)` | — | **Gap** (formatting logic) |
| `send_telegram(bot_token, chat_id, message)` | — | **Gap** (channel-specific send) |
| `deliver_notification(db, notification_id)` | `notify(notification)` | **Partial** — different abstraction level |
| `get_bot_token()` | — | **Gap** (config helper) |
| `get_default_channel()` | — | **Gap** |

### 3.4 Orchestration Layer

#### Python `loop_orchestrator.py` → TS `ILoopOrchestrator`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `start_loop(db, agent, project, goal, done_when, ...)` | `startLoop(agentName, goal, doneCondition, maxIterations?)` | **Partial** — missing project, loop_type, max_cost |
| `on_task_complete(db, loop_id, task_id, result, cost)` | — | **Gap** — critical callback |
| `cancel_loop(db, loop_id)` | `cancelLoop(loopId)` | Covered |
| `approve_loop(db, loop_id)` | — | **Gap** — approval workflow |
| `reject_loop(db, loop_id, feedback)` | — | **Gap** — rejection with feedback |
| `get_loop_status(db, loop_id)` | `getLoopStatus(loopId)` | Covered |
| `decide_loop_type(goal, done_when, ...)` | — | **Gap** |
| `format_loop_list(loops)` / `format_loop_history(loop)` | — | **Gap** |

#### Python `loop_evaluator.py` → TS `ILoopEvaluator`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `evaluate_done_condition(condition, project_dir, ...)` | `evaluate(loop, latestTask, taskSummary)` | **Partial** — different signature |
| `parse_done_condition(condition_str)` | — | **Gap** |
| `validate_done_condition(condition_str)` | — | **Gap** |

#### Python `scheduler.py` → TS `IScheduler`

| Python Function | TS Interface Method | Status |
|----------------|---------------------|--------|
| `run_scheduler(db)` | `start()` | Covered |
| `compute_next_run(schedule, now, error)` | `getNextRun(cronExpression)` | **Partial** — missing error backoff |
| `dispatch_for_schedule(db, schedule, agent)` | — | **Gap** |

### 3.5 Channel Layer

#### Python `channel/server.ts` + `channel/lib.ts` → TS `IChannelAdapter`

The existing TypeScript channel server has significant logic that maps to `IChannelAdapter`:

| Existing Channel Function | TS Interface Method | Status |
|--------------------------|---------------------|--------|
| `bot.on('message', ...)` | `onMessage(handler)` | Covered |
| `bot.api.sendMessage(...)` | `sendMessage(chatId, text, opts?)` | Covered |
| `downloadTelegramFile(...)` | `downloadFile(fileId, destPath)` | Covered |
| `processOutbound(...)` | (internal to adapter) | Covered |
| `loadAllowlist(...)` | (in `channel/core.ts`) | Covered |
| `convertMarkdownToTelegramHtml(...)` | `IMessageFormatter` methods | Covered |
| `chunkTelegramMessage(...)` | `chunkMessage(text)` | Covered |

**Note:** The existing `channel/server.ts` (~2,000 LOC) and `channel/lib.ts` (~1,500 LOC)
contain battle-tested implementations. The migration should absorb this code into
`TelegramAdapter`, not rewrite it.

### 3.6 MCP & CLI Layer

#### Python MCP tools (23 tools) → TS MCP tools (3 tools)

| Python MCP Tool | TS Equivalent | Status |
|----------------|---------------|--------|
| `bridge_dispatch` | `bridge_dispatch` | Scaffold |
| `bridge_status` | `bridge_status` | Scaffold |
| `bridge_agents` | `bridge_list_agents` | Scaffold |
| `bridge_history` | — | **Gap** |
| `bridge_kill` | — | **Gap** |
| `bridge_create_agent` | — | **Gap** |
| `bridge_get_messages` | — | **Gap** |
| `bridge_acknowledge` | — | **Gap** |
| `bridge_reply` | — | **Gap** |
| `bridge_get_notifications` | — | **Gap** |
| `bridge_loop` (+ 8 loop tools) | — | **Gap** |
| `bridge_schedule_*` (5 tools) | — | **Gap** |

**Summary:** 3/23 MCP tools have TS scaffolds. 20 are gaps.

#### Python CLI (10 commands) → TS CLI (9 commands)

| Python Command | TS Command | Status |
|---------------|------------|--------|
| `create-agent` | `create-agent` | Scaffold |
| `delete-agent` | `delete-agent` | Scaffold |
| `dispatch` | `dispatch` | Scaffold |
| `list-agents` | `list-agents` | Scaffold |
| `status` | `status` | Scaffold |
| `kill` | — | **Gap** |
| `history` | — | **Gap** |
| `memory` | — | **Gap** |
| `setup-telegram` | `setup-bot` | Scaffold (renamed) |
| `loop` | `loop` | Scaffold |
| `schedule-*` | `schedule` | Scaffold |
| `daemon` | `daemon` | Scaffold |

### 3.7 Missing from TS Interfaces Entirely

These Python modules have **no corresponding TS interface or scaffold**:

| Python Module | LOC | Functionality | Priority |
|--------------|-----|---------------|----------|
| `agent_md.py` | ~200 | Generate agent .md files with YAML frontmatter | **Wave 3** |
| `claude_md_init.py` | ~100 | Auto-generate CLAUDE.md for new projects | **Wave 3** |
| `permission_relay.py` | ~150 | PreToolUse hook for dangerous command approval | **Wave 5** |
| `message_db.py` | ~300 | Inbound/outbound message queue (separate DB) | **Wave 2** |
| `bridge_cmd.py` | ~400 | tmux/foreground session management | **Wave 6** |
| `daemon.py` | ~600 | launchd/systemd daemon install/management | **Wave 6** |
| `telegram_loop.py` | ~100 | Loop notification formatting for Telegram | **Wave 4** |
| `bridge_bot_claude_md.py` | ~300 | Bridge Bot CLAUDE.md generator | **Wave 5** |

### 3.8 Coverage Summary

```
┌──────────────────────┬──────────┬─────────┬─────────┬────────┐
│ Layer                │ Py Funcs │ TS Intf │ Covered │  Gap % │
├──────────────────────┼──────────┼─────────┼─────────┼────────┤
│ Data (db.py)         │    61    │   20    │   10    │  84%   │
│ Session              │    10    │    3    │    2    │  80%   │
│ Dispatcher           │     6    │    3    │    2    │  67%   │
│ Completion           │     2    │    1    │    1    │  50%   │
│ Watcher              │     2    │    2    │    1    │  50%   │
│ Notifier             │     6    │    1    │    0    │ 100%   │
│ Loop Orchestrator    │     9    │    5    │    2    │  78%   │
│ Loop Evaluator       │     4    │    1    │    0    │ 100%   │
│ Scheduler            │     3    │    3    │    1    │  67%   │
│ Channel Adapter      │    ~20   │   11    │   11    │  45%   │
│ MCP Tools            │    23    │    3    │    0    │ 100%   │
│ CLI                  │    10    │    9    │    0    │ 100%   │
│ No TS equivalent     │   ~50    │    0    │    0    │ 100%   │
├──────────────────────┼──────────┼─────────┼─────────┼────────┤
│ TOTAL                │  ~206    │   62    │   30    │  85%   │
└──────────────────────┴──────────┴─────────┴─────────┴────────┘
```

### 3.9 Interface Expansion Needed

Before implementation begins, the TS interfaces must be expanded to cover the gaps.
The recommended approach per wave:

**Wave 2 (Data Layer):**
- Expand `IDatabase` from 20 → ~55 methods (add queue, permission, notification, message methods)
- Add `IMessageDatabase` interface (maps to Python `message_db.py`)
- Expand `ISessionManager` from 3 → ~8 methods (add validation, workspace, cleanup)

**Wave 3 (Execution):**
- Expand `IDispatcher` from 3 → ~5 methods (add result/stderr file helpers)
- Add `IAgentMdGenerator` interface (maps to `agent_md.py`)
- Add `IClaudeMdInit` interface (maps to `claude_md_init.py`)
- Expand `ICompletionHandler` to include result file parsing

**Wave 4 (Orchestration):**
- Expand `ILoopOrchestrator` from 5 → ~9 methods (add approve/reject/on_task_complete)
- Expand `ILoopEvaluator` from 1 → ~3 methods (add parse/validate)
- Add loop notification formatting

**Wave 7 (MCP):**
- Expand MCP tools from 3 → 23+ (full parity with Python)

---

## 4. Component Design

### 4.1 Layered Architecture Overview

Claude Bridge TS uses a **6-layer architecture** with strict dependency direction:
outer layers depend on inner layers, never the reverse.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Layer 6: ENTRY POINTS                            │
│                                                                         │
│   ┌───────────────┐   ┌──────────────────┐   ┌──────────────────────┐  │
│   │  CLI           │   │  MCP Server      │   │  Stop Hook (bin)     │  │
│   │  src/cli/      │   │  src/mcp/        │   │  on-complete entry   │  │
│   │  index.ts      │   │  server.ts       │   │                      │  │
│   └───────┬────────┘   └────────┬─────────┘   └──────────┬───────────┘  │
│           │                     │                        │             │
├───────────┼─────────────────────┼────────────────────────┼─────────────┤
│           ▼                     ▼                        ▼             │
│                     Layer 5: ORCHESTRATION                              │
│                                                                         │
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐    │
│   │ LoopOrchestrator │  │  LoopEvaluator   │  │   Scheduler      │    │
│   │ orchestration/   │  │  orchestration/  │  │  orchestration/  │    │
│   │ loop.ts          │  │  evaluator.ts    │  │  scheduler.ts    │    │
│   └────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘    │
│            │                     │                      │             │
├────────────┼─────────────────────┼──────────────────────┼─────────────┤
│            ▼                     ▼                      ▼             │
│                      Layer 4: CHANNEL                                  │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                    IChannelAdapter                               │  │
│   │                    IMessageFormatter                             │  │
│   ├──────────────────┬──────────────────┬───────────────────────────┤  │
│   │ TelegramAdapter  │ DiscordAdapter   │ SlackAdapter              │  │
│   │ TelegramFormatter│ DiscordFormatter │ SlackFormatter            │  │
│   │ channel/telegram/│ channel/discord/ │ channel/slack/            │  │
│   └────────┬─────────┘──────────────────┘───────────────────────────┘  │
│            │                                                           │
├────────────┼───────────────────────────────────────────────────────────┤
│            ▼                                                           │
│                     Layer 3: EXECUTION                                  │
│                                                                         │
│   ┌──────────────┐  ┌──────────────────┐  ┌──────────┐  ┌──────────┐ │
│   │  Dispatcher   │  │CompletionHandler │  │ Watcher  │  │ Notifier │ │
│   │  execution/   │  │  execution/      │  │execution/│  │execution/│ │
│   │  dispatcher.ts│  │  on-complete.ts  │  │watcher.ts│  │notify.ts │ │
│   └──────┬────────┘  └────────┬─────────┘  └────┬─────┘  └────┬─────┘ │
│          │                    │                  │             │       │
├──────────┼────────────────────┼──────────────────┼─────────────┼───────┤
│          ▼                    ▼                  ▼             ▼       │
│                      Layer 2: DATA                                     │
│                                                                         │
│   ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│   │  BridgeDatabase  │  │  SessionManager  │  │  ConfigProvider    │  │
│   │  data/db.ts      │  │  data/session.ts │  │  config.ts         │  │
│   └──────┬───────────┘  └──────────────────┘  └────────────────────┘  │
│          │                                                             │
├──────────┼─────────────────────────────────────────────────────────────┤
│          ▼                                                             │
│                      Layer 1: TYPES                                    │
│                                                                         │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │  types.ts — Agent, Task, Loop, Schedule, Notification, Config │   │
│   └────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 4.2 C4 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    C4 — COMPONENT (Claude Bridge TS)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        ENTRY POINTS                                 │   │
│  │                                                                     │   │
│  │  ┌──────────┐    ┌──────────────┐    ┌──────────────────────────┐  │   │
│  │  │   CLI    │    │  MCP Server  │    │    Stop Hook (binary)    │  │   │
│  │  │ [Comp]   │    │   [Comp]     │    │       [Comp]             │  │   │
│  │  │          │    │              │    │                          │  │   │
│  │  │ Parses   │    │ Exposes 23+  │    │ Called by Claude Code    │  │   │
│  │  │ bridge-  │    │ bridge_*     │    │ on task finish. Parses   │  │   │
│  │  │ cli args │    │ tools via    │    │ result JSON, updates DB, │  │   │
│  │  │          │    │ MCP/stdio    │    │ triggers notifications   │  │   │
│  │  └────┬─────┘    └──────┬───────┘    └────────────┬─────────────┘  │   │
│  │       │                 │                         │                │   │
│  └───────┼─────────────────┼─────────────────────────┼────────────────┘   │
│          │                 │                         │                    │
│          ▼                 ▼                         ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     ORCHESTRATION                                   │   │
│  │                                                                     │   │
│  │  ┌────────────────┐  ┌──────────────┐  ┌────────────────────────┐  │   │
│  │  │ Loop           │  │   Loop       │  │     Scheduler          │  │   │
│  │  │ Orchestrator   │  │  Evaluator   │  │      [Comp]            │  │   │
│  │  │   [Comp]       │  │   [Comp]     │  │                        │  │   │
│  │  │                │  │              │  │ Polls due schedules,    │  │   │
│  │  │ Iterates:      │  │ Checks done  │  │ dispatches tasks,      │  │   │
│  │  │ dispatch →     │  │ conditions:  │  │ computes next_run      │  │   │
│  │  │ evaluate →     │  │ command,     │  │ with exp. backoff      │  │   │
│  │  │ decide         │  │ file, LLM,   │  │                        │  │   │
│  │  │                │  │ manual       │  │                        │  │   │
│  │  └────────┬───────┘  └──────┬───────┘  └───────────┬────────────┘  │   │
│  └───────────┼─────────────────┼──────────────────────┼───────────────┘   │
│              │                 │                      │                    │
│              ▼                 ▼                      ▼                    │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       EXECUTION                                     │   │
│  │                                                                     │   │
│  │  ┌──────────────┐  ┌────────────────┐  ┌────────┐  ┌────────────┐ │   │
│  │  │  Dispatcher   │  │  Completion    │  │Watcher │  │  Notifier  │ │   │
│  │  │   [Comp]      │  │  Handler       │  │ [Comp] │  │   [Comp]   │ │   │
│  │  │               │  │   [Comp]       │  │        │  │            │ │   │
│  │  │ Bun.spawn()   │  │               │  │Fallback│  │ Routes to  │ │   │
│  │  │ with detached │  │ Parses result  │  │PID poll│  │ channel    │ │   │
│  │  │ + worktree    │  │ Updates task   │  │every   │  │ adapter    │ │   │
│  │  │               │  │ Dequeues next  │  │5 min   │  │ for send   │ │   │
│  │  └───────┬───────┘  └───────┬────────┘  └───┬────┘  └──────┬─────┘ │   │
│  └──────────┼──────────────────┼────────────────┼──────────────┼──────┘   │
│             │                  │                │              │          │
│             ▼                  ▼                ▼              ▼          │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA                                        │   │
│  │                                                                     │   │
│  │  ┌──────────────────┐  ┌────────────────┐  ┌────────────────────┐  │   │
│  │  │  BridgeDatabase  │  │ SessionManager │  │  ConfigProvider    │  │   │
│  │  │    [Comp]        │  │    [Comp]      │  │     [Comp]         │  │   │
│  │  │                  │  │                │  │                    │  │   │
│  │  │ bun:sqlite WAL   │  │ session_id     │  │ CLAUDE_BRIDGE_HOME │  │   │
│  │  │ agents, tasks,   │  │ derivation,    │  │ config.json        │  │   │
│  │  │ loops, schedules,│  │ workspace &    │  │ env vars           │  │   │
│  │  │ permissions,     │  │ agent .md      │  │                    │  │   │
│  │  │ messages, notifs │  │ path mgmt      │  │                    │  │   │
│  │  └──────────────────┘  └────────────────┘  └────────────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│             ┌────────────────────────────────────┐                          │
│             │  CHANNEL (cross-cutting)            │                          │
│             │                                    │                          │
│             │  ┌──────────┐ ┌────────┐ ┌──────┐ │                          │
│             │  │ Telegram │ │Discord │ │Slack │ │                          │
│             │  │ Adapter  │ │Adapter │ │Adapt.│ │                          │
│             │  │+Formatter│ │+Format.│ │+Fmt. │ │                          │
│             │  └──────────┘ └────────┘ └──────┘ │                          │
│             └────────────────────────────────────┘                          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Component Responsibilities

#### 4.3.1 Entry Points (Layer 6)

**CLI** (`src/cli/index.ts`)
- Parses `bridge-cli <command> [args]` via Bun's built-in arg parsing
- Routes to appropriate layer: data (CRUD), execution (dispatch/kill), orchestration (loop/schedule)
- Maps to Python: `cli.py` (10 commands), `bridge_cmd.py` (6 daemon commands)
- Dependencies: all layers

**MCP Server** (`src/mcp/server.ts` + `src/mcp/tools.ts`)
- Exposes Bridge operations as MCP tools consumed by Bridge Bot
- Transport: stdio (Claude Code spawns Bridge MCP as subprocess)
- 23+ tools mapping 1:1 to Python `mcp_server.py` tool registry
- Dependencies: all layers (each tool delegates to appropriate layer)

**Stop Hook Binary** (entry point TBD, maps to Python `on_complete.py:main()`)
- Invoked by Claude Code when a task's `claude -p` process exits
- Receives: `--session-id`, `--task-id` via CLI args
- Must start fast (<100ms) — imports only data + execution layers
- Dependencies: data layer, CompletionHandler

#### 4.3.2 Orchestration (Layer 5)

**LoopOrchestrator** (`src/orchestration/loop.ts`)
- State machine: `running → (dispatch → evaluate → decide) → completed/failed/cancelled`
- Iteration flow: dispatch task → wait for completion → evaluate done condition → continue or stop
- Tracks: iteration count, consecutive failures, total cost, approval state
- Interfaces: `ILoopOrchestrator` (5 methods, expanding to ~9)
- Dependencies: IDatabase, IDispatcher, ILoopEvaluator, INotifier

**LoopEvaluator** (`src/orchestration/evaluator.ts`)
- Evaluates done conditions: `command:`, `file_exists:`, `file_contains:`, `llm_judge:`, `manual:`
- Parses condition strings into typed DoneCondition objects
- For `llm_judge`: spawns `claude -p` with rubric prompt
- Interface: `ILoopEvaluator` (1 method, expanding to ~3)
- Dependencies: none (pure function + subprocess for llm_judge)

**Scheduler** (`src/orchestration/scheduler.ts`)
- Polls `schedules` table every 60s for due schedules
- Computes next_run using anchor-based timing (prevents drift)
- Error backoff: `interval * 2^consecutive_errors` (capped at 8x)
- Interface: `IScheduler` (3 methods)
- Dependencies: IDatabase, IDispatcher

#### 4.3.3 Channel (Layer 4, cross-cutting)

**IChannelAdapter** — Platform abstraction
- Each platform (Telegram, Discord, Slack) implements the same interface
- Lifecycle: `start()` / `stop()` — connects/disconnects from platform API
- Messaging: `sendMessage()`, `editMessage()`, `deleteMessage()`
- Events: `onMessage()`, `onCommand()` — callback registration
- The Notifier (Layer 3) uses IChannelAdapter to deliver notifications

**IMessageFormatter** — Platform-specific formatting
- Each platform has different markup: HTML (Telegram), Markdown (Discord), mrkdwn (Slack)
- `chunkMessage()` splits long messages respecting platform limits
  - Telegram: 4096 chars, fence-aware splitting
  - Discord: 2000 chars
  - Slack: 40000 chars

**TelegramAdapter** (`src/channel/telegram/adapter.ts`)
- Uses `grammy` SDK for Bot API interaction
- Absorbs logic from existing `channel/server.ts` + `channel/lib.ts` (~3,500 LOC)
- Handles: allowlist, file downloads, inbound tracking, outbound queue

#### 4.3.4 Execution (Layer 3)

**Dispatcher** (`src/execution/dispatcher.ts`)
- Spawns `claude -p --agent <name> --session-id <uuid> --output-format json`
- Process isolation: `detached: true` (own process group)
- Writes stdout to result file, stderr to log file
- Passes `CLAUDE_BRIDGE_HOME` env var
- Interface: `IDispatcher` (3 methods, expanding to ~5)

**CompletionHandler** (`src/execution/on-complete.ts`)
- Parses result JSON from `--output-format json` output
- Extracts: exit_code, cost_usd, num_turns, result_summary, duration
- Updates task in DB → auto-dequeues next task → creates notification
- Hands off to LoopOrchestrator if task belongs to a loop
- Interface: `ICompletionHandler` (1 method)

**ProcessWatcher** (`src/execution/watcher.ts`)
- Fallback for tasks where stop hook didn't fire (process crash, OOM, etc.)
- Polls every 5 min: checks if PID is alive for each `running` task
- If PID dead: marks task failed, creates notification
- Timeout detection: tasks running > 360 min → force kill
- Interface: `IProcessWatcher` (2 methods)

**Notifier** (`src/execution/notify.ts`)
- Formats completion messages (cost, duration, summary, iteration info)
- Routes to appropriate IChannelAdapter based on task's channel field
- Retry logic: exponential backoff, max 3 attempts
- Interface: `INotifier` (1 method)

#### 4.3.5 Data (Layer 2)

**BridgeDatabase** (`src/data/db.ts`)
- `bun:sqlite` with WAL mode, foreign keys ON
- Schema matches Python `db.py` exactly (backward compatible)
- Atomic operations: `BEGIN EXCLUSIVE` for task creation and dequeue
- Interface: `IDatabase` (20 methods, expanding to ~55)

**SessionManager** (`src/data/session.ts`)
- `deriveSessionId(agent, project)` → `"agent--project-basename"`
- Workspace paths: `~/.claude-bridge/workspaces/{session_id}/`
- Agent file paths: `{bot_dir}/.claude/agents/bridge--{session_id}.md`
- Validation: agent names (alphanumeric + hyphens, no `--`)
- Interface: `ISessionManager` (3 methods, expanding to ~8)

**ConfigProvider** (`src/config.ts`)
- Reads `${CLAUDE_BRIDGE_HOME}/config.json` (default: `~/.claude-bridge`)
- Falls back to env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Interface: `IConfigProvider` (1 method + 2 readonly props)

#### 4.3.6 Types (Layer 1)

**types.ts** — shared across all layers
- `Agent`, `Session`, `Task`, `TaskCreateInput`, `TaskStatus`
- `Loop`, `LoopStatus`, `Schedule`
- `BridgeConfig`, `Notification`
- No logic, no dependencies — pure type definitions

### 4.4 Dependency Rules

1. **Types** (Layer 1) → depends on nothing
2. **Data** (Layer 2) → depends on Types only
3. **Execution** (Layer 3) → depends on Data + Types
4. **Channel** (Layer 4) → depends on Types only (adapters are self-contained)
5. **Orchestration** (Layer 5) → depends on Execution + Data + Types
6. **Entry Points** (Layer 6) → depends on all layers

**Cross-cutting exception:** Notifier (Layer 3) depends on IChannelAdapter (Layer 4).
This is acceptable because Notifier uses the channel interface, not implementation.

### 4.5 New Components Needed (Not in Python)

| Component | Purpose | Rationale |
|-----------|---------|-----------|
| `AgentMdGenerator` | Generate agent .md files | Maps to Python `agent_md.py` — no TS interface yet |
| `ClaudeMdInit` | Auto-init project CLAUDE.md | Maps to Python `claude_md_init.py` |
| `PermissionRelay` | PreToolUse hook handler | Maps to Python `permission_relay.py` |
| `MessageDatabase` | Separate DB for messages | Maps to Python `message_db.py` |
| `DaemonManager` | launchd/systemd integration | Maps to Python `daemon.py` |
| `BridgeBotMdGen` | Bridge Bot CLAUDE.md generator | Maps to Python `bridge_bot_claude_md.py` |

These will be added as interfaces are expanded in their respective waves.

---

## 5. Data Architecture

### 5.1 Database Topology

Claude Bridge uses **two SQLite databases** to isolate high-frequency message I/O
from core state management:

```
~/.claude-bridge/                    (CLAUDE_BRIDGE_HOME)
├── bridge.db                        Core state: agents, tasks, loops, schedules, permissions
├── bridge.db-wal                    WAL file (auto-managed by SQLite)
├── bridge.db-shm                    Shared memory file (auto-managed)
├── messages.db                      Message queue: inbound/outbound messages
├── messages.db-wal
├── messages.db-shm
├── config.json                      Instance configuration
└── workspaces/
    └── {session_id}/
        └── tasks/
            ├── task-{id}-result.json   Claude Code JSON output
            └── task-{id}-stderr.log    Process stderr capture
```

### 5.2 Core Database Schema (bridge.db)

Exact replica of Python `db.py` schema — TS must produce identical DDL for
backward compatibility.

```sql
-- Connection setup (every open)
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Agents: one per (name, project_dir) pair
CREATE TABLE IF NOT EXISTS agents (
    name TEXT NOT NULL,
    project_dir TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    agent_file TEXT NOT NULL,
    purpose TEXT,
    state TEXT DEFAULT 'created',         -- created | idle | running
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_task_at TIMESTAMP,
    total_tasks INTEGER DEFAULT 0,
    model TEXT DEFAULT 'sonnet',
    PRIMARY KEY (name, project_dir)
);

-- Tasks: lifecycle tracking for each dispatched task
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES agents(session_id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'pending',         -- pending | running | queued | done | failed | timeout | killed
    position INTEGER,                     -- queue position (for queued tasks)
    pid INTEGER,                          -- OS process ID
    result_file TEXT,                     -- path to result JSON
    result_summary TEXT,                  -- extracted summary from result
    cost_usd REAL,                        -- API cost in USD
    duration_ms INTEGER,                  -- execution time
    num_turns INTEGER,                    -- Claude conversation turns
    exit_code INTEGER,
    error_message TEXT,
    model TEXT,                           -- model used for this task
    task_type TEXT DEFAULT 'standard',    -- standard | team
    parent_task_id INTEGER REFERENCES tasks(id),  -- for team subtasks
    channel TEXT DEFAULT 'cli',           -- cli | telegram | discord | slack
    channel_chat_id TEXT,
    channel_message_id TEXT,
    user_id TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    reported INTEGER DEFAULT 0            -- 1 = notification sent
);

-- Permission relay: tracks approval/denial for dangerous operations
CREATE TABLE IF NOT EXISTS permissions (
    id TEXT PRIMARY KEY,                  -- UUID
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,              -- e.g., "Bash", "Write"
    command TEXT,                         -- the actual command
    description TEXT,
    status TEXT DEFAULT 'pending',        -- pending | approved | denied | timeout
    response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,
    timeout_seconds INTEGER DEFAULT 300
);

-- Teams: multi-agent coordination
CREATE TABLE IF NOT EXISTS teams (
    name TEXT PRIMARY KEY,
    lead_agent TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_members (
    team_name TEXT NOT NULL REFERENCES teams(name) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    PRIMARY KEY (team_name, agent_name)
);

-- Notifications: completion message delivery queue
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    channel TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT DEFAULT 'pending',        -- pending | sent | failed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);

-- Goal loops: iterative task execution
CREATE TABLE IF NOT EXISTS loops (
    loop_id TEXT PRIMARY KEY,             -- UUID
    agent TEXT NOT NULL,
    project TEXT NOT NULL,
    goal TEXT NOT NULL,
    done_when TEXT NOT NULL,              -- condition string: "command:", "file_exists:", etc.
    loop_type TEXT NOT NULL DEFAULT 'bridge',  -- bridge | agent | auto
    status TEXT NOT NULL DEFAULT 'running',    -- running | done | failed | exceeded | cancelled
    max_iterations INTEGER NOT NULL DEFAULT 10,
    max_consecutive_failures INTEGER NOT NULL DEFAULT 3,
    current_iteration INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    max_cost_usd REAL,                   -- cost ceiling (nullable = unlimited)
    pending_approval INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    finish_reason TEXT,
    current_task_id TEXT
);

-- Loop iterations: per-iteration tracking
CREATE TABLE IF NOT EXISTS loop_iterations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    loop_id TEXT NOT NULL,
    iteration_num INTEGER NOT NULL,
    task_id TEXT,
    prompt TEXT,
    result_summary TEXT,
    done_check_passed INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);

-- Schedules: cron-like recurring task definitions
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    interval_minutes INTEGER,             -- interval-based scheduling
    cron_expr TEXT,                        -- cron expression (alternative)
    run_once INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    run_count INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,
    last_run_at TIMESTAMP,
    next_run_at TIMESTAMP,
    last_error TEXT,
    channel TEXT DEFAULT 'cli',
    channel_chat_id TEXT,
    user_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, agent_name)
);

-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON schedules(next_run_at, enabled);
CREATE INDEX IF NOT EXISTS idx_loops_status ON loops(status);
CREATE INDEX IF NOT EXISTS idx_loops_agent ON loops(agent);
CREATE INDEX IF NOT EXISTS idx_loop_iterations_loop ON loop_iterations(loop_id);
CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
CREATE INDEX IF NOT EXISTS idx_permissions_status ON permissions(status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
```

### 5.3 Message Database Schema (messages.db)

```sql
PRAGMA journal_mode=WAL;

-- Inbound: messages received from messaging platforms
CREATE TABLE IF NOT EXISTS inbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'telegram',
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT,
    message_text TEXT NOT NULL,
    message_id TEXT,                      -- platform-specific message ID
    status TEXT DEFAULT 'pending',        -- pending | delivered | acknowledged | failed
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP,
    acknowledged_at TIMESTAMP
);

-- Outbound: messages to send to messaging platforms
CREATE TABLE IF NOT EXISTS outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'telegram',
    chat_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    reply_to_message_id TEXT,
    source TEXT DEFAULT 'bot',            -- bot | notification
    status TEXT DEFAULT 'pending',        -- pending | sent | failed
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP,
    task_id INTEGER                       -- links to tasks.id in bridge.db
);

-- Poller state: tracks platform polling cursors
CREATE TABLE IF NOT EXISTS poller_state (
    key TEXT PRIMARY KEY,
    value TEXT                            -- e.g., last_update_id for Telegram getUpdates
);

CREATE INDEX IF NOT EXISTS idx_inbound_status ON inbound_messages(status);
CREATE INDEX IF NOT EXISTS idx_outbound_status ON outbound_messages(status);
```

### 5.4 WAL Mode & Concurrency

**Why WAL:** Multiple processes access the database concurrently:
- Bridge Bot (MCP server) — reads/writes agents, tasks
- Stop hook (on-complete) — writes task results, reads loops
- Watcher (cron) — reads running tasks, writes timeouts
- Channel server — reads/writes messages.db
- CLI — reads status, writes agent CRUD

**WAL guarantees:**
- Multiple concurrent readers don't block each other
- Single writer doesn't block readers
- Readers see a consistent snapshot (no partial writes)

**Setting WAL in Bun:**
```typescript
import { Database } from "bun:sqlite";

const db = new Database(path, { create: true });
db.exec("PRAGMA journal_mode=WAL");
db.exec("PRAGMA foreign_keys=ON");
```

### 5.5 Critical Transaction Patterns

#### Atomic Task Dispatch (prevents double-dispatch)

```typescript
// Python equivalent: db.py atomic_check_and_create_task()
// Uses BEGIN EXCLUSIVE to lock the database during check-and-insert
function atomicCheckAndCreateTask(
  db: Database,
  sessionId: string,
  prompt: string,
  channel: string,
): { taskId: number | null; busy: boolean } {
  // BEGIN EXCLUSIVE prevents any other connection from reading or writing
  db.exec("BEGIN EXCLUSIVE");
  try {
    const running = db
      .query("SELECT id FROM tasks WHERE session_id = ? AND status = 'running' LIMIT 1")
      .get(sessionId);

    if (running) {
      db.exec("COMMIT");
      return { taskId: null, busy: true };
    }

    const result = db
      .query(
        `INSERT INTO tasks (session_id, prompt, status, channel)
         VALUES (?, ?, 'running', ?)`
      )
      .run(sessionId, prompt, channel);

    db.exec("COMMIT");
    return { taskId: Number(result.lastInsertRowid), busy: false };
  } catch (e) {
    db.exec("ROLLBACK");
    throw e;
  }
}
```

#### Auto-Dequeue (pops next queued task on completion)

```typescript
// After a task completes, check if there's a queued task waiting
function dequeueNextTask(db: Database, sessionId: string): Row | null {
  db.exec("BEGIN EXCLUSIVE");
  try {
    const next = db
      .query(
        `SELECT id, prompt FROM tasks
         WHERE session_id = ? AND status = 'queued'
         ORDER BY position ASC LIMIT 1`
      )
      .get(sessionId);

    if (next) {
      db.query("UPDATE tasks SET status = 'running', started_at = ? WHERE id = ?")
        .run(new Date().toISOString(), next.id);
    }

    db.exec("COMMIT");
    return next;
  } catch (e) {
    db.exec("ROLLBACK");
    throw e;
  }
}
```

### 5.6 State Machines

#### Agent State
```
created ──→ idle ──→ running ──→ idle
                        │          ▲
                        └──────────┘
                       (task done)
```

#### Task Status
```
pending ──→ running ──→ done
    │          │
    │          ├──→ failed
    │          ├──→ timeout
    │          └──→ killed
    │
    └──→ queued ──→ running (dequeued)
            │
            └──→ cancelled
```

#### Loop Status
```
running ──→ done       (done condition met)
    │
    ├──→ failed        (max failures exceeded)
    ├──→ exceeded      (max iterations or cost exceeded)
    ├──→ cancelled     (user cancelled)
    │
    └──→ paused ──→ running (resumed)
```

### 5.7 Bun SQLite Considerations

| Python (`sqlite3`) | Bun (`bun:sqlite`) | Notes |
|--------------------|---------------------|-------|
| `conn.row_factory = sqlite3.Row` | `.all()` returns objects by default | No explicit row factory needed |
| `conn.execute(sql, params)` | `db.query(sql).run/get/all(params)` | Prepared statements are cached |
| `cursor.lastrowid` | `result.lastInsertRowid` | Returns BigInt — cast to Number |
| `conn.isolation_level = None` | `db.exec("BEGIN EXCLUSIVE")` | Manual transaction control |
| `fetchone()` → `Row` or `None` | `.get()` → object or `undefined` | Check `undefined`, not `null` |
| Named params `:name` | Named params `$name` or `?` positional | Different placeholder syntax |

### 5.8 Migration-Safe Schema Evolution

The TS codebase must handle Python databases that may have been created at different
versions. Strategy:

1. Run `CREATE TABLE IF NOT EXISTS` for all tables (idempotent)
2. Use `ALTER TABLE ADD COLUMN IF NOT EXISTS` for columns added after initial release
3. Never drop or rename columns — only add
4. Python's `db.py` already does this pattern (checks for column existence before ALTER)

---

## 6. Integration Points

### 6.1 Integration Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    CLAUDE BRIDGE TS                               │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────────┐  │
│  │ Telegram  │  │ Discord  │  │   Slack   │  │  MCP Server   │  │
│  │ Adapter   │  │ Adapter  │  │  Adapter  │  │  (stdio)      │  │
│  └─────┬─────┘  └────┬─────┘  └─────┬─────┘  └───────┬───────┘  │
│        │              │              │                │          │
└────────┼──────────────┼──────────────┼────────────────┼──────────┘
         │              │              │                │
         ▼              ▼              ▼                ▼
  ┌──────────────┐ ┌──────────┐ ┌──────────┐  ┌──────────────────┐
  │ Telegram Bot │ │ Discord  │ │  Slack   │  │  Claude Code     │
  │ API (HTTPS)  │ │ Gateway  │ │  Socket  │  │  (stdin/stdout)  │
  │              │ │ (WSS)    │ │  Mode    │  │                  │
  │ api.telegram │ │discord.  │ │(WSS)     │  │  Spawns Bridge   │
  │ .org/bot...  │ │ gg       │ │          │  │  MCP as child    │
  └──────────────┘ └──────────┘ └──────────┘  └──────────────────┘
```

### 6.2 MCP Integration (Claude Code ↔ Bridge)

**Transport:** stdio (stdin/stdout JSON-RPC 2.0)

Claude Code spawns Bridge's MCP server as a child process and communicates via stdio.
This is configured in `.mcp.json` (per-project) or `mcp.json` (plugin-level).

**Current channel/server.ts pattern** (to be absorbed):
```typescript
// MCP server with channel capability (push notifications)
const mcp = new Server(
  { name: "bridge", version: "1.0.0" },
  {
    capabilities: {
      tools: {},
      experimental: { "claude/channel": {} },  // Enables push notifications
    },
    instructions: [
      // Bridge Bot behavior instructions embedded in MCP server
    ],
  }
);
```

**Push notification mechanism:**
```typescript
// Push a Telegram message into the Bridge Bot's conversation
mcp.notification({
  method: "notifications/claude/channel",
  params: {
    channel: `<channel source="bridge" chat_id="${chatId}" user="${username}" tracking_id="${trackingId}" ts="${ts}">${messageText}</channel>`,
  },
});
```

**Tool registry (23+ tools):**

| Tool Category | Tools | Protocol |
|---------------|-------|----------|
| **Agent CRUD** | `bridge_agents`, `bridge_create_agent` | MCP CallTool |
| **Task Dispatch** | `bridge_dispatch`, `bridge_status`, `bridge_kill`, `bridge_history` | MCP CallTool |
| **Messaging** | `reply`, `bridge_acknowledge`, `bridge_check_messages`, `bridge_get_notifications` | MCP CallTool |
| **Loop Mgmt** | `bridge_loop`, `bridge_loop_status`, `bridge_loop_cancel`, `bridge_loop_approve`, `bridge_loop_reject`, `bridge_loop_list`, `bridge_loop_history`, `bridge_loop_notify` | MCP CallTool |
| **Schedules** | `bridge_schedule_add`, `bridge_schedule_remove`, `bridge_schedule_list`, `bridge_schedule_pause`, `bridge_schedule_resume` | MCP CallTool |
| **Files** | `download_attachment` | MCP CallTool |

**MCP config (ts-src/mcp.json):**
```json
{
  "mcpServers": {
    "bridge": {
      "command": "bun",
      "args": ["run", "ts-src/src/mcp/server.ts"],
      "env": {
        "CLAUDE_BRIDGE_HOME": "${HOME}/.claude-bridge"
      }
    }
  }
}
```

### 6.3 Telegram Integration

**SDK:** `grammy` (v1.21+) — TypeScript-native Telegram Bot API wrapper

**Connection:** Long polling via `bot.start()` (getUpdates loop)

**Message flow (inbound):**
```
Telegram servers ──getUpdates──→ grammy Bot
                                    │
                    bot.on('message', handler)
                                    │
                    ┌───────────────▼───────────────┐
                    │ 1. Check allowlist             │
                    │ 2. Track in messages.db        │
                    │ 3. Download attachments (if any)│
                    │ 4. Push via MCP notification    │
                    └───────────────────────────────┘
```

**Message flow (outbound):**
```
CompletionHandler ──creates notification──→ messages.db (outbound)
                                                │
                              processOutbound() (interval: 2s)
                                                │
                                    ┌───────────▼───────────────┐
                                    │ bot.api.sendMessage(      │
                                    │   chatId, text,           │
                                    │   { parse_mode: "HTML" }  │
                                    │ )                          │
                                    └───────────────────────────┘
```

**Key implementation details:**
- **Allowlist:** `config.json` → `allowFrom: [chatId1, chatId2]` or `telegram_chat_id: single`
- **Message chunking:** 4096 char limit, fence-aware splitting (don't break code blocks)
- **HTML formatting:** Telegram uses HTML mode — `<b>`, `<i>`, `<code>`, `<pre>`
- **File downloads:** `bot.api.getFile(fileId)` → download to `~/.claude-bridge/inbox/`
- **Retry logic:** Exponential backoff on 429 (rate limit), max 3 retries

**grammy SDK usage:**
```typescript
import { Bot } from "grammy";

const bot = new Bot(token);

bot.on("message", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from?.id);
  const text = ctx.message?.text ?? "";
  // ... process message
});

// Send with HTML formatting
await bot.api.sendMessage(chatId, htmlMessage, { parse_mode: "HTML" });
```

### 6.4 Discord Integration (Phase 3)

**SDK:** `discord.js` (v14+) — requires adding to package.json

**Connection:** WebSocket via Discord Gateway (no public URL needed)

**Key differences from Telegram:**
- **Thread support** — Discord supports threaded conversations natively
- **Message limit** — 2000 chars (vs Telegram's 4096)
- **Markdown** — Standard markdown (`**bold**`, `` `code` ``, ` ```lang\ncode``` `)
- **Reactions** — Full emoji reactions (used for approval workflows)
- **Slash commands** — Discord supports `/dispatch`, `/status` natively

**Adapter contract:**
```typescript
class DiscordAdapter implements IChannelAdapter {
  readonly platform = "discord";
  readonly maxMessageLength = 2000;
  readonly supportsThreads = true;
  readonly supportsReactions = true;
  readonly supportsFileUpload = true;
  readonly markdownFormat = "standard";
}
```

### 6.5 Slack Integration (Phase 6)

**SDK:** `@slack/bolt` (v4+) — requires adding to package.json

**Connection:** Socket Mode (WebSocket, no public URL needed)

**Key differences:**
- **Message limit** — 40000 chars (generous)
- **mrkdwn format** — `*bold*` (not `**`), `_italic_`, `<url|text>` (not `[text](url)`)
- **Blocks API** — Slack supports rich block layouts (sections, buttons, dividers)
- **Thread support** — `thread_ts` parameter for threaded replies
- **No syntax highlighting** — Code blocks have no language-aware highlighting

**Adapter contract:**
```typescript
class SlackAdapter implements IChannelAdapter {
  readonly platform = "slack";
  readonly maxMessageLength = 40000;
  readonly supportsThreads = true;
  readonly supportsReactions = true;
  readonly supportsFileUpload = true;
  readonly markdownFormat = "slack-mrkdwn";
}
```

### 6.6 Claude Code CLI Integration

**Binary:** `claude` (must be in PATH)

**Dispatch command:**
```bash
claude \
  --agent bridge--{session_id} \
  --session-id {deterministic-uuid} \
  --output-format json \
  --dangerously-skip-permissions \
  -p "{task prompt}"
```

**Process management:**
```typescript
const proc = Bun.spawn(cmd, {
  cwd: expandedProjectDir,
  stdout: Bun.file(resultFile),   // Capture JSON output
  stderr: Bun.file(stderrFile),   // Capture logs
  env: {
    ...process.env,
    CLAUDE_BRIDGE_HOME: bridgeHome,
  },
  detached: true,                  // Own process group
});

// Track PID in SQLite
db.query("UPDATE tasks SET pid = ? WHERE id = ?").run(proc.pid, taskId);
```

**Result file parsing (on-complete):**
```typescript
interface ClaudeResult {
  type: "result";
  subtype: "success" | "error_max_turns" | "error_during_execution";
  cost_usd: number;
  duration_ms: number;
  duration_api_ms: number;
  num_turns: number;
  result: string;             // Summary text
  session_id: string;
}
```

**Stop hook integration:**
The agent .md file includes a Stop hook that Claude Code calls when the process exits:
```yaml
---
tools:
  - Read
  - Edit
  - Write
  - Bash
  - Grep
  - Glob
isolation: worktree
memory: project
hooks:
  Stop:
    - command: "bun run ts-src/src/execution/on-complete.ts --session-id SESSION --task-id TASK"
---
```

### 6.7 File System Integration

| Path | Purpose | Owner |
|------|---------|-------|
| `~/.claude-bridge/` | Instance home directory | Bridge |
| `~/.claude-bridge/bridge.db` | Core database | Bridge |
| `~/.claude-bridge/messages.db` | Message queue | Bridge |
| `~/.claude-bridge/config.json` | Configuration | Bridge |
| `~/.claude-bridge/workspaces/{session}/tasks/` | Task results | Bridge |
| `~/.claude-bridge/inbox/` | Downloaded attachments | Bridge |
| `{bot_dir}/.claude/agents/bridge--{session}.md` | Agent definitions | Bridge (generates) |
| `{project}/.claude/settings.local.json` | Stop hook registration | Bridge (modifies) |
| `~/.claude/projects/{path}/memory/` | Auto Memory | Claude Code (read-only for Bridge) |

### 6.8 Integration Sequence: End-to-End Task Dispatch

```
User                Telegram       Bridge         SQLite        Claude Code
  │                   │             │               │               │
  │ "dispatch backend  │             │               │               │
  │  add pagination"   │             │               │               │
  │──────────────────→│             │               │               │
  │                   │ getUpdates  │               │               │
  │                   │────────────→│               │               │
  │                   │             │ trackInbound  │               │
  │                   │             │──────────────→│               │
  │                   │             │               │               │
  │                   │             │ pushMessage   │               │
  │                   │             │ (MCP notif)   │               │
  │                   │             │──→Bridge Bot  │               │
  │                   │             │   (parses)    │               │
  │                   │             │               │               │
  │                   │             │ bridge_dispatch(backend, ...)  │
  │                   │             │ atomicCreate  │               │
  │                   │             │──────────────→│               │
  │                   │             │               │               │
  │                   │             │ spawn claude -p               │
  │                   │             │──────────────────────────────→│
  │                   │             │               │               │
  │                   │             │               │    (working)  │
  │                   │             │               │               │
  │                   │             │               │  Stop hook    │
  │                   │             │←──────────────────────────────│
  │                   │             │ on-complete   │               │
  │                   │             │ updateTask    │               │
  │                   │             │──────────────→│               │
  │                   │             │ createNotif   │               │
  │                   │             │──────────────→│               │
  │                   │             │               │               │
  │                   │ sendMessage │               │               │
  │                   │←────────────│               │               │
  │ "✓ Task done      │             │               │               │
  │  Cost: $0.04"     │             │               │               │
  │←──────────────────│             │               │               │
```

---

## 7. Deployment Model

### 7.1 Deployment Modes

Claude Bridge TS supports three deployment modes:

```
┌─────────────────────────────────────────────────────────────────┐
│                    DEPLOYMENT MODES                              │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐ │
│  │ Mode 1: Plugin   │  │ Mode 2: Standalone│ │ Mode 3: Hybrid │ │
│  │                   │  │                   │ │ (Migration)    │ │
│  │ Installed via     │  │ Cloned repo,     │ │ TS plugin +    │ │
│  │ Claude Code       │  │ bun run directly │ │ Python bridge- │ │
│  │ plugin manager    │  │ or as daemon     │ │ cli fallback   │ │
│  │                   │  │                  │ │                │ │
│  │ Target: post-     │  │ Target: dev &    │ │ Target: during │ │
│  │ migration GA      │  │ self-hosting     │ │ migration      │ │
│  └─────────────────┘  └─────────────────┘  └────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Mode 1: Claude Code Plugin

**Target audience:** End users installing via plugin marketplace

**Plugin structure:**
```
ts-src/
├── .claude-plugin/
│   └── plugin.json           # Plugin metadata (name, version, description)
├── mcp.json                  # MCP server registration
├── skills/                   # Slash commands (/bridge:dispatch, /bridge:status)
│   ├── dispatch.md
│   └── status.md
├── package.json
└── src/
    └── ...                   # All source code
```

**plugin.json:**
```json
{
  "name": "claude-bridge",
  "version": "0.6.0",
  "description": "Multi-session Claude Code dispatch from Telegram, Discord, and Slack.",
  "authors": ["Hieu TRAN"],
  "keywords": ["channel", "mcp", "telegram", "discord", "slack"],
  "license": "MIT"
}
```

**mcp.json** (uses `CLAUDE_PLUGIN_ROOT` for portability):
```json
{
  "mcpServers": {
    "bridge": {
      "command": "bun",
      "args": ["${CLAUDE_PLUGIN_ROOT}/src/mcp/server.ts"],
      "env": {
        "CLAUDE_BRIDGE_HOME": "${HOME}/.claude-bridge"
      }
    }
  }
}
```

**Install flow:**
1. User runs plugin install command (marketplace or git URL)
2. Claude Code clones plugin to `~/.claude/plugins/claude-bridge/`
3. MCP server auto-registered from `mcp.json`
4. Skills available as `/bridge:dispatch`, `/bridge:status`
5. User sets up via `bridge-cli setup --token <token> --chat-id <id>`

### 7.3 Mode 2: Standalone

**Target audience:** Self-hosters, contributors, advanced users

**Setup:**
```bash
# Clone and install
git clone https://github.com/hieutran/claude-bridge
cd claude-bridge/ts-src
bun install

# Configure
bun run src/cli/index.ts setup --token "$TELEGRAM_BOT_TOKEN" --chat-id "$CHAT_ID"

# Run as daemon
bun run src/cli/index.ts daemon install
bun run src/cli/index.ts daemon start

# Or run directly
bun run src/cli/index.ts start
```

### 7.4 Mode 3: Hybrid (During Migration)

**Target audience:** Existing Python users during migration period

During migration, TS can delegate unimplemented features to Python `bridge-cli`:

```typescript
// Fallback to Python CLI for features not yet ported
import { execSync } from "child_process";

function bridgeCliFallback(command: string): string {
  return execSync(`bridge-cli ${command}`, { encoding: "utf-8" });
}
```

**Coexistence rules:**
- Same `~/.claude-bridge/` directory (shared SQLite DB)
- Same `bridge.db` schema (backward compatible)
- TS reads/writes same tables as Python
- MCP tool names identical (no Bridge Bot CLAUDE.md changes needed)

### 7.5 Configuration

**config.json** (`~/.claude-bridge/config.json`):
```json
{
  "telegram_bot_token": "123:ABC...",
  "telegram_chat_id": "123456789",
  "bot_dir": "/Users/hieu/projects/bridge-bot",
  "allowFrom": ["123456789", "987654321"],
  "model": "sonnet"
}
```

**Environment variables (override config.json):**

| Env Var | Purpose | Default |
|---------|---------|---------|
| `CLAUDE_BRIDGE_HOME` | Instance home directory | `~/.claude-bridge` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | from config.json |
| `TELEGRAM_CHAT_ID` | Default chat ID | from config.json |
| `CLAUDE_PLUGIN_ROOT` | Plugin install path (set by Claude Code) | — |

### 7.6 Multi-Instance Support

Multiple Bridge instances run from different `CLAUDE_BRIDGE_HOME` directories:

```bash
# Main instance (default)
~/.claude-bridge/
├── bridge.db
├── messages.db
├── config.json
└── workspaces/

# Second instance (tam)
~/.claude-bridge-tam/
├── bridge.db
├── messages.db
├── config.json
└── workspaces/
```

**Daemon naming:**
- `~/.claude-bridge` → service: `claude-bridge`, launchd: `ai.claude-bridge`
- `~/.claude-bridge-tam` → service: `claude-bridge-tam`, launchd: `ai.claude-bridge-tam`

### 7.7 Daemon Management

**macOS (launchd):**
```xml
<!-- ~/Library/LaunchAgents/ai.claude-bridge.plist -->
<plist>
  <dict>
    <key>Label</key><string>ai.claude-bridge</string>
    <key>ProgramArguments</key>
    <array>
      <string>bun</string>
      <string>run</string>
      <string>/path/to/ts-src/src/cli/index.ts</string>
      <string>start</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>CLAUDE_BRIDGE_HOME</key>
      <string>~/.claude-bridge</string>
    </dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>~/.claude-bridge/bridge.log</string>
    <key>StandardErrorPath</key><string>~/.claude-bridge/bridge.log</string>
  </dict>
</plist>
```

**Linux (systemd):**
```ini
# ~/.config/systemd/user/claude-bridge.service
[Unit]
Description=Claude Bridge
After=network.target

[Service]
ExecStart=/usr/bin/bun run /path/to/ts-src/src/cli/index.ts start
Environment=CLAUDE_BRIDGE_HOME=%h/.claude-bridge
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

---

## 8. Architecture Decision Records

### ADR-1: Bun over Node.js

**Status:** Accepted

**Context:** Claude Code's official plugin ecosystem uses TypeScript/Bun. The migration
must choose a runtime.

**Decision:** Use Bun as the sole runtime.

**Rationale:**
- Claude Code plugins require Bun (ecosystem constraint)
- `bun:sqlite` is built-in — no external `better-sqlite3` dependency (which requires native compilation)
- ~10ms cold start vs Node's ~50ms and Python's ~200ms (critical for stop hooks)
- Native TypeScript execution (no build step for development)
- `Bun.spawn()` with `detached: true` replaces Python's `start_new_session=True`
- Anthropic acquired Bun, signaling long-term investment in the runtime

**Consequences:**
- Cannot use Node-only packages (few in practice)
- Must test with Bun's runtime behavior (subtle differences in EventEmitter, streams)
- `bun:sqlite` API differs slightly from `better-sqlite3` (e.g., `$param` syntax)

**Alternatives rejected:**
- **Node.js** — No native SQLite, slower startup, not plugin-compatible
- **Deno** — Not supported by Claude Code plugin ecosystem

---

### ADR-2: grammy over raw Telegram HTTP

**Status:** Accepted

**Context:** Telegram integration requires either raw HTTP calls or an SDK wrapper.

**Decision:** Use `grammy` SDK for Telegram Bot API.

**Rationale:**
- TypeScript-native with full type safety (built for Deno/Bun/Node)
- Handles: long polling, rate limiting, retry logic, file downloads
- Battle-tested — 3.7k GitHub stars, active maintenance
- Already used in existing `channel/server.ts` (proven in production)
- Reduces boilerplate: `bot.on("message", ...)` vs manual getUpdates loop

**Consequences:**
- Adds a runtime dependency (~200KB)
- Must match grammy version to Telegram Bot API version
- grammy's context object has opinions about middleware patterns

**Alternatives rejected:**
- **Raw fetch()** — Too much boilerplate for polling, retry, rate limiting
- **telegraf** — Less TypeScript-native, larger bundle, maintenance concerns
- **node-telegram-bot-api** — Node-only, no Bun support

---

### ADR-3: Process group isolation via setsid/detached

**Status:** Accepted

**Context:** Claude Bridge spawns long-running `claude -p` processes. If Bridge dies,
spawned agents must continue running.

**Decision:** Spawn processes with `detached: true` (creates new session/process group).

**Python implementation:**
```python
subprocess.Popen(cmd, start_new_session=True)  # calls setsid() on Unix
```

**Bun implementation:**
```typescript
Bun.spawn(cmd, { detached: true })
```

**Rationale:**
- `start_new_session=True` calls `setsid()` → new session ID, new process group
- Bridge's SIGTERM/SIGKILL won't propagate to agent processes
- Agent processes become orphans (reparented to init/launchd) — this is intentional
- PID tracked in SQLite for later kill/status check

**Consequences:**
- Orphaned processes must be cleaned up by watcher (cron) if stop hook fails
- `kill(pid, SIGTERM)` must be sent to the process group: `process.kill(-pid)` in Node
  or `Bun.spawn(["kill", "-TERM", `-${pid}`])` — **Bun.spawn detached does NOT create
  a new process group by default; must verify behavior**
- On macOS, `launchd` may not reap orphans properly in all cases

**Risk:** Bun's `detached` may behave differently from Python's `start_new_session=True`.
Must verify in integration tests that:
1. Bridge exit doesn't kill agent
2. SIGTERM to Bridge doesn't cascade
3. Agent PID is reapable after completion

---

### ADR-4: WAL mode for all SQLite databases

**Status:** Accepted

**Context:** Multiple processes access SQLite concurrently (Bridge Bot, stop hooks,
watcher, channel server).

**Decision:** Enable WAL mode on every database connection open.

**Implementation:**
```typescript
const db = new Database(path);
db.exec("PRAGMA journal_mode=WAL");
db.exec("PRAGMA foreign_keys=ON");
```

**Rationale:**
- WAL allows concurrent readers without blocking writer
- Critical for: stop hook writing task result while Bridge Bot reads status
- `bun:sqlite` supports WAL natively
- Performance: 10-50x faster than default journal mode for concurrent access

**Consequences:**
- WAL files (`-wal`, `-shm`) must be cleaned up properly (auto on clean shutdown)
- WAL checkpoint happens automatically but can be forced if DB grows
- Database portability: WAL mode creates additional files alongside `.db`

---

### ADR-5: Two-database architecture (bridge.db + messages.db)

**Status:** Accepted

**Context:** Channel server writes inbound/outbound messages at high frequency (every 2s
polling + every message received). Core state (agents, tasks) has lower write frequency.

**Decision:** Separate message queue into `messages.db` from core state in `bridge.db`.

**Rationale:**
- SQLite WAL has a single writer — separating DBs doubles write throughput
- Message queue I/O doesn't block task status updates
- Allows independent cleanup (old messages deleted without vacuuming core DB)
- Python already uses this pattern successfully

**Consequences:**
- Two database connections to manage per process
- No foreign key constraints between databases (task_id in outbound_messages is soft reference)
- Must ensure both DBs are in same directory for consistent backups

---

### ADR-6: Atomic task dispatch with BEGIN EXCLUSIVE

**Status:** Accepted

**Context:** Two concurrent dispatch requests (e.g., from Telegram + scheduler) could
both check "no running task" and both spawn, creating a double-dispatch.

**Decision:** Use `BEGIN EXCLUSIVE` transaction for the check-and-create pattern.

**Rationale:**
- `BEGIN EXCLUSIVE` acquires a write lock on the entire database
- Guarantees: only one transaction can check-and-insert at a time
- Pattern: check running → if free, insert with status='running' → commit
- Python uses this pattern in `db.py:atomic_check_and_create_task()`

**Consequences:**
- Brief lock contention during dispatch (~1ms) — acceptable for Bridge's scale
- Must ensure transaction is short (no I/O inside exclusive section)
- Readers using WAL are NOT blocked by exclusive lock (WAL advantage)

---

### ADR-7: Channel abstraction via IChannelAdapter interface

**Status:** Accepted

**Context:** Bridge must support Telegram (now), Discord (Phase 3), and Slack (Phase 6)
with different APIs, message formats, and capabilities.

**Decision:** Define `IChannelAdapter` + `IMessageFormatter` interfaces. Each platform
provides an implementation pair.

**Rationale:**
- Single interface for core logic to send/receive messages
- Formatter handles platform-specific markup (HTML, Markdown, mrkdwn)
- New channels added by implementing interface — no core changes
- Already scaffolded in `ts-src/src/channel/interface.ts`

**Interface:**
```typescript
interface IChannelAdapter {
  readonly platform: string;
  readonly maxMessageLength: number;
  start(): Promise<void>;
  stop(): Promise<void>;
  sendMessage(chatId: string, text: string, opts?: SendOpts): Promise<string>;
  onMessage(handler: (msg: ChannelMessage) => void): void;
}
```

**Consequences:**
- Lowest-common-denominator API (threads, reactions are optional)
- Platform-specific features (Slack Blocks, Discord embeds) not exposed in interface
- Formatting differences handled at formatter level, not adapter level

---

### ADR-8: MCP channel notifications for push-based messaging

**Status:** Accepted

**Context:** Bridge Bot needs to receive Telegram messages. Two approaches: poll-based
(MCP tool that Bridge Bot calls) or push-based (channel notification that arrives automatically).

**Decision:** Use MCP channel capability (`experimental: { "claude/channel": {} }`) for
push-based message delivery.

**Rationale:**
- Push eliminates polling latency (messages arrive in ~2s vs ~10s poll interval)
- Native Claude Code feature — Bridge registers as a "channel"
- Messages appear as `<channel>` tags in Bridge Bot's conversation
- Already implemented and battle-tested in `channel/server.ts`

**Trade-off:** Channel API is marked "experimental" — may change. However, Claude Bridge
already depends on it in production and Anthropic uses it for official channels.

---

### ADR-9: Stop hooks over polling for task completion

**Status:** Accepted

**Context:** Bridge needs to know when a `claude -p` task completes.

**Decision:** Use Claude Code's Stop hook mechanism as primary, with PID polling as fallback.

**Stop hook (primary):**
- Agent .md includes hook in YAML frontmatter
- Claude Code invokes hook script when process exits
- Hook script (`on-complete.ts`) parses result, updates DB, sends notification

**PID watcher (fallback):**
- Cron job every 5 minutes checks PIDs of `running` tasks
- If PID dead but task still `running` → marks as failed, sends notification
- Catches cases where stop hook didn't fire (process crash, OOM kill)

**Rationale:**
- Stop hooks are immediate (0 latency after completion)
- Polling adds up to 5 min delay for missed completions
- Dual approach provides reliability guarantee (QA-1)

**Consequences:**
- Stop hook binary must start fast (<100ms) — critical Bun advantage over Python
- Hook failure is silent — watcher is essential safety net
- Hook script must handle concurrent invocations (multiple tasks finishing simultaneously)

---

## 9. Migration Strategy

### 9.1 Strategy Overview

**Approach:** Incremental wave-based migration with coexistence. TS plugin works from
Wave 1 by delegating to Python CLI. Each subsequent wave replaces one Python layer
with native TS, until Python can be fully removed.

```
Week 1       Week 2-3     Week 3-4     Week 4-5     Week 5-6     Week 6-7     Week 7
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Wave 1   │ │ Wave 2   │ │ Wave 3   │ │ Wave 4   │ │ Wave 5   │ │ Wave 6   │ │ Wave 7   │
│ Plugin   │ │ Data     │ │ Execution│ │ Orchestr.│ │ CLI &    │ │ Infra    │ │ MCP      │
│ Shell    │ │ Layer    │ │ Layer    │ │ Layer    │ │ Integ.   │ │          │ │ Consolid.│
│          │ │          │ │          │ │          │ │          │ │          │ │          │
│ Plugin   │ │ db.ts    │ │dispatch. │ │ loop.ts  │ │ cli.ts   │ │daemon.ts │ │ Merge    │
│ mcp.json │ │session.ts│ │ on-comp. │ │ eval.ts  │ │agent-md. │ │ tmux.ts  │ │ MCP      │
│ skills/  │ │config.ts │ │ watcher  │ │sched.ts  │ │claude-md │ │ perms.ts │ │ servers  │
│          │ │msg-db.ts │ │ notify   │ │          │ │ memory   │ │          │ │ tools.ts │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘
     │            │             │            │            │            │            │
     ▼            ▼             ▼            ▼            ▼            ▼            ▼
  Plugin       Python       Python       Python       Python      TS-only      TS-only
  + Python     partially    partially    partially    mostly       (Python     (Python
  fallback     replaced     replaced     replaced     replaced     removed)    removed)
```

### 9.2 Wave Details

#### Wave 1: Plugin Shell (Week 1)
**Goal:** Plugin installable from Day 1, delegating all logic to Python.

**Deliverable:** `plugin install claude-bridge` works.

**What's built:**
- `.claude-plugin/plugin.json` — plugin metadata
- `mcp.json` — MCP server registration (points to TS entry)
- `skills/` — slash commands (`/bridge:dispatch`, `/bridge:status`)
- Channel server absorbed from `channel/server.ts`

**Coexistence:** MCP tools call `bridge-cli` (Python) via subprocess:
```typescript
function bridgeCli(cmd: string): string {
  const result = Bun.spawnSync(["bridge-cli", ...cmd.split(" ")]);
  return result.stdout.toString();
}
```

#### Wave 2: Data Layer (Weeks 2-3)
**Goal:** Replace Python SQLite/session with native `bun:sqlite`.

**Modules:**
| Python | TypeScript | LOC | Effort |
|--------|-----------|-----|--------|
| `db.py` (977 LOC) | `data/db.ts` | ~800 | High |
| `message_db.py` (263 LOC) | `data/message-db.ts` | ~200 | Medium |
| `session.py` (140 LOC) | `data/session.ts` | ~120 | Low |
| `__init__.py` (50 LOC) | `config.ts` | ~50 | Low |

**Key risks:** Schema parity — TS must read/write identical SQLite as Python.

**Validation:** Run Python test suite against a DB created by TS (and vice versa).

#### Wave 3: Execution Layer (Weeks 3-4)
**Goal:** Replace subprocess spawning with `Bun.spawn()`.

**Modules:**
| Python | TypeScript | LOC | Effort |
|--------|-----------|-----|--------|
| `dispatcher.py` (114 LOC) | `execution/dispatcher.ts` | ~100 | High |
| `on_complete.py` (264 LOC) | `execution/on-complete.ts` | ~200 | Medium |
| `watcher.py` (279 LOC) | `execution/watcher.ts` | ~200 | Medium |
| `notify.py` (146 LOC) | `execution/notify.ts` | ~120 | Low |

**Critical validation:** Process isolation test — spawn, kill Bridge, verify agent survives.

#### Wave 4: Orchestration (Weeks 4-5)
**Goal:** Port loop state machine and scheduler.

**Modules:**
| Python | TypeScript | LOC | Effort |
|--------|-----------|-----|--------|
| `loop_orchestrator.py` (1,059 LOC) | `orchestration/loop.ts` | ~800 | High |
| `loop_evaluator.py` (313 LOC) | `orchestration/evaluator.ts` | ~250 | Medium |
| `scheduler.py` (125 LOC) | `orchestration/scheduler.ts` | ~100 | Low |

#### Wave 5: CLI & Integration (Weeks 5-6)
**Goal:** Replace `bridge-cli` Python command with TS version.

**Modules:**
| Python | TypeScript | LOC | Effort |
|--------|-----------|-----|--------|
| `cli.py` (2,361 LOC) | `cli/index.ts` | ~1,500 | High |
| `agent_md.py` (160 LOC) | `cli/agent-md.ts` | ~130 | Low |
| `claude_md_init.py` (101 LOC) | `cli/claude-md.ts` | ~80 | Low |
| `memory.py` (95 LOC) | `cli/memory.ts` | ~80 | Low |

#### Wave 6: Infrastructure (Weeks 6-7)
**Goal:** Port daemon management and remove Python dependency.

**Modules:**
| Python | TypeScript | LOC | Effort |
|--------|-----------|-----|--------|
| `daemon.py` (500 LOC) | `infra/daemon.ts` | ~400 | High |
| `bridge_cmd.py` (426 LOC) | `infra/bridge-cmd.ts` | ~350 | Medium |
| `permission_relay.py` (89 LOC) | `infra/permissions.ts` | ~70 | Low |

#### Wave 7: MCP Consolidation (Week 7)
**Goal:** Merge Python MCP and channel server into unified TS MCP server.

**Modules:**
| Python | TypeScript | LOC | Effort |
|--------|-----------|-----|--------|
| `mcp_server.py` (348 LOC) | `mcp/server.ts` | ~300 | Medium |
| `mcp_tools.py` (741 LOC) | `mcp/tools.ts` | ~600 | Medium |
| `bridge_bot_claude_md.py` (521 LOC) | `mcp/bridge-md.ts` | ~400 | Medium |

### 9.3 Coexistence Protocol

During migration (Waves 1-6), Python and TS coexist:

```
                   ┌─────────────────────────┐
                   │     Bridge Bot          │
                   │  (Claude Code session)   │
                   └────────┬────────────────┘
                            │ MCP tools
                            ▼
                   ┌────────────────────────┐
                   │   TS MCP Server        │
                   │                        │
                   │  Implemented? ──Yes──→ Handle natively (TS)
                   │       │                │
                   │      No                │
                   │       │                │
                   │  bridge-cli fallback ──→ Python subprocess
                   └────────────────────────┘
```

**Rules for coexistence:**
1. **Same DB** — both Python and TS read/write `~/.claude-bridge/bridge.db`
2. **Same schema** — TS never adds columns that Python doesn't know about
3. **Same MCP tool names** — Bridge Bot's CLAUDE.md works unchanged
4. **Gradual cutover** — each wave replaces Python calls with native TS
5. **Rollback** — if a wave fails, revert to Python fallback for affected tools

### 9.4 Cutover Criteria

Each wave must pass before moving to the next:

| Wave | Gate Criteria |
|------|--------------|
| **Wave 1** | Plugin installs, channel server receives messages, bridge-cli fallback works |
| **Wave 2** | All `IDatabase` tests pass, TS can read Python-created DB and vice versa |
| **Wave 3** | Task dispatch, completion, kill, timeout all work end-to-end |
| **Wave 4** | Loop: start → iterate → evaluate → complete. Schedule: create → fire → complete |
| **Wave 5** | All CLI commands work via `bun run cli.ts <command>` |
| **Wave 6** | Daemon install/start/stop works on macOS (launchd) and Linux (systemd) |
| **Wave 7** | All 23+ MCP tools work, Python CLI no longer called |

### 9.5 Full Cutover (Post Wave 7)

After Wave 7, Python is no longer needed:

1. Remove Python dependency from installation instructions
2. Update `pyproject.toml` to mark as deprecated
3. Archive Python source (keep in repo under `src/claude_bridge/` for reference)
4. Update Bridge Bot CLAUDE.md to reference TS tools only
5. Submit plugin to Claude Code marketplace

### 9.6 Testing Strategy During Migration

```
Per-wave testing:
├── Unit tests (bun test)
│   └── Mock subprocess, mock SQLite, test business logic
├── Integration tests
│   └── Real SQLite DB, real file I/O, mocked Claude CLI
├── Cross-compatibility tests
│   └── Python creates DB → TS reads it (and vice versa)
└── E2E smoke test
    └── Telegram → Bridge Bot → dispatch → complete → notification
```

**Key rule:** Never call real `claude` CLI in tests — always mock subprocess.

---

## 10. Risk Assessment

### 10.1 Risk Matrix

| ID | Risk | Impact | Likelihood | Severity | Mitigation |
|----|------|--------|------------|----------|------------|
| R-1 | Bun `detached` != Python `start_new_session` | **High** | Medium | **High** | Integration test in Wave 3: kill Bridge, verify agent survives |
| R-2 | `bun:sqlite` WAL behavior differs from Python sqlite3 | **High** | Low | **Medium** | Cross-compatibility test: Python writes → TS reads (and reverse) |
| R-3 | MCP channel API changes (marked "experimental") | **High** | Medium | **High** | Pin MCP SDK version, monitor Anthropic changelog, have polling fallback |
| R-4 | grammy SDK breaks on Bun runtime update | **Medium** | Low | **Low** | Pin grammy version, test on Bun upgrade |
| R-5 | 85% interface gap delays migration | **Medium** | High | **Medium** | Expand interfaces wave-by-wave, not all upfront |
| R-6 | Python/TS DB schema divergence during coexistence | **High** | Medium | **High** | Schema parity test suite, no TS-only columns until cutover |
| R-7 | Stop hook latency regression (TS slower than expected) | **Medium** | Low | **Low** | Benchmark in Wave 3: on-complete must finish in <100ms |
| R-8 | Orphaned processes from Bun.spawn | **Medium** | Medium | **Medium** | Watcher cron catches orphans, test kill -0 check in Bun |
| R-9 | Channel server migration breaks Telegram integration | **High** | Medium | **High** | Keep existing channel/server.ts working until Wave 7 |
| R-10 | Loss of data during DB migration | **High** | Low | **Medium** | Read-only access to existing DB; never DROP/ALTER destructively |

### 10.2 Risk Deep Dives

#### R-1: Process Isolation (Severity: High)

**The problem:** Python's `start_new_session=True` calls `setsid()`, creating a new
session and process group. Bun's `detached: true` may not create a new session —
it may only prevent the parent's signals from reaching the child.

**Impact if realized:** Killing Bridge also kills all running agents. Tasks silently
vanish. Data loss.

**Mitigation plan:**
1. **Wave 3 integration test:** Spawn agent → kill Bridge → verify agent PID alive
2. **Fallback:** If `detached` isn't sufficient, use `Bun.spawn(["setsid", "claude", ...])` — call `setsid` as an explicit wrapper
3. **Verify on both macOS and Linux** — behavior may differ

#### R-3: MCP Channel API Stability (Severity: High)

**The problem:** The push notification mechanism uses `experimental: { "claude/channel": {} }`.
Anthropic could change or remove this API.

**Impact if realized:** Push-based messaging breaks. Bridge falls back to polling
(10s latency vs 2s).

**Mitigation plan:**
1. **Dual-mode support:** Keep polling fallback (Python's `bridge_get_messages` pattern)
2. **Pin MCP SDK:** Don't auto-update `@modelcontextprotocol/sdk`
3. **Monitor:** Watch Claude Code release notes for channel API changes
4. **Alternative:** If channel API removed, use Claude Code's native Channel feature
   (if it supports third-party channels)

#### R-6: Schema Divergence (Severity: High)

**The problem:** During coexistence, both Python and TS write to the same DB. If TS
introduces a column that Python doesn't know about, Python queries may fail or
silently lose data.

**Impact if realized:** Task results lost, agent state corrupted.

**Mitigation plan:**
1. **Schema parity rule:** TS never adds columns until Python is fully retired
2. **Cross-compatibility CI test:** Create DB with Python → read with TS → verify all data
3. **Schema checksum:** Hash CREATE TABLE statements, fail if they differ
4. **Column handling:** Use `SELECT *` or explicit column lists (never assume column order)

#### R-9: Channel Server Migration (Severity: High)

**The problem:** The existing `channel/server.ts` (~3,500 LOC) is battle-tested. Absorbing
it into `TelegramAdapter` risks breaking message delivery.

**Impact if realized:** Users stop receiving task notifications. Messages dropped silently.

**Mitigation plan:**
1. **Keep existing channel server until Wave 7** — don't touch what works
2. **Port incrementally:** Extract testable functions → write tests → verify parity
3. **Shadow mode:** Run old and new in parallel, compare outputs
4. **Rollback path:** If new adapter fails, revert to `channel/server.ts`

### 10.3 Risk Acceptance Criteria

A risk is **accepted** when:
- Mitigation is implemented and tested
- Fallback path exists
- Impact is documented and operator is aware

A risk is **escalated** when:
- Mitigation fails in testing
- No fallback path exists
- Impact could cause data loss or extended downtime

### 10.4 Monitoring & Observability

During and after migration, monitor:

| Signal | Tool | Alert Condition |
|--------|------|----------------|
| Task completion rate | `bridge status` | Tasks stuck in `running` > 6h |
| Notification delivery | `messages.db` outbound | Pending outbound > 10 messages |
| Orphaned processes | `watcher.ts` | PIDs not in DB still running |
| DB integrity | `PRAGMA integrity_check` | Any corruption |
| Stop hook latency | stderr timing | > 500ms per invocation |
| Channel connectivity | grammy error events | > 3 consecutive Telegram API failures |

---

## Appendix: Document Revision History

| Version | Date | Changes |
|---------|------|---------|
| 0.1.0 | 2026-04-09 | Initial architecture document — all 10 sections |
