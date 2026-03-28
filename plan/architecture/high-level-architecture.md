# Claude Bridge — High-Level Architecture

> Multi-session Claude Code dispatch from Telegram.
> Built on top of Claude Code native features, not around them.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        YOUR PHONE                                   │
│                                                                     │
│   Telegram App                                                      │
│   ┌───────────────────────────────────────────────────────────┐     │
│   │  /create backend ~/projects/api "REST API dev"           │     │
│   │  dispatch backend add pagination to /users               │     │
│   │  what's running?                                         │     │
│   │                                                          │     │
│   │  ✓ Task #18 (backend) done in 3m — $0.040               │     │
│   └───────────────────────────────────────────────────────────┘     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Telegram Bot API
                             │
┌────────────────────────────┼────────────────────────────────────────┐
│                    YOUR MAC                                         │
│                             │                                       │
│                             ▼                                       │
│   ┌─────────────────────────────────────────────┐                  │
│   │            BRIDGE MCP SERVER                 │                  │
│   │         (Python, long-running)               │                  │
│   │                                              │                  │
│   │  ┌──────────┐  ┌──────────┐  ┌──────────┐   │                  │
│   │  │ Telegram  │  │ Message  │  │ Bridge   │   │                  │
│   │  │ Poller    │  │ Queue    │  │ Ops      │   │                  │
│   │  │ (thread)  │  │ (SQLite) │  │ (tools)  │   │                  │
│   │  └──────────┘  └──────────┘  └──────────┘   │                  │
│   └──────────────────────┬───────────────────────┘                  │
│                          │ stdio (MCP protocol)                     │
│                          │                                          │
│   ┌──────────────────────▼──────────────────────┐                  │
│   │         BRIDGE BOT (Claude Code Session)     │                  │
│   │                                              │                  │
│   │  CLAUDE.md: intent mapping, onboarding,      │                  │
│   │            notifications, error recovery      │                  │
│   │                                              │                  │
│   │  Uses bridge_* MCP tools:                    │                  │
│   │    bridge_get_messages()                      │                  │
│   │    bridge_dispatch(agent, prompt)             │                  │
│   │    bridge_reply(chat_id, text)                │                  │
│   │    bridge_status()                            │                  │
│   └──────────┬──────────────┬──────────────┬─────┘                  │
│              │              │              │                         │
│              ▼              ▼              ▼                         │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │
│   │  Agent #1    │ │  Agent #2    │ │  Agent #3    │               │
│   │  backend     │ │  frontend    │ │  devops      │               │
│   │  --my-api    │ │  --my-web    │ │  --infra     │               │
│   │  worktree ◆  │ │  worktree ◆  │ │  worktree ◆  │               │
│   │  session  ◆  │ │  session  ◆  │ │  session  ◆  │               │
│   │  memory   ◆  │ │  memory   ◆  │ │  memory   ◆  │               │
│   └──────┬───────┘ └──────┬───────┘ └──────┬───────┘               │
│          │                │                │                        │
│          └────────────────┼────────────────┘                        │
│                           │                                         │
│                           ▼                                         │
│                  ┌──────────────────┐                               │
│                  │  Stop Hook       │                               │
│                  │  on_complete.py  │                               │
│                  │                  │                               │
│                  │  → SQLite        │                               │
│                  │  → outbound_msg  │─── Bridge MCP sends to       │
│                  │    queue         │    Telegram                   │
│                  └──────────────────┘                               │
│                                                                     │
│   ◆ = Native Claude Code feature (zero Bridge code)                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      BRIDGE MCP LAYER                         │
│                    (messaging backbone)                        │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Telegram      │  │ Message      │  │ MCP Tools         │  │
│  │ Poller        │  │ Queue        │  │                   │  │
│  │               │  │              │  │ bridge_get_msgs   │  │
│  │ getUpdates    │  │ inbound_msgs │  │ bridge_acknowledge│  │
│  │ sendMessage   │  │ outbound_msgs│  │ bridge_reply      │  │
│  │               │  │              │  │ bridge_dispatch   │  │
│  │ Retry: 3x     │  │ Retry: 5x   │  │ bridge_status     │  │
│  │ per outbound  │  │ per inbound  │  │ bridge_agents     │  │
│  │               │  │ (3s timeout) │  │ bridge_history    │  │
│  └───────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  messages.db (separate from bridge.db)                       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                      BRIDGE CORE LAYER                        │
│                     (what we've built)                        │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ cli.py       │  │on_complete.py│  │   watcher.py      │  │
│  │              │  │              │  │   (cron: 1 min)    │  │
│  │  create      │  │  Stop hook   │  │                   │  │
│  │  dispatch    │  │  handler     │  │  Dead PID cleanup  │  │
│  │  list/status │  │              │  │  Timeout (30 min)  │  │
│  │  kill        │  │  Updates DB  │  │  Retry notifs      │  │
│  │  history     │  │  Queues      │  │                   │  │
│  │  teams       │  │  notification│  │                   │  │
│  │  cost        │  │              │  │                   │  │
│  └──────┬───────┘  └──────────────┘  └───────────────────┘  │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    bridge.db (SQLite)                  │   │
│  │                                                       │   │
│  │  agents: name, project_dir, session_id, purpose,     │   │
│  │          state, model, total_tasks                    │   │
│  │                                                       │   │
│  │  tasks:  id, session_id, prompt, status, pid,        │   │
│  │          result_file, cost, duration, channel,        │   │
│  │          channel_chat_id, task_type, parent_task_id   │   │
│  │                                                       │   │
│  │  teams:  name, lead_agent + team_members              │   │
│  │                                                       │   │
│  │  notifications: task_id, channel, chat_id, status     │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE LAYER                          │
│                (what we leverage — zero code)                 │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  --agent     │  │  --session-id│  │  isolation:       │  │
│  │  .md file    │  │  UUID per    │  │  worktree         │  │
│  │  defines:    │  │  task (not   │  │                   │  │
│  │  - role      │  │  per agent)  │  │  Each task gets   │  │
│  │  - tools     │  │              │  │  isolated git     │  │
│  │  - model     │  │  Agent       │  │  copy of repo     │  │
│  │  - isolation │  │  context     │  │                   │  │
│  │  - memory    │  │  carries     │  │                   │  │
│  │              │  │  forward     │  │                   │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  Auto Memory │  │  CLAUDE.md   │  │  Prompt Caching   │  │
│  │              │  │  Hierarchy   │  │                   │  │
│  │  Agent auto- │  │              │  │  90% cost         │  │
│  │  learns      │  │  Project     │  │  reduction        │  │
│  │  patterns    │  │  instructions│  │                   │  │
│  │              │  │  survive     │  │  Automatic with   │  │
│  │  Readable    │  │  compaction  │  │  --session-id     │  │
│  │  via /memory │  │              │  │                   │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────┐                                            │
│  │  Stop Hook   │  NOTE: Hooks must be in project's          │
│  │              │  .claude/settings.local.json, NOT in        │
│  │  Fires when  │  agent .md frontmatter (frontmatter        │
│  │  agent task  │  hooks don't fire in --agent -p mode)      │
│  │  completes   │                                            │
│  └──────────────┘                                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Session Model

A session is the fundamental unit. It is always the pairing of an **agent role** and a **project**.

```
                    ┌──────────────────────────────────────┐
                    │           SESSION IDENTITY            │
                    │                                      │
                    │   Agent Name ──┐                     │
                    │                ├──→ session_id       │
                    │   Project Path ┘    "backend--my-api"│
                    │                                      │
                    │   Each task gets unique UUID:         │
                    │   uuid5(session_id + task_id)        │
                    └──────────┬───────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  Agent .md   │  │  Workspace   │  │  Stop Hook   │
    │              │  │              │  │              │
    │  Role &      │  │  Task        │  │  Project's   │
    │  tools &     │  │  results &   │  │  .claude/    │
    │  model       │  │  logs        │  │  settings    │
    │              │  │              │  │  .local.json │
    │  ~/.claude/  │  │  ~/.claude-  │  │              │
    │  agents/     │  │  bridge/     │  │  Installed   │
    │              │  │  workspaces/ │  │  per project │
    └──────────────┘  └──────────────┘  └──────────────┘

    BRIDGE GENERATES    BRIDGE MANAGES     BRIDGE INSTALLS
```

---

## 4. Data Flow

### 4.1 Inbound Message (with Bridge MCP)

```
Telegram          Bridge MCP              Bridge Bot           bridge-cli
   │                   │                      │                    │
   │  "dispatch        │                      │                    │
   │   backend         │                      │                    │
   │   add pagination" │                      │                    │
   │──────────────────▶│                      │                    │
   │                   │                      │                    │
   │                   │  Store in            │                    │
   │                   │  inbound_messages    │                    │
   │                   │  (status=pending)    │                    │
   │                   │                      │                    │
   │                   │  bridge_get_messages()                    │
   │                   │◀─────────────────────│                    │
   │                   │──────────────────────▶ msg returned       │
   │                   │                      │                    │
   │                   │                      │ parse intent       │
   │                   │                      │ "dispatch backend  │
   │                   │                      │  add pagination"   │
   │                   │                      │                    │
   │                   │  bridge_dispatch(                         │
   │                   │    agent="backend",  │                    │
   │                   │    prompt="add..")   │                    │
   │                   │◀─────────────────────│                    │
   │                   │                      │                    │
   │                   │                      ├───────────────────▶│
   │                   │                      │  dispatch backend  │
   │                   │                      │  "add pagination"  │
   │                   │                      │◀───────────────────│
   │                   │                      │  Task #18 PID 123  │
   │                   │                      │                    │
   │                   │  bridge_reply(chat_id,                    │
   │                   │    "⏳ Task #18...")  │                    │
   │                   │◀─────────────────────│                    │
   │◀──────────────────│  sendMessage         │                    │
   │  "⏳ Task #18     │                      │                    │
   │   dispatched"     │                      │                    │
   │                   │                      │                    │
   │                   │  bridge_acknowledge(msg_id)               │
   │                   │◀─────────────────────│                    │
   │                   │  mark acknowledged   │                    │
```

### 4.2 Task Completion

```
Claude Code         on_complete.py      messages.db         Bridge MCP       Telegram
   │                     │                   │                   │               │
   │  Agent finishes     │                   │                   │               │
   │  Stop hook fires    │                   │                   │               │
   │────────────────────▶│                   │                   │               │
   │                     │                   │                   │               │
   │                     │ 1. Parse result   │                   │               │
   │                     │ 2. Update         │                   │               │
   │                     │    bridge.db      │                   │               │
   │                     │    (task=done)    │                   │               │
   │                     │                   │                   │               │
   │                     │ 3. Queue outbound │                   │               │
   │                     │──────────────────▶│                   │               │
   │                     │  INSERT outbound  │                   │               │
   │                     │  (notification)   │                   │               │
   │                     │                   │                   │               │
   │                     │                   │  poller reads     │               │
   │                     │                   │◀──────────────────│               │
   │                     │                   │                   │               │
   │                     │                   │                   │──────────────▶│
   │                     │                   │                   │  sendMessage  │
   │                     │                   │                   │               │
   │                     │                   │                   │  "✓ Task #18  │
   │                     │                   │                   │   done $0.04" │
```

### 4.3 Delivery Retry (Inbound)

```
Bridge MCP                              Claude Code
   │                                        │
   │  Msg queued (pending)                  │
   │                                        │
   │  ── Attempt 1 ──                       │
   │  bridge_get_messages → delivered       │
   │─────────────────────────────────────▶  │ (busy processing)
   │                                        │
   │  ... 3s timeout, no acknowledge ...    │
   │                                        │
   │  ── Attempt 2 ──                       │
   │  Reset to pending, redeliver           │
   │─────────────────────────────────────▶  │
   │                                        │
   │  bridge_acknowledge(id)                │
   │◀───────────────────────────────────────│
   │  ✓ Done                                │
   │                                        │
   │  (max 5 retries, then mark failed      │
   │   and notify user "message lost")      │
```

---

## 5. File System Layout

```
YOUR MAC
│
├── ~/.claude-bridge/                          ◄── BRIDGE HOME
│   ├── bridge.db                              SQLite (agents, tasks, teams, notifs)
│   ├── messages.db                            SQLite (inbound, outbound messages)
│   ├── config.json                            Bot token, settings
│   ├── watcher.log                            Cron watcher output
│   │
│   └── workspaces/                            ◄── PER-SESSION STORAGE
│       ├── backend--my-api/
│       │   └── tasks/
│       │       ├── task-1-result.json
│       │       └── task-1-stderr.log
│       └── frontend--my-web/
│           └── tasks/
│
├── ~/.claude/                                 ◄── CLAUDE CODE HOME
│   ├── agents/                                Agent definitions
│   │   ├── bridge--backend--my-api.md         Generated by Bridge
│   │   └── bridge--frontend--my-web.md
│   │
│   ├── channels/telegram/                     Telegram access control
│   │   └── access.json                        allowlist (user IDs)
│   │
│   └── projects/                              ◄── AUTO MEMORY (native)
│       └── <encoded-path>/
│           └── memory/
│               └── MEMORY.md
│
├── ~/projects/bridge-bot/                     ◄── BRIDGE BOT PROJECT
│   ├── .mcp.json                              Bridge MCP server config
│   └── CLAUDE.md                              Generated routing rules
│
├── ~/projects/claude-bridge/                  ◄── BRIDGE SOURCE
│   └── src/claude_bridge/
│       ├── cli.py                             CLI (all commands)
│       ├── db.py                              SQLite ops
│       ├── dispatcher.py                      Task spawner
│       ├── on_complete.py                     Stop hook handler
│       ├── notify.py                          Notification delivery
│       ├── channel.py                         Multi-channel formatting
│       ├── watcher.py                         Cron fallback
│       ├── mcp_server.py                      Bridge MCP server (new)
│       ├── agent_md.py                        Agent .md generator
│       ├── session.py                         Session model
│       └── bridge_bot_claude_md.py            CLAUDE.md generator
│
└── ~/projects/my-api/                         ◄── USER PROJECT
    ├── CLAUDE.md                              Generated on agent create
    └── .claude/
        └── settings.local.json               Stop hook installed here
```

### Ownership Boundaries

```
┌─────────────────────────────────────────────────────────┐
│  BRIDGE OWNS              │  CLAUDE CODE OWNS           │
│  (we create & manage)     │  (native, we only read)     │
├───────────────────────────┼─────────────────────────────┤
│  ~/.claude-bridge/*       │  ~/.claude/projects/*/      │
│  bridge.db, messages.db   │    memory/ (Auto Memory)    │
│  workspaces/              │                             │
│  config.json              │  Project worktrees          │
│                           │    .claude/worktrees/       │
│  BRIDGE GENERATES         │                             │
│  (we write, CC reads)     │  CLAUDE CODE GENERATES      │
├───────────────────────────┤  (CC writes, we read)       │
│  ~/.claude/agents/        ├─────────────────────────────┤
│    bridge--*.md           │  Auto Memory files          │
│                           │  Session JSONL files        │
│  Project CLAUDE.md        │  Worktree contents          │
│  .claude/settings.local   │                             │
│    .json (Stop hook)      │                             │
└───────────────────────────┴─────────────────────────────┘
```

---

## 6. Stop Hook (Critical Detail)

**Hooks in agent .md frontmatter DO NOT fire in `--agent -p` mode.**

Stop hooks must be in the project's `.claude/settings.local.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "PYTHONPATH=/path/to/src /opt/homebrew/bin/python3 -m claude_bridge.on_complete --session-id backend--my-api"
          }
        ]
      }
    ]
  }
}
```

Key requirements:
- **Absolute python path** — cron/hooks may use system Python 3.9, need 3.11+
- **Nested format** — `{hooks: [{hooks: [{type, command}]}]}` (not flat)
- **Installed per project** — `install_stop_hook(project_dir, session_id)` on agent creation
- **`from __future__ import annotations`** in all modules for Python 3.9 compat

---

## 7. Task Lifecycle

```
                    ┌───────────┐
                    │  PENDING  │  Task created in SQLite
                    └─────┬─────┘
                          │ Popen: claude --agent --session-id -p
                          ▼
                    ┌───────────┐
                  ┌─│  RUNNING  │  PID tracked, agent working
                  │ └─────┬─────┘
                  │       │
                  │ ┌─────┼───────────┬───────────┐
                  │ │     │           │           │
                  │ ▼     ▼           ▼           ▼
                  │┌────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
                  ││  DONE  │ │  FAILED  │ │ TIMEOUT │ │  KILLED  │
                  ││        │ │          │ │         │ │          │
                  ││Stop    │ │Stop hook │ │Watcher  │ │/kill cmd │
                  ││hook    │ │+ is_error│ │> 30 min │ │SIGTERM   │
                  │└───┬────┘ └────┬─────┘ └────┬────┘ └────┬─────┘
                  │    │           │            │            │
 Agent busy?      │    └───────────┴────────────┴────────────┘
 Queue instead ───┘                │
                          ┌────────▼─────────┐
   ┌───────────┐          │  NOTIFICATION    │
   │  QUEUED   │          │  → outbound_msgs │
   │           │          │  → Telegram      │
   │ position  │          └──────────────────┘
   │ tracked   │
   │ auto-     │
   │ dequeue   │
   └───────────┘
