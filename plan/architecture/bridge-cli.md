# bridge-cli.py -- Detailed Architecture

> The core Python script (~250 lines) that handles all agent lifecycle and task management for Claude Bridge.
> Called exclusively by the Bridge Bot via the Bash tool.

---

## 1. Overview

`bridge-cli.py` is a single-file Python CLI that sits at the center of the Bridge layer. It has four responsibilities:

1. **Agent CRUD** -- Create, list, delete agents. Each agent is a pairing of a name and a project directory.
2. **Agent .md generation** -- Write native Claude Code agent definition files to `~/.claude/agents/`.
3. **CLAUDE.md initialization** -- Run a one-shot `claude -p` to scan a project and produce a purpose-driven CLAUDE.md.
4. **Task dispatch and tracking** -- Spawn `claude` subprocesses, track PIDs, record results in SQLite, expose status/history/kill.

It reads and writes a single SQLite database at `~/.claude-bridge/bridge.db`. It generates files into `~/.claude/agents/` and `~/.claude-bridge/workspaces/`. It depends only on Python standard library modules -- no pip installs required.

```
Bridge Bot (Session #0)
    |
    |  Bash tool: python3 ~/.claude-bridge/bridge-cli.py <command> [args]
    |
    v
bridge-cli.py
    |
    +---> SQLite (bridge.db)            read/write
    +---> ~/.claude/agents/bridge--*.md  write (generate)
    +---> ~/.claude-bridge/workspaces/   write (task output)
    +---> subprocess: claude ...         spawn (dispatch)
    +---> subprocess: claude -p ...      spawn (CLAUDE.md init)
```

---

## 2. CLI Interface

The script uses `argparse` with subcommands. Every command prints structured text to stdout (consumed by the Bridge Bot) and exits with code 0 on success, non-zero on error.

### Command Reference

| Command | Syntax | Description |
|---------|--------|-------------|
| `create-agent` | `create-agent <name> <path> --purpose "..."` | Register a new agent, generate .md file, init CLAUDE.md |
| `delete-agent` | `delete-agent <name>` | Remove agent record, delete generated .md file |
| `dispatch` | `dispatch <name> "<prompt>"` | Send a task to an agent (spawn claude subprocess) |
| `list-agents` | `list-agents` | List all registered agents with state |
| `status` | `status [name]` | Show agent status; if name omitted, show all running tasks |
| `kill` | `kill <name>` | Send SIGTERM to a running agent's task |
| `history` | `history <name> [--limit N]` | Show completed tasks for an agent (default limit 10) |
| `memory` | `memory <name>` | Read and print the agent's Auto Memory file |

### Pseudocode: Argument Parsing

```python
def build_parser():
    parser = argparse.ArgumentParser(prog="bridge-cli")
    sub = parser.add_subparsers(dest="command", required=True)

    # create-agent
    p = sub.add_parser("create-agent")
    p.add_argument("name")            # e.g. "backend"
    p.add_argument("path")            # e.g. "/Users/me/projects/api"
    p.add_argument("--purpose", required=True)  # e.g. "REST API development"

    # delete-agent
    p = sub.add_parser("delete-agent")
    p.add_argument("name")

    # dispatch
    p = sub.add_parser("dispatch")
    p.add_argument("name")
    p.add_argument("prompt")

    # list-agents
    sub.add_parser("list-agents")

    # status
    p = sub.add_parser("status")
    p.add_argument("name", nargs="?", default=None)

    # kill
    p = sub.add_parser("kill")
    p.add_argument("name")

    # history
    p = sub.add_parser("history")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=10)

    # memory
    p = sub.add_parser("memory")
    p.add_argument("name")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    db = open_db()

    dispatch_table = {
        "create-agent": cmd_create_agent,
        "delete-agent": cmd_delete_agent,
        "dispatch":     cmd_dispatch,
        "list-agents":  cmd_list_agents,
        "status":       cmd_status,
        "kill":         cmd_kill,
        "history":      cmd_history,
        "memory":       cmd_memory,
    }

    try:
        fn = dispatch_table[args.command]
        fn(db, args)
    except BridgeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
```

