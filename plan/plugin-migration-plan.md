# Claude Bridge → Official Plugin Migration Plan

**Date:** 2026-04-09
**Status:** Planning — no code changes

---

## Executive Summary

Claude Bridge should become an official Claude Code plugin, installable via `/plugin install claude-bridge@claude-plugins-official`. This requires two parallel initiatives:

1. **TypeScript Migration** — Rewrite from Python to TypeScript/Bun (aligned with official plugin architecture)
2. **Multi-Channel Support** — Add Discord and Slack channels beyond Telegram

**Key finding:** The official plugin ecosystem (`anthropics/claude-plugins-official`) is 100% TypeScript + Bun. Every channel plugin follows the same structure: `.claude-plugin/plugin.json` + `.mcp.json` + `server.ts`. Python is not supported in the plugin distribution system.

---

## Part 1: Research Findings

### Official Plugin Ecosystem (confirmed via `anthropics/claude-plugins-official`)

- **33 internal plugins** + **17 external plugins** in the official directory
- **4 channel plugins exist:** Discord, Telegram, Slack, iMessage, FakeChat (test)
- **All use Bun as runtime** — `.mcp.json` specifies `"command": "bun"`
- **All TypeScript** — single `server.ts` per channel
- **Installation:** `/plugin install {name}@claude-plugins-official`
- **Plugin structure standard:**
  ```
  plugin-name/
    .claude-plugin/plugin.json    # metadata + keywords: ["channel", "mcp"]
    .mcp.json                     # MCP server config
    package.json                  # bun/npm package
    bun.lock                      # bun lockfile
    server.ts                     # MCP server
    skills/                       # slash commands
    ACCESS.md                     # access control docs
  ```
- **Channels use `--channels` flag:** `claude --channels plugin:telegram@claude-plugins-official`
- **State directory:** `~/.claude/channels/{channel-name}/` for access.json, .env, inbox/

### Current Codebase Size

| Component | Lines | Files |
|-----------|-------|-------|
| Python source (src/claude_bridge/) | 10,012 | 25 |
| Python tests (tests/) | 10,254 | 35 |
| TypeScript (channel/) | 3,490 | 6 |
| **Total** | **23,756** | **66** |

### Channel Platform Comparison

| Platform | Auth | SDK (TS) | Msg Limit | Receive Model | Community | Priority |
|----------|------|----------|-----------|---------------|-----------|----------|
| Telegram ✅ | Simple (token) | grammy | 4096 | Polling | Shipped | Done |
| Discord | Simple (token) | discord.js | 2000 | WebSocket | Strong (5+ repos) | **HIGH** |
| Slack | Medium (token+secret) | @slack/bolt | 40,000 | Socket Mode (WS) | Good (5+ repos) | **HIGH** |
| Google Chat | High (GCP+SA) | REST only | 4096 | Webhook (public URL) | None | LOW |
| Teams | Very High (Azure) | botbuilder | ~28KB | Webhook (public URL) | None | LOW |

---

## Part 2: Initiative 1 — TypeScript Migration

### Why Migrate

1. **Plugin distribution requires it** — official plugins are Bun/TS, no Python runtime
2. **Bun runtime advantages** — built-in SQLite (`bun:sqlite`), fast startup, single binary
3. **Anthropic acquired Bun** — clear signal of preferred runtime
4. **Channel code already TS** — 3,490 lines of channel/ already TypeScript

### Migration Strategy: Inside-Out

