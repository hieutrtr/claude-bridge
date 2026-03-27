# Claude Bridge MVP — Detailed Specification

> Dispatch tasks to multiple Claude Code sessions from one Telegram channel.
> Each session = agent + project. Persistent context. Leverages native Claude Code features.

---

## 1. What MVP Does

```
You (on phone, Telegram):
  /create-agent backend /Users/hieutran/projects/my-api "API development, REST endpoints, DB migrations"
  /create-agent frontend /Users/hieutran/projects/my-web "React UI, components, styling"
  /task backend add pagination to /users endpoint
  /task frontend fix the dark mode toggle on settings page

Both tasks run in parallel, each in its own Claude Code session:
  - Isolated via git worktrees (no file corruption)
  - Session persists (agent remembers all previous work)
  - CLAUDE.md auto-generated on create (project scan + agent purpose)
  - Auto Memory captures what agent learns over time
  - Stop hook reports completion → Telegram notification

"✓ Task #1 (backend) done in 3m. Added cursor-based pagination..."
"✓ Task #2 (frontend) done in 1m 45s. Fixed dark mode toggle..."
```

## 2. What MVP Does NOT Do

- No custom profile format (uses native `--agent` .md files)
- No enhancement accumulation (relies on native Auto Memory)
- No plugin system (uses native Claude Code plugins)
- No permission relay (uses `--allowedTools` / agent frontmatter)
- No persistent daemon process
- No Discord/Slack (Telegram only)
- No task queuing (rejects if busy; Phase 2)
- No multi-user (single user)

## 3. Native Claude Code Features Leveraged

| Feature | What Bridge Gets for Free | Lines of Code |
|---|---|---|
| **`--agent` .md files** | Agent identity, tools, permissions, model, hooks — all in one file | 0 (just generate the file) |
| **`isolation: worktree`** | Each task runs in isolated git worktree — no concurrent corruption | 0 (frontmatter field) |
| **`--session-id`** | Persistent conversation across tasks — agent remembers everything | 0 (CLI flag) |
| **Auto Memory** | Agent auto-learns project patterns, preferences, conventions | 0 (on by default) |
| **Stop hook** | Agent reports completion to Bridge — replaces PID polling watcher | ~30 lines (hook handler) |
| **`--output-format json`** | Structured results with cost, duration, turn count | 0 (CLI flag) |
| **Prompt caching** | 90% cost reduction on repeated context within sessions | 0 (automatic) |
| **CLAUDE.md hierarchy** | Project instructions survive compaction, loaded every session | 0 (native behavior) |

---

## 4. Core Concept: Session = Agent + Project

A session is always the combination of an **agent role** and a **project path**. This pairing defines the session identity, workspace, and context.

### 4.1 Session Identity

```
Agent:    backend
Project:  /Users/hieutran/projects/my-api
Purpose:  "API development, REST endpoints, DB migrations"

Derived:
  session_id:  backend--my-api
  workspace:   ~/.claude-bridge/workspaces/backend--my-api/
  agent_file:  ~/.claude/agents/bridge--backend--my-api.md
  claude_md:   /Users/hieutran/projects/my-api/CLAUDE.md (project-owned)
  auto_memory: ~/.claude/projects/<encoded-path>/memory/ (native)
```

### 4.2 Multiple Combinations

The same agent role can work on different projects, and the same project can have multiple agent roles:

```
backend  + my-api     → session: backend--my-api      (API backend work)
backend  + my-other   → session: backend--my-other    (same role, different project)
frontend + my-api     → session: frontend--my-api     (different role, same project)
devops   + my-api     → session: devops--my-api       (ops work on same project)
```

Each combination is a fully independent session with its own:
- Persistent conversation context (`--session-id`)
- Agent definition file (role, tools, permissions)
- Auto Memory (learned patterns and preferences)
- Workspace folder (task results, logs)
- CLAUDE.md (project context + agent purpose)

### 4.3 Workspace Structure

```
~/.claude-bridge/workspaces/
├── backend--my-api/
│   ├── tasks/
│   │   ├── task-1-result.json
│   │   ├── task-1-stderr.log
│   │   ├── task-2-result.json
│   │   └── ...
│   └── metadata.json          # session creation info
├── frontend--my-web/
│   └── tasks/
│       └── ...
└── ...
```

---

## 5. Architecture

