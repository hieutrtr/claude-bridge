# Phase 1: MVP Core Dispatch -- Detailed Tasks

> Week 1-2 | 10 working days | ~425 lines of Python total
> Goal: Create agent -> dispatch task -> completion detected -> result delivered via Telegram

---

## Milestone 1: Foundation (Day 1-2)

### Task 1.1: Set Up Project Structure

- **Description:** Create the `~/.claude-bridge/` directory structure with all subdirectories. Set up Python project with no external dependencies (stdlib only for MVP).
- **Effort:** 1 hour
- **Dependencies:** None
- **Acceptance Criteria:**
  - [ ] `~/.claude-bridge/` exists with correct permissions (700)
  - [ ] `~/.claude-bridge/workspaces/` directory exists
  - [ ] Running `python3 ~/.claude-bridge/bridge-cli.py --help` prints usage
  - [ ] No external pip dependencies required
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (scaffold with argparse)
  - `~/.claude-bridge/on-complete.py` (empty scaffold)
  - `~/.claude-bridge/watcher.py` (empty scaffold)

### Task 1.2: Create SQLite Schema

- **Description:** Design and create the SQLite schema with two tables: `agents` and `tasks`. Include an `init_db()` function that creates tables if they don't exist (idempotent). Store database at `~/.claude-bridge/bridge.db`.
- **Effort:** 1.5 hours
- **Dependencies:** Task 1.1
- **Acceptance Criteria:**
  - [ ] `bridge.db` created automatically on first run
  - [ ] `agents` table has columns: `name TEXT PRIMARY KEY, project_dir TEXT, session_id TEXT UNIQUE, purpose TEXT, state TEXT DEFAULT 'idle', agent_file TEXT, created_at TEXT`
  - [ ] `tasks` table has columns: `id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, prompt TEXT, status TEXT DEFAULT 'pending', pid INTEGER, result_file TEXT, cost REAL, duration REAL, created_at TEXT, started_at TEXT, completed_at TEXT, reported INTEGER DEFAULT 0`
  - [ ] `init_db()` is idempotent -- safe to call multiple times
  - [ ] Foreign key on `tasks.session_id` references agent
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `init_db()` function and schema)

### Task 1.3: Implement create-agent Command

- **Description:** Implement `bridge-cli.py create-agent <name> <project_dir> "<purpose>"`. Validates project_dir exists, derives session_id as `<name>--<project_basename>`, generates agent `.md` file at `~/.claude/agents/bridge--<session_id>.md`, creates workspace directory, inserts agent row into SQLite.
- **Effort:** 3 hours
- **Dependencies:** Task 1.2
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py create-agent backend /projects/my-api "API development"` succeeds
  - [ ] Validates project_dir exists, errors if not
  - [ ] Validates agent name is alphanumeric + hyphens only
  - [ ] Errors if agent with same name already exists
  - [ ] Session ID derived correctly: `backend--my-api`
  - [ ] Agent `.md` file generated at `~/.claude/agents/bridge--backend--my-api.md`
  - [ ] Agent `.md` contains YAML frontmatter: name, description, tools, model, isolation, memory, hooks (Stop hook pointing to on-complete.py)
  - [ ] Agent `.md` contains markdown body: agent name, project path, purpose, working style
  - [ ] Workspace created at `~/.claude-bridge/workspaces/backend--my-api/`
  - [ ] Workspace contains `tasks/` subdirectory
  - [ ] Agent row inserted into SQLite with state='idle'
  - [ ] Prints confirmation: "Agent 'backend' created for /projects/my-api"
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `create_agent()` function)
  - `~/.claude/agents/bridge--<session_id>.md` (generated)
  - `~/.claude-bridge/workspaces/<session_id>/` (created)

### Task 1.4: Implement delete-agent Command

- **Description:** Implement `bridge-cli.py delete-agent <name>`. Validates agent exists, checks no running tasks, removes agent `.md` file, removes workspace directory, deletes agent row from SQLite.
- **Effort:** 1.5 hours
- **Dependencies:** Task 1.3
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py delete-agent backend` succeeds
  - [ ] Errors if agent doesn't exist
  - [ ] Errors if agent has a running task (must kill first)
  - [ ] Removes `~/.claude/agents/bridge--<session_id>.md`
  - [ ] Removes `~/.claude-bridge/workspaces/<session_id>/` recursively
  - [ ] Deletes agent row from SQLite (tasks history preserved with orphan session_id)
  - [ ] Prints confirmation: "Agent 'backend' deleted"
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `delete_agent()` function)

