# Bridge MCP Server

## Problem

The current setup relies on the official Telegram MCP plugin for message delivery. This has issues:
- Messages sent while Claude Code is "thinking" may be dropped
- No retry mechanism — if the session doesn't acknowledge, the message is lost
- No control over how inbound messages are queued and delivered
- Polling and delivery are tightly coupled in the plugin

## Solution

Build a Bridge MCP server that sits between Telegram (or any chat platform) and the Claude Code Bridge Bot session. It handles:
1. Inbound message polling from Telegram
2. Reliable delivery to Claude Code via MCP tools/resources
3. Outbound message sending to Telegram
4. Task completion notifications (from on_complete.py)

## Architecture

```
Telegram Bot API
       |
       v
Bridge MCP Server (long-running process)
  - Polls Telegram for new messages
  - Queues inbound messages in SQLite
  - Exposes MCP tools for Claude Code to consume
  - Receives outbound messages via MCP tools
  - Sends replies to Telegram
  - Receives on_complete notifications (HTTP endpoint or SQLite polling)
       |
       v
Claude Code Session (Bridge Bot)
  - Reads inbound messages via MCP resource/tool
  - Processes commands (dispatch, status, etc.)
  - Sends replies via MCP tool
```

## Key Design Decisions

### Message Queue (SQLite)

```sql
CREATE TABLE inbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,          -- telegram, discord, slack
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    message_id TEXT,                 -- platform message ID
    status TEXT DEFAULT 'pending',   -- pending, delivered, acknowledged, failed
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP,
    acknowledged_at TIMESTAMP
);

CREATE TABLE outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    reply_to_message_id TEXT,
    status TEXT DEFAULT 'pending',   -- pending, sent, failed
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);
```

### Delivery with Retry

When a new inbound message arrives:
1. Store in `inbound_messages` with status=`pending`
2. Expose via MCP resource `bridge://messages/pending`
3. Claude Code reads the resource and processes the message
4. Claude Code calls `bridge_acknowledge(message_id)` tool to confirm
5. If not acknowledged within 30s, retry (up to 5 times)
6. After 5 failures, mark as `failed` and notify user: "Message not delivered, please retry"

```
Message arrives → queue (pending)
  → expose via MCP → Claude Code reads
    → acknowledged? → done
    → timeout 30s → retry (up to 5)
      → all retries failed → mark failed, notify user
```

### MCP Tools (exposed to Claude Code)

| Tool | Description |
|------|-------------|
| `bridge_get_messages` | Get pending inbound messages |
| `bridge_acknowledge` | Acknowledge a message was processed |
| `bridge_reply` | Send a reply to a specific chat |
| `bridge_send` | Send a message to any chat_id |
| `bridge_get_notifications` | Get pending task completion notifications |
| `bridge_dispatch` | Dispatch a task (replaces Bash shell-out) |
| `bridge_status` | Get agent/task status (replaces Bash shell-out) |
| `bridge_agents` | List agents (replaces Bash shell-out) |

### MCP Resources (exposed to Claude Code)

| Resource | Description |
|----------|-------------|
| `bridge://messages/pending` | Pending inbound messages |
| `bridge://notifications/pending` | Pending task completion notifications |
| `bridge://agents` | All agents and their status |

### Notification Integration

`on_complete.py` currently sends notifications via urllib (direct Bot API). With Bridge MCP:
- `on_complete.py` writes to `outbound_messages` table instead
- Bridge MCP server picks up pending outbound messages and sends them
- Retry logic applies to outbound messages too
- Single point of message delivery — no more direct Bot API calls from multiple places

### Transport

- **stdio** MCP transport (standard for Claude Code MCP servers)
- Bridge MCP server runs as a child process of Claude Code (via .mcp.json)
- Internal polling thread for Telegram + notification queue
- SQLite for persistence (separate DB or shared with bridge.db)

## Implementation Plan

### Phase 1: Core MCP Server
- MCP server skeleton (stdio transport)
- SQLite message queue
- `bridge_get_messages`, `bridge_acknowledge`, `bridge_reply` tools
- .mcp.json configuration

### Phase 2: Telegram Integration
- Telegram polling thread (Grammy or urllib)
- Inbound message → queue → MCP delivery
- Outbound message → Telegram Bot API
- Retry logic (5 retries, 30s timeout)

### Phase 3: Bridge CLI Tools
- `bridge_dispatch`, `bridge_status`, `bridge_agents` tools
- Replace all PYTHONPATH shell-outs in Bridge Bot CLAUDE.md
- Direct DB access instead of subprocess

### Phase 4: Notification Integration
- `on_complete.py` writes to outbound_messages
- Bridge MCP picks up and delivers
- Remove direct Bot API calls from on_complete.py and watcher.py

## Tech Stack

- Python 3.11+ (stdlib + `mcp` SDK)
- SQLite for message queue
- Telegram Bot API via urllib (no Grammy dependency)
- stdio MCP transport

## Open Questions

1. Should Bridge MCP use the same `bridge.db` or a separate `messages.db`?
2. Should the Telegram polling be in-process (thread) or a separate process?
3. How to handle the Bridge Bot session restarting — reconnect to existing Bridge MCP?
4. Rate limiting for Telegram API (30 messages/second per bot)?