```
┌──────────────────────────────────────────────────┐
│  Telegram (your phone)                           │
│                                                  │
│  /create-agent backend /path/to/api "API dev"    │
│  /task backend add pagination                    │
│  /agents                                         │
└──────────────┬───────────────────────────────────┘
               │
               │ MCP (official Telegram channel plugin)
               ▼
┌──────────────────────────────────────────────────┐
│  Bridge Bot (Claude Code session #0)             │
│                                                  │
│  Has: Telegram MCP channel                       │
│  Has: CLAUDE.md with command routing             │
│  Has: Bash access to bridge-cli.py               │
│                                                  │
│  Parses commands → calls bridge-cli.py           │
└──────────────┬───────────────────────────────────┘
               │
               │ Bash tool
               ▼
┌──────────────────────────────────────────────────┐
│  bridge-cli.py                                   │
│                                                  │
│  create-agent → generates agent .md + CLAUDE.md  │
│  dispatch     → spawns claude --agent ...        │
│  list / status / kill / history / memory         │
│                                                  │
│  Reads/writes: ~/.claude-bridge/bridge.db        │
└──────────────┬───────────────────────────────────┘
               │
               │ subprocess.Popen (background)
               ▼
┌──────────────────────────────────────────────────┐
│  claude --agent bridge--backend--my-api           │
│    --session-id backend--my-api                   │
│    --project-dir /Users/hieutran/projects/my-api  │
│    --output-format json                           │
│    -p "add pagination to /users endpoint"         │
│                                                   │
│  Agent .md includes:                              │
│    isolation: worktree  (safe concurrent tasks)   │
│    hooks: Stop → on-complete.py (updates SQLite)  │
│    tools: Read, Edit, Write, Bash, Grep, Glob     │
│    memory: project  (Auto Memory enabled)         │
└───────────────────────────────────────────────────┘
               │
               │ Stop hook fires on completion
               ▼
┌──────────────────────────────────────────────────┐
│  on-complete.py                                  │
│                                                  │
│  1. Parse result JSON                            │
│  2. Update task in SQLite (done/failed)          │
│  3. Update agent state (idle)                    │
│  4. Print formatted report                      │
│     → Bridge Bot relays to Telegram              │
└──────────────────────────────────────────────────┘
```

### 5.1 Component Responsibilities

| Component | What it does | What it is |
|---|---|---|
| **Bridge Bot** | Receives Telegram messages, parses commands, calls bridge-cli, relays results | Claude Code session with Telegram MCP |
| **bridge-cli.py** | Agent CRUD, CLAUDE.md init, agent .md generation, task dispatch, status queries | Python script (~250 lines) |
| **on-complete.py** | Stop hook handler — updates SQLite, prints completion report | Python script (~30 lines) |
| **bridge.db** | Tracks agents (sessions) and tasks | SQLite database |
| **Agent .md files** | Native Claude Code agent definitions with role, tools, permissions, hooks | Generated markdown files |

---

## 6. SQLite Schema

```sql
-- File: ~/.claude-bridge/bridge.db

PRAGMA journal_mode=WAL;

CREATE TABLE agents (
    name TEXT NOT NULL,                   -- "backend", "frontend"
    project_dir TEXT NOT NULL,            -- absolute path
    session_id TEXT NOT NULL UNIQUE,      -- "backend--my-api" (derived)
    agent_file TEXT NOT NULL,             -- path to .md agent file
    purpose TEXT,                         -- "API development, REST endpoints..."
    state TEXT DEFAULT 'created',         -- created/idle/running/failed/timeout
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_task_at TIMESTAMP,
    total_tasks INTEGER DEFAULT 0,
    PRIMARY KEY (name, project_dir)       -- agent + project = unique session
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES agents(session_id),
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'pending',        -- pending/running/done/failed/timeout/killed
    pid INTEGER,                          -- OS process ID
    result_file TEXT,                     -- path to result JSON
    result_summary TEXT,                  -- parsed summary for Telegram
    cost_usd REAL,
    duration_ms INTEGER,
    num_turns INTEGER,
    exit_code INTEGER,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    reported INTEGER DEFAULT 0
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_session ON tasks(session_id);
CREATE INDEX idx_tasks_unreported ON tasks(status, reported)
    WHERE status IN ('done', 'failed', 'timeout') AND reported = 0;
```

---

## 7. Create-Agent Flow

### 7.1 Command

```
/create-agent <name> <project_path> "<purpose>"
```