### Task 1.5: Implement list-agents Command

- **Description:** Implement `bridge-cli.py list-agents`. Lists all registered agents with their state, project directory, and session ID.
- **Effort:** 0.5 hours
- **Dependencies:** Task 1.3
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py list-agents` prints table of agents
  - [ ] Shows columns: name, project, state (idle/busy), session_id
  - [ ] Shows "No agents registered" if empty
  - [ ] Output is parseable by Bridge Bot (clean text, no fancy formatting)
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `list_agents()` function)

### Task 1.6: Test Foundation

- **Description:** Manual testing of all foundation commands from terminal. Verify SQLite state is correct after each operation.
- **Effort:** 1 hour
- **Dependencies:** Tasks 1.3, 1.4, 1.5
- **Acceptance Criteria:**
  - [ ] Create 2 agents, list shows both
  - [ ] Delete 1 agent, list shows 1
  - [ ] Re-create deleted agent succeeds
  - [ ] Error cases tested: duplicate name, missing path, invalid name
  - [ ] SQLite state verified with `sqlite3 ~/.claude-bridge/bridge.db "SELECT * FROM agents;"`

---

## Milestone 2: CLAUDE.md Init (Day 3)

### Task 2.1: Implement Purpose-Driven CLAUDE.md Init

- **Description:** During `create-agent`, run a one-shot Claude Code task to scan the project and generate/update `CLAUDE.md`. The prompt instructs Claude to read project files (package.json, Dockerfile, README, directory structure) and produce a CLAUDE.md with project context + agent-specific purpose section.
- **Effort:** 3 hours
- **Dependencies:** Task 1.3
- **Acceptance Criteria:**
  - [ ] `create-agent` runs `claude -p "<scan prompt>" --no-input` in the project directory
  - [ ] Scan prompt instructs Claude to: read key files, summarize build/test/lint commands, note conventions, add agent purpose section
  - [ ] Generated CLAUDE.md contains: project overview, build commands, test commands, lint commands, directory structure summary, coding conventions, agent purpose section
  - [ ] CLAUDE.md is written to `<project_dir>/CLAUDE.md`
  - [ ] Process completes within 60 seconds (timeout protection)
  - [ ] If Claude Code scan fails, agent is still created with a minimal CLAUDE.md template
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `init_claude_md()` function called from `create_agent()`)
  - `<project_dir>/CLAUDE.md` (generated)

### Task 2.2: Handle Existing CLAUDE.md

- **Description:** If the project already has a CLAUDE.md, append the agent context section rather than overwriting. Detect existing content and only add the Bridge-specific section.
- **Effort:** 1.5 hours
- **Dependencies:** Task 2.1
- **Acceptance Criteria:**
  - [ ] If no CLAUDE.md exists: full generation (project scan + agent section)
  - [ ] If CLAUDE.md exists without Bridge section: append agent section at the end
  - [ ] If CLAUDE.md exists with Bridge section for this agent: skip (no duplicate)
  - [ ] Bridge section is clearly marked with `<!-- claude-bridge:agent:<name> -->` comment delimiters
  - [ ] Original CLAUDE.md content is never modified or deleted
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (update `init_claude_md()`)

### Task 2.3: Test CLAUDE.md Init

- **Description:** Test CLAUDE.md generation with real projects. Verify quality of generated content.
- **Effort:** 1 hour
- **Dependencies:** Tasks 2.1, 2.2
- **Acceptance Criteria:**
  - [ ] Test with a Node.js project: CLAUDE.md mentions npm commands, test framework
  - [ ] Test with a Python project: CLAUDE.md mentions pip/poetry, pytest
  - [ ] Test with empty project: CLAUDE.md still generates with minimal content
  - [ ] Test append mode: existing CLAUDE.md preserved, agent section added
  - [ ] Test duplicate prevention: running create-agent twice doesn't duplicate section

---

## Milestone 3: Task Dispatch (Day 4-5)

### Task 3.1: Implement dispatch Command

- **Description:** Implement `bridge-cli.py dispatch <agent_name> "<prompt>"`. Looks up agent in SQLite, verifies agent is idle, inserts task row, spawns Claude Code via `subprocess.Popen` with correct flags (`--agent`, `--session-id`, `--worktree`, `-p`), stores PID, updates agent state to busy.
- **Effort:** 3 hours
- **Dependencies:** Milestone 1 complete
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py dispatch backend "add pagination to /users endpoint"` succeeds
  - [ ] Errors if agent doesn't exist
  - [ ] Errors if agent is busy (state != idle)
  - [ ] Task row inserted with status='pending' before spawn
  - [ ] Claude Code spawned with: `claude --agent ~/.claude/agents/bridge--<session_id>.md --session-id <session_id> --worktree -p "<prompt>" --output-format json --max-turns 50`
  - [ ] Working directory set to agent's project_dir
  - [ ] stdout redirected to `~/.claude-bridge/workspaces/<session_id>/tasks/task-<id>-result.json`
  - [ ] stderr redirected to `~/.claude-bridge/workspaces/<session_id>/tasks/task-<id>-stderr.log`
  - [ ] PID stored in task row immediately after Popen
  - [ ] Task status updated to 'running', started_at set
  - [ ] Agent state updated to 'busy'
  - [ ] Prints: "Task #<id> dispatched to agent 'backend' (PID: <pid>)"
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `dispatch()` function)

