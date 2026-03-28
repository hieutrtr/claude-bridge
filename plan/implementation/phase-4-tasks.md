# Phase 4: Bridge MCP Server + Bridge Bot System Prompt

## Overview

Two parallel tracks:
- **Track A (M13-M16):** Bridge MCP Server — messaging backbone
- **Track B (M17):** Bridge Bot System Prompt — comprehensive CLAUDE.md

Track A is sequential (each milestone builds on the previous). Track B can start after M14.

---

## Track A: Bridge MCP Server

### Milestone 13: MCP Server Skeleton

#### Task 4.1: MCP Server Bootstrap
- **Description:** Create `mcp_server.py` with stdio transport, server registration, and basic tool scaffolding. Server starts, connects, lists tools.
- **Effort:** 2 hours
- **Dependencies:** None
- **Acceptance Criteria:**
  - [ ] `python3 -m claude_bridge.mcp_server` starts an MCP server on stdio
  - [ ] Server registers with name "bridge"
  - [ ] `list_tools` returns empty tool list (placeholder)
  - [ ] Clean shutdown on EOF/SIGINT
  - [ ] .mcp.json config documented

#### Task 4.2: Message Queue Schema
- **Description:** Create `messages.db` SQLite schema with `inbound_messages`, `outbound_messages`, and `poller_state` tables.
- **Effort:** 1 hour
- **Dependencies:** Task 4.1
- **Acceptance Criteria:**
  - [ ] `MessageDB` class with CRUD operations for inbound/outbound
  - [ ] Separate from `bridge.db` (no write contention)
  - [ ] Status transitions: pending → delivered → acknowledged / failed
  - [ ] WAL mode, foreign keys

#### Task 4.3: Bridge Operation Tools
- **Description:** Implement `bridge_dispatch`, `bridge_status`, `bridge_agents`, `bridge_history`, `bridge_kill`, `bridge_create_agent` as MCP tools. These wrap existing cli.py functions with direct DB access (no subprocess).
- **Effort:** 3 hours
- **Dependencies:** Task 4.1
- **Acceptance Criteria:**
  - [ ] All 6 tools callable via MCP protocol
  - [ ] Return structured JSON (not CLI text output)
  - [ ] Error handling returns MCP error responses
  - [ ] Tests mock MCP transport

---

### Milestone 14: Telegram Integration

#### Task 4.4: Telegram Poller Thread
- **Description:** Background thread in Bridge MCP that polls Telegram `getUpdates` and stores messages in `inbound_messages`.
- **Effort:** 3 hours
- **Dependencies:** Task 4.2
- **Acceptance Criteria:**
  - [ ] Polls with long polling (timeout=30s)
  - [ ] Stores offset in `poller_state` (survives restart)
  - [ ] Extracts: chat_id, user_id, username, text, message_id
  - [ ] Validates chat_id against access.json allowlist
  - [ ] Thread starts on server init, stops on shutdown
  - [ ] Bot token from env var `TELEGRAM_BOT_TOKEN`

#### Task 4.5: Inbound Message Tools
- **Description:** Implement `bridge_get_messages` and `bridge_acknowledge` MCP tools.
- **Effort:** 2 hours
- **Dependencies:** Tasks 4.2, 4.4
- **Acceptance Criteria:**
  - [ ] `bridge_get_messages` returns pending messages, marks as delivered
  - [ ] `bridge_acknowledge(message_id)` marks as acknowledged
  - [ ] Messages not acknowledged within 3s reset to pending
  - [ ] Max 5 retries per message, then mark failed
  - [ ] Failed messages trigger outbound "message not delivered" to user

#### Task 4.6: Outbound Message Tools + Sending
- **Description:** Implement `bridge_reply` and `bridge_send` MCP tools. Poller thread also processes outbound queue.
- **Effort:** 2 hours
- **Dependencies:** Tasks 4.4, 4.5
- **Acceptance Criteria:**
  - [ ] `bridge_reply(chat_id, text)` sends immediately via Bot API
  - [ ] Also queues in outbound_messages for audit trail
  - [ ] Poller thread sends pending outbound messages (from on_complete.py)
  - [ ] Retry: 3 attempts per outbound message
  - [ ] Returns message_id from Telegram on success

---

### Milestone 15: Notification Integration

#### Task 4.7: on_complete.py → Outbound Queue
- **Description:** Modify `on_complete.py` to write to `messages.db outbound_messages` instead of direct Bot API call via urllib.
- **Effort:** 1 hour
- **Dependencies:** Task 4.6
- **Acceptance Criteria:**
  - [ ] `on_complete.py` writes to outbound_messages (source='notification')
  - [ ] Remove direct `send_telegram()` call from on_complete.py
  - [ ] Bridge MCP poller picks up and sends
  - [ ] Watcher.py also writes to outbound queue instead of direct send

#### Task 4.8: Notification Tool
- **Description:** Implement `bridge_get_notifications` MCP tool so Bridge Bot can proactively check for completed tasks.
- **Effort:** 1 hour
- **Dependencies:** Task 4.7
- **Acceptance Criteria:**
  - [ ] Returns unreported task completions from bridge.db
  - [ ] Marks tasks as reported after retrieval
  - [ ] Includes: task_id, agent_name, status, summary, cost, duration

