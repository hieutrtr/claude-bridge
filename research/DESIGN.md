# Claude Bridge — System Design

> Control Claude Code agents from Telegram, Discord, Slack. Profiles evolve intelligently over time.

---

## 1. Vision

**Problem:** Claude Code is powerful on desktop, but you can't dispatch work from mobile. You need to SSH home, or copy-paste tasks manually.

**Solution:** Bridge is a lightweight daemon that:
1. Spawns Claude Code agents on your machine
2. Accepts tasks from Telegram/Discord/Slack
3. Generates context (CLAUDE.md) automatically based on project + profile
4. Relays permission requests back to your phone
5. Learns and evolves profiles over time

**Result:** "Fix the login bug" → agent completes → context automatically refined for next task.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ User Phone (Telegram/Discord/Slack)                         │
│ /spawn coder --project ~/my-app                             │
│ "Fix the login bug"                                         │
│ Approve permission request ✓                                │
└────────────────────────┬────────────────────────────────────┘
                         │ (MCP Channel)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Bridge Daemon (on your machine)                              │
├─────────────────────────────────────────────────────────────┤
│ • Agent Lifecycle Manager                                   │
│ • Profile Manager                                           │
│ • CLAUDE.md Generator                                       │
│ • Enhancement Accumulator                                   │
│ • Permission Relay Handler                                  │
└────┬────────────────┬───────────────────┬──────────────────┘
     │                │                   │
     ▼                ▼                   ▼
┌─────────────┐ ┌──────────────┐  ┌──────────────┐
│ Agent 1     │ │ Agent 2      │  │ Agent 3      │
│ (claude     │ │ (claude      │  │ (claude      │
│  --project) │ │  --project)  │  │  --project)  │
└─────────────┘ └──────────────┘  └──────────────┘

Each agent:
- Runs in tmux for persistence
- Reads its own profile.yaml
- Reads generated CLAUDE.md
- Reports back to Bridge
```

---

## 3. Core Entities

### 3.1 Profile (Configuration)

**Location:** `~/.claude-bridge/agents/{agent-name}/profile.yaml`

**Purpose:** Single source of truth. Bridge reads this → generates everything else.

**Schema:**
```yaml
# Metadata
name: coder-my-app
version: 1
created: 2026-03-26
last_enhanced: 2026-03-26
base_template: coder-fullstack

# Identity
identity:
  role: coder
  display_name: "Senior Full-stack Developer"
  project: ~/projects/my-app

