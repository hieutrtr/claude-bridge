# Phase 1: MVP Core Dispatch

**Goal:** Individual developer can create agents, dispatch tasks from Telegram, and receive results. Full lifecycle working end-to-end: create agent → dispatch → task runs → completion detected → result delivered.

**Status:** [ ] Not started

**Estimated effort:** ~43 hours (10 working days)

**Dependencies:** Claude Code CLI installed and authenticated, Python 3.11+, Git, Telegram account + BotFather token

---

## Demo Scenario

After this phase, the following works end-to-end:

```
[Telegram] → "ask backend to add pagination to the /users endpoint"
          ↓
Bridge Bot routes → bridge-cli dispatch backend "add pagination..."
          ↓
Claude Code agent runs in isolated worktree
          ↓
Stop hook fires → on_complete.py updates SQLite
          ↓
[Telegram] ← "✓ Task #7 done (backend) · 2m 14s · $0.04
              Added cursor-based pagination to GET /users..."
```

You can also: list agents, check status, kill a running task, view history, read agent memory — all from Telegram.

---

## Milestones & Tasks

### Milestone 1: Foundation (Day 1–2) — ~8.5 hours

#### Task 1.1: Set Up Project Structure
- **Effort:** 1 hour
- **Dependencies:** None
- **Acceptance Criteria:**
  - [ ] `~/.claude-bridge/` exists with correct permissions (700)
  - [ ] `~/.claude-bridge/workspaces/` directory exists
  - [ ] Running `python3 -m claude_bridge.cli --help` prints usage
  - [ ] No external pip dependencies required
- **Files:**
  - `src/claude_bridge/cli.py` (argparse scaffold)
  - `src/claude_bridge/on_complete.py` (empty scaffold)
  - `src/claude_bridge/watcher.py` (empty scaffold)

#### Task 1.2: Create SQLite Schema
- **Effort:** 1.5 hours
- **Dependencies:** Task 1.1
- **Acceptance Criteria:**
  - [ ] `bridge.db` created automatically on first run
  - [ ] `agents` table: `name TEXT PRIMARY KEY, project_dir TEXT, session_id TEXT UNIQUE, purpose TEXT, state TEXT DEFAULT 'idle', agent_file TEXT, created_at TEXT`
  - [ ] `tasks` table: `id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, prompt TEXT, status TEXT DEFAULT 'pending', pid INTEGER, result_file TEXT, cost REAL, duration REAL, created_at TEXT, started_at TEXT, completed_at TEXT, reported INTEGER DEFAULT 0`
  - [ ] `init_db()` is idempotent — safe to call multiple times
- **Files:**
  - `src/claude_bridge/db.py` (schema + CRUD)

#### Task 1.3: Implement `create-agent` Command
- **Effort:** 3 hours
- **Dependencies:** Task 1.2
- **Acceptance Criteria:**
  - [ ] `claude-bridge create-agent backend /projects/my-api "API development"` succeeds
  - [ ] Validates project_dir exists; errors if not
  - [ ] Validates agent name is alphanumeric + hyphens only
  - [ ] Errors if agent with same name already exists
  - [ ] Session ID derived correctly: `backend--my-api`
  - [ ] Agent `.md` file generated at `~/.claude/agents/bridge--backend--my-api.md`
  - [ ] Agent `.md` contains YAML frontmatter: name, description, tools, model, isolation, memory, hooks
  - [ ] Agent `.md` contains markdown body: agent name, project path, purpose, working style
  - [ ] Workspace created at `~/.claude-bridge/workspaces/backend--my-api/tasks/`
  - [ ] Agent row inserted with `state='idle'`
  - [ ] Prints: `Agent 'backend' created for /projects/my-api`
- **Files:**
  - `src/claude_bridge/agent_md.py` (agent .md generator)
  - `src/claude_bridge/session.py` (session_id derivation)
  - `src/claude_bridge/cli.py` (create-agent subcommand)
  - `~/.claude/agents/bridge--<session_id>.md` (generated)

#### Task 1.4: Implement `delete-agent` Command
- **Effort:** 1.5 hours
- **Dependencies:** Task 1.3
- **Acceptance Criteria:**
  - [ ] Errors if agent doesn't exist
  - [ ] Errors if agent has a running task (must kill first)
  - [ ] Removes `~/.claude/agents/bridge--<session_id>.md`
  - [ ] Removes `~/.claude-bridge/workspaces/<session_id>/` recursively
  - [ ] Deletes agent row from SQLite (task history preserved)
- **Files:** `src/claude_bridge/cli.py`

#### Task 1.5: Implement `list-agents` Command
- **Effort:** 0.5 hours
- **Dependencies:** Task 1.3
- **Acceptance Criteria:**
  - [ ] Prints table: name, project, state (idle/busy), session_id
  - [ ] Shows "No agents registered" if empty
  - [ ] Output is parseable by Bridge Bot (clean text)
- **Files:** `src/claude_bridge/cli.py`

