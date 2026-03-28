# Phase 5: Bridge Channel Server (Push-Based Messaging)

## Overview

Replace the pull-based Python MCP server with a push-based TypeScript channel server. Messages from Telegram arrive as `<channel>` tags in the Claude Code session — no polling needed.

**Key change:** `mcp.notification('notifications/claude/channel', ...)` pushes messages directly into the session, replacing the `bridge_get_messages()` pull model.

**Language:** TypeScript (Bun) — the channel capability (`capabilities.experimental['claude/channel']`) is only supported in the TypeScript MCP SDK.

---

### Milestone 18: TypeScript Channel Skeleton

#### Task 5.1: Project Scaffold
- **Description:** Create `channel/` directory with package.json, server.ts skeleton declaring channel capability, stdio transport.
- **Effort:** 1.5 hours
- **Dependencies:** Bun installed
- **Acceptance Criteria:**
  - [ ] `channel/package.json` with deps: `@modelcontextprotocol/sdk`, `grammy`, `zod`
  - [ ] `channel/server.ts` creates MCP Server with `capabilities.experimental['claude/channel']`
  - [ ] Server connects via StdioServerTransport
  - [ ] `bun install` in `channel/` installs dependencies
  - [ ] `bun channel/server.ts` starts without errors (waits for MCP init on stdin)

#### Task 5.2: Telegram Bot + Push Notifications
- **Description:** Add grammy bot that polls Telegram and pushes messages into Claude Code session via channel notification.
- **Effort:** 2 hours
- **Dependencies:** Task 5.1
- **Acceptance Criteria:**
  - [ ] Bot token from `TELEGRAM_BOT_TOKEN` env var
  - [ ] `bot.on('message:text', ...)` receives messages
  - [ ] Access control: reads `~/.claude/channels/telegram/access.json` allowlist
  - [ ] Non-allowlisted messages rejected (offset still advanced)
  - [ ] Allowed messages pushed: `mcp.notification({method: 'notifications/claude/channel', params: {content, meta: {chat_id, user_id, user, message_id, ts}}})`
  - [ ] Clean shutdown on stdin EOF / SIGINT / SIGTERM
  - [ ] Bot username resolved via `bot.api.getMe()`

#### Task 5.3: Reply Tool
- **Description:** Implement `reply` MCP tool so Claude can send messages back to Telegram.
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.2
- **Acceptance Criteria:**
  - [ ] Tool: `reply(chat_id, text, reply_to?)` → grammy `bot.api.sendMessage()`
  - [ ] Handles Telegram 4096 char limit (chunks if needed)
  - [ ] Returns success/failure
  - [ ] Validates chat_id against allowlist before sending

---

### Milestone 19: Bridge Operation Tools

#### Task 5.4: CLI Subprocess Wrapper
- **Description:** Helper function `bridgeCli(command, args)` that runs `python3 -m claude_bridge.cli` and returns output.
- **Effort:** 1 hour
- **Dependencies:** Task 5.1
- **Acceptance Criteria:**
  - [ ] Runs subprocess with PYTHONPATH set to `BRIDGE_SRC_PATH` env var
  - [ ] Returns stdout as string
  - [ ] Throws on non-zero exit code with stderr message
  - [ ] Timeout: 30s default

#### Task 5.5: Bridge Tools Registration
- **Description:** Register MCP tools: bridge_dispatch, bridge_status, bridge_agents, bridge_history, bridge_kill, bridge_create_agent.
- **Effort:** 2.5 hours
- **Dependencies:** Task 5.4
- **Acceptance Criteria:**
  - [ ] Each tool has proper inputSchema (zod or JSON Schema)
  - [ ] Each tool calls `bridgeCli()` with correct arguments
  - [ ] Returns structured JSON (parsed from CLI output)
  - [ ] Error handling: CLI failures returned as error content

#### Task 5.6: Notification Tool
- **Description:** `bridge_get_notifications` tool that returns unreported task completions.
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.4
- **Acceptance Criteria:**
  - [ ] Calls `bridgeCli('status', ...)` or reads bridge.db directly
  - [ ] Returns unreported completions with task_id, agent, status, summary, cost
  - [ ] Marks as reported after retrieval

---

### Milestone 20: Outbound Delivery

#### Task 5.7: Outbound Message Poller
- **Description:** Background interval that reads pending outbound_messages from messages.db and sends via grammy.
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.2
- **Acceptance Criteria:**
  - [ ] Runs every 2 seconds via setInterval
  - [ ] Reads `outbound_messages WHERE status='pending'` from messages.db
  - [ ] Sends via `bot.api.sendMessage()`
  - [ ] Marks as sent on success, increments retry on failure
  - [ ] Max 3 retries, then marks as failed
  - [ ] Uses bun:sqlite for direct SQLite access (no Python subprocess needed)

