# Claude Bridge — Architecture

Multi-session Claude Code dispatch from Telegram. Each registered agent maps to a project directory; tasks arrive from Telegram and run as isolated Claude Code subprocesses.

---

## 1. System Overview

```
User (Telegram)
      │
      │ sends message
      ▼
Telegram Bot API ──────────────────────────────────────────────────────────┐
                                                                            │ grammy polling
                                                                            ▼
                                                            Channel Server (server.ts / Bun)
                                                                  │         │
                                            MCP notification      │         │ tracks inbound
                                     notifications/claude/channel │         │ in messages.db
                                                                  ▼         │
                                               Bridge Bot (Claude Code)     │
                                             + --dangerously-load-          │
                                               development-channels         │
                                               server:bridge                │
                                                      │                     │
                                     calls bridge_dispatch tool             │
                                                      │                     │
                                                      ▼                     │
                                                  bridge-cli                │
                                              (Python CLI / cli.py)         │
                                                      │                     │
                                              spawns subprocess             │
                                                      │                     │
                                                      ▼                     │
                                          claude --agent bridge--{id}       │
                                                --session-id {uuid}         │
                                                --output-format json        │
                                                -p "{prompt}"               │
                                                      │                     │
                                            (runs in project dir,           │
                                             isolation: worktree)           │
                                                      │                     │
                                             Stop hook fires                │
                                                      │                     │
                                                      ▼                     │
                                              on_complete.py ──► bridge.db  │
                                              (task status,                 │
                                               queue next,                  │
                                               write outbound) ────────► messages.db
                                                                            │
                                                         processOutbound ◄──┘
                                                         (every 2s)
                                                              │
                                                              │ sendMessage
                                                              ▼
                                                    Telegram Bot API
                                                              │
                                                              ▼
                                                       User (Telegram)
```

**Fallback path:** Cron watcher (`watcher.py`) runs every 5 minutes and catches tasks where the Stop hook didn't fire (process died silently, timeout, etc.).

---

## 2. Components

### 2.1 Channel Server (`channel/server.ts` + `channel/lib.ts`)

**Runtime:** Bun
**Protocol:** MCP server over stdio with Claude Code's `experimental: { "claude/channel": {} }` capability

The channel server is the bridge between Telegram and Claude Code. It runs as a Claude Code channel — started via `claude --dangerously-load-development-channels server:bridge`.

**Responsibilities:**
- Polls Telegram via grammy long-polling
- Tracks every inbound message in `messages.db` (`inbound_tracking` table)
- Pushes messages into the Bridge Bot Claude Code session as `notifications/claude/channel` MCP notifications
- Manages a notification queue to prevent interleaving with in-flight tool responses
- Exposes MCP tools the Bridge Bot calls to act on messages
- Polls `outbound_messages` in `messages.db` every 2s to send task-completion results back to Telegram
- Runs an inbound retry engine — re-pushes unacknowledged messages after 30s, up to 5 retries

**MCP tools exposed:**

| Tool | Purpose |
|------|---------|
| `reply` | Send text to a Telegram chat |
| `bridge_acknowledge` | Mark inbound message as processed (stops retries) |
| `bridge_dispatch` | Dispatch a task to a named agent |
| `bridge_status` | Get running/recent task status |
| `bridge_agents` | List registered agents |
| `bridge_history` | Get task history for an agent |
| `bridge_kill` | Kill a running task |
| `bridge_create_agent` | Register a new agent |
| `bridge_get_notifications` | Poll for task completion updates |
| `bridge_check_messages` | Safety net — pull any pending inbound messages missed by push |

**Config (env vars):**

| Variable | Default | Purpose |
|----------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | required | grammy bot token |
| `BRIDGE_SRC_PATH` / `PYTHONPATH` | `""` | Python src path for bridge-cli invocations |
| `MESSAGES_DB_PATH` | `~/.claude-bridge/messages.db` | Message queue DB |

**Access control:** `~/.claude/channels/telegram/access.json` — `allowFrom: [user_id, ...]`. Empty = allow all.