### Task 3.2: Implement status Command

- **Description:** Implement `bridge-cli.py status [agent_name]`. Shows current state of one or all agents, including running task details if busy.
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.1
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py status` shows all agents with state
  - [ ] `python3 bridge-cli.py status backend` shows single agent detail
  - [ ] If agent is busy: shows task ID, prompt (truncated), PID, elapsed time
  - [ ] If agent is idle: shows last completed task summary
  - [ ] Verifies PID is still alive (os.kill(pid, 0)) and updates if process died without hook
  - [ ] Output is clean text suitable for Telegram relay
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `status()` function)

### Task 3.3: Implement kill Command

- **Description:** Implement `bridge-cli.py kill <agent_name>`. Terminates the running task for the specified agent. Sends SIGTERM, waits briefly, then SIGKILL if needed.
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.1
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py kill backend` terminates running task
  - [ ] Errors if agent doesn't exist
  - [ ] Errors if agent is not busy (no task to kill)
  - [ ] Sends SIGTERM first, waits 5 seconds
  - [ ] If still alive after 5 seconds, sends SIGKILL
  - [ ] Task status updated to 'killed', completed_at set
  - [ ] Agent state updated to 'idle'
  - [ ] Prints: "Task #<id> killed for agent 'backend'"
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `kill_task()` function)

### Task 3.4: Test Task Dispatch

- **Description:** End-to-end test of dispatch, status, and kill commands with real Claude Code.
- **Effort:** 1.5 hours
- **Dependencies:** Tasks 3.1, 3.2, 3.3
- **Acceptance Criteria:**
  - [ ] Dispatch a simple task ("list all files in src/"), verify Claude Code process spawned
  - [ ] Status shows running task with correct PID
  - [ ] Kill terminates the task, status shows idle
  - [ ] Dispatch again after kill succeeds (agent back to idle)
  - [ ] Result JSON file created in workspace tasks directory
  - [ ] Error: dispatch to busy agent shows clear message
  - [ ] Error: kill idle agent shows clear message

---

## Milestone 4: Completion System (Day 6-7)

### Task 4.1: Implement on-complete.py (Stop Hook Handler)