#### Task 1.6: Test Foundation
- **Effort:** 1 hour
- **Dependencies:** Tasks 1.3–1.5
- **Acceptance Criteria:**
  - [ ] Create 2 agents, list shows both
  - [ ] Delete 1 agent, list shows 1
  - [ ] Re-create deleted agent succeeds
  - [ ] Error cases tested: duplicate name, missing path, invalid name

---

### Milestone 2: CLAUDE.md Init (Day 3) — ~5.5 hours

#### Task 2.1: Purpose-Driven CLAUDE.md Init
- **Effort:** 3 hours
- **Dependencies:** Task 1.3
- **Acceptance Criteria:**
  - [ ] `create-agent` runs a one-shot Claude scan in the project directory
  - [ ] Generated CLAUDE.md contains: project overview, build/test commands, coding conventions, agent purpose section
  - [ ] CLAUDE.md written to `<project_dir>/CLAUDE.md`
  - [ ] Completes within 60s (timeout protection)
  - [ ] If Claude scan fails: agent still created with minimal CLAUDE.md template
- **Files:** `src/claude_bridge/claude_md_init.py`, called from cli.py

#### Task 2.2: Handle Existing CLAUDE.md
- **Effort:** 1.5 hours
- **Dependencies:** Task 2.1
- **Acceptance Criteria:**
  - [ ] No CLAUDE.md exists → full generation
  - [ ] CLAUDE.md exists without Bridge section → append agent section at end
  - [ ] CLAUDE.md exists with Bridge section for this agent → skip (no duplicate)
  - [ ] Bridge section delimited by `<!-- claude-bridge:agent:<name> -->` markers
  - [ ] Original content never modified

#### Task 2.3: Test CLAUDE.md Init
- **Effort:** 1 hour
- **Acceptance Criteria:**
  - [ ] Test with Node.js project: CLAUDE.md mentions npm commands
  - [ ] Test with Python project: CLAUDE.md mentions pytest
  - [ ] Test with empty project: minimal CLAUDE.md generated
  - [ ] Test append mode: existing content preserved, agent section added

---

### Milestone 3: Task Dispatch (Day 4–5) — ~7.5 hours

#### Task 3.1: Implement `dispatch` Command
- **Effort:** 3 hours
- **Dependencies:** Milestone 1
- **Acceptance Criteria:**
  - [ ] `claude-bridge dispatch backend "add pagination to /users endpoint"` succeeds
  - [ ] Errors if agent doesn't exist or is busy
  - [ ] Claude Code spawned: `claude --agent bridge--<id> --session-id <uuid> --output-format json --dangerously-skip-permissions -p "<prompt>"`
  - [ ] Working directory = agent's project_dir
  - [ ] stdout → `task-<id>-result.json`, stderr → `task-<id>-stderr.log`
  - [ ] PID stored in task row immediately after Popen
  - [ ] Task status = `running`, agent state = `busy`
  - [ ] `start_new_session=True` (survives bridge-cli exit)
  - [ ] Prints: `Task #<id> dispatched to agent 'backend' (PID: <pid>)`
- **Files:** `src/claude_bridge/dispatcher.py`, `src/claude_bridge/cli.py`

#### Task 3.2: Implement `status` Command
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.1
- **Acceptance Criteria:**
  - [ ] `status` shows all agents; `status backend` shows single agent detail
  - [ ] If busy: shows task ID, prompt (truncated), PID, elapsed time
  - [ ] Verifies PID is still alive; updates if process died without hook
- **Files:** `src/claude_bridge/cli.py`

#### Task 3.3: Implement `kill` Command
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.1
- **Acceptance Criteria:**
  - [ ] Sends SIGTERM; waits 5s; sends SIGKILL if still alive
  - [ ] Task status → `killed`, agent state → `idle`
- **Files:** `src/claude_bridge/cli.py`

#### Task 3.4: Test Task Dispatch
- **Effort:** 1.5 hours
- **Acceptance Criteria:**
  - [ ] Dispatch a simple task, verify Claude Code process spawned
  - [ ] Status shows running task with correct PID
  - [ ] Kill terminates the task; dispatch again succeeds
  - [ ] Error: dispatch to busy agent shows clear message

---

### Milestone 4: Completion System (Day 6–7) — ~7.5 hours

#### Task 4.1: Implement `on_complete.py` (Stop Hook Handler)
- **Effort:** 3 hours
- **Dependencies:** Task 3.1
- **Acceptance Criteria:**
  - [ ] Called by Claude Code Stop hook: `python3 -m claude_bridge.on_complete --session-id <id>`
  - [ ] Finds running task for session_id in SQLite
  - [ ] Reads `task-<id>-result.json` (JSON from `--output-format json`)
  - [ ] Extracts: summary, is_error, cost_usd, duration_ms
  - [ ] Updates task: status=`done`/`failed`, cost, duration, completed_at
  - [ ] Updates agent: state=`idle`
  - [ ] Handles missing/malformed result file gracefully