**Key design detail — notification serialisation:**
When a tool call is in flight, Claude Code cannot receive a concurrent MCP notification (it would corrupt the response stream). The server queues notifications while `toolCallInFlight = true` and flushes them in the `finally` block after each tool handler completes.

---

### 2.2 Python CLI (`src/claude_bridge/cli.py`)

**Entry point:** `bridge-cli` (or `python3 -m claude_bridge.cli`)

The CLI is the command surface for both the channel server (called via `bridgeCli()` in lib.ts) and human operators.

**Subcommands:**

| Command | Purpose |
|---------|---------|
| `create-agent <name> <path> --purpose "..."` | Register agent, write .md file, install Stop hook |
| `delete-agent <name>` | Remove agent and .md file |
| `dispatch <name> <prompt>` | Spawn a task subprocess |
| `list-agents` | Print all agents |
| `status [name]` | Show running/recent tasks |
| `kill <name>` | Kill running task for agent |
| `history <name> [--limit N]` | Task history |
| `memory <name>` | Show Auto Memory for agent |
| `queue [name]` | Show queued tasks |
| `cancel <task_id>` | Cancel a queued task |
| `set-model <name> <model>` | Change agent default model |
| `cost [name] [--period]` | Cost summary |
| `permissions` | List pending permission requests |
| `approve <id>` / `deny <id>` | Respond to permission requests |
| `create-team <name> <lead> [members...]` | Create agent team |

The channel server calls these as subprocesses via `execSync` — not importing Python directly. This keeps the TypeScript/Python boundary clean.

---

### 2.3 Agent Management (`agent_md.py`, `session.py`)

**Session identity:**
```
session_id = "{agent_name}--{project_basename}"

Examples:
  backend  + /projects/my-api   → backend--my-api
  frontend + /projects/my-app   → frontend--my-app
```

Double-dash is the separator; agent names must not contain `--`.

**Agent .md files:**
- Written to: `~/.claude/agents/bridge--{session_id}.md`
- Format: YAML frontmatter + markdown body
- Frontmatter fields: `name`, `description`, `tools`, `model`, `isolation: worktree`, `memory: project`, `hooks` (PreToolUse for permission relay)
- `isolation: worktree` causes Claude Code to run each task in an isolated git worktree (no concurrent write corruption)

**Stop hook:**
- Installed in `{project_dir}/.claude/settings.local.json`
- Fires after each `claude --agent ... -p ...` invocation completes
- Calls `python3 -m claude_bridge.on_complete --session-id {session_id}`
- Note: hooks in agent .md frontmatter do not fire in `--agent -p` mode; must be in project settings

**Workspace layout:**
```
~/.claude-bridge/
  workspaces/
    {session_id}/
      metadata.json         ← agent + project metadata
      tasks/
        task-{id}-result.json   ← claude --output-format json output
        task-{id}-stderr.log    ← stderr capture
```

---

### 2.4 Task Dispatcher (`dispatcher.py`)

Spawns tasks as detached subprocesses:

```python
cmd = [
    "claude",
    "--agent", "bridge--{session_id}",
    "--session-id", "{uuid5}",      # deterministic per task
    "--output-format", "json",
    "--dangerously-skip-permissions",
    "-p", "{prompt}",
]
subprocess.Popen(cmd, cwd=project_dir, start_new_session=True, ...)
```

**Key details:**
- `start_new_session=True` — task runs in its own process group; survives bridge-cli exit
- `--session-id` is a UUIDv5 derived from `session_id:task_id` — deterministic, unique per task
- stdout → `task-{id}-result.json`, stderr → `task-{id}-stderr.log`
- Returns PID, stored in `tasks.pid`

---

### 2.5 Task Completion (`on_complete.py`)

Called by the Claude Code Stop hook after each task finishes.

**Steps:**
1. Find running task for session (by `session_id`)
2. Parse `task-{id}-result.json` (JSON from `--output-format json`)
3. Update task status (`done` / `failed`), cost, duration, turns, summary
4. If sub-task: check if all siblings done → aggregate parent team task
5. Auto-dequeue next queued task if any (serial queue per agent)
6. Update agent state to `idle` (or keep running if next task started)
7. Queue outbound notification to `messages.db` if task came from a channel
8. Mark task as `reported = 1`