#### Task 4.9: End-to-End Test
- **Description:** Full integration test: send Telegram message → Bridge MCP queues → Claude Code reads → dispatches → agent completes → notification sent.
- **Effort:** 2 hours
- **Dependencies:** Tasks 4.7, 4.8
- **Acceptance Criteria:**
  - [ ] Inbound: mock Telegram → queue → tool read → acknowledge
  - [ ] Outbound: tool reply → queue → mock Telegram send
  - [ ] Notification: mock on_complete → queue → send
  - [ ] Retry: simulate timeout → verify retry → acknowledge
  - [ ] Failed: 5 retries exhausted → user notified

---

### Milestone 16: .mcp.json + Migration

#### Task 4.10: .mcp.json Generator
- **Description:** Update `setup` command to generate `.mcp.json` for Bridge MCP server alongside CLAUDE.md.
- **Effort:** 1 hour
- **Dependencies:** Task 4.9
- **Acceptance Criteria:**
  - [ ] `bridge-cli setup` outputs both CLAUDE.md and .mcp.json
  - [ ] .mcp.json points to `python3 -m claude_bridge.mcp_server`
  - [ ] Includes env: TELEGRAM_BOT_TOKEN, PYTHONPATH, DB paths
  - [ ] Bridge Bot starts with just `claude --dangerously-skip-permissions` (no --channels)

#### Task 4.11: Remove Telegram MCP Plugin Dependency
- **Description:** Update README, CLAUDE.md generator, and docs to use Bridge MCP instead of official Telegram plugin.
- **Effort:** 1 hour
- **Dependencies:** Task 4.10
- **Acceptance Criteria:**
  - [ ] README setup guide uses Bridge MCP (no --channels flag)
  - [ ] CLAUDE.md uses bridge_* tools (no PYTHONPATH shell-outs)
  - [ ] Old shell-out mode still works as fallback
  - [ ] Migration guide for existing setups

---

## Track B: Bridge Bot System Prompt

### Milestone 17: Comprehensive CLAUDE.md

#### Task 4.12: Identity + Core Loop
- **Description:** Rewrite `bridge_bot_claude_md.py` with identity section, core message processing loop, and rules.
- **Effort:** 1.5 hours
- **Dependencies:** M14 (needs bridge_* tools to exist)
- **Acceptance Criteria:**
  - [ ] Identity: concise, mobile-friendly, proactive
  - [ ] Core loop: get messages → parse → execute → reply → check notifications
  - [ ] Rules: always acknowledge, always check notifications, keep short

#### Task 4.13: Intent Mapping + Commands
- **Description:** Add natural language intent recognition and command reference to CLAUDE.md.
- **Effort:** 1.5 hours
- **Dependencies:** Task 4.12
- **Acceptance Criteria:**
  - [ ] 15+ NL patterns mapped to commands
  - [ ] Full command table with tool names
  - [ ] Ambiguity handling: ask one clarifying question

#### Task 4.14: Onboarding Flow
- **Description:** Add first-time user detection and guided agent creation.
- **Effort:** 1 hour
- **Dependencies:** Task 4.12
- **Acceptance Criteria:**
  - [ ] Detect no agents → trigger onboarding
  - [ ] Step-by-step: name → path → purpose
  - [ ] Also support one-shot: `/create backend ~/api "API dev"`

#### Task 4.15: Notification Handling + Error Recovery
- **Description:** Add notification awareness and error recovery patterns.
- **Effort:** 1 hour
- **Dependencies:** Task 4.12
- **Acceptance Criteria:**
  - [ ] After every message: check bridge_get_notifications
  - [ ] Format: ✓/✗ + task_id + agent + summary + cost
  - [ ] Error table: 10+ error → suggestion mappings
  - [ ] Never show raw tracebacks

#### Task 4.16: Two-Mode Generator
- **Description:** Update generator to support both shell-out mode (current) and MCP mode (with Bridge MCP).
- **Effort:** 1 hour
- **Dependencies:** Tasks 4.12-4.15
- **Acceptance Criteria:**
  - [ ] `generate_bridge_bot_claude_md(use_mcp=False)` → shell-out commands
  - [ ] `generate_bridge_bot_claude_md(use_mcp=True)` → bridge_* tools
  - [ ] Auto-detect: if Bridge MCP is configured, use MCP mode

---

## Summary

| Milestone | Track | Tasks | Effort | Description |
|-----------|-------|-------|--------|-------------|
| M13 | A | 4.1-4.3 | 6h | MCP server skeleton + bridge ops tools |
| M14 | A | 4.4-4.6 | 7h | Telegram poller + message tools |
| M15 | A | 4.7-4.9 | 4h | Notification integration + E2E test |
| M16 | A | 4.10-4.11 | 2h | .mcp.json generator + migration |
| M17 | B | 4.12-4.16 | 6h | Comprehensive Bridge Bot CLAUDE.md |

**Total: 25 hours**

## Dependencies

```
M13 (skeleton) → M14 (telegram) → M15 (notifications) → M16 (migration)
                       ↓
                 M17 (system prompt) — can start after M14
```