---

## 3. SQLite Database Module

### 3.1 Database Location

```
~/.claude-bridge/bridge.db
```

Created on first run if it does not exist.

### 3.2 Schema

```sql
-- Enable WAL mode for concurrent reads during writes
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
    name         TEXT NOT NULL,
    project_dir  TEXT NOT NULL,
    session_id   TEXT NOT NULL UNIQUE,
    purpose      TEXT NOT NULL,
    state        TEXT NOT NULL DEFAULT 'idle',   -- idle | busy
    agent_file   TEXT NOT NULL,                  -- path to generated .md
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (name, project_dir)
);

CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    prompt       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending', -- pending | running | done | failed | timeout | killed
    pid          INTEGER,
    result_file  TEXT,                            -- path to JSON output
    stderr_file  TEXT,                            -- path to stderr log
    cost         REAL,                            -- USD cost from Claude output
    duration     REAL,                            -- seconds
    summary      TEXT,                            -- extracted result summary
    reported     INTEGER NOT NULL DEFAULT 0,      -- 0 = not yet sent to Telegram
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT,

    FOREIGN KEY (session_id) REFERENCES agents(session_id)
);
```

**Composite primary key** on `agents(name, project_dir)` -- the same agent name can exist across different projects, but each combination is unique. The `session_id` column is also `UNIQUE` because it is derived deterministically from the name + project and must not collide.

### 3.3 WAL Mode

WAL (Write-Ahead Logging) is enabled so that:
- The Bridge Bot can read agent/task state while `on-complete.py` writes completion results.
- The watcher cron can read running tasks while dispatch writes new ones.
- No `SQLITE_BUSY` errors under normal concurrent access patterns.

### 3.4 Connection Handling

```python
import sqlite3
import os

BRIDGE_HOME = os.path.expanduser("~/.claude-bridge")
DB_PATH = os.path.join(BRIDGE_HOME, "bridge.db")

def open_db():
    """Open database connection, create tables if needed."""
    os.makedirs(BRIDGE_HOME, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    _create_tables(conn)
    return conn

def _create_tables(conn):
    conn.executescript(SCHEMA_SQL)
    conn.commit()
```

### 3.5 Query Functions

```python
def get_agent(db, name):
    """Fetch agent by name. Raises BridgeError if not found."""
    row = db.execute(
        "SELECT * FROM agents WHERE name = ?", (name,)
    ).fetchone()
    if not row:
        raise BridgeError(f"Agent '{name}' not found")
    return row

def get_agent_by_session(db, session_id):
    """Fetch agent by session_id."""
    row = db.execute(
        "SELECT * FROM agents WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise BridgeError(f"No agent with session '{session_id}'")
    return row

def insert_agent(db, name, project_dir, session_id, purpose, agent_file):
    db.execute(
        """INSERT INTO agents (name, project_dir, session_id, purpose, agent_file)
           VALUES (?, ?, ?, ?, ?)""",
        (name, project_dir, session_id, purpose, agent_file)
    )
    db.commit()

def set_agent_state(db, session_id, state):
    db.execute(
        "UPDATE agents SET state = ? WHERE session_id = ?",
        (state, session_id)
    )
    db.commit()

def insert_task(db, session_id, prompt):
    """Insert a new task, return its id."""
    cur = db.execute(
        "INSERT INTO tasks (session_id, prompt, status) VALUES (?, ?, 'pending')",
        (session_id, prompt)
    )
    db.commit()
    return cur.lastrowid

def update_task_running(db, task_id, pid, result_file, stderr_file):
    db.execute(
        """UPDATE tasks SET status = 'running', pid = ?,
           result_file = ?, stderr_file = ?
           WHERE id = ?""",
        (pid, result_file, stderr_file, task_id)
    )
    db.commit()

def get_running_task(db, session_id):
    """Return the running task for a session, or None."""
    return db.execute(
        "SELECT * FROM tasks WHERE session_id = ? AND status = 'running'",
        (session_id,)
    ).fetchone()

def get_task_history(db, session_id, limit=10):
    return db.execute(
        """SELECT * FROM tasks WHERE session_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (session_id, limit)
    ).fetchall()
```

