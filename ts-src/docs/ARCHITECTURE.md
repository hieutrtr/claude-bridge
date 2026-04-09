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
