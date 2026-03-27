# Channels Specification

## Overview

**One Telegram channel, one Bridge Bot.** The Bridge Bot is the only Claude Code session with a Telegram MCP channel. It receives all user commands and dispatches tasks to agent sessions via `claude -p`.

Agents do NOT have their own channels. They are headless `claude -p` processes.

---

## 1. Architecture

### 1.1 Single Channel Design

```
┌─────────────────────────┐
│  Telegram (1 channel)   │
└────────────┬────────────┘
             │ MCP (stdio)
             ▼
┌─────────────────────────┐
│  Bridge Bot             │  ← The ONLY session with Telegram
│  (Claude Code #0)       │
│                         │
│  Responsibilities:      │
│  - Parse user commands  │
│  - Dispatch to agents   │
│  - Report completions   │
│  - Handle permissions   │
└─────────────────────────┘
             │
             │ claude -p --session-id ...
             ▼
     ┌───────────────┐
     │ Agent sessions │  ← No channels, headless
     │ (claude -p)    │
     └───────────────┘
```

**Key difference from previous design:** Agents don't poll Telegram. Only the Bridge Bot does.

---

## 2. Bridge Bot Channel

### 2.1 MCP Configuration

The Bridge Bot runs as a Claude Code session with Telegram MCP:

```bash
claude --channel telegram
```

Or configured in `.claude/settings.json`:
```json
{
  "channels": ["telegram"]
}
```

The Telegram MCP plugin handles:
- Polling Telegram Bot API (outbound, no webhooks)
- Sending messages back to user
- Inline keyboard buttons (for permissions)

### 2.2 Configuration

```yaml
# ~/.claude-bridge/config.yaml
telegram:
  bot_token: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

  # Who can control the Bridge Bot
  admin_users: [987654321]
  allowed_users: [987654321, 111111111]

  # Polling
  poll_interval_seconds: 2
  timeout_seconds: 30
```

---

## 3. Command Routing

### 3.1 User Commands

All commands go through the Bridge Bot:

```
/create-agent <name> <path> [description]   → Register agent
/delete-agent <name>                         → Remove agent
/agents                                      → List agents + status

/task <agent> <prompt>                       → Dispatch task
/status [agent]                              → Check running tasks
/kill <agent>                                → Kill running task
/history <agent> [n]                         → Last n task results
```

### 3.2 Command Parsing

The Bridge Bot parses incoming Telegram messages:

```python
def parse_command(text: str) -> Command:
    """
    Parse Telegram message into command.

    Examples:
        "/task api-backend add pagination"
        → Command(action="task", agent="api-backend", args="add pagination")

        "/agents"
        → Command(action="agents", agent=None, args=None)

        "fix the login bug on api-backend"
        → Command(action="task", agent="api-backend", args="fix the login bug")
          (natural language parsing, infer agent from context)
    """
    pass
```

### 3.3 Response Flow

```
User sends: /task api-backend add pagination
                    │
Bridge Bot receives via MCP
                    │
                    ├─→ Parse command
                    ├─→ Validate agent exists
                    ├─→ Dispatch task (claude -p ...)
                    ├─→ Reply: "✓ Task #42 dispatched to api-backend"
                    │
                    ... (task runs in background) ...
                    │
Watcher detects completion
                    │
Bridge Bot sends:   "✓ Task #42 (api-backend) done in 2m 15s
                     Added pagination to /users endpoint."
```

---

## 4. Message Formatting

### 4.1 Task Dispatched

```
✓ Task #42 dispatched to api-backend
Prompt: add pagination to /users endpoint
```

### 4.2 Task Completed

```
✓ Task #42 (api-backend) — done in 2m 15s
Added pagination to /users endpoint.
Files changed: src/routes/users.ts, src/utils/paginate.ts
Cost: $0.045
```

### 4.3 Task Failed

```
✗ Task #42 (api-backend) — failed
Error: npm test returned non-zero exit code
Duration: 45s
```

### 4.4 Agent List

```
Agents:
  api-backend   IDLE    /projects/my-api       (3 tasks)
  web-frontend  RUNNING /projects/web   #47    (2m elapsed)
  ml-pipeline   IDLE    /projects/ml           (1 task)
```

### 4.5 Permission Request

```
🔒 Permission needed (api-backend, task #42)

Action: git push origin main
Risk: high

[✅ Approve]  [❌ Deny]
```

---

## 5. Permission Relay

### 5.1 How It Works

When a `claude -p` agent hits a permission prompt, it blocks waiting for input. The Bridge Bot cannot intercept this directly since `claude -p` runs non-interactively.

**Solution for MVP:** Use `--allowedTools` or Claude Code permissions to pre-approve safe actions. Dangerous actions are blocked by default.

```bash
claude -p "task" \
  --session-id agent-api-backend \
  --project-dir /projects/api \
  --allowedTools "Edit,Write,Bash(npm test),Bash(npm run lint)" \
  --output-format json
```

**Solution for Phase 2:** Use Claude Code hooks to relay permission requests:
1. Pre-tool-use hook detects dangerous action
2. Hook script writes request to SQLite
3. Watcher picks up request, sends to Telegram
4. User taps approve/deny
5. Hook script reads response from SQLite
6. Returns exit code (0=allow, 2=deny)

---

## 6. Error Handling

| Error | Recovery |
|---|---|
| Unknown command | Reply with help text |
| Agent not found | "Agent 'xyz' not found. Use /agents to list." |
| Agent busy | "api-backend is busy with task #42. Use /kill to cancel." |
| Telegram API down | Retry with exponential backoff |
| MCP connection lost | Claude Code handles reconnection |

---

## 7. Future Channels

The architecture supports adding Discord/Slack later:
- Same Bridge Bot, different MCP channel plugin
- Command parsing is channel-agnostic
- Only the message formatting layer changes

---

## 8. Success Criteria

Channels complete when:

- [ ] Bridge Bot receives Telegram messages via MCP
- [ ] Commands parsed correctly (create-agent, task, status, etc.)
- [ ] Tasks dispatched to correct agent
- [ ] Completion reports sent to Telegram
- [ ] Agent list displays correctly
- [ ] Permission handling works (at least via pre-approved tools)
- [ ] Error messages helpful and clear