---

### 2.6 Cron Watcher (`watcher.py`)

Fallback for tasks whose Stop hook didn't fire (process crash, Claude Code restart, etc.).

**Runs every 5 minutes via cron.**

**Actions per running task:**
- No PID → mark `failed`
- PID dead → parse result file → mark `done` or `failed`
- Timeout (default 30m) → SIGTERM → SIGKILL → mark `timeout`
- Unreported completed tasks → queue outbound notifications

---

### 2.7 Databases

**Two separate SQLite files** (WAL mode, both):

#### `~/.claude-bridge/bridge.db` — Core State

| Table | Purpose |
|-------|---------|
| `agents` | Registered agents (name, project_dir, session_id, model, state) |
| `tasks` | Task records (prompt, status, pid, result, cost, channel info) |
| `permissions` | Pending/approved/denied permission requests |
| `teams` | Agent teams (lead + members) |
| `team_members` | Team membership |
| `notifications` | Legacy notification table (Python-side delivery) |

**Task status lifecycle:** `pending` → `running` → `done` / `failed` / `timeout` / `killed` / `cancelled`
**Task types:** `standard` | `team` (spawned by create-team dispatch)
**Queue:** Tasks can be `queued` (with `position`) when agent is busy; dequeued serially by on_complete

#### `~/.claude-bridge/messages.db` — Message Queue

| Table | Purpose |
|-------|---------|
| `inbound_messages` | Python-side inbound tracking (telegram_poller) |
| `outbound_messages` | Task completion results to send back to Telegram |
| `poller_state` | Telegram polling offset |
| `inbound_tracking` | Channel server inbound tracking (written by Bun) |

**Separation rationale:** Avoids write contention between the Bun channel server polling loop and the Python bridge operations. The channel server writes `inbound_tracking` and reads/writes `outbound_messages` directly; Python writes `outbound_messages` from on_complete and watcher.

---

### 2.8 Notification Flow

When a task completes, the result reaches the user via this chain:

```
on_complete.py
  └─ MessageDB.create_outbound("telegram", chat_id, message, source="notification")
        ↓ writes to messages.db outbound_messages
Channel server processOutbound (every 2s)
  └─ reads pending outbound_messages
  └─ bot.api.sendMessage(chat_id, message)
  └─ marks row "sent"
        ↓
User receives Telegram message
```

---

### 2.9 Permission Relay (`permission_relay.py`)

Agent .md files include PreToolUse hooks for dangerous operations (e.g., `git push`, `rm -rf`):

```
PreToolUse hook → permission_relay.py --session-id {id} --tool Bash --command "..."
  └─ writes permission request to bridge.db
  └─ bridge bot sees it via bridge_status / polling
  └─ user approves/denies via Telegram → approve/deny CLI command
  └─ permission_relay reads response from DB
```

---

### 2.10 Auto Memory (`memory.py`)

Reads Claude Code's native Auto Memory: `~/.claude/projects/{encoded_path}/memory/MEMORY.md`

- Bridge reads Auto Memory; it **never writes** to it
- Exposed via `bridge-cli memory <agent>` and the Bridge Bot's memory command

---

## 3. File System Layout