---

## 4. Agent .md Generator

When `create-agent` runs, it generates a native Claude Code agent definition file. This file is placed in `~/.claude/agents/` where Claude Code automatically discovers it.

### 4.1 File Naming

```
~/.claude/agents/bridge--{session_id}.md
```

Example: `~/.claude/agents/bridge--backend--my-api.md`

The `bridge--` prefix namespaces all Bridge-generated agents so they do not collide with user-created agent files.

### 4.2 Template Structure

The file consists of two parts: YAML frontmatter (metadata for Claude Code) and a Markdown body (system prompt injected into the agent's context).

```python
AGENT_MD_TEMPLATE = """\
---
name: bridge--{session_id}
description: "{purpose}"
tools:
  - Read
  - Edit
  - Write
  - Bash
  - Grep
  - Glob
model: sonnet
isolation: worktree
memory: project
hooks:
  Stop:
    - type: command
      command: "python3 {bridge_home}/on-complete.py --session-id {session_id} --task-id $TASK_ID"
---

# Agent: {name}

**Project:** {project_dir}
**Purpose:** {purpose}

## Working Style
- Complete the task fully before stopping.
- Run tests if the project has a test suite configured.
- Lint or format code if the project has linting configured.
- Summarize what you changed when done: files modified, tests passing, any warnings.
- If you encounter an ambiguous requirement, make a reasonable choice and note the assumption.
"""
```

### 4.3 Generation Function

```python
import os

AGENTS_DIR = os.path.expanduser("~/.claude/agents")

def generate_agent_md(session_id, name, project_dir, purpose):
    """Generate the agent .md file. Return the file path."""
    os.makedirs(AGENTS_DIR, exist_ok=True)

    filename = f"bridge--{session_id}.md"
    filepath = os.path.join(AGENTS_DIR, filename)

    content = AGENT_MD_TEMPLATE.format(
        session_id=session_id,
        name=name,
        project_dir=project_dir,
        purpose=purpose,
        bridge_home=BRIDGE_HOME,
    )

    with open(filepath, "w") as f:
        f.write(content)

    return filepath
```

### 4.4 Frontmatter Fields Explained

| Field | Value | Effect |
|-------|-------|--------|
| `name` | `bridge--{session_id}` | Unique identifier used with `--agent` flag |
| `description` | Agent's purpose | Shown in `claude agent list` |
| `tools` | Read, Edit, Write, Bash, Grep, Glob | Full tool access for autonomous work |
| `model` | `sonnet` | Cost-effective default; overridable in Phase 2 |
| `isolation` | `worktree` | Each task runs in an isolated git worktree |
| `memory` | `project` | Enables Auto Memory -- agent learns across tasks |
| `hooks.Stop` | `on-complete.py` command | Fires when agent finishes, updates DB + notifies |

---

## 5. CLAUDE.md Init

When creating an agent, `bridge-cli.py` runs a one-shot Claude Code invocation to generate (or augment) the project's CLAUDE.md file. This gives the agent immediate project awareness.

### 5.1 Two Paths

```
Does CLAUDE.md exist in project_dir?
    |
    +-- NO  --> Full generation: scan project + inject purpose
    |
    +-- YES --> Append only: add agent context section to existing file
```

### 5.2 Full Generation (New CLAUDE.md)

When no CLAUDE.md exists, bridge-cli runs `claude -p` with a prompt that instructs Claude Code to scan the project structure and produce a complete CLAUDE.md.

```python
INIT_PROMPT_NEW = """\
You are initializing a CLAUDE.md file for this project. Do the following:

1. Scan the project directory structure, config files (package.json, pyproject.toml, \
Cargo.toml, Makefile, Dockerfile, etc.), and README if present.
2. Identify: language/framework, build commands, test commands, lint commands, \
directory structure conventions, coding style patterns.
3. Write a CLAUDE.md file in the project root with this structure:

# Project: {project_basename}

## Overview
(1-2 sentence description based on what you found)

## Build & Run
(commands to build, run, test, lint)

## Project Structure
(key directories and their purposes)

## Conventions
(naming, patterns, style rules observed)

## Agent Context
Purpose: {purpose}
Focus areas for this agent based on the purpose above.

Write the file to: {project_dir}/CLAUDE.md
Keep it concise -- under 60 lines. Facts only, no filler.
"""
```

### 5.3 Append Path (Existing CLAUDE.md)

When a CLAUDE.md already exists, bridge-cli preserves it and only appends an agent context section.

```python
INIT_PROMPT_APPEND = """\
A CLAUDE.md already exists in this project. Do NOT overwrite it.
Append the following section at the end of the file:

## Agent Context: {name}
Purpose: {purpose}
(Add 2-3 bullet points about what this agent should focus on, based on the purpose \
and the existing CLAUDE.md content.)

Append to: {project_dir}/CLAUDE.md
"""
```

### 5.4 Init Execution

```python
import subprocess

def init_claude_md(project_dir, name, purpose):
    """Run claude -p to generate or augment CLAUDE.md."""
    claude_md_path = os.path.join(project_dir, "CLAUDE.md")

    if os.path.exists(claude_md_path):
        prompt = INIT_PROMPT_APPEND.format(
            name=name,
            purpose=purpose,
            project_dir=project_dir,
        )
    else:
        prompt = INIT_PROMPT_NEW.format(
            project_basename=os.path.basename(project_dir),
            purpose=purpose,
            project_dir=project_dir,
        )

    result = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "text"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=120,  # 2 minute timeout for init
    )

    if result.returncode != 0:
        raise BridgeError(
            f"CLAUDE.md init failed: {result.stderr[:200]}"
        )

    return claude_md_path
```

### 5.5 Why This Matters

The CLAUDE.md lives in the project root and is loaded by Claude Code on every invocation in that project. By generating it at agent creation time:

- The agent immediately knows how to build, test, and lint the project.
- The agent understands the project's conventions from task #1.
- CLAUDE.md survives conversation compaction (unlike chat history).
- Multiple agents on the same project share the same CLAUDE.md context.

---

## 6. Session Identity

### 6.1 Derivation

A session_id is a deterministic string derived from the agent name and the project directory's basename:

```
session_id = "{agent_name}--{project_basename}"
```

Examples:

| Agent Name | Project Path | session_id |
|------------|-------------|------------|
| `backend` | `/Users/me/projects/my-api` | `backend--my-api` |
| `frontend` | `/Users/me/projects/my-web` | `frontend--my-web` |
| `backend` | `/Users/me/projects/other-api` | `backend--other-api` |

```python
def derive_session_id(name, project_dir):
    """Derive a session_id from agent name and project basename."""
    basename = os.path.basename(os.path.normpath(project_dir))
    session_id = f"{name}--{basename}"
    # Sanitize: only allow alphanumeric, hyphens, underscores, double-dash separator
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+--[a-zA-Z0-9_.-]+$', session_id):
        raise BridgeError(
            f"Invalid session_id '{session_id}'. "
            "Agent name and project directory basename must contain only "
            "alphanumeric characters, hyphens, and underscores."
        )
    return session_id
```

### 6.2 Workspace Directory

Each session gets a workspace directory for task output storage:

```
~/.claude-bridge/workspaces/{session_id}/
    metadata.json
    tasks/
        task-{id}-result.json
        task-{id}-stderr.log
```

```python
def create_workspace(session_id, name, project_dir, purpose):
    """Create workspace directory and write metadata.json."""
    workspace = os.path.join(BRIDGE_HOME, "workspaces", session_id)
    tasks_dir = os.path.join(workspace, "tasks")
    os.makedirs(tasks_dir, exist_ok=True)

    metadata = {
        "session_id": session_id,
        "agent_name": name,
        "project_dir": project_dir,
        "purpose": purpose,
        "created_at": datetime.now().isoformat(),
    }

    metadata_path = os.path.join(workspace, "metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    return workspace
```

### 6.3 metadata.json

```json
{
  "session_id": "backend--my-api",
  "agent_name": "backend",
  "project_dir": "/Users/me/projects/my-api",
  "purpose": "REST API development, database migrations",
  "created_at": "2026-03-27T10:30:00"
}
```

This file is informational only. The source of truth is SQLite. It exists so that a human browsing the filesystem can understand what a workspace belongs to.

---

## 7. Task Dispatcher

The dispatcher is the most critical function. It spawns a `claude` subprocess in the background with the correct agent, session, and project arguments.

### 7.1 Full Claude Command

```bash
claude \
  --agent bridge--{session_id} \
  --session-id {session_id} \
  --project-dir {project_dir} \
  --output-format json \
  -p "{prompt}"
```

| Flag | Purpose |
|------|---------|
| `--agent` | Loads the generated .md file (role, tools, hooks, isolation) |
| `--session-id` | Persistent conversation -- agent remembers past tasks |
| `--project-dir` | Sets working directory for the Claude Code session |
| `--output-format json` | Structured output for parsing by on-complete.py |
| `-p` | Non-interactive prompt mode -- runs and exits |

### 7.2 Dispatch Flow

```
cmd_dispatch(db, args)
    |
    +-- 1. get_agent(db, name)           --> agent row or BridgeError
    +-- 2. check not busy                --> reject if running task exists
    +-- 3. insert_task(db, session_id)   --> task_id
    +-- 4. set_agent_state(db, "busy")
    +-- 5. prepare output file paths     --> result.json, stderr.log
    +-- 6. subprocess.Popen(claude ...)  --> pid
    +-- 7. update_task_running(db, ...)  --> store pid + file paths
    +-- 8. print confirmation            --> "Task #{id} dispatched to {name}"
```

### 7.3 Pseudocode

```python
def cmd_dispatch(db, args):
    agent = get_agent(db, args.name)
    session_id = agent["session_id"]
    project_dir = agent["project_dir"]

    # Busy check
    running = get_running_task(db, session_id)
    if running:
        raise BridgeError(
            f"Agent '{args.name}' is busy with task #{running['id']}. "
            f"Wait for it to finish or run: bridge-cli kill {args.name}"
        )

    # Insert task record
    task_id = insert_task(db, session_id, args.prompt)

    # Set agent busy
    set_agent_state(db, session_id, "busy")

    # Prepare output paths
    workspace = os.path.join(BRIDGE_HOME, "workspaces", session_id, "tasks")
    result_file = os.path.join(workspace, f"task-{task_id}-result.json")
    stderr_file = os.path.join(workspace, f"task-{task_id}-stderr.log")

    # Build command
    cmd = [
        "claude",
        "--agent", f"bridge--{session_id}",
        "--session-id", session_id,
        "--project-dir", project_dir,
        "--output-format", "json",
        "-p", args.prompt,
    ]

    # Spawn subprocess (non-blocking)
    with open(result_file, "w") as stdout_f, \
         open(stderr_file, "w") as stderr_f:
        proc = subprocess.Popen(
            cmd,
            stdout=stdout_f,
            stderr=stderr_f,
            cwd=project_dir,
            start_new_session=True,  # detach from parent process group
        )

    # Record PID and file paths
    update_task_running(db, task_id, proc.pid, result_file, stderr_file)

    print(f"Task #{task_id} dispatched to agent '{args.name}' (PID {proc.pid})")
    print(f"Prompt: {args.prompt[:100]}{'...' if len(args.prompt) > 100 else ''}")
```

### 7.4 Key Design Decisions

**`start_new_session=True`** -- The spawned claude process runs in its own process group. This means it survives if the Bridge Bot session that dispatched it terminates. Tasks are fire-and-forget from bridge-cli's perspective.

**stdout to file** -- The `--output-format json` output goes to a file, not to bridge-cli's stdout. The `on-complete.py` hook (or the watcher) reads this file after the process exits.

**Busy check** -- Single task execution model. If the agent is busy, dispatch rejects immediately with a clear error message suggesting `/kill` or waiting. Queue support is deferred to Phase 2.

**Environment variable `TASK_ID`** -- The Stop hook receives the task ID via an environment variable so `on-complete.py` knows which row to update. This is set by the agent .md hook definition via `$TASK_ID`, which Claude Code passes through from its internal tracking.

---

## 8. Agent Memory Reader

Claude Code's Auto Memory stores learned knowledge per project in:

```
~/.claude/projects/<encoded-path>/memory/MEMORY.md
```

The `memory` command reads this file and prints its contents.

### 8.1 Path Encoding Logic

Claude Code encodes the project path by replacing `/` with `-` and prepending `-`:

```
/Users/me/projects/my-api  -->  -Users-me-projects-my-api
```

```python
def encode_project_path(project_dir):
    """Encode a project directory path the way Claude Code does.

    Claude Code stores per-project data under ~/.claude/projects/
    using a path encoding scheme where:
    - The absolute path is taken
    - All '/' separators are replaced with '-'
    - The result starts with '-' (from the leading '/')
    """
    abs_path = os.path.abspath(project_dir)
    encoded = abs_path.replace("/", "-")
    return encoded
```

### 8.2 Memory File Location

```python
CLAUDE_HOME = os.path.expanduser("~/.claude")

def get_memory_path(project_dir):
    """Return the path to the agent's Auto Memory file."""
    encoded = encode_project_path(project_dir)
    return os.path.join(
        CLAUDE_HOME, "projects", encoded, "memory", "MEMORY.md"
    )
```

### 8.3 Memory Command

```python
def cmd_memory(db, args):
    agent = get_agent(db, args.name)
    memory_path = get_memory_path(agent["project_dir"])

    if not os.path.exists(memory_path):
        print(f"No memory file found for agent '{args.name}'.")
        print(f"Expected at: {memory_path}")
        print("Memory is created automatically after the agent completes tasks.")
        return

    with open(memory_path, "r") as f:
        content = f.read()

    print(f"=== Memory for agent '{args.name}' ===")
    print(f"Project: {agent['project_dir']}")
    print(f"File: {memory_path}")
    print("---")
    print(content)
```

### 8.4 Additional Memory Files

Auto Memory can create topic-specific files beyond MEMORY.md (e.g., `testing.md`, `api_patterns.md`). The `memory` command reads the primary MEMORY.md. A future enhancement could list and read all files in the `memory/` directory.

---

## 9. Error Handling

All user-facing errors are raised as `BridgeError`, caught in `main()`, and printed to stderr with exit code 1.

### 9.1 Error Class

```python
class BridgeError(Exception):
    """User-facing error with a clear message."""
    pass
```

### 9.2 Error Scenarios

| Scenario | Detection | Message |
|----------|-----------|---------|
| **Agent not found** | `get_agent()` returns None | `Agent '{name}' not found. Run list-agents to see available agents.` |
| **Agent already exists** | `INSERT` hits UNIQUE constraint | `Agent '{name}' already exists for project '{path}'.` |
| **Agent busy** | `get_running_task()` returns a row | `Agent '{name}' is busy with task #{id}. Wait or run: bridge-cli kill {name}` |
| **Project doesn't exist** | `os.path.isdir()` check | `Project directory does not exist: {path}` |
| **Project not a git repo** | Check for `.git` dir | `Project directory is not a git repository: {path}. Worktree isolation requires git.` |
| **claude not found** | `shutil.which("claude")` | `'claude' CLI not found in PATH. Install Claude Code first.` |
| **SQLite locked** | `sqlite3.OperationalError` timeout | `Database is locked. Another process may be writing. Try again.` |
| **CLAUDE.md init fails** | Non-zero exit from `claude -p` | `CLAUDE.md init failed: {stderr snippet}` |
| **Kill: no running task** | No task with `status='running'` | `Agent '{name}' has no running task.` |
| **Kill: process already dead** | `os.kill(pid, 0)` raises `OSError` | `Task process (PID {pid}) already exited.` (still mark task as killed) |

### 9.3 Validation on Create

```python
def cmd_create_agent(db, args):
    name = args.name
    project_dir = os.path.abspath(args.path)
    purpose = args.purpose

    # Validate project directory exists
    if not os.path.isdir(project_dir):
        raise BridgeError(f"Project directory does not exist: {project_dir}")

    # Validate it's a git repo (required for worktree isolation)
    if not os.path.isdir(os.path.join(project_dir, ".git")):
        raise BridgeError(
            f"Project directory is not a git repository: {project_dir}. "
            "Worktree isolation requires git."
        )

    # Validate claude CLI is available
    if not shutil.which("claude"):
        raise BridgeError("'claude' CLI not found in PATH. Install Claude Code first.")

    # Derive session_id (validates name + basename characters)
    session_id = derive_session_id(name, project_dir)

    # Check for duplicate
    existing = db.execute(
        "SELECT 1 FROM agents WHERE name = ? AND project_dir = ?",
        (name, project_dir)
    ).fetchone()
    if existing:
        raise BridgeError(f"Agent '{name}' already exists for project '{project_dir}'.")

    # --- All validations passed, proceed with creation ---

    # Generate agent .md file
    agent_file = generate_agent_md(session_id, name, project_dir, purpose)

    # Init CLAUDE.md (run claude -p to scan project)
    init_claude_md(project_dir, name, purpose)

    # Create workspace
    create_workspace(session_id, name, project_dir, purpose)

    # Insert into database
    insert_agent(db, name, project_dir, session_id, purpose, agent_file)

    print(f"Agent '{name}' created successfully.")
    print(f"  Session:   {session_id}")
    print(f"  Project:   {project_dir}")
    print(f"  Purpose:   {purpose}")
    print(f"  Agent file: {agent_file}")
```

### 9.4 Kill Implementation

```python
import signal

def cmd_kill(db, args):
    agent = get_agent(db, args.name)
    session_id = agent["session_id"]

    running = get_running_task(db, session_id)
    if not running:
        raise BridgeError(f"Agent '{args.name}' has no running task.")

    pid = running["pid"]
    task_id = running["id"]

    # Attempt SIGTERM
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"Sent SIGTERM to task #{task_id} (PID {pid}).")
    except ProcessLookupError:
        print(f"Task process (PID {pid}) already exited.")

    # Update database regardless (process may have died without hook firing)
    db.execute(
        """UPDATE tasks SET status = 'killed', finished_at = datetime('now')
           WHERE id = ?""",
        (task_id,)
    )
    set_agent_state(db, session_id, "idle")
    db.commit()

    print(f"Agent '{args.name}' is now idle.")
```

---

## 10. Dependencies

`bridge-cli.py` uses **only Python standard library modules**. No `pip install`, no virtual environment, no requirements.txt.

| Module | Usage |
|--------|-------|
| `argparse` | CLI argument parsing and subcommand routing |
| `sqlite3` | Database connection, queries, schema creation |
| `subprocess` | `Popen` for task dispatch, `run` for CLAUDE.md init |
| `json` | Write metadata.json, parse Claude output |
| `os` | Path manipulation, directory creation, `os.kill` for SIGTERM |
| `os.path` | `exists`, `isdir`, `join`, `abspath`, `basename`, `expanduser`, `normpath` |
| `signal` | `signal.SIGTERM` constant |
| `datetime` | Timestamps in metadata.json |
| `sys` | `sys.exit`, `sys.stderr` |
| `shutil` | `shutil.which("claude")` for CLI availability check |
| `re` | Session ID validation |

### Why stdlib-only?

- **Zero setup friction.** The user does not need to manage a Python venv or install packages. macOS ships with Python 3 since Xcode Command Line Tools.
- **No dependency rot.** No `pip freeze`, no version conflicts, no supply chain risk for a 250-line script.
- **Portability.** Works on any macOS (or Linux) with Python 3.8+. No compiled extensions, no platform-specific wheels.
- **Simplicity.** Every dependency in the list is battle-tested, stable, and well-documented. There is no external library that would save meaningful LOC for what bridge-cli does.

---

## Appendix A: Remaining Commands

### list-agents

```python
def cmd_list_agents(db, args):
    rows = db.execute(
        "SELECT name, project_dir, session_id, purpose, state, created_at FROM agents ORDER BY name"
    ).fetchall()

    if not rows:
        print("No agents registered. Create one with: bridge-cli create-agent <name> <path> --purpose '...'")
        return

    for row in rows:
        state_icon = "BUSY" if row["state"] == "busy" else "idle"
        print(f"  {row['name']} [{state_icon}]")
        print(f"    Project:  {row['project_dir']}")
        print(f"    Purpose:  {row['purpose']}")
        print(f"    Session:  {row['session_id']}")
        print()
```

### status

```python
def cmd_status(db, args):
    if args.name:
        # Status for a specific agent
        agent = get_agent(db, args.name)
        running = get_running_task(db, agent["session_id"])
        print(f"Agent: {args.name}")
        print(f"State: {agent['state']}")
        if running:
            print(f"Running task: #{running['id']}")
            print(f"  Prompt: {running['prompt'][:100]}")
            print(f"  PID:    {running['pid']}")
            print(f"  Since:  {running['created_at']}")
            # Check if process is actually alive
            try:
                os.kill(running["pid"], 0)
                print(f"  Process: alive")
            except OSError:
                print(f"  Process: dead (hook may not have fired)")
        else:
            print("No running task.")
    else:
        # Show all running tasks across all agents
        rows = db.execute(
            """SELECT t.id, t.prompt, t.pid, t.created_at, a.name
               FROM tasks t JOIN agents a ON t.session_id = a.session_id
               WHERE t.status = 'running'
               ORDER BY t.created_at"""
        ).fetchall()
        if not rows:
            print("No tasks currently running.")
        else:
            for row in rows:
                print(f"  Task #{row['id']} ({row['name']}): {row['prompt'][:80]}")
                print(f"    PID {row['pid']} since {row['created_at']}")
```

### history

```python
def cmd_history(db, args):
    agent = get_agent(db, args.name)
    rows = get_task_history(db, agent["session_id"], limit=args.limit)

    if not rows:
        print(f"No task history for agent '{args.name}'.")
        return

    print(f"=== Task history for '{args.name}' (last {args.limit}) ===")
    for row in rows:
        status = row["status"].upper()
        cost_str = f"${row['cost']:.4f}" if row["cost"] else "n/a"
        duration_str = f"{row['duration']:.0f}s" if row["duration"] else "n/a"
        print(f"  #{row['id']} [{status}] {cost_str} {duration_str}")
        print(f"    {row['prompt'][:100]}")
        if row["summary"]:
            print(f"    Result: {row['summary'][:150]}")
        print()
```

### delete-agent

```python
def cmd_delete_agent(db, args):
    agent = get_agent(db, args.name)
    session_id = agent["session_id"]

    # Reject if agent is busy
    running = get_running_task(db, session_id)
    if running:
        raise BridgeError(
            f"Cannot delete agent '{args.name}' -- it has a running task (#{running['id']}). "
            f"Kill it first: bridge-cli kill {args.name}"
        )

    # Remove agent .md file
    agent_file = agent["agent_file"]
    if os.path.exists(agent_file):
        os.remove(agent_file)

    # Remove database records (tasks first due to FK)
    db.execute("DELETE FROM tasks WHERE session_id = ?", (session_id,))
    db.execute("DELETE FROM agents WHERE session_id = ?", (session_id,))
    db.commit()

    # Note: workspace directory is NOT deleted (preserves history on disk)

    print(f"Agent '{args.name}' deleted.")
    print(f"  Removed: {agent_file}")
    print(f"  Workspace preserved: ~/.claude-bridge/workspaces/{session_id}/")
```

---

## Appendix B: Complete Command Flow Summary

```
create-agent:  validate --> generate .md --> claude -p init --> workspace --> SQLite
delete-agent:  validate --> rm .md file --> delete SQLite rows (keep workspace)
dispatch:      validate --> busy check --> insert task --> Popen --> store PID
list-agents:   SELECT * FROM agents --> format + print
status:        lookup agent --> check running task --> check PID alive
kill:          lookup running task --> SIGTERM --> mark killed --> set idle
history:       lookup agent --> SELECT tasks ORDER BY created_at DESC
memory:        lookup agent --> encode path --> read MEMORY.md --> print
```