Example:
```
/create-agent backend /Users/hieutran/projects/my-api "API development, REST endpoints, DB migrations"
```

### 7.2 What Happens

```python
def create_agent(name: str, project_dir: str, purpose: str):
    """
    Register agent and bootstrap Claude Code session.

    Steps:
    1. Validate inputs
    2. Derive session identity
    3. Generate agent .md file (native Claude Code format)
    4. Run CLAUDE.md init (project scan + purpose injection)
    5. Create workspace directory
    6. Register in SQLite
    """
```

#### Step 1: Validate

- `project_dir` exists and is a directory
- `name` is alphanumeric + hyphens, 1-30 chars
- Combination of `name + project_dir` is unique

#### Step 2: Derive Session Identity

```python
project_name = os.path.basename(project_dir)  # "my-api"
session_id = f"{name}--{project_name}"         # "backend--my-api"
agent_file_name = f"bridge--{session_id}"      # "bridge--backend--my-api"
workspace = f"~/.claude-bridge/workspaces/{session_id}/"
```

#### Step 3: Generate Agent .md File

Write to `~/.claude/agents/bridge--backend--my-api.md`:

```markdown
---
name: bridge--backend--my-api
description: "{purpose}"
tools: Read, Edit, Write, Bash, Grep, Glob
model: sonnet
isolation: worktree
memory: project
hooks:
  Stop:
    - hooks:
        - type: command
          command: "python3 ~/.claude-bridge/on-complete.py --session-id backend--my-api"
---

# Agent: {name}
Project: {project_dir}
Purpose: {purpose}

You are a {name} agent working on this project.
Your focus: {purpose}

## Working Style
- Complete the task fully before stopping
- Run tests if the project has them
- Summarize what you changed when done
```

#### Step 4: Run CLAUDE.md Init (Project Scan + Purpose)

If the project does NOT already have a CLAUDE.md:

```bash
claude -p "Analyze this codebase thoroughly. Generate a CLAUDE.md file that includes:

1. PROJECT OVERVIEW
   - What this project does (infer from code, README, package.json, etc.)
   - Tech stack detected

2. BUILD & TEST COMMANDS
   - How to install dependencies
   - How to run tests
   - How to lint/format
   - How to build

3. PROJECT STRUCTURE
   - Key directories and what they contain
   - Important files and their purpose

4. CONVENTIONS
   - Coding style detected (from linter configs, existing code patterns)
   - Git workflow (branch naming, commit style)
   - Any patterns you notice

5. AGENT CONTEXT
   This project has a Bridge agent assigned with the following purpose:
   Purpose: {purpose}
   When working on tasks, keep this purpose in mind as your primary focus area.

Write the result to CLAUDE.md in the project root." \
  --project-dir {project_dir} \
  --allowedTools "Read,Grep,Glob,Write" \
  --output-format json
```

If the project ALREADY has a CLAUDE.md, append the agent context section:

```bash
claude -p "Read the existing CLAUDE.md. Append an '## Agent Context' section at the end:

## Agent Context
This project has a Bridge agent assigned:
- Agent: {name}
- Purpose: {purpose}

Do not modify the existing content, only append." \
  --project-dir {project_dir} \
  --allowedTools "Read,Write" \
  --output-format json
```

#### Step 5: Create Workspace

```bash
mkdir -p ~/.claude-bridge/workspaces/{session_id}/tasks/
```

Write `~/.claude-bridge/workspaces/{session_id}/metadata.json`:
```json
{
  "agent_name": "backend",
  "project_dir": "/Users/hieutran/projects/my-api",
  "session_id": "backend--my-api",
  "purpose": "API development, REST endpoints, DB migrations",
  "created_at": "2026-03-27T10:00:00"
}
```

#### Step 6: Register in SQLite

```sql
INSERT INTO agents (name, project_dir, session_id, agent_file, purpose)
VALUES ('backend', '/Users/hieutran/projects/my-api', 'backend--my-api',
        '~/.claude/agents/bridge--backend--my-api.md',
        'API development, REST endpoints, DB migrations');
```

#### Step 7: Output

```
Agent 'backend' created for /Users/hieutran/projects/my-api
Session: backend--my-api
Purpose: API development, REST endpoints, DB migrations
CLAUDE.md: initialized (project scanned + purpose injected)
Agent file: ~/.claude/agents/bridge--backend--my-api.md
Ready for tasks.
```

---