- **Description:** Implement the Stop hook handler that fires when Claude Code finishes a task. Parses the result JSON, updates SQLite (task status, cost, duration), updates agent state to idle, and prints a completion report to stdout (which Bridge Bot reads).
- **Effort:** 3 hours
- **Dependencies:** Task 3.1 (dispatch must write result files)
- **Acceptance Criteria:**
  - [ ] Called by Claude Code Stop hook: `python3 on-complete.py --session-id <session_id>`
  - [ ] Finds the most recent 'running' task for the session_id in SQLite
  - [ ] Reads result JSON from workspace tasks directory
  - [ ] Extracts: summary text, is_error flag, cost_usd, duration_ms from Claude output
  - [ ] Updates task row: status='done' or status='failed' (based on is_error), cost, duration, completed_at
  - [ ] Updates agent row: state='idle'
  - [ ] Prints formatted report to stdout: task ID, agent name, status, duration, cost, summary
  - [ ] Handles missing result file gracefully (marks task as 'failed' with note)
  - [ ] Handles malformed JSON gracefully (marks task as 'failed', logs raw content)
- **Files Touched:**
  - `~/.claude-bridge/on-complete.py` (full implementation)

### Task 4.2: Implement watcher.py (Fallback PID Checker)

- **Description:** Implement the fallback watcher that runs via cron every 5 minutes. Checks all tasks with status='running', verifies their PIDs are still alive, and handles dead processes and timeouts.
- **Effort:** 2 hours
- **Dependencies:** Task 4.1
- **Acceptance Criteria:**
  - [ ] Queries SQLite for all tasks with status='running'
  - [ ] For each: checks if PID is alive via `os.kill(pid, 0)`
  - [ ] If PID is dead and task not updated by hook: marks task as 'failed' with note "Process died unexpectedly"
  - [ ] If PID is alive and running > 30 minutes: sends SIGTERM, marks as 'timeout'
  - [ ] Updates agent state to 'idle' for any resolved tasks
  - [ ] Logs actions to `~/.claude-bridge/watcher.log`
  - [ ] Safe to run concurrently (SQLite transactions)
  - [ ] No-op if no running tasks (exits silently)
- **Files Touched:**
  - `~/.claude-bridge/watcher.py` (full implementation)

### Task 4.3: Set Up Cron for Watcher

