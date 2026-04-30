# Phase 4: Bridge MCP Server + Bridge Bot System Prompt

**Goal:** Replace the Telegram MCP plugin dependency with a self-contained Python MCP server. Bridge Bot operates via native MCP tools (`bridge_*`) instead of shell-outs. Full message reliability with retry, acknowledgment, and notification queuing.

**Status:** [ ] Not started

**Estimated effort:** ~25 hours

**Dependencies:** Phase 2 complete; understanding of Claude Code MCP tool protocol

---

## Demo Scenario

After this phase:

```
# No more --dangerously-load-development-channels or Telegram MCP plugin
# Bridge Bot starts with just:
claude --dangerously-skip-permissions

# Bridge Bot .mcp.json points to Bridge MCP server (Python)
# All bridge operations via MCP tools, not subprocess shell-outs

# Message reliability:
[Telegram user sends message]
  → Python MCP server polls, stores in messages.db (inbound_messages)
  → Bridge Bot calls bridge_get_messages() → receives messages
  → Bridge Bot calls bridge_acknowledge(msg_id) → stops retries
  → Bridge Bot calls bridge_dispatch("backend", "add feature")
  → Claude Code agent runs
  → on_complete.py writes to outbound_messages
  → MCP poller sends result to Telegram
  → Bridge Bot calls bridge_get_notifications() → sees completion
```

---

## Two Parallel Tracks

**Track A (Milestones 13–16):** Bridge MCP Server — the messaging backbone
**Track B (Milestone 17):** Bridge Bot System Prompt — comprehensive CLAUDE.md

Track A is sequential. Track B can start after Milestone 14.

---

## Track A: Bridge MCP Server

### Milestone 13: MCP Server Skeleton

#### Task 4.1: MCP Server Bootstrap
- **Effort:** 2 hours
- **Dependencies:** None
- **Acceptance Criteria:**
  - [ ] `python3 -m claude_bridge.mcp_server` starts an MCP server on stdio
  - [ ] Server registers with name "bridge"
  - [ ] `list_tools` returns placeholder tool list
  - [ ] Clean shutdown on EOF/SIGINT
  - [ ] `.mcp.json` config documented
- **Files:** `src/claude_bridge/mcp_server.py`

#### Task 4.2: Message Queue Schema
- **Effort:** 1 hour
- **Dependencies:** Task 4.1
- **Acceptance Criteria:**
  - [ ] `MessageDB` class with CRUD for inbound/outbound messages
  - [ ] `messages.db` separate from `bridge.db` (no write contention)
  - [ ] Tables: `inbound_messages`, `outbound_messages`, `poller_state`
  - [ ] Status transitions: `pending` → `delivered` → `acknowledged` / `failed`
  - [ ] WAL mode, foreign keys
- **Files:** `src/claude_bridge/message_db.py`

#### Task 4.3: Bridge Operation Tools
- **Effort:** 3 hours
- **Dependencies:** Task 4.1
- **Acceptance Criteria:**
  - [ ] MCP tools: `bridge_dispatch`, `bridge_status`, `bridge_agents`, `bridge_history`, `bridge_kill`, `bridge_create_agent`
  - [ ] Direct DB access (no subprocess calls)
  - [ ] Return structured JSON (not CLI text)
  - [ ] Error handling returns MCP error responses
- **Files:** `src/claude_bridge/mcp_tools.py`

---

### Milestone 14: Telegram Integration

#### Task 4.4: Telegram Poller Thread
- **Effort:** 3 hours
- **Dependencies:** Task 4.2
- **Acceptance Criteria:**
  - [ ] Background thread polls Telegram `getUpdates` (long polling timeout=30s)
  - [ ] Stores offset in `poller_state` (survives restart)
  - [ ] Extracts: `chat_id`, `user_id`, `username`, `text`, `message_id`
  - [ ] Validates `chat_id` against `~/.claude/channels/telegram/access.json`
  - [ ] Thread starts on server init, stops on shutdown
  - [ ] Bot token from `TELEGRAM_BOT_TOKEN` env var
- **Files:** `src/claude_bridge/telegram_poller.py`

#### Task 4.5: Inbound Message Tools
- **Effort:** 2 hours
- **Dependencies:** Tasks 4.2, 4.4
- **Acceptance Criteria:**
  - [ ] `bridge_get_messages` returns pending messages, marks as delivered
  - [ ] `bridge_acknowledge(message_id)` marks as acknowledged
  - [ ] Messages not acknowledged within 3s reset to pending
  - [ ] Max 5 retries per message, then mark failed
  - [ ] Failed messages trigger outbound "message not delivered" to user
- **Files:** `src/claude_bridge/mcp_tools.py`

#### Task 4.6: Outbound Message Tools + Sending
- **Effort:** 2 hours
- **Dependencies:** Tasks 4.4, 4.5
- **Acceptance Criteria:**
  - [ ] `bridge_reply(chat_id, text)` sends immediately via Bot API + queues for audit
  - [ ] Poller thread sends pending outbound messages (from on_complete.py)
  - [ ] Retry: 3 attempts per outbound message
  - [ ] Returns `message_id` from Telegram on success
- **Files:** `src/claude_bridge/mcp_tools.py`, `src/claude_bridge/telegram_poller.py`