## 8. Task Dispatch

### 8.1 Command

```
/task <name> <prompt>
```

Example:
```
/task backend add pagination to /users endpoint with cursor-based approach
```

### 8.2 Dispatch Logic

```python
def dispatch(name: str, prompt: str):
    # 1. Look up agent session
    agent = db.get_agent_by_name(name)
    # If multiple projects for same agent name, pick the one or ask
    # For MVP: agent name must be unique (or user specifies project)

    # 2. Check not busy
    running = db.get_running_task(agent.session_id)
    if running:
        raise AgentBusyError(f"'{name}' busy with task #{running.id}")

    # 3. Insert task
    task_id = db.insert_task(agent.session_id, prompt)

    # 4. Build result paths
    workspace = f"~/.claude-bridge/workspaces/{agent.session_id}"
    result_file = f"{workspace}/tasks/task-{task_id}-result.json"
    stderr_file = f"{workspace}/tasks/task-{task_id}-stderr.log"

    # 5. Spawn
    pid = spawn_claude(
        agent_file=f"bridge--{agent.session_id}",
        session_id=agent.session_id,
        project_dir=agent.project_dir,
        prompt=prompt,
        result_file=result_file,
        stderr_file=stderr_file,
    )

    # 6. Update state
    db.update_task(task_id, status="running", pid=pid, result_file=result_file)
    db.update_agent(agent.session_id, state="running")

    return task_id, pid
```

### 8.3 The CLI Command

```bash
claude --agent bridge--backend--my-api \
  --session-id backend--my-api \
  --project-dir /Users/hieutran/projects/my-api \
  --output-format json \
  -p "add pagination to /users endpoint" \
  > ~/.claude-bridge/workspaces/backend--my-api/tasks/task-42-result.json \
  2> ~/.claude-bridge/workspaces/backend--my-api/tasks/task-42-stderr.log
```

**What each flag does:**

| Flag | Purpose |
|---|---|
| `--agent bridge--backend--my-api` | Load agent definition (role, tools, hooks, isolation) |
| `--session-id backend--my-api` | Resume persistent conversation — agent remembers all previous work |
| `--project-dir /path` | Work in this project directory |
| `--output-format json` | Structured result with cost, duration, turns |
| `-p "prompt"` | Non-interactive: run and exit |

**What the agent .md provides automatically:**
- `isolation: worktree` — task runs in isolated git worktree
- `memory: project` — Auto Memory captures learnings
- `hooks: Stop` — on-complete.py fires when task ends
- `tools` — pre-approved tool list (no permission prompts)

### 8.4 Subprocess Spawning

```python
import subprocess
import os

def spawn_claude(agent_file: str, session_id: str, project_dir: str,
                 prompt: str, result_file: str, stderr_file: str) -> int:
    """Spawn claude as background process. Returns PID."""

    os.makedirs(os.path.dirname(result_file), exist_ok=True)

    with open(result_file, "w") as out_f, open(stderr_file, "w") as err_f:
        process = subprocess.Popen(
            [
                "claude",
                "--agent", agent_file,
                "--session-id", session_id,
                "--project-dir", project_dir,
                "--output-format", "json",
                "-p", prompt,
            ],
            stdout=out_f,
            stderr=err_f,
            start_new_session=True,
        )
    return process.pid
```

---

## 9. Task Completion (Stop Hook)

### 9.1 How It Works

The agent .md includes a Stop hook. When `claude -p` finishes (success or failure), the hook fires automatically:

```yaml
hooks:
  Stop:
    - hooks:
        - type: command
          command: "python3 ~/.claude-bridge/on-complete.py --session-id backend--my-api"
```

### 9.2 on-complete.py

