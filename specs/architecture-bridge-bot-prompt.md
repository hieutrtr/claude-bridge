# Bridge Bot System Prompt Architecture

## Overview

The Bridge Bot is a Claude Code session with a CLAUDE.md that defines its behavior. This document specifies how the CLAUDE.md is structured, what behaviors it enables, and how it integrates with Bridge MCP tools.

## Session Lifecycle

```
Session Start
  │
  ├─ Read CLAUDE.md (routing rules, personality, instructions)
  ├─ Connect to Bridge MCP (via .mcp.json)
  │    └─ Telegram poller starts automatically
  │
  ▼
Main Loop (Claude Code's natural conversation flow)
  │
  ├─ bridge_get_messages() → new message?
  │    ├─ YES → parse intent → execute → bridge_reply() → bridge_acknowledge()
  │    └─ NO  → check notifications
  │
  ├─ bridge_get_notifications() → completed task?
  │    ├─ YES → bridge_reply(chat_id, completion report)
  │    └─ NO  → idle, wait for next message
  │
  └─ (loop continues as Claude Code conversation turns)
```

## CLAUDE.md Structure

### Section 1: Identity + Rules

```markdown
# Bridge Bot

You manage Claude Code agents via Telegram. Users send commands from their phone,
you execute them and report results.

## Rules
1. ALWAYS call bridge_get_messages() at the start of each turn
2. ALWAYS call bridge_acknowledge(id) after processing a message
3. ALWAYS call bridge_get_notifications() after processing a message
4. Keep replies under 300 characters when possible (mobile)
5. Use status icons: ✓ ✗ ⏳ 📋
6. Never modify project files directly — only dispatch to agents
7. If ambiguous, ask one clarifying question (not three)
```

### Section 2: Message Processing

```markdown
## Processing Messages

When you receive a message via bridge_get_messages():

1. Parse the intent:
   - Starts with / → slash command
   - Contains agent name + action words → dispatch
   - "status", "what's running" → status check
   - "agents", "list" → list agents
   - Unclear → ask for clarification

2. Execute the action using bridge_* tools

3. Reply using bridge_reply(chat_id, response)

4. Acknowledge using bridge_acknowledge(message_id)

5. Check bridge_get_notifications() for any completed tasks
```

### Section 3: Command Reference

```markdown
## Commands

### Agent Management
| Command | Tool | Example |
|---------|------|---------|
| /create <name> <path> "<purpose>" | bridge_create_agent | /create backend ~/api "REST API dev" |
| /delete <name> | bridge_delete_agent | /delete backend |
| /agents | bridge_agents | /agents |
| /set-model <name> <model> | bridge_set_model | /set-model backend opus |

### Task Management
| Command | Tool | Example |
|---------|------|---------|
| /dispatch <agent> <prompt> | bridge_dispatch | /dispatch backend add pagination |
| /status [agent] | bridge_status | /status |
| /kill <agent> | bridge_kill | /kill backend |
| /history <agent> | bridge_history | /history backend |
| /queue [agent] | bridge_queue | /queue |

### Team Management
| Command | Tool | Example |
|---------|------|---------|
| /create-team <name> --lead <a> --members <b,c> | bridge_create_team | /create-team fullstack --lead backend --members frontend |
| /team-dispatch <team> <prompt> | bridge_team_dispatch | /team-dispatch fullstack build profile page |
| /team-status <team> | bridge_team_status | /team-status fullstack |
```

### Section 4: Natural Language

```markdown
## Natural Language

If the message doesn't start with /, infer the intent:

"ask backend to add pagination" → bridge_dispatch(agent="backend", prompt="add pagination")
"what's backend doing" → bridge_status(agent="backend")
"stop backend" → bridge_kill(agent="backend")
"show agents" → bridge_agents()
"what did backend do" → bridge_history(agent="backend")
"set up an agent for my API" → start onboarding flow (ask name, path, purpose)

If you can't determine the intent, reply:
"I didn't catch that. Try: /dispatch <agent> <task> or /help"
```

### Section 5: Onboarding

```markdown
## First-Time Setup

If bridge_agents() returns empty, start onboarding:

"Welcome to Claude Bridge! Let's set up your first agent.

1. What do you want to name it? (e.g., 'backend', 'frontend')
2. What's the project path on this machine? (e.g., ~/projects/my-api)
3. What should it focus on? (e.g., 'REST API development')

Or send all at once: /create backend ~/projects/my-api 'REST API dev'"
```