- **Description:** Configure a cron job to run watcher.py every 5 minutes. Provide instructions for manual setup and a helper command.
- **Effort:** 0.5 hours
- **Dependencies:** Task 4.2
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py install-cron` adds cron entry: `*/5 * * * * /usr/bin/python3 ~/.claude-bridge/watcher.py`
  - [ ] Cron entry uses full paths (no PATH dependency)
  - [ ] Does not duplicate if already installed
  - [ ] `bridge-cli.py uninstall-cron` removes the entry
  - [ ] Cron output redirected to watcher.log
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `install_cron()` and `uninstall_cron()`)

### Task 4.4: Test Completion System

- **Description:** End-to-end test of the completion pipeline. Dispatch a real task, let it complete, verify hook fires and SQLite is updated.
- **Effort:** 2 hours
- **Dependencies:** Tasks 4.1, 4.2, 4.3
- **Acceptance Criteria:**
  - [ ] Dispatch a quick task ("echo hello"), let it complete naturally
  - [ ] Verify Stop hook fired: task status='done' in SQLite
  - [ ] Verify cost and duration recorded
  - [ ] Verify agent state back to 'idle'
  - [ ] Kill a task with SIGKILL (bypassing hook), verify watcher catches it within 5 min
  - [ ] Test timeout: dispatch long task, set watcher timeout to 1 min, verify timeout detection
  - [ ] Verify report output is clean and informative

---

## Milestone 5: Bridge Bot Integration (Day 8-9)

### Task 5.1: Write Bridge Bot CLAUDE.md

- **Description:** Write the CLAUDE.md file that defines the Bridge Bot's command routing behavior. This is the "brain" of the Bridge Bot -- Claude Code reads these instructions and routes Telegram messages to bridge-cli.py commands.
- **Effort:** 2 hours
- **Dependencies:** Milestones 1-4 complete
- **Acceptance Criteria:**
  - [ ] CLAUDE.md placed at `~/.claude-bridge/CLAUDE.md`
  - [ ] Defines command routing: `/create-agent` -> `bridge-cli.py create-agent`, `/task` -> `bridge-cli.py dispatch`, `/status` -> `bridge-cli.py status`, `/kill` -> `bridge-cli.py kill`, `/agents` -> `bridge-cli.py list-agents`, `/history` -> `bridge-cli.py history`, `/memory` -> `bridge-cli.py memory`
  - [ ] Includes natural language fallback: "ask backend to add pagination" -> dispatch
  - [ ] Specifies output formatting rules: keep responses concise for mobile
  - [ ] Includes error handling guidance: if command fails, relay error message
  - [ ] Specifies that Bridge Bot should relay all bridge-cli.py stdout to the user
- **Files Touched:**
  - `~/.claude-bridge/CLAUDE.md` (full implementation)

### Task 5.2: Set Up Telegram Bot

- **Description:** Create a Telegram bot via BotFather, configure the official Telegram MCP plugin, and test basic message send/receive.
- **Effort:** 1.5 hours
- **Dependencies:** Telegram account, BotFather access
- **Acceptance Criteria:**
  - [ ] Bot created via @BotFather with name "Claude Bridge" (or similar)
  - [ ] Bot token saved securely (not in git)
  - [ ] Telegram MCP plugin installed in Claude Code
  - [ ] Plugin configured with bot token and allowed_users (your Telegram user ID)
  - [ ] Test: send message to bot, Claude Code Bridge Bot receives it
  - [ ] Test: Bridge Bot sends response back to Telegram
- **Files Touched:**
  - Claude Code MCP plugin configuration (per Claude Code docs)
  - `~/.claude-bridge/config.yaml` (store bot config reference)

### Task 5.3: Install and Configure Telegram MCP Plugin

- **Description:** Install the official Anthropic Telegram MCP plugin for Claude Code. Configure it for the Bridge Bot session.
- **Effort:** 1 hour
- **Dependencies:** Task 5.2
- **Acceptance Criteria:**
  - [ ] MCP plugin installed via Claude Code plugin system
  - [ ] Plugin configured with bot token
  - [ ] Plugin configured with allowed Telegram user IDs
  - [ ] Bridge Bot session can read incoming messages
  - [ ] Bridge Bot session can send outgoing messages
  - [ ] Bridge Bot session can send inline keyboard buttons (for future permission relay)
- **Files Touched:**
  - MCP plugin configuration files

### Task 5.4: Test Bridge Bot End-to-End

- **Description:** Full end-to-end test: send commands from Telegram, verify Bridge Bot routes them correctly, results returned to Telegram.
- **Effort:** 2 hours
- **Dependencies:** Tasks 5.1, 5.2, 5.3
- **Acceptance Criteria:**
  - [ ] Start Bridge Bot: `claude --agent bridge-bot --session-id bridge-bot` (or similar)
  - [ ] Send `/agents` from Telegram -> receive list of agents
  - [ ] Send `/create-agent test /tmp/test-project "testing"` -> agent created, confirmation received
  - [ ] Send `/task test "list files in current directory"` -> task dispatched, confirmation received
  - [ ] Wait for task completion -> receive result report in Telegram
  - [ ] Send `/status test` -> shows idle (after completion)
  - [ ] Send `/kill test` while task is running -> task killed, confirmation received
  - [ ] Send `/delete-agent test` -> agent deleted, confirmation received
  - [ ] Natural language: "ask test to list files" -> correctly parsed and dispatched

---

## Milestone 6: Polish (Day 10)

### Task 6.1: Implement history Command

- **Description:** Implement `bridge-cli.py history [agent_name] [--limit N]`. Shows completed task history with status, duration, cost, and prompt summary.
- **Effort:** 1 hour
- **Dependencies:** Milestone 4 complete
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py history` shows all tasks, most recent first
  - [ ] `python3 bridge-cli.py history backend` shows tasks for specific agent
  - [ ] `python3 bridge-cli.py history --limit 5` limits output
  - [ ] Shows: task ID, agent, status (done/failed/killed/timeout), duration, cost, prompt (truncated to 80 chars)
  - [ ] Output suitable for Telegram relay
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `history()` function)