```python
#!/usr/bin/env python3
"""Stop hook handler. Called by Claude Code when agent task completes."""

import argparse
import json
import sqlite3
import os
from datetime import datetime

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    db = sqlite3.connect(os.path.expanduser("~/.claude-bridge/bridge.db"))

    # Find the running task for this session
    task = db.execute(
        "SELECT * FROM tasks WHERE session_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
        (args.session_id,)
    ).fetchone()

    if not task:
        return

    task_id = task[0]
    result_file = task[5]  # result_file column

    # Parse result
    status = "done"
    summary = ""
    cost = 0.0
    duration = 0
    turns = 0
    exit_code = 0
    error = None

    try:
        with open(os.path.expanduser(result_file)) as f:
            result = json.load(f)
        if result.get("is_error"):
            status = "failed"
            error = result.get("result", "Unknown error")[:500]
        else:
            summary = result.get("result", "")[:500]
        cost = result.get("cost_usd", 0)
        duration = result.get("duration_ms", 0)
        turns = result.get("num_turns", 0)
    except Exception as e:
        status = "failed"
        error = str(e)
        exit_code = -1

    # Update task
    db.execute("""
        UPDATE tasks SET status=?, result_summary=?, cost_usd=?, duration_ms=?,
        num_turns=?, exit_code=?, error_message=?, completed_at=?
        WHERE id=?
    """, (status, summary, cost, duration, turns, exit_code, error,
          datetime.now().isoformat(), task_id))

    # Update agent state
    db.execute(
        "UPDATE agents SET state='idle', last_task_at=?, total_tasks=total_tasks+1 WHERE session_id=?",
        (datetime.now().isoformat(), args.session_id)
    )
    db.commit()

    # Print report (Bridge Bot picks this up from hook output)
    duration_str = f"{duration // 60000}m {(duration % 60000) // 1000}s"
    if status == "done":
        print(f"✓ Task #{task_id} ({args.session_id}) — done in {duration_str}")
        print(f"  {summary[:200]}")
        print(f"  Cost: ${cost:.3f} | Turns: {turns}")
    else:
        print(f"✗ Task #{task_id} ({args.session_id}) — failed after {duration_str}")
        print(f"  Error: {error[:200]}")

if __name__ == "__main__":
    main()
```

### 9.3 Fallback: PID Watcher

The Stop hook handles most completions, but a lightweight watcher handles edge cases (process killed externally, hook fails):

```python
# watcher.py — fallback only, runs via cron every 5 min
# Checks for tasks with status='running' where PID is dead
# but on-complete.py didn't fire (crash, SIGKILL, etc.)
```

This is ~50 lines and only catches stragglers. The primary mechanism is the Stop hook.

---

## 10. Reading Auto Memory

### 10.1 memory Command

```
/memory <name>
```

Bridge Bot runs:
```bash
python3 bridge-cli.py memory backend
```

Which reads `~/.claude/projects/<encoded-project-path>/memory/MEMORY.md` and returns it.

### 10.2 What You See

```
Agent: backend (my-api)
Learned memories:

- [Project conventions](conventions.md) — Uses Express.js with TypeScript, Prisma ORM
- [Testing patterns](testing.md) — Jest with supertest for API integration tests
- [DB migrations](db_patterns.md) — Always run prisma migrate dev after schema changes
- [API patterns](api_patterns.md) — Cursor-based pagination preferred over offset
```

This is free — Auto Memory writes these automatically. Bridge just reads and displays them.

---

## 11. Telegram Commands

```
AGENT MANAGEMENT:
  /create-agent <name> <path> "<purpose>"    Create agent session
  /delete-agent <name>                       Delete agent + workspace
  /agents                                    List all agents with status

TASK DISPATCH:
  /task <name> <prompt>                      Dispatch task to agent
  /status [name]                             Check running tasks
  /kill <name>                               Kill running task
  /history <name> [n]                        Last n task results

INSIGHT:
  /memory <name>                             Show agent's Auto Memory
  /help                                      Show commands

NATURAL LANGUAGE:
  "fix the login bug on backend"             → /task backend fix the login bug
  "what's running?"                          → /status
  "what has backend learned?"                → /memory backend
```

---

## 12. Bridge Bot CLAUDE.md

```markdown
# Bridge Bot

You are the Bridge Bot for Claude Bridge. You receive commands from Telegram
and manage Claude Code agent sessions via bridge-cli.py.

## Commands

Parse incoming messages and run the appropriate command:

### /create-agent <name> <path> "<purpose>"
Run: `python3 ~/.claude-bridge/bridge-cli.py create-agent <name> <path> --purpose "<purpose>"`
This generates the agent .md file and initializes CLAUDE.md for the project.
Reply with the full output.

### /delete-agent <name>
Run: `python3 ~/.claude-bridge/bridge-cli.py delete-agent <name>`

### /task <name> <prompt...>
Run: `python3 ~/.claude-bridge/bridge-cli.py dispatch <name> "<prompt>"`
Reply with task ID and confirmation.

### /agents
Run: `python3 ~/.claude-bridge/bridge-cli.py list-agents`

### /status [name]
Run: `python3 ~/.claude-bridge/bridge-cli.py status [name]`

### /kill <name>
Run: `python3 ~/.claude-bridge/bridge-cli.py kill <name>`

### /history <name>
Run: `python3 ~/.claude-bridge/bridge-cli.py history <name>`

### /memory <name>
Run: `python3 ~/.claude-bridge/bridge-cli.py memory <name>`
Show what the agent has learned from Auto Memory.

### /help
Show available commands.

## Natural Language

If the message doesn't start with /, infer the intent:
- "fix the login bug on backend" → /task backend fix the login bug
- "what's running?" → /status
- "what has backend learned?" → /memory backend
- "kill frontend" → /kill frontend

## Rules
- Always relay script output verbatim
- If a command fails, show the error and suggest a fix
- Don't modify agent projects directly — only dispatch tasks
```