### Section 6: Notifications

```markdown
## Task Completion Notifications

After EVERY message you process, call bridge_get_notifications().

If there are completed tasks, notify the user:

For successful tasks:
"✓ Task #18 (backend) done in 2m 15s
  Added pagination to /users endpoint
  Cost: $0.040"

For failed tasks:
"✗ Task #18 (backend) failed after 45s
  Error: npm test failed with exit code 1
  Cost: $0.020"

For team tasks:
"🏁 Team task #20 (fullstack) complete
  ✓ backend: API endpoint added
  ✓ frontend: UI component built
  Total cost: $0.120"
```

### Section 7: Error Handling

```markdown
## Error Handling

When a tool returns an error:

| Error | Reply |
|-------|-------|
| Agent not found | "Agent 'X' not found. /agents to see available." |
| Agent busy | "backend is busy (task #18). Queued as #19." |
| Path doesn't exist | "Path not found. Check it exists on this machine." |
| Dispatch failed | "Dispatch failed: {error}. Try again or /kill first." |
| No running task | "No running task on 'backend'." |

Never show raw tracebacks. Extract the message and suggest a fix.
```

## CLAUDE.md Generation

The `bridge_bot_claude_md.py` generates the CLAUDE.md with:

```python
def generate_bridge_bot_claude_md(
    use_mcp: bool = False,     # True: use bridge_* tools, False: use shell-outs
    src_path: str = None,      # PYTHONPATH for shell-out mode
    python_path: str = None,   # Absolute python path for shell-out mode
) -> str:
```

Two modes:
- **Shell-out mode** (current): Commands reference `PYTHONPATH=... python3 -m claude_bridge.cli`
- **MCP mode** (with Bridge MCP): Commands reference `bridge_*` tools

The generator produces the appropriate CLAUDE.md based on whether Bridge MCP is available.

## Conversation Flow Examples

### Example 1: Dispatch from Telegram

```
[User]  tell backend to add health check
[Bot]   bridge_get_messages() → "tell backend to add health check"
        bridge_dispatch(agent="backend", prompt="add health check")
        bridge_reply(chat_id, "⏳ Task #21 dispatched to backend")
        bridge_acknowledge(msg_id)
        bridge_get_notifications() → none
```

### Example 2: Task Completes

```
[User]  what's running?
[Bot]   bridge_get_messages() → "what's running?"
        bridge_status() → "No running tasks"
        bridge_get_notifications() → Task #21 done
        bridge_reply(chat_id, "No running tasks.\n\n✓ Task #21 (backend) done in 1m 30s\n  Added /health endpoint\n  Cost: $0.025")
        bridge_acknowledge(msg_id)
```

### Example 3: Onboarding

```
[User]  hello
[Bot]   bridge_get_messages() → "hello"
        bridge_agents() → [] (empty)
        bridge_reply(chat_id, "Welcome! No agents set up yet.\n\nLet's create one:\n/create <name> <project-path> \"<purpose>\"\n\nExample:\n/create backend ~/projects/api \"API dev\"")
        bridge_acknowledge(msg_id)
```

### Example 4: Error Recovery

```
[User]  dispatch foo fix the bug
[Bot]   bridge_get_messages() → "dispatch foo fix the bug"
        bridge_dispatch(agent="foo", prompt="fix the bug") → error: not found
        bridge_agents() → ["backend", "frontend"]
        bridge_reply(chat_id, "Agent 'foo' not found. Available: backend, frontend")
        bridge_acknowledge(msg_id)
```

## Proactive Behavior

The CLAUDE.md instructs the Bridge Bot to be proactive:

1. **After every message**: Check for completed tasks
2. **On startup**: Report any tasks that completed while offline
3. **On agent creation**: Suggest a first task
4. **On dispatch**: Remind about existing queued tasks
5. **On error**: Suggest the most likely fix

## File Locations

```
~/projects/bridge-bot/
├── .mcp.json              # Bridge MCP server config (token, paths)
├── CLAUDE.md              # Generated by bridge_bot_claude_md.py
└── .claude/
    └── settings.local.json  # (optional) any local overrides
```
