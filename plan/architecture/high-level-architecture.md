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
│   │  /create-agent backend /projects/api "REST API dev"      │     │
│   │  /task backend add pagination to /users                  │     │
│   │  /memory backend                                         │     │
│   │                                                          │     │
│   │  ✓ Task #1 (backend) done in 3m. Added pagination...    │     │
│   └───────────────────────────────────────────────────────────┘     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             │ Telegram Bot API (outbound polling)
                             │
┌────────────────────────────┼────────────────────────────────────────┐
│                    YOUR MAC                                         │
│                             │                                       │
│                             ▼                                       │
│   ┌─────────────────────────────────────────────┐                  │
│   │         BRIDGE BOT (Session #0)              │                  │
│   │                                              │                  │
│   │  Claude Code + Telegram MCP Channel          │                  │
│   │  ┌────────────────────────────────────────┐  │                  │
│   │  │  CLAUDE.md (command routing rules)     │  │                  │
│   │  │  bridge-cli.py (via Bash tool)         │  │                  │
│   │  │  bridge.db (SQLite)                    │  │                  │
│   │  └────────────────────────────────────────┘  │                  │
│   └──────────┬──────────────┬──────────────┬─────┘                  │
│              │              │              │                         │
│              ▼              ▼              ▼                         │
│   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │
│   │  Agent #1    │ │  Agent #2    │ │  Agent #3    │               │
│   │              │ │              │ │              │               │
│   │  backend     │ │  frontend    │ │  devops      │               │
│   │  --my-api    │ │  --my-web    │ │  --infra     │               │
│   │              │ │              │ │              │               │
│   │  worktree ◆  │ │  worktree ◆  │ │  worktree ◆  │               │
│   │  session  ◆  │ │  session  ◆  │ │  session  ◆  │               │
│   │  memory   ◆  │ │  memory   ◆  │ │  memory   ◆  │               │
│   └──────┬───────┘ └──────┬───────┘ └──────┬───────┘               │
│          │                │                │                        │
│          └────────────────┼────────────────┘                        │
│                           │                                         │
│                           ▼                                         │
│                  ┌─────────────────┐                                │
│                  │  Stop Hook      │                                │
│                  │  on-complete.py │                                │
│                  │                 │                                │
│                  │  → SQLite       │                                │
│                  │  → Telegram     │                                │
│                  └─────────────────┘                                │
│                                                                     │
│   ◆ = Native Claude Code feature (zero Bridge code)                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      BRIDGE LAYER                             │
│                   (what we build)                             │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ bridge-cli.py│  │on-complete.py│  │   watcher.py      │  │
│  │              │  │              │  │   (fallback)       │  │
│  │  create      │  │  Stop hook   │  │                   │  │
│  │  dispatch    │  │  handler     │  │  PID check for    │  │
│  │  list/status │  │              │  │  crashed tasks    │  │
│  │  kill        │  │  Updates DB  │  │                   │  │
│  │  history     │  │  Prints      │  │  Cron: */5 * * * │  │
│  │  memory      │  │  report      │  │                   │  │
│  └──────┬───────┘  └──────────────┘  └───────────────────┘  │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    bridge.db (SQLite)                  │   │
│  │                                                       │   │
│  │  agents: name, project_dir, session_id, purpose,     │   │
│  │          state, agent_file                            │   │
│  │                                                       │   │
│  │  tasks:  id, session_id, prompt, status, pid,        │   │
│  │          result_file, cost, duration, reported        │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE LAYER                          │
│                (what we leverage — zero code)                 │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  --agent     │  │  --session-id│  │  isolation:       │  │
│  │              │  │              │  │  worktree         │  │
│  │  .md file    │  │  Persistent  │  │                   │  │
│  │  defines:    │  │  conversation│  │  Each task gets   │  │
│  │  - role      │  │  across all  │  │  isolated git     │  │
│  │  - tools     │  │  tasks       │  │  copy of repo     │  │
│  │  - hooks     │  │              │  │                   │  │
│  │  - model     │  │  Agent       │  │  No concurrent    │  │
│  │  - isolation │  │  remembers   │  │  file corruption  │  │
│  │  - memory    │  │  everything  │  │                   │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  Auto Memory │  │  CLAUDE.md   │  │  Prompt Caching   │  │
│  │              │  │  Hierarchy   │  │                   │  │
│  │  Agent auto- │  │              │  │  90% cost         │  │
│  │  learns:     │  │  Project     │  │  reduction on     │  │
│  │  - patterns  │  │  instructions│  │  repeated context │  │
│  │  - prefs     │  │  survive     │  │                   │  │
│  │  - context   │  │  compaction  │  │  Automatic with   │  │
│  │              │  │              │  │  --session-id     │  │
│  │  Readable    │  │  Init: scan  │  │                   │  │
│  │  via /memory │  │  + purpose   │  │                   │  │
│  └──────────────┘  └──────────────┘  └───────────────────┘  │
│                                                              │
│  ┌──────────────┐  ┌──────────────────────────────────────┐  │
│  │  Stop Hook   │  │  Telegram MCP Channel                │  │
│  │              │  │  (official Anthropic plugin)          │  │
│  │  Fires when  │  │                                      │  │
│  │  agent task  │  │  Outbound polling — no webhooks      │  │
│  │  completes   │  │  Bidirectional messaging              │  │
│  │              │  │  Inline keyboard buttons              │  │
│  │  Calls       │  │  File attachments                    │  │
│  │  on-complete │  │                                      │  │
│  └──────────────┘  └──────────────────────────────────────┘  │
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
                    └──────────┬───────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  Agent .md   │  │  Workspace   │  │  Claude Code │
    │              │  │              │  │  Session     │
    │  Role &      │  │  Task        │  │              │
    │  tools &     │  │  results &   │  │  --session-id│
    │  hooks &     │  │  logs        │  │  Persistent  │
    │  permissions │  │              │  │  context     │
    │              │  │  ~/.claude-  │  │              │
    │  ~/.claude/  │  │  bridge/     │  │  Auto Memory │
    │  agents/     │  │  workspaces/ │  │  ~/.claude/  │
    │              │  │  {session}/  │  │  projects/   │
    └──────────────┘  └──────────────┘  └──────────────┘

    BRIDGE GENERATES    BRIDGE MANAGES     CLAUDE CODE OWNS
```

### Session Combinations

```
┌──────────┬─────────────────┬──────────────────────┐
│  Agent   │  Project        │  Session ID          │
├──────────┼─────────────────┼──────────────────────┤
│ backend  │ /projects/api   │ backend--api         │
│ backend  │ /projects/other │ backend--other       │
│ frontend │ /projects/api   │ frontend--api        │
│ devops   │ /projects/infra │ devops--infra        │
└──────────┴─────────────────┴──────────────────────┘

Each row = independent session with own context, memory, workspace
```

---

## 4. Data Flow

### 4.1 Create Agent

```
Telegram                Bridge Bot              bridge-cli.py          Claude Code
   │                        │                        │                      │
   │  /create-agent         │                        │                      │
   │  backend /path "purpose"                        │                      │
   │───────────────────────▶│                        │                      │
   │                        │  Bash: create-agent    │                      │
   │                        │───────────────────────▶│                      │
   │                        │                        │                      │
   │                        │                        │  1. Validate path    │
   │                        │                        │  2. Derive session   │
   │                        │                        │     ID               │
   │                        │                        │                      │
   │                        │                        │  3. Generate         │
   │                        │                        │     agent .md file   │
   │                        │                        │──────────────────────│
   │                        │                        │     ~/.claude/agents/│
   │                        │                        │                      │
   │                        │                        │  4. CLAUDE.md init   │
   │                        │                        │───────────────────▶  │
   │                        │                        │   claude -p "scan    │
   │                        │                        │   project + inject   │
   │                        │                        │   purpose"           │
   │                        │                        │  ◀───────────────────│
   │                        │                        │   CLAUDE.md written  │
   │                        │                        │                      │
   │                        │                        │  5. Create workspace │
   │                        │                        │  6. Insert SQLite    │
   │                        │                        │                      │
   │                        │  ◀─────────────────────│  Output: "created"   │
   │  ◀────────────────────│  Relay output           │                      │
   │  "Agent created..."   │                        │                      │
```

### 4.2 Dispatch Task

```
Telegram                Bridge Bot              bridge-cli.py          Claude Code
   │                        │                        │                      │
   │  /task backend         │                        │                      │
   │  add pagination        │                        │                      │
   │───────────────────────▶│                        │                      │
   │                        │  Bash: dispatch        │                      │
   │                        │───────────────────────▶│                      │
   │                        │                        │                      │
   │                        │                        │  1. Look up agent    │
   │                        │                        │  2. Check not busy   │
   │                        │                        │  3. Insert task row  │
   │                        │                        │                      │
   │                        │                        │  4. Spawn subprocess │
   │                        │                        │───────────────────▶  │
   │                        │                        │   claude             │
   │                        │                        │     --agent ...      │
   │                        │                        │     --session-id ... │
   │                        │                        │     --worktree ...   │
   │                        │                        │     -p "prompt"      │
   │                        │                        │                      │
   │                        │                        │  5. Store PID        │
   │                        │                        │  6. Update SQLite    │
   │                        │                        │                      │
   │                        │  ◀─────────────────────│  "Task #1 dispatched"│
   │  ◀────────────────────│  Relay                  │                      │
   │  "Task #1 dispatched"  │                        │                      │
   │                        │                        │                      │
   │                        │                        │         ┌────────────│
   │                        │                        │         │ Agent runs │
   │                        │                        │         │ in worktree│
   │                        │                        │         │ with full  │
   │                        │                        │         │ context... │
   │                        │                        │         └────────────│
```

### 4.3 Task Completion

```
Claude Code             on-complete.py           SQLite              Bridge Bot → Telegram
   │                        │                      │                      │
   │  Agent finishes        │                      │                      │
   │  Stop hook fires       │                      │                      │
   │───────────────────────▶│                      │                      │
   │                        │                      │                      │
   │                        │  1. Parse result JSON │                      │
   │                        │  2. Update task       │                      │
   │                        │─────────────────────▶│                      │
   │                        │     status=done       │                      │
   │                        │     summary=...       │                      │
   │                        │     cost=$0.04        │                      │
   │                        │                      │                      │
   │                        │  3. Update agent      │                      │
   │                        │─────────────────────▶│                      │
   │                        │     state=idle        │                      │
   │                        │                      │                      │
   │                        │  4. Print report      │                      │
   │                        │─────────────────────────────────────────────▶│
   │                        │  "✓ Task #1 done..."  │                      │
   │                        │                      │                 ─────▶│
   │                        │                      │           Telegram msg│
```

---

## 5. File System Layout

```
YOUR MAC
│
├── ~/.claude-bridge/                          ◄── BRIDGE HOME
│   ├── CLAUDE.md                              Bridge Bot instructions
│   ├── bridge-cli.py                          CLI dispatcher (250 lines)
│   ├── on-complete.py                         Stop hook handler (30 lines)
│   ├── watcher.py                             Fallback PID checker (50 lines)
│   ├── bridge.db                              SQLite (agents + tasks)
│   ├── config.yaml                            Global config
│   │
│   └── workspaces/                            ◄── PER-SESSION STORAGE
│       ├── backend--my-api/
│       │   ├── metadata.json                  Session creation info
│       │   └── tasks/
│       │       ├── task-1-result.json          Claude JSON output
│       │       ├── task-1-stderr.log           Stderr capture
│       │       └── ...
│       └── frontend--my-web/
│           └── tasks/
│               └── ...
│
├── ~/.claude/                                 ◄── CLAUDE CODE HOME
│   ├── agents/                                Native agent definitions
│   │   ├── bridge--backend--my-api.md         Generated by Bridge
│   │   ├── bridge--frontend--my-web.md        Generated by Bridge
│   │   └── ...
│   │
│   └── projects/                              ◄── AUTO MEMORY (native)
│       ├── <encoded-my-api-path>/
│       │   └── memory/
│       │       ├── MEMORY.md                  Agent's learned knowledge
│       │       ├── api_patterns.md            Topic files
│       │       └── testing.md
│       └── <encoded-my-web-path>/
│           └── memory/
│               └── MEMORY.md
│
└── ~/projects/                                ◄── YOUR PROJECTS
    ├── my-api/
    │   ├── CLAUDE.md                          Generated on create-agent
    │   ├── .claude/worktrees/                 Task worktrees (native)
    │   │   ├── task-1/                        Isolated git copy
    │   │   └── task-2/
    │   └── src/...                            Your code
    │
    └── my-web/
        ├── CLAUDE.md                          Generated on create-agent
        └── src/...
```

### Ownership Boundaries

```
┌─────────────────────────────────────────────────────────┐
│  BRIDGE OWNS              │  CLAUDE CODE OWNS           │
│  (we create & manage)     │  (native, we only read)     │
├───────────────────────────┼─────────────────────────────┤
│  ~/.claude-bridge/*       │  ~/.claude/projects/*/      │
│  bridge.db                │    memory/ (Auto Memory)    │
│  workspaces/              │                             │
│  bridge-cli.py            │  Project worktrees          │
│  on-complete.py           │    .claude/worktrees/       │
│                           │                             │
│  BRIDGE GENERATES         │  CLAUDE CODE GENERATES      │
│  (we write, CC reads)     │  (CC writes, we read)       │
├───────────────────────────┼─────────────────────────────┤
│  ~/.claude/agents/        │  Auto Memory files          │
│    bridge--*.md           │  Session JSONL files        │
│                           │  Worktree contents          │
│  Project CLAUDE.md        │                             │
│    (on create-agent)      │                             │
└───────────────────────────┴─────────────────────────────┘
```

---

## 6. Agent .md File (Native Format)

Bridge generates one per session in `~/.claude/agents/`:

```
┌─────────────────────────────────────────────────────────┐
│  ~/.claude/agents/bridge--backend--my-api.md             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ---                                   ◄── YAML        │
│  name: bridge--backend--my-api             frontmatter  │
│  description: "API dev, REST, DB migrations"            │
│  tools: Read, Edit, Write, Bash, Grep, Glob             │
│  model: sonnet                                          │
│  isolation: worktree              ◄── safe concurrency  │
│  memory: project                  ◄── Auto Memory on    │
│  hooks:                                                 │
│    Stop:                          ◄── completion notify  │
│      - hooks:                                           │
│          - type: command                                │
│            command: "python3 ~/.claude-bridge/           │
│              on-complete.py --session-id backend--my-api"│
│  ---                                                    │
│                                                         │
│  # Agent: backend                      ◄── Markdown     │
│  Project: /Users/hieutran/projects/my-api   body =      │
│  Purpose: API development, REST endpoints   system      │
│                                             prompt      │
│  ## Working Style                                       │
│  - Complete the task fully before stopping              │
│  - Run tests if the project has them                    │
│  - Summarize what you changed when done                 │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 7. CLAUDE.md Init (Purpose-Driven)

When creating an agent, Bridge runs a one-shot Claude Code task to generate CLAUDE.md:

```
┌─────────────────────────────────────────────────────────┐
│  CLAUDE.md INIT PROCESS                                  │
│                                                         │
│  Input:                                                 │
│    project_dir = /projects/my-api                       │
│    purpose = "API development, REST endpoints"          │
│                                                         │
│  Step 1: claude -p scans project                        │
│    ┌────────────────────────────────────────┐           │
│    │  Reads: package.json, tsconfig,       │           │
│    │  Dockerfile, .eslintrc, README,       │           │
│    │  directory structure, test files...   │           │
│    └────────────────────────────────────────┘           │
│                                                         │
│  Step 2: Generates CLAUDE.md with both                  │
│    ┌────────────────────────────────────────┐           │
│    │  PROJECT CONTEXT (from scan)          │           │
│    │  - Overview: Express.js + TS + Prisma │           │
│    │  - Build: npm run build               │           │
│    │  - Test: npm test (Jest + supertest)  │           │
│    │  - Lint: npm run lint (ESLint)        │           │
│    │  - Structure: src/routes, src/models  │           │
│    │  - Conventions: camelCase, Zod valid  │           │
│    │                                        │           │
│    │  AGENT CONTEXT (from purpose)         │           │
│    │  - Purpose: API dev, REST, DB         │           │
│    │  - Focus areas for this agent         │           │
│    └────────────────────────────────────────┘           │
│                                                         │
│  Output: /projects/my-api/CLAUDE.md                     │
│                                                         │
│  If CLAUDE.md already exists:                           │
│    → Append agent context section only                  │
│    → Don't overwrite existing content                   │
└─────────────────────────────────────────────────────────┘
```

---

## 8. Task Lifecycle

```
                    ┌───────────┐
                    │  PENDING  │  Task created in SQLite
                    └─────┬─────┘
                          │ subprocess.Popen spawns claude
                          ▼
                    ┌───────────┐
                    │  RUNNING  │  PID tracked, agent working
                    └─────┬─────┘
                          │
              ┌───────────┼───────────┬───────────┐
              │           │           │           │
              ▼           ▼           ▼           ▼
        ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
        │   DONE   │ │  FAILED  │ │ TIMEOUT │ │  KILLED  │
        │          │ │          │ │         │ │          │
        │ Stop hook│ │ Stop hook│ │ Watcher │ │ /kill    │
        │ fires    │ │ fires    │ │ detects │ │ command  │
        │ result   │ │ is_error │ │ > 30min │ │ SIGTERM  │
        │ parsed   │ │ = true   │ │ kills   │ │          │
        └────┬─────┘ └────┬─────┘ └────┬────┘ └────┬─────┘
             │            │            │            │
             └────────────┴────────────┴────────────┘
                          │
                          ▼
                    ┌───────────┐
                    │ REPORTED  │  Sent to Telegram
                    └───────────┘
```

---

## 9. Completion Detection (Dual Mechanism)

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│  PRIMARY: Stop Hook (immediate)                         │
│  ─────────────────────────────                          │
│  Agent .md frontmatter includes:                        │
│    hooks:                                               │
│      Stop:                                              │
│        - type: command                                  │
│          command: on-complete.py --session-id ...        │
│                                                         │
│  ✓ Fires immediately when task ends                     │
│  ✓ Works for success and failure                        │
│  ✓ No polling needed                                    │
│  ✗ Won't fire if process is SIGKILL'd or crashes hard   │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  FALLBACK: Watcher (cron, every 5 min)                  │
│  ─────────────────────────────────────                  │
│  Catches edge cases:                                    │
│    - Process killed externally (SIGKILL)                │
│    - Hook script fails                                  │
│    - Zombie processes                                   │
│    - Timeout detection (> 30 min)                       │
│                                                         │
│  Logic:                                                 │
│    SELECT * FROM tasks WHERE status = 'running'         │
│    For each: os.kill(pid, 0) → alive?                   │
│    If dead + not updated by hook → mark failed          │
│    If running > 30 min → kill + mark timeout            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 10. Security Model

```
┌─────────────────────────────────────────────────────────┐
│  LAYER 1: Telegram Auth                                  │
│  Only allowed_users can message the bot                  │
│  Configured in Telegram MCP plugin settings              │
├─────────────────────────────────────────────────────────┤
│  LAYER 2: Agent Permissions                              │
│  Each agent .md defines allowed tools:                   │
│    tools: Read, Edit, Write, Bash, Grep, Glob           │
│    disallowedTools: Bash(rm -rf *), Bash(git push -f *)  │
├─────────────────────────────────────────────────────────┤
│  LAYER 3: Worktree Isolation                             │
│  Each task runs in isolated git worktree                 │
│  Changes don't affect main branch until reviewed         │
├─────────────────────────────────────────────────────────┤
│  LAYER 4: Network Security                               │
│  Telegram MCP uses outbound polling only                 │
│  No inbound ports, no webhooks exposed                   │
│  Everything runs locally on your machine                 │
└─────────────────────────────────────────────────────────┘
```

---

## 11. Build vs Leverage Summary

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│  WHAT WE BUILD                    WHAT CLAUDE CODE PROVIDES      │
│  (~425 lines of Python)          (zero Bridge code)              │
│                                                                  │
│  ┌────────────────────┐          ┌────────────────────────────┐  │
│  │  bridge-cli.py     │          │  --agent .md files         │  │
│  │  250 lines         │          │  Identity, tools, hooks,   │  │
│  │                    │          │  model, permissions        │  │
│  │  Agent CRUD        │          ├────────────────────────────┤  │
│  │  CLAUDE.md init    │          │  --session-id              │  │
│  │  .md generation    │          │  Persistent context        │  │
│  │  Task dispatch     │          │  across all tasks          │  │
│  │  Status queries    │          ├────────────────────────────┤  │
│  │  Memory reader     │          │  isolation: worktree       │  │
│  ├────────────────────┤          │  Safe concurrent tasks     │  │
│  │  on-complete.py    │          ├────────────────────────────┤  │
│  │  30 lines          │          │  Auto Memory + AutoDream   │  │
│  │                    │          │  Agent learns patterns     │  │
│  │  Stop hook handler │          │  Readable via /memory      │  │
│  │  SQLite updater    │          ├────────────────────────────┤  │
│  │  Report printer    │          │  Stop hook                 │  │
│  ├────────────────────┤          │  Completion detection      │  │
│  │  watcher.py        │          ├────────────────────────────┤  │
│  │  50 lines          │          │  Prompt caching            │  │
│  │                    │          │  90% cost savings          │  │
│  │  Fallback only     │          ├────────────────────────────┤  │
│  │  Cron: */5 * * *   │          │  Telegram MCP Channel      │  │
│  ├────────────────────┤          │  Official Anthropic plugin │  │
│  │  CLAUDE.md         │          ├────────────────────────────┤  │
│  │  60 lines          │          │  CLAUDE.md hierarchy       │  │
│  │                    │          │  Survives compaction       │  │
│  │  Bridge Bot        │          │  Loaded every session      │  │
│  │  command routing   │          └────────────────────────────┘  │
│  ├────────────────────┤                                          │
│  │  bridge.db schema  │                                          │
│  │  25 lines          │                                          │
│  │                    │                                          │
│  │  SQLite: agents    │                                          │
│  │  + tasks tracking  │                                          │
│  └────────────────────┘                                          │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 12. Phase 2+ Extensions

```
┌──────────────────────────────────────────────────────────┐
│  PHASE 2 (leverage more native features)                  │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Task Queue   │  │ Permission   │  │ Model Routing │  │
│  │              │  │ Relay        │  │               │  │
│  │ Queue tasks  │  │ Hook-based   │  │ Sonnet for    │  │
│  │ when agent   │  │ Telegram     │  │ routine,      │  │
│  │ busy         │  │ approval     │  │ Opus for      │  │
│  │              │  │              │  │ complex       │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  PHASE 3 (native Claude Code features)                   │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Agent Teams  │  │ Multi-Channel│  │ Cost          │  │
│  │              │  │              │  │ Dashboard     │  │
│  │ Coordinate   │  │ Discord,     │  │               │  │
│  │ lead +       │  │ Slack via    │  │ Track spend   │  │
│  │ teammates    │  │ native       │  │ per agent     │  │
│  │ for complex  │  │ Channels     │  │ and project   │  │
│  │ tasks        │  │              │  │               │  │
│  └──────────────┘  └──────────────┘  └───────────────┘  │
└──────────────────────────────────────────────────────────┘
```
