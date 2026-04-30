# Bridge MCP Architecture

## Overview

Bridge MCP is the messaging backbone of Claude Bridge. It replaces direct Telegram MCP plugin usage and shell-out bridge-cli commands with a single MCP server that handles:
- Inbound message polling + reliable delivery
- Outbound message sending (replies + notifications)
- Bridge operations as MCP tools (dispatch, status, agents)

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Code Session                   │
│                      (Bridge Bot)                        │
│                                                          │
│  CLAUDE.md: routing rules, intent mapping, onboarding    │
│                                                          │
│  Uses MCP tools:                                         │
│    bridge_get_messages()   → read inbound                │
│    bridge_acknowledge(id)  → confirm processed           │
│    bridge_reply(chat, msg) → send to user                │
│    bridge_dispatch(agent, prompt) → dispatch task         │
│    bridge_status()         → check agents/tasks          │
│    bridge_agents()         → list agents                 │
│    bridge_history(agent)   → task history                 │
└──────────────────────┬──────────────────────────────────┘
                       │ stdio (MCP protocol)
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   Bridge MCP Server                      │
│                  (Python, long-running)                   │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐   │
│  │  Telegram    │  │   Message    │  │   Bridge      │   │
│  │  Poller      │  │   Queue      │  │   Operations  │   │
│  │  (thread)    │  │   (SQLite)   │  │   (DB access) │   │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘   │
│         │                 │                   │           │
│         │  inbound_messages                   │           │
│         │  outbound_messages    bridge.db ←───┘           │
│         │         │                                       │
│  ┌──────▼─────────▼──────────────────────────────────┐   │
│  │                    SQLite                          │   │
│  │  messages.db: inbound, outbound, delivery state    │   │
│  │  bridge.db:   agents, tasks, teams, notifications  │   │
│  └────────────────────────────────────────────────────┘   │
└──────────┬───────────────────────────────────────────────┘
           │ HTTPS (Bot API)
           │
┌──────────▼──────────┐         ┌──────────────────────┐
│   Telegram Bot API   │         │    on_complete.py     │
│                      │         │    (Stop hook)        │
│   getUpdates (poll)  │         │                       │
│   sendMessage        │         │  writes to SQLite:    │
└──────────────────────┘         │  - task status        │
                                 │  - outbound_messages  │
                                 └──────────────────────┘
```

## Components

### 1. Telegram Poller (Thread)

Long-running thread inside the Bridge MCP server process.

```
while running:
    updates = getUpdates(offset, timeout=30)  # long poll
    for update in updates:
        insert into inbound_messages (pending)
        offset = update.id + 1
    deliver_pending_messages()
    send_pending_outbound()
```

**Polling details:**
- Uses Telegram Bot API `getUpdates` with long polling (timeout=30s)
- Stores `offset` in SQLite to survive restarts
- Only polls from one place — no conflict with other sessions
- Extracts: chat_id, user_id, message_text, message_id

**Outbound sending:**
- Reads `outbound_messages WHERE status='pending'`
- Sends via `sendMessage` Bot API
- Marks as `sent` or `failed`
- Retries failed messages (max 3 attempts)

### 2. Message Queue (SQLite)

Separate `messages.db` to avoid write contention with `bridge.db`.

```sql
-- Inbound: messages from users
CREATE TABLE inbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'telegram',
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT,
    message_text TEXT NOT NULL,
    message_id TEXT,
    status TEXT DEFAULT 'pending',
    -- pending: waiting for Claude Code to read
    -- delivered: Claude Code read it (bridge_get_messages returned it)
    -- acknowledged: Claude Code confirmed processing (bridge_acknowledge called)
    -- failed: delivery failed after max retries
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP,
    acknowledged_at TIMESTAMP
);

-- Outbound: messages to users (replies + notifications)
CREATE TABLE outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'telegram',
    chat_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    reply_to_message_id TEXT,
    source TEXT DEFAULT 'bot',
    -- bot: reply from Bridge Bot via bridge_reply
    -- notification: from on_complete.py
    -- system: from Bridge MCP itself (errors, retries)
    status TEXT DEFAULT 'pending',
    -- pending: waiting to send
    -- sent: delivered to Telegram
    -- failed: send failed after max retries
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);

-- Poller state
CREATE TABLE poller_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Stores: telegram_offset, last_poll_at
```

### 3. Delivery Engine

Handles reliable delivery of inbound messages to Claude Code.

```
Delivery cycle (runs every 3s in poller thread):

1. SELECT * FROM inbound_messages WHERE status = 'pending'
2. For each message:
   a. If retry_count >= max_retries → mark 'failed', send error to user
   b. Mark status = 'delivered', delivered_at = now
   c. (Claude Code will read via bridge_get_messages)
3. SELECT * FROM inbound_messages WHERE status = 'delivered'
   AND delivered_at < now - 3s AND acknowledged_at IS NULL
4. For each unacknowledged:
   a. Increment retry_count
   b. Reset status = 'pending' (will be re-delivered next cycle)
