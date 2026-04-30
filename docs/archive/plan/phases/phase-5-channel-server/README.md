# Phase 5: Bridge Channel Server (Push-Based Messaging)

**Goal:** Replace the pull-based Python MCP server with a push-based TypeScript channel server. Messages from Telegram arrive as `<channel>` tags in the Claude Code session — no polling loop needed in the Bridge Bot.

**Status:** [ ] Not started

**Estimated effort:** ~21 hours

**Dependencies:** Phase 4 complete; Bun installed; understanding of Claude Code channel capability

---

## Key Change

The Python MCP server used a **pull model**: Bridge Bot called `bridge_get_messages()` repeatedly to check for new messages.

The channel server uses a **push model**: when a Telegram message arrives, the channel server immediately pushes a `notifications/claude/channel` notification into the Claude Code session. The Bridge Bot reacts instantly — no polling needed.

```
Before (Phase 4):  Bridge Bot → bridge_get_messages() → check → check → check...
After  (Phase 5):  Telegram message → channel server → notification/push → Bridge Bot reacts
```

**Language:** TypeScript (Bun). The channel capability (`capabilities.experimental['claude/channel']`) is only supported in the TypeScript MCP SDK.

---

## Demo Scenario

After this phase:

```
# Start command (new):
cd ~/projects/bridge-bot
claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions

# .mcp.json points to: bun run ~/.claude-bridge/channel/dist/server.js
# TELEGRAM_BOT_TOKEN set in .mcp.json env

# What the Bridge Bot session sees when a Telegram message arrives:
<channel source="bridge" chat_id="123456" user_id="789" user="@hieu" ts="1234567890">
  ask backend to refactor the auth module
</channel>

# Bridge Bot responds by calling:
reply(chat_id="123456", text="Dispatching to backend...")
bridge_dispatch(agent="backend", prompt="refactor the auth module")

# When task completes:
<channel source="bridge" source="task_completion" task_id="42">
  Task #42 completed
</channel>

# Bridge Bot calls reply with the formatted result
```

---

## Milestones & Tasks

### Milestone 18: TypeScript Channel Skeleton

#### Task 5.1: Project Scaffold
- **Effort:** 1.5 hours
- **Dependencies:** Bun installed
- **Acceptance Criteria:**
  - [ ] `channel/package.json` with deps: `@modelcontextprotocol/sdk`, `grammy`, `zod`
  - [ ] `channel/server.ts` creates MCP Server with `capabilities.experimental['claude/channel']`
  - [ ] Server connects via `StdioServerTransport`
  - [ ] `bun install` in `channel/` installs dependencies
  - [ ] `bun channel/server.ts` starts without errors (waits for MCP init on stdin)
- **Files:** `channel/package.json`, `channel/server.ts`

#### Task 5.2: Telegram Bot + Push Notifications
- **Effort:** 2 hours
- **Dependencies:** Task 5.1
- **Acceptance Criteria:**
  - [ ] Bot token from `TELEGRAM_BOT_TOKEN` env var
  - [ ] `bot.on('message:text', ...)` receives messages
  - [ ] Access control: reads `~/.claude/channels/telegram/access.json` allowlist
  - [ ] Non-allowlisted messages rejected (offset still advanced)
  - [ ] Allowed messages pushed: `mcp.notification({method: 'notifications/claude/channel', params: {content, meta: {chat_id, user_id, user, message_id, ts}}})`
  - [ ] Notification serialisation: messages queued while `toolCallInFlight=true`, flushed in `finally` block
  - [ ] Clean shutdown on stdin EOF / SIGINT / SIGTERM
- **Files:** `channel/server.ts`, `channel/lib.ts`

#### Task 5.3: `reply` Tool
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.2
- **Acceptance Criteria:**
  - [ ] Tool: `reply(chat_id, text, reply_to?)` → grammy `bot.api.sendMessage()`
  - [ ] Handles Telegram 4096 char limit (chunks if needed)
  - [ ] Validates `chat_id` against allowlist before sending
  - [ ] Returns success/failure
- **Files:** `channel/server.ts`

---

### Milestone 19: Bridge Operation Tools

#### Task 5.4: CLI Subprocess Wrapper (`bridgeCli`)
- **Effort:** 1 hour
- **Dependencies:** Task 5.1
- **Acceptance Criteria:**
  - [ ] `bridgeCli(command, args)` runs `python3 -m claude_bridge.cli` with correct env
  - [ ] `BRIDGE_SRC_PATH` env var sets PYTHONPATH
  - [ ] Returns stdout as string; throws on non-zero exit with stderr message
  - [ ] Timeout: 30s default
- **Files:** `channel/lib.ts`

#### Task 5.5: Bridge Tools Registration
- **Effort:** 2.5 hours
- **Dependencies:** Task 5.4
- **Acceptance Criteria:**
  - [ ] MCP tools: `bridge_dispatch`, `bridge_status`, `bridge_agents`, `bridge_history`, `bridge_kill`, `bridge_create_agent`
  - [ ] Each tool has proper inputSchema (zod)
  - [ ] Each tool calls `bridgeCli()` with correct arguments
  - [ ] Returns structured JSON (parsed from CLI output)
  - [ ] Error handling: CLI failures returned as MCP error content
- **Files:** `channel/server.ts`