---

## 13. File Structure

```
~/.claude-bridge/
├── CLAUDE.md                          # Bridge Bot instructions
├── bridge-cli.py                      # CLI (~250 lines)
├── on-complete.py                     # Stop hook handler (~30 lines)
├── watcher.py                         # Fallback PID checker (~50 lines)
├── bridge.db                          # SQLite
├── config.yaml                        # Global config
├── workspaces/
│   ├── backend--my-api/
│   │   ├── metadata.json              # Session creation info
│   │   └── tasks/
│   │       ├── task-1-result.json
│   │       ├── task-1-stderr.log
│   │       └── ...
│   ├── frontend--my-web/
│   │   └── tasks/
│   │       └── ...
│   └── ...
└── logs/
    └── bridge.log

~/.claude/agents/
├── bridge--backend--my-api.md         # Generated agent definitions
├── bridge--frontend--my-web.md
└── ...

Projects (untouched except CLAUDE.md init):
/Users/hieutran/projects/my-api/
├── CLAUDE.md                          # Generated on create-agent
├── ... (project files)

/Users/hieutran/projects/my-web/
├── CLAUDE.md                          # Generated on create-agent
└── ...
```

---

## 14. Permissions Strategy

### 14.1 Via Agent .md Frontmatter

Each agent .md defines allowed tools:

```yaml
tools: Read, Edit, Write, Bash, Grep, Glob
```

For a read-only reviewer agent:
```yaml
tools: Read, Grep, Glob
```

For a devops agent:
```yaml
tools: Read, Edit, Write, Bash, Grep, Glob
disallowedTools: Bash(rm -rf *), Bash(git push --force *)
```

### 14.2 Combined with isolation: worktree

Since each task runs in an isolated worktree:
- Agent can freely edit files — changes are isolated
- If task fails, worktree is discarded automatically
- Successful changes can be reviewed before merging

---

## 15. Error Handling

| Error | Cause | Output |
|---|---|---|
| Agent not found | Typo in name | `Error: Agent 'xyz' not found. Available: backend, frontend` |
| Agent busy | Running a task | `Error: 'backend' busy with task #4. Use /kill to cancel.` |
| Project dir missing | Path doesn't exist | `Error: Directory '/bad/path' does not exist.` |
| Duplicate session | Same name+project | `Error: Agent 'backend' already exists for my-api.` |
| claude not found | CLI not installed | `Error: 'claude' command not found.` |
| CLAUDE.md init fails | Project analysis error | Agent created but CLAUDE.md not generated. Warning shown. |
| Stop hook fails | on-complete.py error | Watcher fallback detects completion via PID. |
| Process crashes | Non-zero exit | Stop hook marks failed. Watcher as backup. |
| Process hangs | Running > 30 min | Watcher kills + marks timeout. |

---

## 16. Walkthrough