### Task 6.2: Implement memory Command

- **Description:** Implement `bridge-cli.py memory <agent_name>`. Reads the agent's Auto Memory files from Claude Code's native storage and prints them.
- **Effort:** 1.5 hours
- **Dependencies:** Milestone 1 complete
- **Acceptance Criteria:**
  - [ ] `python3 bridge-cli.py memory backend` reads Auto Memory
  - [ ] Locates memory at `~/.claude/projects/<encoded-path>/memory/MEMORY.md`
  - [ ] Handles encoded project path (Claude Code's path encoding scheme)
  - [ ] Prints memory content to stdout
  - [ ] If no memory exists yet: prints "No memory accumulated yet for agent 'backend'"
  - [ ] Lists additional topic memory files if present
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (add `memory()` function)

### Task 6.3: Natural Language Parsing in Bridge Bot

- **Description:** Enhance Bridge Bot CLAUDE.md with natural language parsing rules. Users should be able to type conversational commands instead of slash commands.
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.1
- **Acceptance Criteria:**
  - [ ] "ask backend to add pagination" -> dispatch to backend
  - [ ] "what's backend doing?" -> status backend
  - [ ] "stop backend" / "cancel backend task" -> kill backend
  - [ ] "show my agents" / "list agents" -> list-agents
  - [ ] "what has backend done today?" -> history backend --limit 10
  - [ ] "what does backend know?" -> memory backend
  - [ ] Ambiguous input gets clarification response
- **Files Touched:**
  - `~/.claude-bridge/CLAUDE.md` (enhance routing rules)

### Task 6.4: Error Messages and Edge Cases

- **Description:** Review all commands for proper error handling. Ensure all error messages are clear, actionable, and suitable for Telegram relay.
- **Effort:** 1.5 hours
- **Dependencies:** All previous tasks
- **Acceptance Criteria:**
  - [ ] All commands handle missing arguments with usage hint
  - [ ] All commands handle non-existent agents with clear message
  - [ ] Dispatch handles Claude Code not installed: "Claude Code CLI not found. Install from..."
  - [ ] Dispatch handles Claude Code auth expired: detect and report
  - [ ] Kill handles already-dead PID gracefully
  - [ ] SQLite connection errors are caught and reported
  - [ ] No Python tracebacks shown to user -- all errors are human-readable
- **Files Touched:**
  - `~/.claude-bridge/bridge-cli.py` (error handling throughout)
  - `~/.claude-bridge/on-complete.py` (error handling)

### Task 6.5: End-to-End Test with Real Projects

- **Description:** Complete end-to-end test using a real project. Run through the full user journey from Telegram.
- **Effort:** 2 hours
- **Dependencies:** All previous tasks
- **Acceptance Criteria:**
  - [ ] Create agent for a real project from Telegram
  - [ ] Dispatch a meaningful task (not just "list files")
  - [ ] Task completes successfully, result appears in Telegram
  - [ ] Result summary is useful and accurate
  - [ ] Cost tracking shows reasonable amount
  - [ ] Agent memory updated after task
  - [ ] Check memory from Telegram shows learned context
  - [ ] Dispatch second task, verify session continuity (agent remembers first task)
  - [ ] Kill a long-running task from Telegram
  - [ ] Clean up: delete agent from Telegram
  - [ ] Total time from install to first result < 10 minutes

---

## Summary

| Milestone | Days | Tasks | Total Effort |
|-----------|------|-------|-------------|
| 1. Foundation | Day 1-2 | 6 tasks | ~8.5 hours |
| 2. CLAUDE.md Init | Day 3 | 3 tasks | ~5.5 hours |
| 3. Task Dispatch | Day 4-5 | 4 tasks | ~7.5 hours |
| 4. Completion System | Day 6-7 | 4 tasks | ~7.5 hours |
| 5. Bridge Bot Integration | Day 8-9 | 4 tasks | ~6.5 hours |
| 6. Polish | Day 10 | 5 tasks | ~7.5 hours |
| **Total** | **10 days** | **26 tasks** | **~43 hours** |