```

---

## 8. Notification Flow (Dual Path)

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  PATH 1: Stop Hook (immediate)                          │
│  ──────────────────────────────                         │
│  Agent finishes → settings.local.json hook fires        │
│  → on_complete.py                                       │
│    → updates bridge.db (task=done, cost, summary)       │
│    → queues outbound notification (messages.db)         │
│    → marks task as reported                             │
│                                                         │
│  Bridge MCP poller picks up outbound → sends Telegram   │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  PATH 2: Watcher (cron, every 1 minute)                 │
│  ──────────────────────────────────────                  │
│  Catches when Stop hook fails:                          │
│    - Process crashed (SIGKILL)                          │
│    - Hook script errored                                │
│    - Timeout (> 30 min → kill)                          │
│                                                         │
│  Also: retries failed notification deliveries           │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  PATH 3: Proactive check (Bridge Bot)                   │
│  ────────────────────────────────────                    │
│  After every user interaction, CLAUDE.md instructs:     │
│    bridge_get_notifications() → report any completions  │
│                                                         │
│  This catches completions even if Telegram send failed  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 9. Agent Teams

```
/create-team fullstack --lead backend --members frontend

┌──────────────────────────────────────────────────────┐
│  TEAM: fullstack                                      │
│                                                       │
│  ┌──────────────────┐                                │
│  │  Lead: backend   │  Receives augmented prompt:    │
│  │                  │  - Original task                │
│  │  Decomposes task │  - Teammate list + purposes     │
│  │  Dispatches to   │  - How to dispatch sub-tasks    │
│  │  teammates       │                                │
│  └────────┬─────────┘                                │
│           │                                           │
│     ┌─────┴─────┐                                    │
│     ▼           ▼                                    │
│  ┌────────┐  ┌────────┐                              │
│  │frontend│  │backend │  Sub-tasks linked via        │
│  │sub-task│  │sub-task│  parent_task_id               │
│  └───┬────┘  └───┬────┘                              │
│      │           │                                    │
│      └─────┬─────┘                                   │
│            ▼                                          │
│  ┌──────────────────┐                                │
│  │  All done?       │  on_complete checks siblings   │
│  │  Aggregate cost  │  Marks parent task done         │
│  │  Merge summaries │  Total cost = sum of all        │
│  └──────────────────┘                                │
└──────────────────────────────────────────────────────┘
```

---

## 10. Security Model

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 1: Telegram Auth                                  │
│  access.json allowlist — only paired user IDs            │
│  Bridge MCP validates chat_id before processing          │
├─────────────────────────────────────────────────────────┤
│  LAYER 2: Agent Permissions                              │
│  --dangerously-skip-permissions for autonomous tasks     │
│  PreToolUse hooks for dangerous commands (git push, rm)  │
├─────────────────────────────────────────────────────────┤
│  LAYER 3: Worktree Isolation                             │
│  Each task runs in isolated git worktree                 │
│  Changes don't affect main branch until reviewed         │
├─────────────────────────────────────────────────────────┤
│  LAYER 4: Network                                        │
│  Telegram: outbound polling only (no webhooks)           │
│  Bot token in config.json (not committed to git)         │
│  Everything runs locally on your machine                 │
└─────────────────────────────────────────────────────────┘
```

---

## 11. Migration Path (Current → Bridge MCP)

```
CURRENT (shell-out mode)              TARGET (Bridge MCP mode)
─────────────────────────              ────────────────────────

Telegram MCP plugin                   Bridge MCP server
  (--channels flag needed)              (started via .mcp.json)

CLAUDE.md with Bash commands          CLAUDE.md with bridge_* tools
  PYTHONPATH=... python3 -m ...         bridge_dispatch(agent, prompt)

on_complete.py → direct Bot API       on_complete.py → outbound queue
                                        Bridge MCP sends to Telegram

watcher.py → direct Bot API           watcher.py → outbound queue

No message retry                      5x retry with 3s timeout

Bridge Bot: claude --channels ...     Bridge Bot: claude
  --dangerously-skip-permissions        --dangerously-skip-permissions
```