---

### Milestone 15: Notification Integration

#### Task 4.7: `on_complete.py` → Outbound Queue
- **Effort:** 1 hour
- **Dependencies:** Task 4.6
- **Acceptance Criteria:**
  - [ ] `on_complete.py` writes to `outbound_messages` instead of direct urllib call
  - [ ] `watcher.py` also writes to outbound queue (not direct send)
  - [ ] Bridge MCP poller picks up and sends
- **Files:** `src/claude_bridge/on_complete.py`, `src/claude_bridge/watcher.py`

#### Task 4.8: `bridge_get_notifications` Tool
- **Effort:** 1 hour
- **Dependencies:** Task 4.7
- **Acceptance Criteria:**
  - [ ] Returns unreported task completions from `bridge.db`
  - [ ] Marks tasks as `reported=1` after retrieval
  - [ ] Includes: task_id, agent_name, status, summary, cost, duration
- **Files:** `src/claude_bridge/mcp_tools.py`

#### Task 4.9: End-to-End Test
- **Effort:** 2 hours
- **Dependencies:** Tasks 4.7, 4.8
- **Acceptance Criteria:**
  - [ ] Inbound: mock Telegram → queue → tool read → acknowledge
  - [ ] Outbound: tool reply → queue → mock Telegram send
  - [ ] Notification: mock on_complete → queue → send
  - [ ] Retry: simulate timeout → verify retry → acknowledge
  - [ ] Failed: 5 retries exhausted → user notified

---

### Milestone 16: `.mcp.json` + Migration

#### Task 4.10: `.mcp.json` Generator
- **Effort:** 1 hour
- **Dependencies:** Task 4.9
- **Acceptance Criteria:**
  - [ ] `claude-bridge setup` generates `.mcp.json` pointing to `python3 -m claude_bridge.mcp_server`
  - [ ] Includes env: `TELEGRAM_BOT_TOKEN`, `PYTHONPATH`, DB paths
  - [ ] Bridge Bot starts with `claude --dangerously-skip-permissions` (no `--channels`)
- **Files:** `src/claude_bridge/cli.py` (setup command)

#### Task 4.11: Remove Telegram MCP Plugin Dependency
- **Effort:** 1 hour
- **Dependencies:** Task 4.10
- **Acceptance Criteria:**
  - [ ] README setup guide uses Bridge MCP (no `--channels` flag)
  - [ ] CLAUDE.md uses `bridge_*` tools (no PYTHONPATH shell-outs)
  - [ ] Old shell-out mode still works as fallback
  - [ ] Migration guide for existing setups

---

## Track B: Bridge Bot System Prompt

### Milestone 17: Comprehensive CLAUDE.md

#### Task 4.12: Identity + Core Loop
- **Effort:** 1.5 hours
- **Dependencies:** Milestone 14 (bridge_* tools must exist)
- **Acceptance Criteria:**
  - [ ] Identity: concise, mobile-friendly, proactive
  - [ ] Core loop: get messages → parse → execute → reply → check notifications
  - [ ] Rules: always acknowledge, always check notifications, keep short
- **Files:** `src/claude_bridge/bridge_bot_claude_md.py`

#### Task 4.13: Intent Mapping + Commands
- **Effort:** 1.5 hours
- **Acceptance Criteria:**
  - [ ] 15+ NL patterns mapped to commands
  - [ ] Full command table with MCP tool names
  - [ ] Ambiguity handling: ask one clarifying question

#### Task 4.14: Onboarding Flow
- **Effort:** 1 hour
- **Acceptance Criteria:**
  - [ ] Detect no agents → trigger onboarding
  - [ ] Step-by-step: name → path → purpose
  - [ ] Also support one-shot: `/create backend ~/api "API dev"`

#### Task 4.15: Notification Handling + Error Recovery
- **Effort:** 1 hour
- **Acceptance Criteria:**
  - [ ] After every message: call `bridge_get_notifications()`
  - [ ] Format: `✓/✗ + task_id + agent + summary + cost`
  - [ ] Error table: 10+ error → suggestion mappings
  - [ ] Never show raw tracebacks

#### Task 4.16: Two-Mode Generator
- **Effort:** 1 hour
- **Acceptance Criteria:**
  - [ ] `generate_bridge_bot_claude_md(use_mcp=False)` → shell-out commands
  - [ ] `generate_bridge_bot_claude_md(use_mcp=True)` → bridge_* tools
  - [ ] Auto-detect: if Bridge MCP configured, use MCP mode

---

## Summary

| Milestone | Track | Tasks | Effort |
|-----------|-------|-------|--------|
| M13 — MCP skeleton | A | 4.1–4.3 | 6 h |
| M14 — Telegram integration | A | 4.4–4.6 | 7 h |
| M15 — Notification integration | A | 4.7–4.9 | 4 h |
| M16 — .mcp.json + migration | A | 4.10–4.11 | 2 h |
| M17 — Bridge Bot CLAUDE.md | B | 4.12–4.16 | 6 h |
| **Total** | | **16 tasks** | **~25 h** |

## Dependency Graph

```
M13 (skeleton) → M14 (telegram) → M15 (notifications) → M16 (migration)
                       ↓
                 M17 (system prompt) — can start after M14
```
