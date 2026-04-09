# Claude Bridge TypeScript Migration — Implementation Plan

> **Version:** 0.1.0 | **Created:** 2026-04-09
> **Input:** `ts-src/docs/ARCHITECTURE.md` v0.1.0
> **Scope:** Complete implementation plan for migrating Claude Bridge from Python to TypeScript/Bun

---

## Table of Contents

1. [Scope & Assumptions](#1-scope--assumptions)
2. [Work Breakdown Structure](#2-work-breakdown-structure)
3. [Dependency Mapping & Critical Path](#3-dependency-mapping--critical-path)
4. [Timeline & Milestones](#4-timeline--milestones)
5. [Resource Allocation](#5-resource-allocation)
6. [Acceptance Criteria](#6-acceptance-criteria)
7. [Quality Gates & Review Checkpoints](#7-quality-gates--review-checkpoints)
8. [Risk Mitigation Actions](#8-risk-mitigation-actions)
9. [Rollback Strategy](#9-rollback-strategy)
10. [Success Metrics & KPIs](#10-success-metrics--kpis)

---

## 1. Scope & Assumptions

### 1.1 Scope Statement

#### IN SCOPE

| Category | Details | Evidence |
|----------|---------|----------|
| **Python source migration** | All 24 modules in `src/claude_bridge/` (10,012 LOC) → TypeScript in `ts-src/src/` | Architecture doc §1.7, §3.1–3.8 |
| **Channel server absorption** | `channel/server.ts` (1,107 LOC) + `channel/lib.ts` (460 LOC) absorbed into unified TS codebase | Architecture doc §3.5, §4.3.3 |
| **TS interface expansion** | Expand from 62 → ~206 interface methods (85% gap) to reach full Python feature parity | Architecture doc §3.8–3.9 |
| **MCP tool parity** | Expand from 3 scaffolded → 23+ MCP tools | Architecture doc §3.6 |
| **CLI parity** | All 10 CLI commands implemented in TS | Architecture doc §3.6 |
| **Plugin packaging** | `.claude-plugin/plugin.json`, `mcp.json`, `skills/` for Claude Code plugin marketplace | Architecture doc §7.2 |
| **Daemon management** | launchd (macOS) + systemd (Linux) integration | Architecture doc §7.7 |
| **Dual-DB architecture** | `bridge.db` (core) + `messages.db` (channel I/O) with `bun:sqlite` WAL | Architecture doc §5.1–5.4 |
| **Multi-instance support** | `CLAUDE_BRIDGE_HOME` env var for isolated instances | Architecture doc §7.6 |
| **Cross-compatibility** | Python-created DBs readable by TS and vice versa during coexistence | Architecture doc §9.3 |

#### OUT OF SCOPE

| Item | Reason |
|------|--------|
| Claude Code CLI internals | Treated as opaque binary (`claude` in PATH) — Architecture doc §1.3 |
| Telegram/Discord/Slack API changes | External platform APIs are consumed, not modified |
| Bridge Bot CLAUDE.md prompt rewrite | Stays as-is; only tool references updated post-Wave 7 — Architecture doc §1.7 |
| New features not in Python | No feature additions during migration; strict parity first |
| Windows support | macOS (launchd) + Linux (systemd) only — Architecture doc §7.7 |
| Performance optimization beyond parity | Bun gives startup gains for free; no active perf work unless regression |

#### DEFERRED (Post-Migration)

| Item | Target |
|------|--------|
| Discord adapter implementation | Phase 3 (post-migration) — Architecture doc §6.4 |
| Slack adapter implementation | Phase 6 (post-migration) — Architecture doc §6.5 |
| Team coordination features | Post-migration; Python has DB schema but minimal usage |
| Plugin marketplace submission | After Wave 7 completion + stabilization period |
| Python source archival | After 2-week burn-in with TS-only |

### 1.2 Wave Approach Confirmation

The 7-wave strategy from Architecture doc §9.2 is confirmed with the following rationale:

```
Wave    Layer           Python LOC    TS Target LOC    Rationale for Order
─────   ──────────────  ──────────    ─────────────    ───────────────────────────
  1     Plugin Shell         0           ~200          Enables Day 1 install; zero Python changes
  2     Data Layer       1,430         ~1,170          Foundation — every upper layer depends on it
  3     Execution          803           ~620          Needs Data (Wave 2); enables E2E test path
  4     Orchestration    1,497         ~1,150          Needs Execution (Wave 3) + Data (Wave 2)
  5     CLI & Integration 2,717        ~1,790          Needs all lower layers; replaces user-facing CLI
  6     Infrastructure   1,015           ~820          Daemon/perms; needs CLI (Wave 5)
  7     MCP Consolidation 1,610        ~1,300          Final merge; needs everything; kills Python dep
─────                    ──────        ──────
TOTAL                    9,072         ~7,050
```

**Why bottom-up:** Each wave builds on the previous layer's native TS implementation.
Data (Wave 2) must exist before Execution (Wave 3) can use `bun:sqlite` directly.
Orchestration (Wave 4) depends on both Data and Execution. This prevents circular
fallback dependencies and enables incremental testing at each boundary.

**Why 7 waves, not fewer:** Combining waves would create untestable chunks. The
architecture's 6-layer design maps naturally to 7 waves (Layer 1 types are pre-built;
Wave 1 is the plugin shell; Waves 2-7 map to Layers 2-6 + MCP consolidation).

**Why 7 waves, not more:** Each wave delivers a testable, deployable increment.
Splitting further (e.g., separating `db.ts` from `session.ts`) would add coordination
overhead without reducing risk — they share the same test harness.

### 1.3 Definition of "Done" for Entire Migration

The migration is **complete** when ALL of the following are true:

| # | Criterion | Verification Method |
|---|-----------|-------------------|
| D-1 | All 23+ MCP tools respond identically to Python versions | Automated MCP tool response comparison test |
| D-2 | All 10 CLI commands produce identical output format | CLI output snapshot tests |
| D-3 | `bun run ts-src/src/cli/index.ts` replaces `bridge-cli` (Python) as sole entry point | Remove Python from PATH, verify all ops work |
| D-4 | SQLite DBs created by TS pass `PRAGMA integrity_check` | Automated DB validation |
| D-5 | Python-created DB (v0.5.x) readable by TS without migration | Cross-compat test with production DB snapshot |
| D-6 | Plugin installs via `plugin install claude-bridge` | Manual test on clean machine |
| D-7 | Daemon management works on macOS (launchd) | `bridge-cli daemon install/start/stop/status` |
| D-8 | Stop hook completes in <100ms (p95) | Benchmark 100 invocations |
| D-9 | E2E: Telegram → dispatch → complete → notification in <5s (excluding task runtime) | Timed E2E test |
| D-10 | Zero silent task drops over 24h continuous use | Soak test with synthetic tasks |
| D-11 | Test coverage ≥80% line coverage across all TS modules | `bun test --coverage` |
| D-12 | No Python runtime required to run any Bridge feature | Uninstall Python bridge package, verify |

### 1.4 Assumptions

| # | Assumption | Risk if Wrong | Validated By |
|---|-----------|---------------|-------------|
| A-1 | Bun ≥1.1 is stable for production daemon use | Daemon crashes → fallback to Node shim | Wave 6 soak test |
| A-2 | `bun:sqlite` WAL behavior matches Python `sqlite3` | Data corruption → R-2 mitigation | Wave 2 cross-compat test |
| A-3 | `Bun.spawn({ detached: true })` ≈ Python `start_new_session=True` | Agent killed with Bridge → R-1 mitigation | Wave 3 integration test |
| A-4 | MCP channel API (`experimental`) remains stable through migration | Push messaging breaks → R-3 fallback | Monitor Anthropic changelog |
| A-5 | Claude Code plugin format is stable (`.claude-plugin/plugin.json`) | Plugin shell invalid → delay marketplace submission | Wave 1 install test |
| A-6 | grammy SDK works on Bun without patches | Telegram broken → pin version, test | Wave 1 (existing channel server proves this) |
| A-7 | Solo developer velocity: ~150-200 LOC/day net (TS, tested) | Timeline slips → re-plan at each milestone | Track actuals per wave |
| A-8 | Existing Python test suite can validate TS output (DB, CLI) | No regression baseline → write comparison tests first | Wave 2 setup |

### 1.5 Existing Assets Inventory

| Asset | Status | LOC | Reuse Plan |
|-------|--------|-----|-----------|
| `ts-src/src/types.ts` | Complete | ~150 | Use as-is; expand per wave |
| `ts-src/src/*/interfaces.ts` (4 files) | Scaffold | ~400 | Expand from 62 → ~206 methods |
| `ts-src/src/data/db.ts` | Scaffold | ~80 | Rewrite with full `bun:sqlite` impl |
| `ts-src/src/data/session.ts` | Scaffold | ~60 | Expand to ~120 LOC |
| `ts-src/src/execution/*.ts` (4 files) | Scaffold | ~200 | Rewrite with full impl |
| `ts-src/src/orchestration/*.ts` (3 files) | Scaffold | ~150 | Rewrite with full impl |
| `ts-src/src/mcp/server.ts` + `tools.ts` | Scaffold | ~150 | Expand to 23+ tools |
| `ts-src/src/cli/index.ts` | Scaffold | ~100 | Rewrite with all 10 commands |
| `ts-src/src/config.ts` | Scaffold | ~50 | Expand with env var override |
| `channel/server.ts` + `channel/lib.ts` | **Production** | 1,567 | Absorb into TelegramAdapter (Wave 7) |
| Total scaffold | — | 1,441 | ~20% of target; 80% to write |

---

## 2. Work Breakdown Structure

### 2.1 WBS Overview

Each wave is decomposed into tasks of 1-3 days. Tasks are numbered `W{wave}.{task}`.

```
CLAUDE BRIDGE TS MIGRATION
│
├── W1: Plugin Shell (3 tasks, ~3 days)
├── W2: Data Layer (6 tasks, ~8 days)
├── W3: Execution Layer (5 tasks, ~6 days)
├── W4: Orchestration Layer (4 tasks, ~6 days)
├── W5: CLI & Integration (5 tasks, ~7 days)
├── W6: Infrastructure (4 tasks, ~5 days)
└── W7: MCP Consolidation (4 tasks, ~5 days)
                                    ─────
                              TOTAL: ~40 days
```

### 2.2 Wave 1: Plugin Shell

**Goal:** Plugin installable from Day 1, delegating to Python CLI.
**Python LOC:** 0 (new code only) | **TS Target:** ~200 LOC | **Duration:** ~3 days

| Task | Description | Python Source | TS Target | Key Work | Est. Days |
|------|------------|---------------|-----------|----------|-----------|
| W1.1 | Plugin metadata & structure | — | `.claude-plugin/plugin.json`, `mcp.json` | Create plugin.json, mcp.json, package.json. Verify `plugin install` works | 1 |
| W1.2 | MCP server with Python fallback | `mcp_server.py` (interface only) | `src/mcp/server.ts` | MCP server that shells out to `bridge-cli` (Python) for all 23+ tools. Stdio transport | 1 |
| W1.3 | Skills & smoke test | — | `skills/dispatch.md`, `skills/status.md` | Create slash commands, E2E test: install plugin → invoke tool → Python CLI responds | 1 |

**Dependencies:** None (Wave 1 is standalone)
**Interface changes:** None (uses Python CLI as black box)

### 2.3 Wave 2: Data Layer

**Goal:** Replace Python SQLite/session with native `bun:sqlite`.
**Python LOC:** 1,430 (db.py 977 + message_db.py 263 + session.py 140 + __init__.py 50)
**TS Target:** ~1,170 LOC | **Duration:** ~8 days

| Task | Description | Python Source | TS Target | Key Work | Est. Days |
|------|------------|---------------|-----------|----------|-----------|
| W2.1 | Expand IDatabase interface | `db.py` (63 fns) | `src/data/interfaces.ts` | Expand from 20 → ~55 methods. Add queue, permission, notification, team, cost methods. Type all params/returns | 1 |
| W2.2 | BridgeDatabase core (agents + tasks) | `db.py` agent/task methods (25 fns, ~400 LOC) | `src/data/db.ts` | Schema DDL, WAL setup, CRUD for agents + tasks, atomic dispatch (`BEGIN EXCLUSIVE`), queue ops | 2 |
| W2.3 | BridgeDatabase extended (loops, schedules, permissions, notifications) | `db.py` remaining methods (38 fns, ~577 LOC) | `src/data/db.ts` | Loop CRUD + iterations, schedule CRUD + due query, permission relay, notification queue, cost summary | 2 |
| W2.4 | MessageDatabase | `message_db.py` (24 fns, 263 LOC) | `src/data/message-db.ts` | Separate DB, inbound/outbound message queue, poller state, cleanup. New `IMessageDatabase` interface | 1 |
| W2.5 | SessionManager & ConfigProvider | `session.py` (10 fns, 140 LOC) + `__init__.py` (50 LOC) | `src/data/session.ts`, `src/config.ts` | Expand ISessionManager from 3 → ~8 methods. Session ID derivation, workspace/agent-md paths, validation, instance prefix. Config from JSON + env vars | 1 |
| W2.6 | Cross-compatibility test suite | — | `tests/data/cross-compat.test.ts` | Create DB with Python → read with TS. Create DB with TS → read with Python. Schema checksum comparison. Run Python test suite against TS-created DB | 1 |

**Python → TS mapping detail:**

```
db.py (977 LOC, 63 fns)
├── Schema DDL + connection setup     →  db.ts constructor + initSchema()
├── Agent CRUD (7 fns)                →  db.ts createAgent/get/list/delete/update
├── Task CRUD + atomic dispatch (12 fns) → db.ts createTask/get/update + atomicCheckAndCreate
├── Queue ops (4 fns)                 →  db.ts enqueue/dequeue/getQueued/cancelQueued
├── Loop ops (10 fns)                 →  db.ts createLoop/get/update/iterations
├── Schedule ops (7 fns)              →  db.ts createSchedule/get/update/getDue/delete
├── Permission ops (6 fns)            →  db.ts createPermission/get/update/timeout
├── Notification ops (5 fns)          →  db.ts createNotification/get/markSent/retry
├── Team ops (5 fns)                  →  db.ts createTeam/addMember/getTeam/list
├── Cost/analytics (3 fns)            →  db.ts getCostSummary/getTaskStats
└── Cleanup/maintenance (4 fns)       →  db.ts vacuum/cleanup/migrate

session.py (140 LOC, 10 fns)
├── derive_session_id()               →  session.ts deriveSessionId()
├── get_workspace_dir()               →  session.ts getWorktreePath()
├── get_agent_file_path()             →  session.ts getAgentMdPath()
├── validate_agent_name()             →  session.ts validateAgentName()
���── validate_project_dir()            →  session.ts validateProjectDir()
├── get_tasks_dir()                   ���  session.ts getTasksDir()
├── create_workspace()                →  session.ts createWorkspace()
├── cleanup_workspace()               →  session.ts cleanupWorkspace()
├── derive_agent_file_name()          →  session.ts deriveAgentFileName()
└── get_instance_prefix()             →  session.ts getInstancePrefix()
```

### 2.4 Wave 3: Execution Layer

**Goal:** Replace subprocess spawning with `Bun.spawn()`, stop hook with TS binary.
**Python LOC:** 803 (dispatcher.py 114 + on_complete.py 264 + watcher.py 279 + notify.py 146)
**TS Target:** ~620 LOC | **Duration:** ~6 days

| Task | Description | Python Source | TS Target | Key Work | Est. Days |
|------|------------|---------------|-----------|----------|-----------|
| W3.1 | Expand execution interfaces | All execution modules | `src/execution/interfaces.ts` | Expand IDispatcher (3→5), ICompletionHandler (1→3), INotifier (1→3). Add result file types, graceful kill params | 0.5 |
| W3.2 | Dispatcher | `dispatcher.py` (6 fns, 114 LOC) | `src/execution/dispatcher.ts` | `Bun.spawn({ detached: true })`, PID tracking, result/stderr file paths, session-id-to-uuid, env passthrough. **Critical:** verify process isolation | 2 |
| W3.3 | CompletionHandler (on-complete) | `on_complete.py` (3 fns, 264 LOC) | `src/execution/on-complete.ts` | CLI arg parsing, result JSON parsing, task update, auto-dequeue, notification creation, loop handoff. Must start in <100ms | 1.5 |
| W3.4 | ProcessWatcher | `watcher.py` (4 fns, 279 LOC) | `src/execution/watcher.ts` | PID alive check (`kill -0`), timeout detection (>360min), mark failed, notification. Interval-based polling | 1 |
| W3.5 | Notifier + process isolation E2E test | `notify.py` (6 fns, 146 LOC) | `src/execution/notify.ts` + `tests/execution/e2e.test.ts` | Format completion message, route to channel adapter, retry logic. **E2E test:** spawn → kill Bridge → verify agent PID alive | 1 |

**Python → TS mapping detail:**

```
dispatcher.py (114 LOC, 6 fns)
��── spawn_task()                      →  dispatcher.ts dispatch()
├── pid_alive()                       →  dispatcher.ts isRunning()
├── kill_process()                    →  dispatcher.ts cancel() [SIGTERM→10s→SIGKILL]
├── session_id_to_uuid()              →  dispatcher.ts sessionIdToUuid()
├── get_result_file()                 →  dispatcher.ts getResultFile()
└── get_stderr_file()                 →  dispatcher.ts getStderrFile()

on_complete.py (264 LOC, 3 fns)
├─�� parse_result_file()               →  on-complete.ts parseResultFile()
├── main()                            →  on-complete.ts handleCompletion() + CLI entry
└── (dequeue + notify logic)          →  on-complete.ts (embedded in handleCompletion)

watcher.py (279 LOC, 4 fns)
├── watch()                           →  watcher.ts start()
├── check_pid()                       →  watcher.ts checkPid()
├── handle_dead_task()                →  watcher.ts handleDeadTask()
└── main()                            →  watcher.ts (CLI entry, not needed as method)

notify.py (146 LOC, 6 fns)
├── format_completion_message()       →  notify.ts formatMessage()
├── send_telegram()                   →  notify.ts (via IChannelAdapter.sendMessage)
├── deliver_notification()            →  notify.ts notify()
├── retry_failed()                    →  notify.ts retryFailed()
├── get_bot_token()                   →  config.ts (moved to ConfigProvider)
└── get_default_channel()             →  config.ts (moved to ConfigProvider)
```

### 2.5 Wave 4: Orchestration Layer

**Goal:** Port loop state machine, evaluator, and scheduler.
**Python LOC:** 1,497 (loop_orchestrator.py 1,059 + loop_evaluator.py 313 + scheduler.py 125)
**TS Target:** ~1,150 LOC | **Duration:** ~6 days

| Task | Description | Python Source | TS Target | Key Work | Est. Days |
|------|------------|---------------|-----------|----------|-----------|
| W4.1 | Expand orchestration interfaces | All orchestration modules | `src/orchestration/interfaces.ts` | Expand ILoopOrchestrator (5���9), ILoopEvaluator (1→3), IScheduler (3→4). Add approve/reject/on_task_complete, parse/validate condition, dispatch_for_schedule | 0.5 |
| W4.2 | LoopOrchestrator | `loop_orchestrator.py` (21 fns, 1,059 LOC) | `src/orchestration/loop.ts` | State machine (running→done/failed/exceeded/cancelled), iteration tracking, cost ceiling, approval workflow, on_task_complete callback, formatting | 2.5 |
| W4.3 | LoopEvaluator | `loop_evaluator.py` (8 fns, 313 LOC) | `src/orchestration/evaluator.ts` | Parse done conditions (command:, file_exists:, file_contains:, llm_judge:, manual:), evaluate against task result, subprocess spawn for llm_judge | 1.5 |
| W4.4 | Scheduler | `scheduler.py` (3 fns, 125 LOC) | `src/orchestration/scheduler.ts` | Poll due schedules (60s interval), anchor-based next_run computation, error backoff (interval * 2^errors, cap 8x), dispatch_for_schedule | 1.5 |

**Python → TS mapping detail:**

```
loop_orchestrator.py (1,059 LOC, 21 fns)
├── start_loop()                      →  loop.ts startLoop()
├── on_task_complete()                →  loop.ts onTaskComplete()  [CRITICAL]
├── cancel_loop()                     →  loop.ts cancelLoop()
├── approve_loop()                    →  loop.ts approveLoop()
├── reject_loop()                     →  loop.ts rejectLoop()
├─��� get_loop_status()                 →  loop.ts getLoopStatus()
├── decide_loop_type()                →  loop.ts decideLoopType()
├── dispatch_next_iteration()         →  loop.ts (private)
├── check_limits()                    →  loop.ts (private)
├── format_loop_list()                →  loop.ts formatLoopList()
├── format_loop_history()             →  loop.ts formatLoopHistory()
└── (10 helper fns)                   →  loop.ts (private helpers)

loop_evaluator.py (313 LOC, 8 fns)
├── evaluate_done_condition()         ��  evaluator.ts evaluate()
├── parse_done_condition()            →  evaluator.ts parseDoneCondition()
├── validate_done_condition()         →  evaluator.ts validateDoneCondition()
├── eval_command()                    →  evaluator.ts (private)
├── eval_file_exists()                →  evaluator.ts (private)
├── eval_file_contains()              ��  evaluator.ts (private)
├── eval_llm_judge()                  →  evaluator.ts (private, spawns claude -p)
└── eval_manual()                     →  evaluator.ts (private)

scheduler.py (125 LOC, 3 fns)
├── run_scheduler()                   →  scheduler.ts start()
├── compute_next_run()                →  scheduler.ts computeNextRun()
└── dispatch_for_schedule()           →  scheduler.ts dispatchForSchedule()
```

### 2.6 Wave 5: CLI & Integration

**Goal:** Replace `bridge-cli` (Python) with TS CLI. Port agent .md generation.
**Python LOC:** 2,717 (cli.py 2,361 + agent_md.py 160 + claude_md_init.py 101 + memory.py 95)
**TS Target:** ~1,790 LOC | **Duration:** ~7 days

| Task | Description | Python Source | TS Target | Key Work | Est. Days |
|------|------------|---------------|-----------|----------|-----------|
| W5.1 | CLI framework + core commands | `cli.py` core (create-agent, delete-agent, list-agents, status, dispatch — ~800 LOC) | `src/cli/index.ts` | Arg parsing (Bun built-in or yargs), command routing, output formatting. 5 core commands | 2 |
| W5.2 | CLI extended commands | `cli.py` extended (kill, history, memory, loop, schedule, daemon — ~1,561 LOC) | `src/cli/index.ts` | 5 remaining commands. Loop/schedule subcommands, daemon subcommands, memory reader | 2 |
| W5.3 | AgentMdGenerator | `agent_md.py` (4 fns, 160 LOC) | `src/cli/agent-md.ts` | YAML frontmatter generation (tools, isolation, memory, hooks), Markdown body, stop hook injection. New `IAgentMdGenerator` interface | 1 |
| W5.4 | ClaudeMdInit + Memory reader | `claude_md_init.py` (1 fn, 101 LOC) + `memory.py` (3 fns, 95 LOC) | `src/cli/claude-md.ts`, `src/cli/memory.ts` | Auto-init CLAUDE.md for new projects. Read Auto Memory via `claude /memory` subprocess | 1 |
| W5.5 | CLI snapshot tests | — | `tests/cli/snapshot.test.ts` | Output snapshot tests for all 10 commands. Verify format parity with Python CLI | 1 |

### 2.7 Wave 6: Infrastructure

**Goal:** Port daemon management, tmux sessions, permission relay. Remove Python dependency.
**Python LOC:** 1,015 (daemon.py 500 + bridge_cmd.py 426 + permission_relay.py 89)
**TS Target:** ~820 LOC | **Duration:** ~5 days

| Task | Description | Python Source | TS Target | Key Work | Est. Days |
|------|------------|---------------|-----------|----------|-----------|
| W6.1 | DaemonManager | `daemon.py` (24 fns, 500 LOC) | `src/infra/daemon.ts` | launchd plist generation (macOS), systemd unit generation (Linux), install/uninstall/start/stop/status/logs. Platform detection | 2 |
| W6.2 | BridgeCmd (session management) | `bridge_cmd.py` (17 fns, 426 LOC) | `src/infra/bridge-cmd.ts` | tmux/foreground session management, setup-bot workflow, start/stop Bridge process, health check | 1.5 |
| W6.3 | PermissionRelay | `permission_relay.py` (1 fn, 89 LOC) | `src/infra/permissions.ts` | PreToolUse hook handler for dangerous command approval. Check DB for pending permission, wait for Telegram response | 1 |
| W6.4 | Python removal verification | — | `tests/infra/no-python.test.ts` | Test all Bridge operations with Python uninstalled. Verify zero Python subprocess calls remain | 0.5 |

### 2.8 Wave 7: MCP Consolidation

**Goal:** Merge Python MCP + channel server into unified TS MCP server. Kill Python dependency.
**Python LOC:** 1,610 (mcp_server.py 348 + mcp_tools.py 741 + bridge_bot_claude_md.py 521)
**TS Target:** ~1,300 LOC | **Duration:** ~5 days

| Task | Description | Python Source | TS Target | Key Work | Est. Days |
|------|------------|---------------|-----------|----------|-----------|
| W7.1 | MCP tool registry (23+ tools) | `mcp_tools.py` (26 fns, 741 LOC) | `src/mcp/tools.ts` | Implement all 23+ tools: agent CRUD (2), task dispatch (4), messaging (4), loop mgmt (8), schedules (5), files (1). Each tool delegates to appropriate layer | 2 |
| W7.2 | MCP server with channel capability | `mcp_server.py` (28 fns, 348 LOC) | `src/mcp/server.ts` | Stdio transport, tool registration, channel push notifications, instructions embedding. Absorb channel/server.ts MCP logic | 1 |
| W7.3 | BridgeBotMdGenerator | `bridge_bot_claude_md.py` (3 fns, 521 LOC) | `src/mcp/bridge-md.ts` | Generate Bridge Bot CLAUDE.md with tool documentation, behavior rules, channel instructions | 1 |
| W7.4 | Full E2E integration test | — | `tests/e2e/full-pipeline.test.ts` | Telegram → Bridge Bot → MCP tool → dispatch → complete → notification. All TS, no Python. 24h soak test plan | 1 |

### 2.9 WBS Summary Table

```
┌────────┬───────────────────────┬───────────┬───────────┬────────┬──────────┐
│ Wave   │ Layer                 │ Py LOC    │ TS Target │ Tasks  │ Est Days │
├────────┼───────────────────────┼─────���─────┼───────────┼────────���──────────┤
│ W1     │ Plugin Shell          │      0    │     ~200  │   3    │    3     │
│ W2     │ Data Layer            │  1,430    │   ~1,170  ���   6    │    8     │
│ W3     │ Execution Layer       │    803    │     ~620  │   5    │    6     │
│ W4     │ Orchestration Layer   │  1,497    │   ~1,150  │   4    │    6     │
│ W5     �� CLI & Integration     │  2,717    │   ~1,790  │   5    │    7     │
│ W6     │ Infrastructure        │  1,015    │     ~820  │   4    │    5     ��
│ W7     │ MCP Consolidation     │  1,610    │   ~1,300  ��   4    │    5     │
��────────┼─────────────────────��─┼───────────┼───────────┼────────┼──────────┤
│ TOTAL  │                       │  9,072    │   ~7,050  │  31    │   40     │
└────────┴───────────────────────┴─���─────────┴────���──────┴────────┴──────���───┘
```

**LOC reduction rationale:** TS is ~22% fewer LOC than Python due to:
- TypeScript's more concise syntax (arrow functions, optional chaining, template literals)
- Type system eliminates runtime type checking boilerplate
- `bun:sqlite` API is more concise than Python `sqlite3`
- Channel server already exists in TS (1,567 LOC absorbed, not rewritten)

---

## 3. Dependency Mapping & Critical Path

### 3.1 Inter-Wave Dependencies

```
W1 ─────────────────────────────────────────────────────────────────→ (standalone)
     │
     └──→ W2 ──→ W3 ──→ W4 ──→ W5 ──→ W6 ──→ W7
          │       │       │       │              │
          │       │       │       └──────────────┤
          │       │       └──────────────────────┤
          │       └──────────────────────────────┤
          └──────────────────────────────────────┘
                                                 │
                                          W7 needs ALL
```

**Formal dependency chain:**

| Task | Depends On | Reason |
|------|-----------|--------|
| W1.* | — | Standalone; uses Python CLI as black box |
| W2.1 | W1.3 (soft) | Interface expansion benefits from seeing MCP tool signatures |
| W2.2 | W2.1 | BridgeDatabase implements expanded IDatabase |
| W2.3 | W2.2 | Extended DB methods share connection/schema from core |
| W2.4 | W2.1 | MessageDatabase implements new IMessageDatabase interface |
| W2.5 | W2.1 | SessionManager implements expanded ISessionManager |
| W2.6 | W2.2, W2.4, W2.5 | Cross-compat tests need all data components |
| W3.1 | W2.1 | Execution interfaces reference data types |
| W3.2 | W3.1, W2.2, W2.5 | Dispatcher uses BridgeDatabase + SessionManager |
| W3.3 | W3.2, W2.2 | CompletionHandler needs Dispatcher (result files) + DB |
| W3.4 | W2.2 | Watcher reads running tasks from DB |
| W3.5 | W3.3, W3.4 | Notifier integrates with CompletionHandler flow |
| W4.1 | W3.1 | Orchestration interfaces reference execution types |
| W4.2 | W4.1, W3.2, W2.2 | LoopOrchestrator uses Dispatcher + DB |
| W4.3 | W4.1 | Evaluator is pure logic + subprocess (no DB dep) |
| W4.4 | W4.1, W3.2, W2.2 | Scheduler uses Dispatcher + DB |
| W5.1 | W2.*, W3.* | CLI core commands use Data + Execution layers |
| W5.2 | W4.* | Extended CLI uses Orchestration layer |
| W5.3 | W2.5 | AgentMdGenerator needs SessionManager for paths |
| W5.4 | — (standalone) | ClaudeMdInit/Memory are subprocess-based |
| W5.5 | W5.1, W5.2 | Snapshot tests need all commands |
| W6.1 | W5.1 | DaemonManager references CLI entry point |
| W6.2 | W5.1, W2.5 | BridgeCmd uses CLI + SessionManager |
| W6.3 | W2.2 | PermissionRelay needs DB for permission records |
| W6.4 | W6.1, W6.2, W6.3 | Verification needs all infra components |
| W7.1 | W2.*, W3.*, W4.* | MCP tools delegate to all layers |
| W7.2 | W7.1 | MCP server registers tools |
| W7.3 | W5.3 | BridgeBotMdGen references AgentMdGenerator patterns |
| W7.4 | W7.1, W7.2, W7.3 | E2E test needs everything |

### 3.2 Intra-Wave Task Dependencies

```
Wave 2:  W2.1 ──→ W2.2 ──→ W2.3
              ├──→ W2.4
              └──→ W2.5
         W2.2 + W2.4 + W2.5 ──→ W2.6

Wave 3:  W3.1 ──→ W3.2 ──→ W3.3 ──→ W3.5
              ├──→ W3.4 ──────────→ W3.5

Wave 4:  W4.1 ──→ W4.2
              ├──→ W4.3  (parallel with W4.2)
              └──→ W4.4  (parallel with W4.2)

Wave 5:  W5.1 ──→ W5.2 ──→ W5.5
         W5.3  (parallel with W5.1)
         W5.4  (parallel with W5.1)

Wave 6:  W6.1  ──→ W6.4
         W6.2  ──→ W6.4
         W6.3  ──→ W6.4

Wave 7:  W7.1 ──→ W7.2 ──→ W7.4
         W7.3 ────────────→ W7.4
```

### 3.3 Parallel Opportunities

| Parallel Set | Tasks | Condition | Saves |
|-------------|-------|-----------|-------|
| **P1** | W2.4 ∥ W2.5 | Both depend only on W2.1 | ~1 day |
| **P2** | W3.4 ∥ W3.2-W3.3 | Watcher only needs DB, not Dispatcher | ~1 day |
| **P3** | W4.3 ∥ W4.4 ∥ W4.2 | Evaluator and Scheduler are independent of each other | ~1.5 days |
| **P4** | W5.3 ∥ W5.4 ∥ W5.1 | AgentMd and ClaudeMd are independent of CLI framework | ~1 day |
| **P5** | W6.1 ∥ W6.2 ∥ W6.3 | All three infra modules are independent | ~2 days |
| **P6** | W7.3 ∥ W7.1-W7.2 | BridgeBotMdGen is independent of MCP server | ~0.5 day |

**Note:** Parallel opportunities are relevant for multi-dev scenarios or for interleaving
work (start W4.3 when blocked on W4.2 review). For a solo dev, the primary benefit is
flexibility — work on the unblocked task when stuck.

### 3.4 Critical Path

The critical path is the longest chain of dependent tasks that determines the minimum
project duration. All slack is measured against this path.

```
CRITICAL PATH (31.5 days of sequential work):

W1.1 → W1.2 → W1.3 → W2.1 → W2.2 → W2.3 → W2.6 → W3.1 → W3.2 → W3.3 → W3.5
  1d     1d     1d     1d     2d     2d     1d    0.5d    2d    1.5d    1d
                                                                          │
→ W4.1 → W4.2 → W5.1 → W5.2 → W5.5 → W6.1 → W6.4 → W7.1 → W7.2 → W7.4
  0.5d   2.5d    2d     2d     1d     2d    0.5d    2d     1d     1d

Total critical path: 3 + 7 + 5 + 3 + 5 + 2.5 + 3 + 4 = 33 days
```

**Simplified critical path by wave:**

```
          W1        W2        W3       W4      W5       W6      W7
         3 days → 7 days → 5 days → 3 days → 5 days → 2.5d → 4 days
         ──────────────────────────────────────────────────────────────
                                                          Total: ~30 days*
```

*With parallel opportunities exploited (P1-P6), the effective timeline compresses
from 40 sequential days to ~30 critical-path days.

### 3.5 Blocking Dependencies (High Risk)

These dependencies are on the critical path AND involve high-risk work:

| Blocker | Blocked By | Risk | Impact if Delayed |
|---------|-----------|------|-------------------|
| W2.2 (BridgeDatabase core) | Schema parity with Python | R-2, R-6 | Blocks ALL subsequent waves |
| W3.2 (Dispatcher) | `Bun.spawn detached` behavior | R-1 | Blocks Execution, Orchestration, CLI |
| W3.3 (CompletionHandler) | Stop hook <100ms requirement | R-7 | Blocks loop integration |
| W7.2 (MCP server) | Channel API stability | R-3, R-9 | Blocks final integration |

### 3.6 Dependency Diagram (Full)

```
                    W1.1 ──→ W1.2 ──→ W1.3
                                         │ (soft)
                                         ▼
                    ┌───────────────── W2.1 ─────────────────┐
                    │                    │                     │
                    ▼                    ▼                     ▼
                  W2.4                 W2.2                  W2.5
                    │                    │                     │
                    │                    ▼                     │
                    │                  W2.3                    │
                    │                    │                     │
                    └────────────────────┼─────────────────────┘
                                         │
                                         ▼
                                       W2.6
                                         │
                    ┌────────────────────┤
                    │                    │
                    ▼                    ▼
                  W3.4                 W3.1
                    │                    │
                    │           ┌────────┤
                    │           ▼        ▼
                    │         W3.2     (W3.4)
                    │           │
                    │           ▼
                    │         W3.3
                    │           │
                    └─────────→ ▼
                              W3.5
                                │
                    ┌───────────┤
                    │           │
                    ▼           ▼
                  W4.1 ──→ ┌─ W4.2
                    │      ├─ W4.3  (parallel)
                    └────→ └─ W4.4  (parallel)
                                │
                    ┌───────────┤
                    │           │
                    ▼           ▼
            W5.3, W5.4      W5.1 ──→ W5.2 ──→ W5.5
                                                  │
                    ┌─────────────────────────────┤
                    │           │                  │
                    ▼           ▼                  ▼
                  W6.1       W6.2               W6.3
                    │           │                  │
                    └───────────┼──────────────────┘
                                ▼
                              W6.4
                                │
                    ┌───────────┤
                    │           │
                    ▼           ▼
                  W7.1       W7.3
                    │           │
                    ▼           │
                  W7.2          │
                    │           │
                    └─────→ W7.4
```

---

## 4. Timeline & Milestones

### 4.1 Timeline Assumptions

- **Work mode:** Solo developer, part-time (~4h/day effective coding)
- **Effective days/week:** 5 (Mon-Fri)
- **Net velocity:** ~100-120 LOC/day (tested TS, including test code)
- **Buffer:** 20% added per wave for unknowns, debugging, and review
- **Start date:** Relative (Day 1 = project kickoff)

### 4.2 Wave Timeline (Gantt-style)

```
Day   1    5   10   15   20   25   30   35   40   45   50
      │    │    │    │    │    │    │    │    │    │    │
W1    ████                                              Plugin Shell
      │3d+1d buffer│
W2         ██████████                                   Data Layer
           │8d+2d buf│
W3                    ████████                          Execution
                      │6d+1d│
W4                           ███████                    Orchestration
                             │6d+1d│
W5                                  █████████           CLI & Integration
                                    │7d+1d│
W6                                          ██████      Infrastructure
                                            │5d+1d│
W7                                               █████ MCP Consolidation
                                                 │5d+1d│
      │    │    │    │    │    │    │    │    │    │    │
      M0   M1        M2        M3        M4   M5  M6  M7
```

### 4.3 Milestone Schedule

| Milestone | Day | Wave | Deliverable | Gate |
|-----------|-----|------|-------------|------|
| **M0** | 1 | — | Project kickoff, dev env setup | Bun installed, `bun test` runs, repo structure verified |
| **M1** | 4 | W1 | Plugin installable | `plugin install claude-bridge` works, MCP tools respond via Python fallback |
| **M2** | 14 | W2 | Native data layer | All IDatabase tests pass, cross-compat with Python DB verified |
| **M3** | 22 | W3 | E2E task lifecycle | Dispatch → complete → notify works entirely in TS. Process isolation verified |
| **M4** | 30 | W4 | Loop & schedule | Loop: start → iterate → evaluate → complete. Schedule: create → fire → complete |
| **M5** | 38 | W5 | CLI replacement | `bun run cli.ts` replaces `bridge-cli` for all 10 commands |
| **M6** | 44 | W6 | Python-free | Daemon works, permissions work, zero Python subprocess calls |
| **M7** | 50 | W7 | Migration complete | All 23+ MCP tools native TS. E2E passes. Ready for plugin submission |

### 4.4 Key Checkpoints (Within Waves)

| Checkpoint | Day | Description | Go/No-Go Decision |
|-----------|-----|-------------|-------------------|
| CP-1 | 2 | W1.2 MCP fallback working | If Python CLI not callable from Bun → investigate PATH/env issues before proceeding |
| CP-2 | 8 | W2.2 Core DB passes unit tests | If schema parity fails → stop, debug with `PRAGMA table_info`, compare column-by-column |
| CP-3 | 12 | W2.6 Cross-compat suite green | If Python can't read TS DB → schema divergence; must fix before W3 |
| CP-4 | 17 | W3.2 Process isolation verified | If `detached` doesn't isolate → switch to `setsid` wrapper; blocks all subsequent work |
| CP-5 | 19 | W3.3 Stop hook <100ms | If >100ms → profile, lazy-load imports, consider compiled entry point |
| CP-6 | 26 | W4.2 Loop state machine complete | If state transitions incorrect → regression against Python loop test cases |
| CP-7 | 34 | W5.1 Core CLI commands pass snapshots | If output format differs → align with Python; blocks user-facing cutover |
| CP-8 | 42 | W6.4 Zero Python calls verified | If Python still called → grep for `bridge-cli` / `python` in TS source; fix before W7 |
| CP-9 | 48 | W7.4 Full E2E passes | If E2E fails → identify broken link in chain; fix before declaring migration complete |

### 4.5 Buffer Strategy

| Wave | Base Days | Buffer (20%) | Total Days | Buffer Use |
|------|-----------|-------------|------------|-----------|
| W1 | 3 | 1 | 4 | Plugin install debugging, MCP transport issues |
| W2 | 8 | 2 | 10 | Schema parity debugging, bun:sqlite quirks |
| W3 | 6 | 1 | 7 | Process isolation investigation, stop hook perf |
| W4 | 6 | 1 | 7 | Loop state machine edge cases |
| W5 | 7 | 1 | 8 | CLI output format alignment, arg parsing edge cases |
| W6 | 5 | 1 | 6 | Platform-specific daemon issues (launchd vs systemd) |
| W7 | 5 | 1 | 6 | MCP tool parity, channel server absorption |
| **Total** | **40** | **8** | **48** | |

**Unused buffer policy:** If a wave finishes early, buffer days roll forward to
the next wave. They do NOT compress the timeline (use for thorough testing instead).

### 4.6 Calendar Mapping (Part-Time Example)

For a part-time schedule (~4h/day, 5 days/week):

| Week | Days | Wave(s) | Key Deliverable |
|------|------|---------|----------------|
| Week 1 | 1-5 | W1 + W2 start | M1: Plugin installable |
| Week 2 | 6-10 | W2 | Data layer core |
| Week 3 | 11-15 | W2 finish + W3 start | M2: Native data layer |
| Week 4 | 16-20 | W3 | M3: E2E task lifecycle |
| Week 5 | 21-25 | W3 finish + W4 | Orchestration start |
| Week 6 | 26-30 | W4 finish | M4: Loop & schedule |
| Week 7 | 31-35 | W5 | CLI core commands |
| Week 8 | 36-40 | W5 finish + W6 start | M5: CLI replacement |
| Week 9 | 41-45 | W6 finish | M6: Python-free |
| Week 10 | 46-50 | W7 | M7: Migration complete |

**Total: ~10 weeks (part-time) or ~7 weeks (full-time at ~6h/day)**

---

## 5. Resource Allocation

### 5.1 Solo Developer Capacity

| Resource | Details |
|----------|---------|
| **Developer** | 1 (solo) |
| **Available hours** | ~4h/day effective coding (part-time), 5 days/week |
| **Net output** | ~100-120 LOC/day (tested TS), ~500-600 LOC/week |
| **Total LOC target** | ~7,050 LOC (production) + ~3,000 LOC (tests) ≈ 10,000 LOC |
| **Estimated duration** | ~50 working days (10 weeks part-time) with 20% buffer |

### 5.2 Tools & Infrastructure Required

| Tool | Purpose | When Needed | Setup Effort |
|------|---------|-------------|-------------|
| **Bun ≥1.1** | Runtime, test runner, package manager | Day 1 | `curl -fsSL https://bun.sh/install \| bash` — already installed |
| **bun:sqlite** | Native SQLite driver | Wave 2 | Built into Bun — zero setup |
| **@modelcontextprotocol/sdk** | MCP server implementation | Wave 1 | `bun add @modelcontextprotocol/sdk` — already in package.json |
| **grammy** | Telegram Bot API SDK | Wave 7 (absorption) | Already used in channel/server.ts |
| **Python 3.11+** | Cross-compat testing, fallback | Waves 1-6 | Already installed |
| **pytest** | Run Python tests against TS-created DBs | Wave 2 | Already configured |
| **SQLite CLI** | Schema inspection, debugging | Wave 2 | `brew install sqlite3` — likely already available |
| **Claude Code CLI** | Integration testing (mocked in unit tests) | Wave 3+ | Already installed |
| **tmux** | Session management testing | Wave 6 | Already installed |
| **git** | Version control, worktree testing | All waves | Already configured |

### 5.3 Dev Environment Setup (Day 0)

```bash
# Verify prerequisites
bun --version          # ≥1.1
python3 --version      # ≥3.11
claude --version       # Claude Code CLI
sqlite3 --version      # SQLite CLI

# Install TS dependencies
cd ts-src && bun install

# Verify test runner
bun test               # Should run existing scaffold tests

# Verify Python tests still pass
cd .. && pytest tests/ --ignore=tests/test_telegram_poller.py
```

### 5.4 Effort Distribution by Activity

| Activity | % of Time | Hours/Wave (avg) | Notes |
|----------|-----------|-------------------|-------|
| **Implementation** | 45% | ~10h | Writing production TS code |
| **Testing** | 30% | ~7h | Unit, integration, cross-compat, E2E |
| **Debugging & Investigation** | 15% | ~3.5h | Bun quirks, schema issues, process isolation |
| **Review & Documentation** | 10% | ~2.5h | Code review checklist, wave reports |

### 5.5 Bottleneck Analysis

| Bottleneck | Wave | Impact | Mitigation |
|-----------|------|--------|-----------|
| **Schema parity debugging** | W2 | Could consume entire buffer if bun:sqlite behaves differently | Write cross-compat tests FIRST (W2.6 moved earlier as TDD); fail fast |
| **Process isolation verification** | W3 | Manual testing required (spawn, kill, verify) — slow feedback loop | Create automated integration test; run on both macOS and Linux |
| **CLI output alignment** | W5 | 60 Python CLI fns → output format must match exactly | Generate Python CLI output snapshots first; use as golden files |
| **MCP tool count** | W7 | 23+ tools is mechanical but time-consuming | Template-based generation; most tools are thin wrappers over layer calls |
| **Single-threaded development** | All | No parallel dev capacity; blocked tasks block everything | Exploit intra-wave parallelism (§3.3); switch to unblocked task when stuck |

### 5.6 AI-Assisted Development Strategy

Claude Code itself accelerates the migration:

| Activity | AI Leverage | Expected Speedup |
|----------|------------|------------------|
| Python → TS translation | Feed Python fn + interface → generate TS impl | 2-3x for mechanical translation |
| Test generation | Generate test cases from Python test suite | 2x for unit test boilerplate |
| MCP tool stubs | 23 tools follow same pattern → batch generate | 3-4x for W7.1 |
| CLI arg parsing | Translate argparse → Bun/yargs patterns | 2x for W5.1 |
| Schema DDL | Direct copy from Python + syntax adjustment | Trivial (copy-paste) |
| Code review | Automated review per `.claude/rules/code-review.md` | Consistent quality |

**Realistic velocity with AI:** 150-200 LOC/day (vs 100-120 manual), potentially
compressing timeline to ~35-40 days effective.

---

## 6. Acceptance Criteria

### 6.1 Wave 1: Plugin Shell — "Plugin installs and tools respond"

| # | Criterion | Test Method | Pass Condition |
|---|-----------|-------------|---------------|
| AC-1.1 | Plugin metadata valid | `cat .claude-plugin/plugin.json \| jq .` | Valid JSON with name, version, description |
| AC-1.2 | MCP server starts | `bun run src/mcp/server.ts` (stdio) | Responds to `initialize` JSON-RPC |
| AC-1.3 | MCP tools listed | `tools/list` JSON-RPC call | Returns 23+ tool definitions with correct schemas |
| AC-1.4 | Python fallback works | Call `bridge_dispatch` tool | Shells out to `bridge-cli dispatch`, returns result |
| AC-1.5 | Skills files exist | `ls skills/` | `dispatch.md`, `status.md` present |
| AC-1.6 | Plugin install works | `plugin install` from local path | Plugin appears in installed list, MCP server registered |

### 6.2 Wave 2: Data Layer — "Native DB with Python compatibility"

| # | Criterion | Test Method | Pass Condition |
|---|-----------|-------------|---------------|
| AC-2.1 | Schema matches Python | `PRAGMA table_info(agents)` on both DBs | Identical columns, types, defaults |
| AC-2.2 | WAL mode enabled | `PRAGMA journal_mode` | Returns `wal` |
| AC-2.3 | Foreign keys ON | `PRAGMA foreign_keys` | Returns `1` |
| AC-2.4 | Agent CRUD | Unit tests: create, get, list, delete, update | All 7 agent methods pass |
| AC-2.5 | Atomic task dispatch | Concurrent dispatch test | Only one task created; second returns `busy: true` |
| AC-2.6 | Queue operations | Unit tests: enqueue, dequeue, cancel | FIFO order preserved, dequeue atomic |
| AC-2.7 | Loop CRUD | Unit tests: create, get, update, iterations | 10 loop methods pass |
| AC-2.8 | Schedule CRUD | Unit tests: create, get, getDue, update, delete | 7 schedule methods pass |
| AC-2.9 | Permission CRUD | Unit tests: create, get, update, timeout | 6 permission methods pass |
| AC-2.10 | Notification queue | Unit tests: create, get, markSent, retry | 5 notification methods pass |
| AC-2.11 | MessageDatabase | Unit tests: inbound/outbound CRUD, poller state | 24 methods pass |
| AC-2.12 | SessionManager | Unit tests: deriveSessionId, paths, validation | 8 methods pass |
| AC-2.13 | ConfigProvider | Unit tests: JSON + env var override | Config loaded correctly |
| AC-2.14 | Cross-compat (TS→Py) | Create DB with TS → run Python tests | All Python DB tests pass |
| AC-2.15 | Cross-compat (Py→TS) | Create DB with Python → read with TS | All TS DB tests pass |
| AC-2.16 | Test coverage | `bun test --coverage` | ≥85% line coverage for data layer |

**Performance targets:**
- DB open + schema init: <50ms
- Agent CRUD operation: <5ms
- Atomic task dispatch: <10ms
- Query (list agents, running tasks): <5ms

### 6.3 Wave 3: Execution Layer — "Tasks dispatch and complete end-to-end"

| # | Criterion | Test Method | Pass Condition |
|---|-----------|-------------|---------------|
| AC-3.1 | Dispatch spawns process | Mock `claude` binary, dispatch task | Process spawned with correct args, PID in DB |
| AC-3.2 | Process isolation | Spawn agent → kill Bridge process → check PID | Agent process survives Bridge death |
| AC-3.3 | Graceful kill | Dispatch → cancel | SIGTERM sent, 10s wait, SIGKILL if needed |
| AC-3.4 | Result file written | Dispatch with mock claude → check file | `task-{id}-result.json` exists with valid JSON |
| AC-3.5 | on-complete parses result | Feed result JSON to CompletionHandler | Task status=done, cost/duration/summary extracted |
| AC-3.6 | on-complete dequeues | Complete task with queued task waiting | Next task auto-dispatched |
| AC-3.7 | on-complete notifies | Complete task with channel | Notification created in DB |
| AC-3.8 | on-complete start time | Time 100 invocations | p95 < 100ms |
| AC-3.9 | Watcher detects dead PID | Set task PID to non-existent PID, run watcher | Task marked failed, notification created |
| AC-3.10 | Watcher timeout | Task running > 360min (mocked time) | Task force-killed, marked timeout |
| AC-3.11 | Notifier formats message | Format completion notification | Contains cost, duration, summary, agent name |
| AC-3.12 | Notifier retry | Simulate send failure, retry | Retries with exponential backoff, max 3 |
| AC-3.13 | Test coverage | `bun test --coverage` | ≥80% line coverage for execution layer |

### 6.4 Wave 4: Orchestration — "Loops iterate and schedules fire"

| # | Criterion | Test Method | Pass Condition |
|---|-----------|-------------|---------------|
| AC-4.1 | Loop start | Start loop with goal + condition | Loop created in DB, first task dispatched |
| AC-4.2 | Loop iterate | Complete task → on_task_complete | Next iteration dispatched, iteration recorded |
| AC-4.3 | Loop done | Done condition met | Loop status=done, finish_reason set |
| AC-4.4 | Loop max iterations | Exceed max_iterations | Loop status=exceeded |
| AC-4.5 | Loop max failures | 3 consecutive failures | Loop status=failed |
| AC-4.6 | Loop cost ceiling | Exceed max_cost_usd | Loop status=exceeded |
| AC-4.7 | Loop approve/reject | Pending approval → approve/reject | State transitions correctly |
| AC-4.8 | Loop cancel | Cancel running loop | Loop status=cancelled, current task killed |
| AC-4.9 | Evaluator: command | `command:exit 0` condition | Returns done=true |
| AC-4.10 | Evaluator: file_exists | `file_exists:path` condition | Returns done=true when file exists |
| AC-4.11 | Evaluator: file_contains | `file_contains:path:pattern` | Returns done=true when pattern found |
| AC-4.12 | Evaluator: manual | `manual:` condition | Returns done=false (always, until manual approval) |
| AC-4.13 | Schedule create + fire | Create schedule, advance time past next_run | Task dispatched for schedule |
| AC-4.14 | Schedule next_run | Anchor-based computation | No drift over 100 iterations |
| AC-4.15 | Schedule error backoff | Consecutive errors | next_run interval doubles, caps at 8x |
| AC-4.16 | Test coverage | `bun test --coverage` | ≥80% line coverage for orchestration layer |

### 6.5 Wave 5: CLI & Integration — "CLI replaces Python bridge-cli"

| # | Criterion | Test Method | Pass Condition |
|---|-----------|-------------|---------------|
| AC-5.1 | create-agent | `bun cli.ts create-agent backend /path --purpose "dev"` | Agent created in DB, agent .md file generated |
| AC-5.2 | delete-agent | `bun cli.ts delete-agent backend` | Agent removed from DB, tasks cascaded |
| AC-5.3 | list-agents | `bun cli.ts list-agents` | Table format output matching Python |
| AC-5.4 | status | `bun cli.ts status` | Shows running agents, active tasks, daemon state |
| AC-5.5 | dispatch | `bun cli.ts dispatch backend "task"` | Task dispatched, PID shown |
| AC-5.6 | kill | `bun cli.ts kill backend` | Running task killed gracefully |
| AC-5.7 | history | `bun cli.ts history backend` | Last N tasks shown with status, cost, duration |
| AC-5.8 | memory | `bun cli.ts memory backend` | Auto Memory contents displayed |
| AC-5.9 | loop | `bun cli.ts loop backend --goal "..." --done-when "..."` | Loop started |
| AC-5.10 | schedule | `bun cli.ts schedule add ...` | Schedule created |
| AC-5.11 | Agent .md generation | Create agent → inspect .md file | YAML frontmatter with tools, isolation, hooks. Stop hook points to TS binary |
| AC-5.12 | CLAUDE.md init | Create agent for new project | CLAUDE.md created with project-specific content |
| AC-5.13 | Output format parity | Snapshot tests vs Python CLI output | All 10 commands produce compatible output |
| AC-5.14 | Test coverage | `bun test --coverage` | ≥80% line coverage for CLI layer |

### 6.6 Wave 6: Infrastructure — "Daemon runs, Python removed"

| # | Criterion | Test Method | Pass Condition |
|---|-----------|-------------|---------------|
| AC-6.1 | launchd install (macOS) | `bun cli.ts daemon install` | Plist created in ~/Library/LaunchAgents/ |
| AC-6.2 | launchd start/stop | `bun cli.ts daemon start/stop` | Service starts/stops via launchctl |
| AC-6.3 | systemd install (Linux) | `bun cli.ts daemon install` on Linux | Unit file created in ~/.config/systemd/user/ |
| AC-6.4 | Daemon keepalive | Kill Bridge process | Daemon restarts automatically |
| AC-6.5 | setup-bot workflow | `bun cli.ts setup-bot /path` | Config created, agent .md files generated, MCP registered |
| AC-6.6 | Permission relay | Trigger dangerous command in agent | Permission request created, Telegram notification sent, approval workflow works |
| AC-6.7 | Zero Python calls | `grep -r "bridge-cli\|python" ts-src/src/` | No Python subprocess calls in production code |
| AC-6.8 | Python uninstall test | `pip uninstall claude-agent-bridge` → run all Bridge ops | Everything works without Python |

### 6.7 Wave 7: MCP Consolidation — "Full TS, plugin-ready"

| # | Criterion | Test Method | Pass Condition |
|---|-----------|-------------|---------------|
| AC-7.1 | All 23+ MCP tools | Call each tool via JSON-RPC | All return correct results |
| AC-7.2 | Tool response parity | Compare TS tool output vs Python tool output | Identical format for all tools |
| AC-7.3 | Channel push notifications | Send Telegram message → check MCP notification | Bridge Bot receives `<channel>` tag |
| AC-7.4 | Channel server absorbed | No separate `channel/server.ts` process needed | Single MCP server handles everything |
| AC-7.5 | Bridge Bot CLAUDE.md | Generate and inspect | Contains all 23+ tool docs, behavior rules |
| AC-7.6 | E2E: dispatch cycle | Telegram → dispatch → complete → notification | Full cycle works in <5s (excluding task runtime) |
| AC-7.7 | E2E: loop cycle | Telegram → start loop → 3 iterations → done | Loop completes with correct iteration count |
| AC-7.8 | E2E: schedule cycle | Create schedule → advance time → fires | Schedule dispatches on time |
| AC-7.9 | Soak test | Run 24h with synthetic tasks | Zero silent drops, zero crashes |
| AC-7.10 | Plugin submission ready | Verify plugin.json, mcp.json, skills/ | All files valid, passes linting |
| AC-7.11 | Overall test coverage | `bun test --coverage` | ≥80% line coverage across all modules |