Migrate the TypeScript channel layer first (it's the plugin entry point), then progressively replace Python modules. During transition, TS can shell out to `bridge-cli` (Python) for complex operations — same pattern the current channel/server.ts already uses.

### Module-by-Module Migration Order

#### Wave 1: Plugin Shell (Week 1)
*Goal: Installable as a plugin, delegates to Python for logic*

| Module | Lines | Effort | Notes |
|--------|-------|--------|-------|
| `.claude-plugin/plugin.json` | New | Low | Plugin metadata, keywords: ["channel", "mcp"] |
| `.mcp.json` | Exists | Low | Already have this |
| `package.json` | Exists | Low | Add "start" script |
| `skills/` | New | Low | Skill definitions for /bridge:dispatch etc. |
| `server.ts` (channel) | 1,107 | Low | Already exists, minor adjustments |

**Deliverable:** `/plugin install claude-bridge` works, uses existing Python CLI underneath.

#### Wave 2: Core Data Layer (Week 2-3)
*Goal: Replace Python sqlite/session with native Bun*

| Module (Python → TS) | Py Lines | Effort | Notes |
|-----------------------|----------|--------|-------|
| `db.py` → `db.ts` | 977 | High | 8 tables, WAL mode, migrations. Use `bun:sqlite` |
| `message_db.py` → part of `db.ts` | 263 | Medium | Merge into main db module |
| `session.py` → `session.ts` | 140 | Low | Path derivation, pure logic |
| `__init__.py` → `config.ts` | 50 | Low | CLAUDE_BRIDGE_HOME resolution |

**Complexity notes:**
- `bun:sqlite` natively supports WAL mode, prepared statements, and is synchronous (matches Python's sqlite3)
- Row factory pattern → just use `.all()` which returns objects in Bun
- Schema migrations: same try/catch ALTER TABLE approach works

#### Wave 3: Task Execution (Week 3-4)
*Goal: Replace subprocess spawning with Bun child_process*

| Module | Py Lines | Effort | Notes |
|--------|----------|--------|-------|
| `dispatcher.py` → `dispatcher.ts` | 114 | High | `Bun.spawn()` + process groups |
| `on_complete.py` → `on-complete.ts` | 264 | Medium | Hook handler, reads result files |
| `watcher.py` → `watcher.ts` | 279 | Medium | PID polling loop |
| `notify.py` → `notify.ts` | 146 | Low | HTTP POST via `fetch()` |

**Biggest challenge:** `start_new_session=True` for process isolation.
- **Bun solution:** `Bun.spawn()` with `detached: true` creates new process group
- **Signal handling:** `process.kill(pid, 'SIGTERM')` works in Bun/Node
- **PID check:** `process.kill(pid, 0)` throws if process doesn't exist (same as Python)

#### Wave 4: Orchestration (Week 4-5)
*Goal: Port the brain — loops, evaluation, scheduling*

| Module | Py Lines | Effort | Notes |
|--------|----------|--------|-------|
| `loop_orchestrator.py` → `loop.ts` | 1,059 | High | State machine, iteration management |
| `loop_evaluator.py` → `evaluator.ts` | 313 | Medium | Done conditions, subprocess calls |
| `scheduler.py` → `scheduler.ts` | 125 | Low | Cron expression evaluation |

#### Wave 5: CLI & Integration (Week 5-6)
*Goal: Replace bridge-cli with TypeScript CLI*

| Module | Py Lines | Effort | Notes |
|--------|----------|--------|-------|
| `cli.py` → `cli.ts` | 2,361 | High | Largest file. Use `commander` or Bun's built-in arg parsing |
| `bridge_cmd.py` → `bridge-cmd.ts` | 426 | Medium | Bridge bot command handler |
| `agent_md.py` → `agent-md.ts` | 160 | Low | File generation |
| `claude_md_init.py` → `claude-md.ts` | 101 | Low | CLAUDE.md init |
| `memory.py` → `memory.ts` | 95 | Low | Read-only memory access |

#### Wave 6: Infrastructure (Week 6-7)
*Goal: Replace daemon and tmux management*

| Module | Py Lines | Effort | Notes |
|--------|----------|--------|-------|
| `daemon.py` → `daemon.ts` | 500 | High | launchd/systemd plist generation |
| `tmux_session.py` → `tmux.ts` | 201 | Medium | Shell out to tmux (same approach) |
| `telegram_poller.py` → absorbed into channel | 272 | Medium | Merge with channel server |
| `telegram_loop.py` → absorbed into channel | 409 | Medium | Conversation state machine |
| `permission_relay.py` → `permissions.ts` | 89 | Low | Permission request forwarding |

#### Wave 7: MCP Server (Week 7)
*Goal: Consolidate MCP layer*

| Module | Py Lines | Effort | Notes |
|--------|----------|--------|-------|
| `mcp_server.py` → merge into `server.ts` | 348 | Medium | Already have TS MCP server |
| `mcp_tools.py` → `tools.ts` | 741 | Medium | Tool implementations |
| `bridge_bot_claude_md.py` → `bridge-md.ts` | 521 | Medium | Agent MD generation for bridge bot |

### Migration Dependency Graph

```
Wave 1 (Plugin Shell) ─────────────────────┐
                                            │
Wave 2 (Data Layer: db, session, config) ───┤
           │                                │
           ▼                                │
Wave 3 (Task Execution: dispatcher, hook) ──┤
           │                                │
           ▼                                │
Wave 4 (Orchestration: loops, scheduler) ───┤
           │                                │
           ▼                                │
Wave 5 (CLI & Integration) ────────────────┤
           │                                │
           ▼                                │
Wave 6 (Infrastructure: daemon, tmux) ──────┤
                                            │
Wave 7 (MCP Consolidation) ────────────────┘
```

Waves 1 and 2 can partially overlap. Wave 1 is independent. Everything else is sequential.

### What Must Stay as Shell-Outs

These are Unix tools that both Python and TypeScript call via subprocess — no migration needed:
- `tmux` commands (new-session, kill-session, send-keys, etc.)
- `claude` CLI invocations
- `git` operations (worktree)
- `systemctl` / `launchctl` for daemon management

### Test Migration

**10,254 lines of Python tests** need rewriting in Bun's test runner.

Strategy: Migrate tests alongside their modules (same wave). Bun test has:
- `describe/it/expect` — familiar Jest-like API
- `mock()` — function mocking
- `bun:sqlite` — same DB in tests
- `tmpdir()` — temp directories
- No pytest fixtures → use `beforeEach/afterEach`

### Risk Assessment (TS Migration)

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Process isolation differences (start_new_session) | High | Medium | `Bun.spawn({ detached: true })` + verify on macOS/Linux |
| SQLite behavior differences | Medium | Low | `bun:sqlite` is well-tested, same SQL |
| Test coverage regression | High | Medium | Migrate tests first (TDD), run both suites during transition |
| Feature freeze during migration | High | High | Wave 1 lets plugin work with Python backend — no freeze needed |
| Bun API instability | Medium | Low | Pin Bun version, use stable APIs only |

---

## Part 3: Initiative 2 — Multi-Channel Support

### Priority Order

1. **Discord** — Simplest auth, best community validation, WebSocket (no public URL), official channel already exists as reference
2. **Slack** — Socket Mode (no public URL), 40K char limit, high enterprise demand, Slack plugin exists but is MCP-only (no channel server)
3. **Google Chat** — Skip unless requested (requires GCP + public URL)
4. **Teams** — Skip unless requested (requires Azure + public URL)

### Wait — Official Channels Already Exist?

Yes. Discord and Telegram channels exist in `claude-plugins-official/external_plugins/`. But they are **simple 1:1 channels** — one user talks to one Claude session.

**Claude Bridge's unique value is orchestration:**
- Multi-agent dispatch (multiple sessions with different purposes)
- Goal loops (iterative task execution with done conditions)
- Task queue and scheduling
- Multi-user access control
- Session management across projects

The official channels are "chat with Claude." Claude Bridge is "command Claude to work."

### Channel Abstraction Architecture

```typescript
// channel/interface.ts — Common channel interface

interface ChannelMessage {
  id: string;
  text: string;
  senderId: string;
  senderName: string;
  chatId: string;
  threadId?: string;          // Slack threads, Discord threads
  replyToMessageId?: string;
  files?: ChannelFile[];
  timestamp: number;
}

interface ChannelFile {
  name: string;
  url: string;
  mimeType: string;
  size: number;
}

interface ChannelAdapter {
  // Lifecycle
  start(): Promise<void>;
  stop(): Promise<void>;

  // Messaging
  sendMessage(chatId: string, text: string, opts?: SendOpts): Promise<string>;  // returns message ID
  editMessage(chatId: string, messageId: string, text: string): Promise<void>;
  deleteMessage(chatId: string, messageId: string): Promise<void>;

  // Reactions (optional)
  addReaction?(chatId: string, messageId: string, emoji: string): Promise<void>;

  // File handling
  downloadFile(fileId: string, destPath: string): Promise<void>;

  // Events
  onMessage(handler: (msg: ChannelMessage) => void): void;
  onCommand(handler: (cmd: string, args: string, msg: ChannelMessage) => void): void;

  // Capabilities
  maxMessageLength: number;
  supportsThreads: boolean;
  supportsReactions: boolean;
  supportsFileUpload: boolean;
  markdownFormat: 'standard' | 'slack-mrkdwn' | 'html';
}

interface SendOpts {
  threadId?: string;
  parseMode?: string;
  replyToMessageId?: string;
}
```

### Per-Channel Implementation Plan

#### Discord Channel (Week 1-2 of channel work)

**SDK:** `discord.js ^14.14.0`
**Reference:** `claude-plugins-official/external_plugins/discord/`

| Task | Effort | Notes |
|------|--------|-------|
| DiscordAdapter implements ChannelAdapter | Medium | WebSocket gateway via discord.js |
| Message chunking (2000 char limit) | Low | Reuse Telegram chunking logic |
| Slash command registration | Medium | `/dispatch`, `/status`, `/loop` |
| Thread support | Medium | Use Discord threads for task output |
| File handling (attachments) | Low | discord.js has built-in attachment download |
| Access control (allowlist) | Low | Port from Telegram's access.json pattern |
| Formatting (MD → Discord MD) | Low | Discord supports standard Markdown natively |

**Key difference from Telegram:** Discord uses persistent WebSocket connection (not polling). `discord.js` manages reconnection automatically.

**Bot setup:** Create app at discord.dev → add bot → generate token → invite to server with `applications.commands` + `bot` scopes.

#### Slack Channel (Week 2-3 of channel work)

**SDK:** `@slack/bolt ^4.0.0`
**Reference:** `claude-plugins-official/external_plugins/slack/` (MCP-only, no channel server — opportunity!)

| Task | Effort | Notes |
|------|--------|-------|
| SlackAdapter implements ChannelAdapter | Medium | Socket Mode via Bolt SDK |
| Message formatting (mrkdwn) | Medium | Slack uses own markdown variant, no syntax highlighting |
| Slash command registration | Low | Bolt SDK handles this natively |
| Thread support | Medium | Slack threads are first-class — use for task output |
| File handling | Medium | Slack files API requires separate upload/download |
| Access control | Low | Workspace-level + channel-level permissions |
| Block Kit for rich output | Medium | Optional but valuable for status displays |

**Key advantage:** Socket Mode means no public URL needed (same as Telegram polling). 40K char limit means minimal chunking.

**Slack's mrkdwn differences from standard Markdown:**
- Bold: `*text*` (not `**text**`)
- Italic: `_text_` (not `*text*`)
- Code blocks: `` ``` `` (same, but no language hint for syntax highlighting)
- Links: `<url|text>` (not `[text](url)`)

**App setup:** Create app at api.slack.com → enable Socket Mode → add bot scopes (`chat:write`, `commands`, `files:read`, `files:write`) → install to workspace.

### Formatter Architecture

```typescript
// channel/format.ts already exists for Telegram HTML
// Extend with format adapters:

interface MessageFormatter {
  formatCodeBlock(code: string, language?: string): string;
  formatBold(text: string): string;
  formatItalic(text: string): string;
  formatLink(url: string, text: string): string;
  formatList(items: string[]): string;
  escapeSpecialChars(text: string): string;
  chunkMessage(text: string): string[];   // Split by platform limit
}

// Implementations:
// TelegramFormatter  — HTML tags, 4096 char chunks
// DiscordFormatter   — Standard Markdown, 2000 char chunks
// SlackFormatter     — mrkdwn syntax, 40000 char chunks
```

### Risk Assessment (Multi-Channel)

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Discord rate limits (50 requests/s per bot) | Medium | Medium | Implement queue + backoff (discord.js handles most) |
| Slack app review for distribution | Medium | High | Socket Mode apps don't need review for single-workspace |
| Message format inconsistency across platforms | Low | High | Formatter abstraction + per-platform tests |
| Thread model differences | Medium | Medium | Normalize to ChannelMessage.threadId |
| Maintaining 3 platform SDKs | Medium | Certain | Worth it for reach; SDKs are stable |

---

## Part 4: Combined Execution Plan

### Phase 1: Plugin Packaging (1 week)
*Make claude-bridge installable as a plugin without rewriting anything*

1. Create `.claude-plugin/plugin.json` with proper metadata
2. Adjust `.mcp.json` to use `${CLAUDE_PLUGIN_ROOT}`
3. Add `skills/` directory with bridge skill definitions
4. Create proper `package.json` with `"start"` script
5. Test: `/plugin install` from local path works
6. Submit to `claude-plugins-official` as external plugin

**Parallel work:** Can start Initiative 2 design alongside.

### Phase 2: Channel Abstraction (2 weeks)
*Extract Telegram-specific code behind ChannelAdapter interface*

1. Define `ChannelAdapter` and `MessageFormatter` interfaces
2. Refactor current `channel/server.ts` → `TelegramAdapter` + `TelegramFormatter`
3. Extract shared logic (access control, message queue, inbound tracking) into `channel/core.ts`
4. Ensure existing Telegram functionality works unchanged

### Phase 3: Discord Channel (2 weeks)
*First new channel — validates the abstraction*

1. Implement `DiscordAdapter` using `discord.js`
2. Implement `DiscordFormatter`
3. Add Discord-specific skills (`/bridge:discord-access`)
4. Test with real Discord server
5. Document setup flow in ACCESS.md

### Phase 4: TypeScript Core Migration — Data Layer (2-3 weeks)
*Replace Python db/session with Bun native*

1. Port `db.py` → `db.ts` using `bun:sqlite`
2. Port `session.py` → `session.ts`
3. Port tests alongside (TDD)
4. Switch `server.ts` from shelling out to `bridge-cli` to importing `db.ts` directly
5. Remove Python db dependency from MCP server path

### Phase 5: TypeScript Core Migration — Execution (2-3 weeks)
*Replace Python subprocess management*

1. Port `dispatcher.py` → `dispatcher.ts` using `Bun.spawn()`
2. Port `on_complete.py` → `on-complete.ts`
3. Port `watcher.py` → `watcher.ts`
4. Port `notify.py` → `notify.ts`
5. Validate process isolation works on macOS and Linux

### Phase 6: Slack Channel (2 weeks)
*Can run parallel with Phase 5*

1. Implement `SlackAdapter` using `@slack/bolt`
2. Implement `SlackFormatter` (mrkdwn variant)
3. Add Slack skills and access control
4. Test with real Slack workspace

### Phase 7: TypeScript Core Migration — Everything Else (3-4 weeks)

1. Port `loop_orchestrator.py` → `loop.ts`
2. Port `loop_evaluator.py` → `evaluator.ts`
3. Port `cli.py` → `cli.ts` (largest file, 2361 lines)
4. Port `daemon.py` → `daemon.ts`
5. Port `tmux_session.py` → `tmux.ts`
6. Port remaining modules
7. Consolidate MCP servers (Python + TS → single TS)
8. Remove Python package, update `pyproject.toml` → `package.json` only

### Phase 8: Polish & Submission (1 week)

1. Full test suite passing in Bun
2. Documentation (README, ACCESS.md per channel)
3. Plugin submission to `claude-plugins-official`
4. PyPI deprecation notice (point to plugin install)

---

## Part 5: Timeline Summary

| Phase | Duration | Can Parallel With | Cumulative |
|-------|----------|-------------------|------------|
| P1: Plugin Packaging | 1 week | — | Week 1 |
| P2: Channel Abstraction | 2 weeks | — | Week 3 |
| P3: Discord Channel | 2 weeks | — | Week 5 |
| P4: TS Migration — Data | 2-3 weeks | — | Week 7-8 |
| P5: TS Migration — Execution | 2-3 weeks | P6 (Slack) | Week 9-11 |
| P6: Slack Channel | 2 weeks | P5 | Week 9-11 |
| P7: TS Migration — Rest | 3-4 weeks | — | Week 13-15 |
| P8: Polish & Submit | 1 week | — | Week 14-16 |

**Total: ~14-16 weeks** (part-time, ~15-20 hrs/week)
**Compressed: ~8-10 weeks** (full-time)

### What Can Run in Parallel

- **P5 + P6:** Slack channel implementation is independent of core TS migration
- **P1 can start immediately** — no dependencies
- **P2 informs P3** — abstraction must be done before Discord
- **P4 before P5** — execution layer depends on data layer

### What Must Be Sequential

- P2 → P3 (abstraction before new channels)
- P4 → P5 → P7 (data → execution → everything else)
- P7 → P8 (all migration done before final polish)

---

## Part 6: Decision Points

### Should We Even Fully Migrate to TS?

**Alternative: Hybrid approach** — Keep Python core, package TS channel layer as the plugin.
- Pro: Less work (skip Phases 4-5-7)
- Con: Plugin would need Python runtime on user machine, not standard for plugins
- Con: Two languages to maintain forever
- **Recommendation:** Full migration. The official ecosystem is TS/Bun-only. Fighting that is a losing battle.

### Discord vs Slack — Which First?

- **Discord first:** Simpler auth, closer to Telegram's model, stronger community validation
- **Slack first:** Higher enterprise demand, unique opportunity (official Slack channel has no server.ts)
- **Recommendation:** Discord first (validates abstraction with simpler platform), Slack second

### What About Claude Bridge's Unique Features?

The official Discord/Telegram channels are basic chat bridges. Claude Bridge adds:
- **Multi-agent dispatch** — the killer feature, no official equivalent
- **Goal loops** — iterative task execution
- **Scheduling** — cron-based recurring tasks
- **Multi-user** — team dispatch from one channel

These features are the reason to exist as a separate plugin, not to compete with official channels.

---

## Part 7: File Mapping (Python → TypeScript)

Complete mapping for reference during migration:

```
src/claude_bridge/                    →  src/
  __init__.py                         →  config.ts
  cli.py (2361 lines)                 →  cli.ts
  db.py (977 lines)                   →  db.ts
  session.py (140 lines)              →  session.ts
  agent_md.py (160 lines)             →  agent-md.ts
  claude_md_init.py (101 lines)       →  claude-md.ts
  dispatcher.py (114 lines)           →  dispatcher.ts
  on_complete.py (264 lines)          →  on-complete.ts
  watcher.py (279 lines)              →  watcher.ts
  notify.py (146 lines)               →  notify.ts
  memory.py (95 lines)                →  memory.ts
  loop_orchestrator.py (1059 lines)   →  loop.ts
  loop_evaluator.py (313 lines)       →  evaluator.ts
  scheduler.py (125 lines)            →  scheduler.ts
  daemon.py (500 lines)               →  daemon.ts
  bridge_cmd.py (426 lines)           →  bridge-cmd.ts
  tmux_session.py (201 lines)         →  tmux.ts
  telegram_poller.py (272 lines)      →  (absorbed into channel/)
  telegram_loop.py (409 lines)        →  (absorbed into channel/)
  mcp_server.py (348 lines)           →  (merged into server.ts)
  mcp_tools.py (741 lines)            →  tools.ts
  message_db.py (263 lines)           →  (merged into db.ts)
  permission_relay.py (89 lines)      →  permissions.ts
  channel.py (58 lines)               →  (absorbed into channel/)
  bridge_bot_claude_md.py (521 lines) →  bridge-md.ts

channel/                              →  channel/
  server.ts (1107 lines)              →  server.ts (refactored)
  lib.ts (460 lines)                  →  telegram/adapter.ts
  format.ts (265 lines)               →  telegram/format.ts
  (new)                               →  interface.ts
  (new)                               →  core.ts
  (new)                               →  discord/adapter.ts
  (new)                               →  discord/format.ts
  (new)                               →  slack/adapter.ts
  (new)                               →  slack/format.ts

tests/                                →  tests/ (*.test.ts, Bun test runner)
```

**Total Python to port: ~10,012 lines → estimated ~8,000-9,000 lines TypeScript** (TS is slightly more concise for some patterns, slightly more verbose for others).