```
# 1. Start Bridge Bot (one-time, run in terminal)
$ claude --channel telegram --project-dir ~/.claude-bridge

# 2. Create agents from Telegram
You: /create-agent backend /Users/hieutran/projects/my-api "API development, REST endpoints, DB migrations"
Bot: Agent 'backend' created for /Users/hieutran/projects/my-api
     Session: backend--my-api
     Purpose: API development, REST endpoints, DB migrations
     CLAUDE.md: initialized (detected Express.js + TypeScript + Prisma)
     Ready for tasks.

You: /create-agent frontend /Users/hieutran/projects/my-web "React UI, components, dark mode, responsive design"
Bot: Agent 'frontend' created for /Users/hieutran/projects/my-web
     Session: frontend--my-web
     Purpose: React UI, components, dark mode, responsive design
     CLAUDE.md: initialized (detected Next.js + React + Tailwind)
     Ready for tasks.

# 3. Dispatch tasks (parallel)
You: /task backend add pagination to /users endpoint with cursor-based approach
Bot: Task #1 dispatched to 'backend' (PID 12345)

You: /task frontend fix the dark mode toggle on settings page
Bot: Task #2 dispatched to 'frontend' (PID 12346)

# 4. Check status
You: /status
Bot: RUNNING:
       #1  backend   "add pagination..."    running 1m 30s
       #2  frontend  "fix dark mode..."     running 45s

# 5. Completion reports (via Stop hook, automatic)
Bot: ✓ Task #2 (frontend--my-web) — done in 1m 45s
     Fixed dark mode toggle by updating ThemeContext provider.
     Cost: $0.02 | Turns: 3

Bot: ✓ Task #1 (backend--my-api) — done in 3m 22s
     Added cursor-based pagination to /users endpoint.
     Cost: $0.04 | Turns: 5

# 6. Follow-up (same session, agent remembers everything)
You: /task backend now add the same pagination to /products
Bot: Task #3 dispatched to 'backend' (PID 12400)
# Agent remembers the cursor-based approach from task #1

# 7. Check what agent has learned
You: /memory backend
Bot: Agent: backend (my-api)
     Learned:
     - API uses cursor-based pagination (established in task #1)
     - Prisma ORM with PostgreSQL
     - Jest + supertest for integration tests
     - Express.js route pattern: router.get('/resource', handler)
```

---

## 17. Implementation Order

### Week 1: Core

| Day | Task | Output |
|---|---|---|
| 1 | SQLite schema + bridge-cli.py (create-agent with session identity) | Agent CRUD works |
| 2 | Agent .md generation + CLAUDE.md init | Agents bootstrapped with full context |
| 3 | bridge-cli.py (dispatch with --agent + --worktree) | Task dispatch works |
| 4 | on-complete.py (Stop hook handler) + watcher.py fallback | Completion detection works |
| 5 | Bridge Bot CLAUDE.md + test with Telegram MCP | End-to-end flow works |

### Week 2: Polish

| Day | Task | Output |
|---|---|---|
| 6 | /memory command (read Auto Memory) | Insight into agent learning |
| 7 | /history, /status formatting, natural language parsing | Complete UX |
| 8 | Error handling, edge cases, duplicate agent names | Robust |
| 9 | Watcher fallback cron, workspace cleanup | Production-ready |
| 10 | Test with real projects, fix issues | Ready for daily use |

### Deliverables

```
~/.claude-bridge/bridge-cli.py     ~250 lines
~/.claude-bridge/on-complete.py    ~30 lines
~/.claude-bridge/watcher.py        ~50 lines (fallback only)
~/.claude-bridge/CLAUDE.md         ~60 lines
~/.claude-bridge/config.yaml       ~10 lines
SQLite schema                      ~25 lines
```

**Total: ~425 lines of Python + config**

---

## 18. Success Criteria

- [ ] Can create agents with purpose-driven CLAUDE.md init
- [ ] Session identity = agent + project (unique pairing)
- [ ] Agent .md files generated in native Claude Code format
- [ ] CLAUDE.md generated with project scan + purpose context
- [ ] Tasks dispatch with `--agent` + `--session-id` + `isolation: worktree`
- [ ] Stop hook fires on completion → updates SQLite → reports to Telegram
- [ ] Sessions persist across tasks (agent remembers)
- [ ] Auto Memory captures learnings (readable via /memory)
- [ ] Multiple agents run in parallel without corruption (worktrees)
- [ ] Can check status, kill tasks, view history from Telegram
- [ ] Works reliably for a full day of use

---

## 19. Out of Scope (Phase 2+)

| Feature | Why Not MVP | Leverages |
|---|---|---|
| Task queuing | Reject if busy; queue later | — |
| Permission relay | Pre-approved via agent .md tools | Phase 2: hooks |
| Discord/Slack | Telegram first | Native Channels |
| Agent Teams | Single-agent dispatch first | Native Agent Teams |
| Web dashboard | Telegram is the UI | — |
| Multi-user | Single user (you) | — |
| Model routing | Sonnet default; Opus later | Agent .md `model` field |
| Cost dashboard | Basic cost in task reports | — |