# Context
context:
  stack: [nextjs, typescript, prisma, react-query]

  key_files:
    - path: prisma/schema.prisma
      reason: "DB schema — agent refers often"
    - path: src/auth/session.ts
      reason: "Auth bugs tend to be here"
    - path: src/payments/**
      sensitive: true
      reason: "Payment processing — confirm before edit"

# Rules
rules:
  hard:
    - "No push to main without PR"
    - "Confirm before touching /payments"

  soft:
    - text: "Use Zod not Joi"
      learned_from: task_005
      confidence: high
    - text: "React Query not SWR"
      learned_from: task_007
      confidence: high

# Plugins/Extensions
plugins:
  - name: typescript-linter
    source: marketplace
  - name: custom-reviewer
    source: github/myorg/claude-reviewer
  - name: local-plugin
    source: ./plugins/custom-helper

# Skills (slash commands)
skills: [review, test, commit, explain]

# Hook Configuration
hooks:
  pre_tool_use:
    bash:
      - block_pattern: "rm -rf"
      - block_pattern: "git push --force"
      - relay_permission: "prisma migrate"

  post_tool_use:
    write:
      - run: "npx eslint --fix {file}"
        async: true

  stop:
    - check_tests_written: true

# Reporting
reporting:
  channel: telegram
  style: summary
  on_complete:
    include: [summary, files_changed, test_results]
  on_error:
    include: [error_message, what_was_tried, suggested_fix]
```

### 3.2 CLAUDE.md (Generated Context)

**Location:** Multiple layers
- `{project}/CLAUDE.md` — project-wide rules, stack, general context
- `{project}/src/auth/CLAUDE.md` — auth-specific rules, context files
- `{project}/src/payments/CLAUDE.md` — payment-specific rules, constraints

**Purpose:** Agent reads this to understand project conventions, rules, critical files.

**Generated from:** Profile.yaml + project analysis

**Example output:**
```markdown
# Agent: coder-my-app

## 🎭 Role
Senior Full-stack Developer for ~/projects/my-app
Stack: Next.js, TypeScript, Prisma, React Query

## 📁 Project Structure
- `src/auth/` — Authentication (see CLAUDE.md in this dir)
- `src/api/` — API endpoints
- `src/payments/` — ⚠️ SENSITIVE (confirm before edit)

## 📎 Key Files to Know
- `prisma/schema.prisma` — DB schema
- `src/auth/session.ts` — Auth bugs tend to happen here
- `docs/payment-flow.md` — Payment processing logic

## 🔒 Hard Rules — NEVER BREAK
1. No push to main without PR
2. Confirm before touching /payments

## 📐 Conventions (Learned)
- Use Zod not Joi for validation
- React Query not SWR
- Always run npm test after changes

## 📣 Reporting
- On complete: summary + files changed + test results
- On permission needed: action + risk + file preview
- On error: what failed + what was tried + suggested fix
```

### 3.3 Enhancement Accumulator

**Location:** `~/.claude-bridge/agents/{agent-name}/enhancement-accumulator.yaml`

**Purpose:** Collect signals during work. When threshold hit, propose enhancements.

**Signal Types:**
- `user_corrected` — User had to fix/correct agent's work
- `agent_asked` — Agent repeatedly asked about something
- `hook_blocked` — Hook blocked dangerous action
- `pattern_detected` — Agent's repeated behavior observed
- `files_touched` — Files agent frequently edits
- `task_pattern` — Similar tasks keep coming up

**Threshold:** 5+ signals of the **same type** → trigger enhancement proposal

**Example:**
```yaml
signals:
  user_corrected:
    - task_001: "User corrected validation approach"
    - task_003: "User fixed API error handling"
    - task_005: "User changed from Joi to Zod"
    - task_007: "User corrected state management"
    - task_009: "User switched to React Query"

  # 5 user_corrected signals → Enhancement triggered!
  # Proposed: Add "Use Zod" + "Use React Query" as soft rules

  agent_asked:
    - task_002: "What's the payment flow?"
    - task_004: "How do I handle webhooks?"
    - task_006: "What's in .env?"
    - task_008: "Where's the auth logic?"
    # 4 agent_asked → almost there, accumulate more
```

---

## 4. Agent Lifecycle

### 4.1 Spawn Agent

**User command (on Telegram):**
```
/spawn coder --project ~/my-app
```

**Bridge flow:**
1. Create agent directory: `~/.claude-bridge/agents/coder-my-app/`
2. Create empty profile.yaml with minimal data
3. Analyze project (detect stack, key dirs)
4. Generate initial CLAUDE.md
5. Initialize enhancement-accumulator.yaml
6. Return: "Agent ready! Send me a task."

### 4.2 Onboarding (Optional, for customization)

**User command:**
```
/new-agent
```

**3-question flow:**
```
Q1: Project path? ~/my-app
Q2: Agent role? [Coder] [Researcher] [Reviewer] [DevOps]
Q3: Critical rule? (e.g., "No push to main without PR")
```

**Result:** Customized profile.yaml instead of defaults.

### 4.3 Task Execution

**User sends task:**
```
"Fix the login bug in auth module"
```

**Bridge flow:**
1. Load agent's profile.yaml
2. Check if persistent session exists (in tmux)
3. If not, spawn new Claude Code process:
   ```bash
   claude --project ~/my-app \
          --print \
          -p "System prompt from profile + CLAUDE.md..." \
          --channels telegram
   ```
4. Pipe task to agent's stdin
5. Monitor stdout → relay to Telegram
6. If permission needed → send inline keyboard to user
7. On completion:
   - Collect what agent did (files changed, commands run)
   - Log signals for enhancement accumulator
   - Return summary to Telegram

### 4.4 Persistent Session (Optional)

**User starts persistent conversation:**
```
/attach coder-my-app
```

**Bridge flow:**
1. Check if tmux session exists → attach
2. If not → spawn new Claude Code in tmux
3. Keep session alive
4. User can send multiple messages without re-spawning
5. Context preserved across messages (up to compaction limit)

---

## 5. Profile Enhancement Flow

### 5.1 Accumulation Phase

**During task execution:**
- User corrects agent → signal: `user_corrected`
- Agent asks "How do I...?" → signal: `agent_asked`
- Hook blocks `rm -rf` → signal: `hook_blocked` (validates rule)
- Agent edits files repeatedly → signal: `pattern_detected`

**All signals logged to enhancement-accumulator.yaml**

### 5.2 Enhancement Trigger

**Automatic:**
- If any signal type accumulates 5+ signals → propose enhancement

**Manual:**
- User: `/enhance` → show all accumulated signals → propose changes

### 5.3 Enhancement Proposal

**Bridge shows:**
```
Found enhancements:

🔴 user_corrected (5 signals):
   • "Use Zod not Joi" — suggested in 5 tasks
   • "Always run npm test" — user did this 5 times

🟡 agent_asked (4 signals):
   • "What's the payment flow?" — agent asked 4 times
   • "Where's auth logic?" — agent asked 3 times

[✅ Apply All] [👁️ Review Each] [❌ Skip]
```

### 5.4 User Decision

**User reviews** → can approve all at once or pick & choose

**Result:**
- Update profile.yaml (add soft rules, critical files, etc.)
- Regenerate CLAUDE.md
- Clear accumulator signals that were applied
- Keep signals that user rejected

---

## 6. Plugin System

**Declared in profile.yaml:**
```yaml
plugins:
  - name: typescript-linter
    source: marketplace          # Claude Code marketplace
  - name: custom-reviewer
    source: github/myorg/repo    # GitHub repo
  - name: local-plugin
    source: ./plugins/helper     # Local file
```

**Installation:**
- Bridge tells Claude Code which plugins to install
- Claude Code handles installation (TBD: how exactly via MCP?)
- Plugins available as commands in agent's skills

---

## 7. Hook System

**Hooks = hardcoded rules** that prevent mistakes, relay permissions, sync dev docs.

**Hook types:**
- `SessionStart` — Load profile, CLAUDE.md, dev docs
- `PreToolUse[Bash]` — Block dangerous patterns
- `PostToolUse[Write]` — Run linter/formatter
- `Stop` — Validate task completion
- `PreCompact` — Update dev docs before context compaction

**Permission relay:**
- Hook blocks action (e.g., `prisma migrate`)
- Bridge sends Telegram message with inline keyboard
- User taps ✅ or ❌
- Bridge returns exit code to hook
- Agent continues or stops

---

## 8. Project Structure

```
claude-bridge/
├── claude_bridge/
│   ├── daemon/
│   │   ├── agent_manager.py       # Spawn/kill/monitor agents
│   │   ├── profile_manager.py     # Load/save profiles
│   │   ├── claude_md_generator.py # Generate CLAUDE.md from profile
│   │   ├── enhancement_engine.py  # Accumulate signals, propose changes
│   │   └── permission_relay.py    # Telegram approval handler
│   │
│   ├── channels/
│   │   ├── telegram_channel.py    # Telegram MCP plugin
│   │   ├── discord_channel.py     # (Future)
│   │   └── slack_channel.py       # (Future)
│   │
│   └── cli/
│       ├── commands.py            # /spawn, /new-agent, /enhance
│       └── config.py              # CLI arg parsing
│
├── profiles/
│   └── templates/
│       ├── coder-fullstack.yaml
│       ├── researcher.yaml
│       ├── reviewer.yaml
│       ├── devops.yaml
│       ├── writer.yaml
│       └── analyst.yaml
│
└── docs/
    └── (design docs)
```

---

## 9. Key Data Flows

### Flow 1: Spawn Agent

```
User: /spawn coder --project ~/my-app
  ↓
Bridge: Create ~/.claude-bridge/agents/coder-my-app/
  ↓
Bridge: Analyze project → detect stack
  ↓
Bridge: Create profile.yaml with defaults
  ↓
Bridge: Generate CLAUDE.md at project root
  ↓
Bridge: Initialize enhancement-accumulator.yaml
  ↓
Telegram: "Agent ready!"
```

### Flow 2: Execute Task

```
User: "Fix the login bug"
  ↓
Bridge: Load profile.yaml + CLAUDE.md
  ↓
Bridge: Spawn "claude --project ~/my-app ..."
  ↓
Bridge: Pipe task to agent
  ↓
Agent: Reads CLAUDE.md, executes task
  ↓
Agent: Needs permission (e.g., git push)
  ↓
Hook: PreToolUse intercepts, relays to Bridge
  ↓
Bridge: Sends Telegram with [✅ Approve] [❌ Deny]
  ↓
User: Taps ✅
  ↓
Bridge: Sends exit code 0 to hook
  ↓
Agent: Continues
  ↓
Agent: Task complete
  ↓
Bridge: Collect signals (files changed, corrections made)
  ↓
Bridge: Log to enhancement-accumulator.yaml
  ↓
Bridge: Check if any signal type hit 5+ threshold
  ↓
If yes: Show enhancement proposal to user
If no: Silent (accumulating)
```

### Flow 3: Enhance Profile

```
User: /enhance
  OR automatic trigger (5+ signals of same type)
  ↓
Bridge: Load enhancement-accumulator.yaml
  ↓
Bridge: Analyze signals → generate proposals
  ↓
Telegram: Show enhancement UI with [✅ Apply] [❌ Skip]
  ↓
User: Reviews and approves
  ↓
Bridge: Update profile.yaml
  ↓
Bridge: Regenerate CLAUDE.md (all layers)
  ↓
Bridge: Clear applied signals from accumulator
  ↓
Telegram: "Profile enhanced! Next task?"
```

---

## 10. Success Criteria (MVP)

- [x] Design complete
- [ ] Daemon can spawn Claude Code agents
- [ ] Profile.yaml loads correctly
- [ ] CLAUDE.md generates from profile (single + multi-layer)
- [ ] Telegram channel receives tasks
- [ ] Tasks route to agent, output relayed back
- [ ] Permission relay works (user approves on Telegram)
- [ ] Enhancement accumulator tracks signals
- [ ] Enhancement proposal triggers at 5+ threshold
- [ ] Profile updates work correctly

---

## 11. Future (Phase 2+)

- [ ] Discord + Slack channels
- [ ] Multi-agent coordination (/spawn multiple agents in parallel)
- [ ] Profile templates marketplace
- [ ] Custom plugin upload to Bridge
- [ ] Agent analytics dashboard
- [ ] Task history + replay