- **Files:** `src/claude_bridge/on_complete.py`

#### Task 4.2: Implement `watcher.py` (Fallback PID Checker)
- **Effort:** 2 hours
- **Dependencies:** Task 4.1
- **Acceptance Criteria:**
  - [ ] Queries SQLite for all `status='running'` tasks
  - [ ] PID dead + hook not fired → marks `failed`
  - [ ] PID alive + running >30 min → SIGTERM, marks `timeout`
  - [ ] Updates agent state to `idle` for resolved tasks
  - [ ] Logs actions to `~/.claude-bridge/watcher.log`
  - [ ] SQLite transactions (safe to run concurrently)
- **Files:** `src/claude_bridge/watcher.py`

#### Task 4.3: Set Up Cron for Watcher
- **Effort:** 0.5 hours
- **Acceptance Criteria:**
  - [ ] `setup-cron` adds cron entry: `*/5 * * * * python3 -m claude_bridge.watcher`
  - [ ] Does not duplicate if already installed
  - [ ] `uninstall-cron` removes the entry
- **Files:** `src/claude_bridge/cli.py`

#### Task 4.4: Test Completion System
- **Effort:** 2 hours
- **Acceptance Criteria:**
  - [ ] Dispatch quick task; let it complete; verify Stop hook fired; task=`done` in SQLite
  - [ ] Cost and duration recorded; agent back to `idle`
  - [ ] Kill task with SIGKILL; verify watcher catches it within 5 min
  - [ ] Timeout detection works

---

### Milestone 5: Bridge Bot Integration (Day 8–9) — ~6.5 hours

#### Task 5.1: Write Bridge Bot CLAUDE.md
- **Effort:** 2 hours
- **Dependencies:** Milestones 1–4
- **Acceptance Criteria:**
  - [ ] Defines command routing for all bridge-cli commands
  - [ ] Natural language fallback: "ask backend to add pagination" → dispatch
  - [ ] Output formatting rules: concise for mobile
  - [ ] Error handling: relay bridge-cli stderr to user
- **Files:** `src/claude_bridge/bridge_bot_claude_md.py`, generated `bridge-bot/CLAUDE.md`

#### Task 5.2–5.3: Set Up Telegram Bot + MCP Channel
- **Effort:** 2.5 hours
- **Acceptance Criteria:**
  - [ ] Bot created via @BotFather; token saved securely
  - [ ] Channel server running: `claude --dangerously-load-development-channels server:bridge`
  - [ ] Bridge Bot can receive and send Telegram messages

#### Task 5.4: Test Bridge Bot End-to-End
- **Effort:** 2 hours
- **Acceptance Criteria:**
  - [ ] `/agents` from Telegram → list of agents
  - [ ] Dispatch task from Telegram → confirmation → wait → result in Telegram
  - [ ] Status, kill, history all work from Telegram
  - [ ] Natural language dispatch works

---

### Milestone 6: Polish (Day 10) — ~7.5 hours

#### Task 6.1: `history` Command
- **Acceptance Criteria:**
  - [ ] Shows task ID, agent, status, duration, cost, prompt (truncated 80 chars)
  - [ ] Filterable by agent name and `--limit N`

#### Task 6.2: `memory` Command
- **Acceptance Criteria:**
  - [ ] Reads `~/.claude/projects/<encoded-path>/memory/MEMORY.md`
  - [ ] Handles Claude Code's path encoding scheme
- **Files:** `src/claude_bridge/memory.py`

#### Task 6.3: Natural Language Parsing in Bridge Bot
- **Acceptance Criteria:**
  - [ ] "ask backend to add pagination" → dispatch
  - [ ] "what's backend doing?" → status
  - [ ] "stop backend" → kill
  - [ ] "what has backend done today?" → history

#### Task 6.4: Error Handling & Edge Cases
- **Acceptance Criteria:**
  - [ ] All errors are human-readable (no Python tracebacks to user)
  - [ ] Claude Code not found → helpful install message
  - [ ] Auth expired → detected and reported

#### Task 6.5: End-to-End Test with Real Project
- **Acceptance Criteria:**
  - [ ] Create agent for a real project from Telegram
  - [ ] Dispatch meaningful task; result appears in Telegram
  - [ ] Cost tracking shows reasonable amounts
  - [ ] Agent memory updated after task; visible from Telegram
  - [ ] Total time from install to first result < 10 minutes

---

## Summary

| Milestone | Days | Effort |
|-----------|------|--------|
| 1. Foundation | Day 1–2 | ~8.5 h |
| 2. CLAUDE.md Init | Day 3 | ~5.5 h |
| 3. Task Dispatch | Day 4–5 | ~7.5 h |
| 4. Completion System | Day 6–7 | ~7.5 h |
| 5. Bridge Bot Integration | Day 8–9 | ~6.5 h |
| 6. Polish | Day 10 | ~7.5 h |
| **Total** | **10 days** | **~43 h** |