#### Task 5.8: Completion Push Notification
- **Description:** When outbound poller sends a notification-source message, also push a `notifications/claude/channel` notification so Claude sees it in-session.
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.7
- **Acceptance Criteria:**
  - [ ] Outbound messages with `source='notification'` trigger a channel push
  - [ ] Push content: "Task #ID completed" with meta: `{source: 'task_completion', task_id}`
  - [ ] Claude session sees `<channel source="bridge" source="task_completion">` tag
  - [ ] Regular bot replies (source='bot') do NOT trigger a push (avoid echo loop)

---

### Milestone 21: CLAUDE.md + Setup

#### Task 5.9: Channel-Mode CLAUDE.md Template
- **Description:** New template in `bridge_bot_claude_md.py` for channel mode. Messages arrive as `<channel>` tags, no polling loop.
- **Effort:** 2 hours
- **Dependencies:** M18-M20 (channel server working)
- **Acceptance Criteria:**
  - [ ] Instructions say: messages arrive as `<channel source="bridge" chat_id="..." ...>` tags
  - [ ] Reply using `reply(chat_id, text)` tool
  - [ ] No `bridge_get_messages` or `bridge_acknowledge` references
  - [ ] Still check `bridge_get_notifications()` after processing (for completions that arrived before channel push)
  - [ ] Intent mapping, onboarding, error handling preserved
  - [ ] `generate_bridge_bot_claude_md(mode='channel')` produces this template

#### Task 5.10: Setup Command Update
- **Description:** `setup-bot` generates .mcp.json pointing to `bun channel/server.ts` and prints correct startup command.
- **Effort:** 2 hours
- **Dependencies:** Task 5.9
- **Acceptance Criteria:**
  - [ ] .mcp.json: `command: "bun"`, `args: ["run", "<path>/channel/server.ts"]`
  - [ ] .mcp.json: env includes TELEGRAM_BOT_TOKEN, BRIDGE_SRC_PATH, MESSAGES_DB_PATH
  - [ ] Prints: `claude --channels server:bridge --dangerously-skip-permissions`
  - [ ] Detects if bun is installed, warns if not
  - [ ] `setup-bot --mode shell` falls back to Python MCP server

---

### Milestone 22: Migration + Cleanup

#### Task 5.11: Deprecate Python MCP Server
- **Description:** Mark Python MCP modules as deprecated. Keep for backward compat but not default.
- **Effort:** 1 hour
- **Dependencies:** M21
- **Acceptance Criteria:**
  - [ ] `mcp_server.py` header: "DEPRECATED — use channel/server.ts instead"
  - [ ] `setup-bot` defaults to channel mode
  - [ ] `setup-bot --mode python` still generates old config

#### Task 5.12: Update Documentation
- **Description:** Update architecture docs and README for channel-based architecture.
- **Effort:** 1.5 hours
- **Dependencies:** M21
- **Acceptance Criteria:**
  - [ ] `plan/architecture/high-level-architecture.md` updated with channel flow
  - [ ] `plan/architecture/bridge-mcp.md` → `bridge-channel.md` (or rewritten)
  - [ ] README: setup uses `setup-bot`, startup uses `--channels server:bridge`
  - [ ] README: no reference to Python MCP server as primary

#### Task 5.13: End-to-End Test
- **Description:** Full test: Telegram message → channel tag → dispatch → complete → notification pushed.
- **Effort:** 1.5 hours
- **Dependencies:** M21
- **Acceptance Criteria:**
  - [ ] Manual: send Telegram message, verify `<channel>` tag in Claude session
  - [ ] Manual: Claude calls reply tool, verify message in Telegram
  - [ ] Manual: dispatch task, complete, verify notification pushed to session
  - [ ] Automated: mock grammy bot, verify notification format

---

## Summary

| Milestone | Tasks | Effort | Description |
|-----------|-------|--------|-------------|
| M18 | 5.1-5.3 | 5h | TypeScript channel skeleton + Telegram + reply |
| M19 | 5.4-5.6 | 5h | Bridge CLI wrapper + operation tools |
| M20 | 5.7-5.8 | 3h | Outbound delivery + completion push |
| M21 | 5.9-5.10 | 4h | CLAUDE.md channel template + setup command |
| M22 | 5.11-5.13 | 4h | Deprecation + docs + E2E test |

**Total: 13 tasks, ~21 hours**

## Dependencies

```
M18 (channel skeleton) → M19 (bridge tools) → M20 (outbound)
                                                    ↓
                                              M21 (CLAUDE.md + setup)
                                                    ↓
                                              M22 (migration + docs)
```