```

**Why 3s timeout:** Claude Code reads messages via `bridge_get_messages` tool. If it reads but doesn't call `bridge_acknowledge` within 3s, the message is retried. This handles cases where Claude Code is busy or the tool call was interrupted.

### 4. MCP Tools

#### Inbound Tools

**`bridge_get_messages`**
```json
{
  "name": "bridge_get_messages",
  "description": "Get pending inbound messages from users",
  "input": {},
  "output": {
    "messages": [
      {
        "id": 1,
        "chat_id": "8137063402",
        "user_id": "8137063402",
        "username": "hieutran",
        "text": "dispatch backend add pagination",
        "platform": "telegram",
        "created_at": "2026-03-28T16:00:00"
      }
    ]
  }
}
```

**`bridge_acknowledge`**
```json
{
  "name": "bridge_acknowledge",
  "description": "Acknowledge that a message was processed",
  "input": { "message_id": 1 }
}
```

#### Outbound Tools

**`bridge_reply`**
```json
{
  "name": "bridge_reply",
  "description": "Reply to a user message",
  "input": {
    "chat_id": "8137063402",
    "text": "Task #18 dispatched to backend",
    "reply_to_message_id": "optional"
  }
}
```

#### Bridge Operations Tools

These replace shell-out `PYTHONPATH=... python3 -m claude_bridge.cli` commands.

**`bridge_dispatch`**
```json
{
  "name": "bridge_dispatch",
  "description": "Dispatch a task to an agent",
  "input": {
    "agent": "backend",
    "prompt": "add pagination to /users endpoint",
    "model": "optional"
  }
}
```

**`bridge_status`**
```json
{
  "name": "bridge_status",
  "description": "Get status of running tasks",
  "input": { "agent": "optional" }
}
```

**`bridge_agents`**
```json
{
  "name": "bridge_agents",
  "description": "List all registered agents"
}
```

**`bridge_create_agent`**
```json
{
  "name": "bridge_create_agent",
  "description": "Create a new agent",
  "input": {
    "name": "backend",
    "path": "/Users/me/projects/my-api",
    "purpose": "API development",
    "model": "sonnet"
  }
}
```

**`bridge_history`**
```json
{
  "name": "bridge_history",
  "description": "Get task history for an agent",
  "input": { "agent": "backend", "limit": 10 }
}
```

**`bridge_kill`**
```json
{
  "name": "bridge_kill",
  "description": "Kill a running task",
  "input": { "agent": "backend" }
}
```

**`bridge_get_notifications`**
```json
{
  "name": "bridge_get_notifications",
  "description": "Get pending task completion notifications",
  "output": {
    "notifications": [
      {
        "task_id": 18,
        "agent": "backend",
        "status": "done",
        "summary": "Added pagination...",
        "cost": 0.04
      }
    ]
  }
}
```

### 5. on_complete.py Integration

Currently `on_complete.py` sends notifications via direct Bot API call (urllib). With Bridge MCP:

```python
# on_complete.py — AFTER Bridge MCP is available
def _send_notification(db, task_id, channel, chat_id, message):
    """Write to outbound_messages. Bridge MCP handles delivery."""
    msg_db = MessageDB()  # messages.db
    msg_db.create_outbound(
        platform=channel,
        chat_id=chat_id,
        message_text=message,
        source="notification",
    )
    msg_db.close()
```

No more direct Bot API calls. Bridge MCP is the single point for all Telegram communication.

## Process Lifecycle

```
User runs:
  cd ~/projects/bridge-bot
  claude --dangerously-skip-permissions

Claude Code starts:
  1. Reads .mcp.json → starts Bridge MCP server (stdio)
  2. Bridge MCP starts Telegram poller thread
  3. Bridge MCP starts delivery engine
  4. Reads CLAUDE.md → knows how to use bridge_* tools

User sends Telegram message:
  1. Poller receives via getUpdates
  2. Stored in inbound_messages (pending)
  3. Claude Code calls bridge_get_messages → gets the message
  4. Claude Code processes (dispatch, status, etc.)
  5. Claude Code calls bridge_acknowledge(id)
  6. Claude Code calls bridge_reply(chat_id, response)
  7. Bridge MCP sends reply via Bot API

Agent completes task:
  1. on_complete.py fires (Stop hook)
  2. Updates bridge.db (task status, cost)
  3. Writes to messages.db outbound_messages
  4. Bridge MCP poller picks up outbound → sends to Telegram
  5. Next time Claude Code calls bridge_get_notifications → sees it

Claude Code session ends:
  1. Bridge MCP server receives EOF on stdio
  2. Poller thread stops
  3. Undelivered messages stay in SQLite
  4. Next session start → picks up where it left off
```

## .mcp.json Configuration

```json
{
  "mcpServers": {
    "bridge": {
      "type": "stdio",
      "command": "/opt/homebrew/bin/python3",
      "args": ["-m", "claude_bridge.mcp_server"],
      "env": {
        "PYTHONPATH": "/path/to/claude-bridge/src",
        "TELEGRAM_BOT_TOKEN": "your-token",
        "BRIDGE_DB_PATH": "~/.claude-bridge/bridge.db",
        "MESSAGES_DB_PATH": "~/.claude-bridge/messages.db"
      }
    }
  }
}
```

## Security

- Bot token stored in .mcp.json env (per-project, not committed)
- Access control via existing `~/.claude/channels/telegram/access.json` allowlist
- Bridge MCP validates chat_id against allowlist before processing inbound
- No unauthenticated messages processed

## Migration Path

1. Build Bridge MCP with all tools
2. Update Bridge Bot CLAUDE.md to use bridge_* tools
3. Keep shell-out CLAUDE.md as fallback
4. Remove direct Bot API calls from on_complete.py and watcher.py
5. Remove Telegram MCP plugin dependency (--channels flag no longer needed)
6. Bridge Bot starts with just: `claude --dangerously-skip-permissions`