```
Runtime directories (created at setup):
~/.claude-bridge/
  config.json                   ← bot token, bot-dir, preferences
  bridge.db                     ← SQLite: agents, tasks, permissions, teams
  messages.db                   ← SQLite: inbound/outbound message queue
  workspaces/
    {session_id}/
      metadata.json
      tasks/
        task-{id}-result.json
        task-{id}-stderr.log

~/.claude/
  agents/
    bridge--{session_id}.md     ← Claude Code agent definitions (generated)
  channels/
    telegram/
      access.json               ← allowFrom: [user_id]
  projects/                     ← Claude Code auto-creates; bridge reads only
    {encoded_path}/
      memory/MEMORY.md

{bot_project_dir}/              ← e.g., ~/projects/bridge-bot
  CLAUDE.md                     ← Bridge Bot persona + instructions
  .mcp.json                     ← MCP server config (channel server path + env)
  .claude/
    settings.local.json         ← Stop hook (per project, per agent)

Repo (git clone / installed package):
channel/
  server.ts                     ← Channel server entry point
  lib.ts                        ← Extracted testable functions
  package.json                  ← grammy, @modelcontextprotocol/sdk, zod
  bun.lock

src/claude_bridge/
  __init__.py                   ← version
  cli.py                        ← CLI dispatcher
  db.py                         ← BridgeDB (bridge.db)
  session.py                    ← Session ID derivation, workspace paths
  agent_md.py                   ← Agent .md generator, Stop hook installer
  claude_md_init.py             ← Project CLAUDE.md initializer
  bridge_bot_claude_md.py       ← Bridge Bot CLAUDE.md generator
  dispatcher.py                 ← subprocess.Popen wrapper
  on_complete.py                ← Stop hook handler
  watcher.py                    ← Cron fallback PID watcher
  memory.py                     ← Auto Memory reader
  notify.py                     ← Notification formatting + Telegram send
  message_db.py                 ← MessageDB (messages.db)
  permission_relay.py           ← PreToolUse hook handler
  mcp_server.py                 ← Python MCP server (separate from channel)
  mcp_tools.py                  ← MCP tool implementations
  channel.py                    ← Channel abstraction
  telegram_poller.py            ← Python-side Telegram polling
```

---

## 4. How Claude Code Integration Works

### 4.1 Channel Protocol

The channel server registers with Claude Code via the MCP `experimental: { "claude/channel": {} }` capability. When started with `--dangerously-load-development-channels server:bridge`, Claude Code:

1. Starts `bun channel/server.ts` as a subprocess (connected via stdio MCP)
2. Receives `notifications/claude/channel` messages from it
3. The Bridge Bot session processes these as user messages to respond to
4. The Bridge Bot calls MCP tools (`bridge_dispatch`, `reply`, etc.) exposed by the channel server

### 4.2 Agent Invocation

Tasks run via:
```bash
claude \
  --agent bridge--{session_id} \    # loads ~/.claude/agents/bridge--{session_id}.md
  --session-id {uuid} \             # persistent context for this task
  --output-format json \            # result → stdout as JSON
  --dangerously-skip-permissions \  # bridge manages permissions separately
  -p "{prompt}"                     # non-interactive, single prompt
```

The `isolation: worktree` in agent .md frontmatter causes Claude Code to create a temporary git worktree for each task — concurrent tasks on the same repo don't corrupt each other.

### 4.3 Stop Hook

Defined in `{project_dir}/.claude/settings.local.json`:
```json
{
  "hooks": {
    "Stop": [{ "hooks": [{ "type": "command", "command": "python3 -m claude_bridge.on_complete --session-id {id}" }] }]
  }
}
```

Claude Code fires the Stop hook when the `-p` invocation completes. `on_complete.py` reads the result file, updates the DB, and queues the notification.

---

## 5. Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Python core | Python (stdlib only) | ≥3.11 |
| CLI framework | argparse | stdlib |
| Database | SQLite (WAL) | stdlib |
| Subprocess | subprocess.Popen | stdlib |
| Notifications | urllib.request (Telegram Bot API) | stdlib |
| Channel server | TypeScript + Bun | Bun ≥1.0 |
| Telegram bot | grammy | ^1.21.0 |
| MCP protocol | @modelcontextprotocol/sdk | ^1.0.0 |
| Agent runtime | Claude Code CLI (`claude`) | current |

**No pip dependencies** for the Python core. TypeScript dependencies managed by Bun.

---

## 6. State Machine

### Agent State
```
created → idle → running → idle
                         ↗
          queued task dequeued
```

### Task Status
```
pending → running → done
                  → failed
                  → timeout
                  → killed
queued  → pending (dequeued by on_complete)
        → cancelled
```