#### Task 5.6: `bridge_get_notifications` Tool
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.4
- **Acceptance Criteria:**
  - [ ] Calls `bridgeCli('status', ...)` or reads bridge.db directly via bun:sqlite
  - [ ] Returns unreported completions: task_id, agent, status, summary, cost
  - [ ] Marks as reported after retrieval
- **Files:** `channel/server.ts`

---

### Milestone 20: Outbound Delivery

#### Task 5.7: Outbound Message Poller
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.2
- **Acceptance Criteria:**
  - [ ] Runs every 2 seconds via `setInterval`
  - [ ] Reads `outbound_messages WHERE status='pending'` from `messages.db` via bun:sqlite
  - [ ] Sends via `bot.api.sendMessage()`
  - [ ] Marks as sent on success, increments retry on failure
  - [ ] Max 3 retries, then marks as failed
- **Files:** `channel/server.ts` (processOutbound function), `channel/lib.ts`

#### Task 5.8: Completion Push Notification
- **Effort:** 1.5 hours
- **Dependencies:** Task 5.7
- **Acceptance Criteria:**
  - [ ] Outbound messages with `source='notification'` trigger a channel push
  - [ ] Push content: "Task #ID completed" with meta: `{source: 'task_completion', task_id}`
  - [ ] Bridge Bot session sees `<channel source="bridge" ...>Task #ID completed</channel>`
  - [ ] Regular bot replies (`source='bot'`) do NOT trigger a push (no echo loop)
- **Files:** `channel/server.ts`

---

### Milestone 21: CLAUDE.md + Setup

#### Task 5.9: Channel-Mode CLAUDE.md Template
- **Effort:** 2 hours
- **Dependencies:** Milestones 18–20
- **Acceptance Criteria:**
  - [ ] Instructions: messages arrive as `<channel source="bridge" chat_id="..." ...>` tags
  - [ ] Reply using `reply(chat_id, text)` tool
  - [ ] No `bridge_get_messages` or `bridge_acknowledge` references
  - [ ] Still call `bridge_get_notifications()` after processing (belt-and-suspenders)
  - [ ] Intent mapping, onboarding, error handling preserved from Phase 4
  - [ ] `generate_bridge_bot_claude_md(mode='channel')` produces this template
- **Files:** `src/claude_bridge/bridge_bot_claude_md.py`

#### Task 5.10: Setup Command Update
- **Effort:** 2 hours
- **Dependencies:** Task 5.9
- **Acceptance Criteria:**
  - [ ] `setup-bot` generates `.mcp.json`: `command: "bun"`, `args: ["run", "<path>/channel/server.ts"]`
  - [ ] `.mcp.json` env: `TELEGRAM_BOT_TOKEN`, `BRIDGE_SRC_PATH`, `MESSAGES_DB_PATH`
  - [ ] Prints startup command: `claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions`
  - [ ] Detects if Bun is installed; warns if not
  - [ ] `setup-bot --mode shell` falls back to Python MCP server
- **Files:** `src/claude_bridge/cli.py`

---

### Milestone 22: Migration + Cleanup

#### Task 5.11: Deprecate Python MCP Server
- **Effort:** 1 hour
- **Dependencies:** Milestone 21
- **Acceptance Criteria:**
  - [ ] `mcp_server.py` header: "DEPRECATED — use channel/server.ts instead"
  - [ ] `setup-bot` defaults to channel mode
  - [ ] `setup-bot --mode python` still generates old config
- **Files:** `src/claude_bridge/mcp_server.py`

#### Task 5.12: Update Documentation
- **Effort:** 1.5 hours
- **Dependencies:** Milestone 21
- **Acceptance Criteria:**
  - [ ] `plan/architecture/high-level-architecture.md` updated with channel flow
  - [ ] `plan/architecture/bridge-mcp.md` → rewritten as `bridge-channel.md`
  - [ ] README: setup uses `setup-bot`, startup uses `--dangerously-load-development-channels server:bridge`
- **Files:** `plan/architecture/` docs, `README.md`

#### Task 5.13: End-to-End Test
- **Effort:** 1.5 hours
- **Dependencies:** Milestone 21
- **Acceptance Criteria:**
  - [ ] Manual: send Telegram message, verify `<channel>` tag in Claude session
  - [ ] Manual: Claude calls `reply` tool, verify message in Telegram
  - [ ] Manual: dispatch task, complete, verify notification pushed to session
  - [ ] Automated: mock grammy bot, verify channel notification format

---

## Summary

| Milestone | Tasks | Effort |
|-----------|-------|--------|
| M18 — Channel skeleton + Telegram + reply | 5.1–5.3 | 5 h |
| M19 — Bridge CLI wrapper + operation tools | 5.4–5.6 | 5 h |
| M20 — Outbound delivery + completion push | 5.7–5.8 | 3 h |
| M21 — CLAUDE.md channel template + setup | 5.9–5.10 | 4 h |
| M22 — Deprecation + docs + E2E test | 5.11–5.13 | 4 h |
| **Total** | **13 tasks** | **~21 h** |

## Dependency Graph

```
M18 (channel skeleton) → M19 (bridge tools) → M20 (outbound)
                                                    ↓
                                              M21 (CLAUDE.md + setup)
                                                    ↓
                                              M22 (migration + docs)
```
