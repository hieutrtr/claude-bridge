# MCP Server and Channel Adapters

Reference for the two boundaries between claude-bridge and the outside world:
the MCP server (Claude Code talks to the bridge) and the channel adapters
(users talk to the bridge via Telegram / Slack / Discord). Three tasks this
doc is optimised for: adding a new MCP tool, tracing a Telegram message end
to end, and adding a second channel adapter.

**Files in scope**:

- `src/mcp/server.ts` — MCP stdio server, notification queue, auto-start glue.
- `src/mcp/tools.ts` — tool name registry, JSON-Schema definitions, and a
  (largely dormant) Python CLI fallback.
- `src/mcp/tool-handlers.ts` — native TS handlers for every tool, one switch
  arm per tool name.
- `src/mcp/telegram-inbound.ts` — grammy bot that turns Telegram updates into
  `notifications/claude/channel` MCP notifications.
- `src/mcp/channel-format.ts` — builder for the `meta` object on those
  notifications.
- `src/mcp/bridge-md.ts` — generates the bridge bot's `CLAUDE.md`.
- `src/mcp/index.ts` — barrel; exports the startup, tool, and bridge-md
  surfaces.
- `src/channel/interface.ts` — `IChannelAdapter` / `IMessageFormatter`
  interfaces (Phase 2+ multi-channel target).
- `src/channel/core.ts` — stub holder for cross-adapter access-control helpers.
- `src/channel/index.ts` — barrel for the `channel/` layer.
- `src/channel/telegram/{adapter,format}.ts` — Telegram adapter + formatter
  stubs (not yet used; real send path is in `execution/notify.ts`).
- `src/channel/slack/{adapter,format}.ts` — Slack stubs.
- `src/channel/discord/{adapter,format}.ts` — Discord stubs.
- `src/execution/notify.ts` — today's real outbound path (direct HTTP to
  Telegram); referenced here only at the seam with channel adapters.

Cross-refs: `02-execution-pipeline.md` owns the notification queue and
at-least-once semantics; `03-orchestration.md` owns the loop / schedule tool
implementations this file dispatches into.

## 1. Files by role

| File | Role |
| --- | --- |
| `src/mcp/server.ts` | MCP stdio server, capability declaration, notification queue. |
| `src/mcp/tools.ts` | Tool registry and CLI fallback. |
| `src/mcp/tool-handlers.ts` | Native TS `switch` over tool names. |
| `src/mcp/telegram-inbound.ts` | grammy polling loop; pushes `notifications/claude/channel`. |
| `src/mcp/channel-format.ts` | `buildInboundMeta` — shape of the `meta` object. |
| `src/mcp/bridge-md.ts` | `CLAUDE.md` generator for the bridge bot. |
| `src/channel/interface.ts` | `IChannelAdapter` / `IMessageFormatter` interfaces (forward-looking). |
| `src/channel/core.ts` | Stub for shared adapter helpers. |
| `src/channel/{telegram,slack,discord}/*` | Adapter + formatter stubs; formatters mostly implemented, adapters throw. |
| `src/execution/notify.ts` | Actual outbound sender (direct Telegram HTTP). |

## 2. MCP server startup

`src/mcp/server.ts:28` constructs a single module-scoped
`@modelcontextprotocol/sdk` `Server` with `name: "claude-bridge"`, advertises
`capabilities.tools: {}` and the experimental `claude/channel` capability,
and sets an `instructions` string (`src/mcp/server.ts:17`) that primes the
bot on how to read `<channel>` tags and which tools to call in what order
(ack, `bridge_get_notifications`, `bridge_check_messages`).

Two handlers are registered:

- `ListToolsRequestSchema` (`src/mcp/server.ts:78`) — returns
  `TOOL_DEFINITIONS` verbatim.
- `CallToolRequestSchema` (`src/mcp/server.ts:84`) — validates the tool name
  against `TOOL_NAMES` (unknown names throw) and delegates to
  `executeToolNative` in `src/mcp/tool-handlers.ts`.

Transport is stdio (`StdioServerTransport` at `src/mcp/server.ts:104`). The
server is connected by `startServer()` and does not return — the Claude Code
parent owns the lifetime.

### 2.1 Launching from the startup orchestrator

`src/infra/startup.ts:30` (`StartupOrchestrator.start`) spins up the process
watcher and the notification loop, then awaits `startServer()` as the last
step so the stdio transport owns the event loop. The orchestrator is the
entry point used both by the daemon and by `import.meta.main` inside
`src/mcp/server.ts:115`, where the server also optionally boots the Telegram
inbound polling loop when `TELEGRAM_BOT_TOKEN` is present
(`src/mcp/server.ts:123`).

### 2.2 Queued notifications

MCP stdio multiplexes tool responses and server-initiated notifications on a
single JSON-RPC stream. If a notification is written to stdout while a tool
response is mid-serialisation, the client sees an interleaved frame and the
whole session dies. `src/mcp/server.ts:49-74` implements a simple gate: a
module-level `toolCallInFlight` flag; any call to `queuedNotification`
during a handler is pushed onto `pendingNotifications` and flushed in the
`finally` of the tool handler (`src/mcp/server.ts:95-98`). `getQueuedNotifier`
(`src/mcp/server.ts:110`) exposes this safe wrapper to
`telegram-inbound.ts`, which would otherwise race the server's own stdout
writes.

## 3. Tool registry

`TOOL_NAMES` (`src/mcp/tools.ts:27`) is the accept-list checked by
`CallToolRequestSchema` before dispatch. `TOOL_DEFINITIONS`
(`src/mcp/tools.ts:58`) is the parallel array of JSON-Schema entries. Each
tool is one switch arm of `handleTool` in `src/mcp/tool-handlers.ts`.

| Tool | Definition | Handler |
| --- | --- | --- |
| `bridge_dispatch` | `src/mcp/tools.ts:60` | `src/mcp/tool-handlers.ts:91` |
| `bridge_status` | `src/mcp/tools.ts:75` | `src/mcp/tool-handlers.ts:125` |
| `bridge_agents` | `src/mcp/tools.ts:85` | `src/mcp/tool-handlers.ts:58` |
| `bridge_history` | `src/mcp/tools.ts:90` | `src/mcp/tool-handlers.ts:146` |
| `bridge_kill` | `src/mcp/tools.ts:102` | `src/mcp/tool-handlers.ts:162` |
| `bridge_create_agent` | `src/mcp/tools.ts:113` | `src/mcp/tool-handlers.ts:68` |
| `bridge_get_messages` | `src/mcp/tools.ts:127` | `src/mcp/tool-handlers.ts:181` |
| `bridge_acknowledge` | `src/mcp/tools.ts:132` | `src/mcp/tool-handlers.ts:195` |
| `bridge_reply` | `src/mcp/tools.ts:143` | `src/mcp/tool-handlers.ts:205` |
| `bridge_get_notifications` | `src/mcp/tools.ts:156` | `src/mcp/tool-handlers.ts:213` |
| `bridge_loop` | `src/mcp/tools.ts:161` | `src/mcp/tool-handlers.ts:223` |
| `bridge_loop_status` | `src/mcp/tools.ts:180` | `src/mcp/tool-handlers.ts:250` |
| `bridge_loop_cancel` | `src/mcp/tools.ts:191` | `src/mcp/tool-handlers.ts:267` |
| `bridge_loop_approve` | `src/mcp/tools.ts:202` | `src/mcp/tool-handlers.ts:274` |
| `bridge_loop_reject` | `src/mcp/tools.ts:213` | `src/mcp/tool-handlers.ts:281` |
| `bridge_loop_list` | `src/mcp/tools.ts:225` | `src/mcp/tool-handlers.ts:292` |
| `bridge_loop_history` | `src/mcp/tools.ts:237` | `src/mcp/tool-handlers.ts:302` |
| `bridge_loop_notify` | `src/mcp/tools.ts:248` | `src/mcp/tool-handlers.ts:312` |
| `bridge_parse_loop_command` | `src/mcp/tools.ts:260` | `src/mcp/tool-handlers.ts:323` |
| `bridge_schedule_add` | `src/mcp/tools.ts:271` | `src/mcp/tool-handlers.ts:330` |
| `bridge_schedule_remove` | `src/mcp/tools.ts:287` | `src/mcp/tool-handlers.ts:344` |
| `bridge_schedule_list` | `src/mcp/tools.ts:298` | `src/mcp/tool-handlers.ts:349` |
| `bridge_schedule_pause` | `src/mcp/tools.ts:308` | `src/mcp/tool-handlers.ts:359` |
| `bridge_schedule_resume` | `src/mcp/tools.ts:319` | `src/mcp/tool-handlers.ts:364` |
| `bridge_check_messages` | `src/mcp/tools.ts:330` | `src/mcp/tool-handlers.ts:370` |
| `download_attachment` | `src/mcp/tools.ts:335` | `src/mcp/tool-handlers.ts:387` |

`bridge_loop` accepts (beyond the standard `agent`/`goal`/`done_when`):
`max_iterations`, `loop_type` (`bridge` / `agent` / `auto`), `max_cost_usd`,
`chat_id` (channel routing for per-iter + end-of-loop notifications),
`user_id`, `plan_first` (default true — iter 1 produces a JSON plan
and iters 2..N+1 execute one sub-task each; see `03-orchestration.md` §1.6),
and `pass_threshold` (default 1 — number of consecutive PASS verdicts
required to terminate; raise to 2–3 for stochastic conditions like
`llm_judge`; see `03-orchestration.md` §1.7).
Set `plan_first: false` to skip planning and attempt the goal directly in
iter 1. `plan_first: true` overrides `loop_type: "agent"` to `"bridge"`.

The legacy Python-CLI fallback (`buildCliArgs`, `src/mcp/tools.ts:352`, and
`executeTool`, `src/mcp/tools.ts:470`) is retained for parity with the Wave-1
shell-out path but is not on any hot path today. `download_attachment`
deliberately has no CLI fallback (`src/mcp/tools.ts:458`).

## 4. Tool handler patterns

The wrapper `executeToolNative` (`src/mcp/tool-handlers.ts:34`) opens a
single `BridgeDatabase` against `CLAUDE_BRIDGE_HOME/bridge.db`, delegates
to `handleTool`, wraps the entire call in try/catch so any thrown `Error`
becomes a `ToolResult` with `isError: true`, and always closes the DB in
`finally`. Handlers do not catch their own errors unless they need to
re-shape the message.

Input validation is minimal: `String(args["name"])` coerces and optional
fields are read conditionally. Zod is not used — the MCP SDK rejects
malformed calls against the JSON Schema before the handler runs. Helpers
`text` / `error` (`src/mcp/tool-handlers.ts:25-31`) wrap strings in
`ToolResult` shape. Outputs are human-readable plain text except
`bridge_check_messages` (`src/mcp/tool-handlers.ts:367`), which emits JSON.

`bridge_dispatch` (`src/mcp/tool-handlers.ts:91`) is the canonical exemplar
and exercises every layer handlers touch:

1. Coerce args; look up the agent via `db.getAgent`. Return an error if
   missing.
2. Call `db.atomicCheckAndCreateTask` — the single serialisation point for
   concurrent dispatches (owned by `02-execution-pipeline.md`).
3. If busy, create a `queued` row and return a status string.
4. Otherwise construct a `Dispatcher` and hand off to `startTask`; on
   throw, return an error string (the dispatcher itself reconciles the DB
   row — handlers never leave half-running state).
5. Return `text(...)` with the dispatched task id.

Handlers reach the rest of the system via three layers: `BridgeDatabase` /
`MessageDatabase` (most tools), `Dispatcher` + `Notifier` from `execution/`
(dispatch, kill, reply), and `LoopOrchestrator` / `LoopEvaluator` from
`orchestration/` (every `bridge_loop_*` arm). No dependency injection —
collaborators are constructed inline using `bridgeHome`.

## 5. `bridge-md.ts` and `channel-format.ts`

These two files produce model-facing artefacts rather than runtime
behaviour.

`src/mcp/bridge-md.ts`. `generateBridgeBotMd` (`src/mcp/bridge-md.ts:31`)
concatenates a fixed behaviour-rules preamble with per-tool docs derived
from `TOOL_DEFINITIONS` — each tool becomes an H3 section with its
description and a bulleted argument list. `writeBridgeBotMd`
(`src/mcp/bridge-md.ts:88`) writes the result to `{botDir}/CLAUDE.md`. It
is invoked from `bridge setup-bot` (see `05-cli.md`) and re-runs on every
scaffold so the bot's instructions stay in sync with `tools.ts`.

`src/mcp/channel-format.ts`. `buildInboundMeta`
(`src/mcp/channel-format.ts:31`) emits a flat string-keyed object with
required keys (`source`, `chat_id`, `user`, `user_id`, `message_id`,
`tracking_id`, `ts`) and optional attachment keys (`image_path`,
`attachment_kind`, `attachment_file_id`, `attachment_mime`,
`attachment_name`, `attachment_size`). Claude Code renders this into a
`<channel source="bridge" ...>...</channel>` tag; the
`CHANNEL_INSTRUCTIONS` string at `src/mcp/server.ts:17` teaches the bot
how to read it. `safeName` (`src/mcp/channel-format.ts:51`) strips shell
and path metacharacters from attachment filenames before they hit disk in
`{bridgeHome}/inbox/`. Meta is one-way (user → bot); outbound payload
construction lives in `execution/notify.ts`.

## 6. Telegram inbound path

`src/mcp/telegram-inbound.ts` is the grammy polling loop. It is started by
the auto-start block of `src/mcp/server.ts:123`, not by
`StartupOrchestrator`, because it needs the `queuedNotifier` returned by
`getQueuedNotifier`.

### 6.1 Bot setup

`startTelegramInbound` (`src/mcp/telegram-inbound.ts:124`) takes the bot
token, a `McpNotifier` (the queued notifier), a `MessageDatabase`, and
`bridgeHome`. It creates a `new Bot(token)` (grammy), registers a single
catch-all `bot.catch` handler that logs to stderr, and registers one handler
per message kind: `message:text`, `message:photo`, `message:document`,
`message:voice`, `message:audio` (`src/mcp/telegram-inbound.ts:186-297`).

### 6.2 Permission check

Allowlist is loaded once at startup by `loadAllowlist`
(`src/mcp/telegram-inbound.ts:38`) from `{bridgeHome}/config.json`, reading
`allowFrom` (array of string/number user ids) with a fallback to a single
`telegram_chat_id`. `isAllowed` (`src/mcp/telegram-inbound.ts:58`) is
**fail-closed**: if the allowlist is empty, no one is let in. The check
happens at the top of every handler before any DB or network work.

### 6.3 Message → MCP tool call mapping

Inbound messages do **not** map to tool calls. They map to MCP
*notifications*. The shared helper `pushInbound`
(`src/mcp/telegram-inbound.ts:140`) does three things:

1. `messageDb.createInbound("telegram", chatId, userId, text, messageId, username)`
   — inserts into the `inbound_messages` table and returns a `tracking_id`.
2. `buildInboundMeta` assembles the meta object
   (`src/mcp/telegram-inbound.ts:159`).
3. `notifier.notification({ method: "notifications/claude/channel", params: { content: text, meta } })`
   — pushes over stdio via the server's queued notifier
   (`src/mcp/telegram-inbound.ts:170`).
4. `messageDb.markInboundDelivered(trackingId)` flips the row to `delivered`
   so subsequent `bridge_check_messages` calls don't re-surface it.

The bot then decides which tools to call — typically `bridge_acknowledge`
(tracking id), `bridge_get_notifications`, `bridge_check_messages`, and
whatever dispatch/loop action the user intended. The mapping is prompt-driven
via `CHANNEL_INSTRUCTIONS`, not code.

### 6.4 Attachments

Photos are downloaded immediately via `downloadTelegramFile`
(`src/mcp/telegram-inbound.ts:67`) to `{bridgeHome}/inbox/` and the local
path is embedded as `image_path` in the meta so the model can `Read` it
directly. Documents / voice / audio are **not** pre-downloaded — only
`attachment_file_id` is forwarded; the bot invokes the `download_attachment`
tool (`src/mcp/tool-handlers.ts:384`) on demand. Both paths enforce a 20 MB
hard limit (`FILE_SIZE_LIMIT` at `src/mcp/telegram-inbound.ts:16`; repeated
in the tool handler).

### 6.5 Session routing

There is no session routing in the inbound path itself — `chat_id` and
`user_id` flow through the meta to the bot, and the bot chooses an agent.
`bridge_dispatch` (`src/mcp/tool-handlers.ts:91`) records both onto the
`tasks` row so that when the task completes, `Notifier` can route the
outbound notification back to the originating chat (cross-ref:
`02-execution-pipeline.md` §5).

### 6.6 Startup and shutdown

`bot.start` with `drop_pending_updates: true`
(`src/mcp/telegram-inbound.ts:305`) is launched but not awaited — the
function instead races the grammy `onStart` callback against a 3-second
timeout so a bad token does not hang the MCP server boot. The returned
handle's `.stop()` awaits `bot.stop()` followed by the long-lived polling
promise.

## 7. Outbound / channel adapter pattern

Today's outbound path and the forward-looking adapter design live in two
different places and are not yet wired together.

### 7.1 The `IChannelAdapter` interface

`src/channel/interface.ts:49` defines the target shape. Every adapter
declares compile-time capabilities (`platform`, `maxMessageLength`,
`supportsThreads`, `supportsReactions`, `supportsFileUpload`,
`markdownFormat`) and implements `start` / `stop`, `sendMessage` /
`editMessage` / `deleteMessage`, optional `addReaction`, `downloadFile`, and
event registration (`onMessage`, `onCommand`). The parallel
`IMessageFormatter` interface (`src/channel/interface.ts:37`) covers
formatting primitives (`formatCodeBlock`, `formatBold`, `formatItalic`,
`formatLink`, `formatList`, `escapeSpecialChars`, `chunkMessage`).

### 7.2 How `notify.ts` picks an adapter today

`src/execution/notify.ts` **does not** use `IChannelAdapter`. `Notifier.notify`
(`src/execution/notify.ts:73`) reads `telegram_token` from
`{homeDir}/config.json` (falling back to `TELEGRAM_BOT_TOKEN`) and POSTs
directly to `https://api.telegram.org/bot{token}/sendMessage` with
`parse_mode: "HTML"`. There is no retry, no chunking, no rate-limit
awareness — a 4xx / 5xx response becomes `false` and the notification loop
in `StartupOrchestrator` (`src/infra/startup.ts:63`) calls
`markNotificationFailed`. The only "channel selection" today is that the
`tasks.channel` column is always `"telegram"` — see `bridge_dispatch`
(`src/mcp/tool-handlers.ts:105`) and `bridge_schedule_add`
(`src/mcp/tool-handlers.ts:334`), both of which hard-code it.

This is the outbound seam a contributor will eventually cut on: today it is
a single HTTP call inside `Notifier`; tomorrow it should be `adapter =
registry.get(task.channel); await adapter.sendMessage(task.channel_chat_id,
formattedMessage)`.

### 7.3 Telegram's concrete adapter

`src/channel/telegram/adapter.ts` declares the right capabilities
(`maxMessageLength: 4096`, `markdownFormat: "html"`, no threads, supports
reactions and file upload) but every method throws `Not implemented`. The
real Telegram send logic lives in `execution/notify.ts`.

`src/channel/telegram/format.ts` (`TelegramFormatter`) is functional: HTML
bold/italic/link/code-block, `escapeSpecialChars` for `&<>`, and a naive
`chunkMessage` that splits on the 4096-char boundary without respecting
open HTML tags (flagged TODO at `src/channel/telegram/format.ts:44`). None
of it is on the live code path.

### 7.4 Slack and Discord stubs

Both Slack (`src/channel/slack/adapter.ts`, targets `@slack/bolt` Socket
Mode, Phase 6) and Discord (`src/channel/discord/adapter.ts`, targets
`discord.js`, Phase 3) declare their capabilities correctly but throw
`"Not implemented"` from every lifecycle and send method. Their formatters
(`format.ts` in each directory) are fully implemented, including Slack's
mrkdwn quirks (`*bold*` not `**bold**`, `<url|text>` links) and Discord's
standard Markdown with escape of `*_~\`|\\`.

`src/channel/core.ts` holds a minimal `isAllowed` helper and a TODO stub
for `loadAllowlist`. Today, Telegram's allowlist logic lives in
`src/mcp/telegram-inbound.ts:38`; lifting it into `core.ts` is a Phase-2
task.

## 8. How to add a new MCP tool

Touch-list, in order:

- Add the tool name to the `TOOL_NAMES` literal array
  (`src/mcp/tools.ts:27`). The `as const` suffix makes this a compile-time
  literal union.
- Add the JSON-Schema entry to `TOOL_DEFINITIONS`
  (`src/mcp/tools.ts:58`). Keep the shape consistent with existing entries
  (`type: "object"`, `properties`, `required`).
- Add a handler arm to the `switch` in
  `src/mcp/tool-handlers.ts` (`handleTool`, `src/mcp/tool-handlers.ts:56`).
  Return via `text(...)` / `error(...)`; let exceptions bubble to the
  wrapper for generic error wrapping.
- (Optional) If the tool should have a `bridge <cmd>` CLI counterpart, also
  add a case to `buildCliArgs` (`src/mcp/tools.ts:352`) — but only if you
  actually intend to keep the CLI fallback working; new tools do not need it.
- Regenerate the bot's `CLAUDE.md` by re-running `bridge setup-bot` so the
  new tool appears in the auto-generated docs (`src/mcp/bridge-md.ts:13`
  walks `TOOL_DEFINITIONS`).
- Add a wave-7 test mirroring the style of `tests/wave7/tool-handlers.test.ts`.
  Never call the real `claude` CLI (see `CLAUDE.md` conventions).

## 9. How to add a new channel adapter

Touch-list, in order:

- Implement `IChannelAdapter` (`src/channel/interface.ts:49`) and
  `IMessageFormatter` (`src/channel/interface.ts:37`) under
  `src/channel/<name>/{adapter,format}.ts`. Use the Slack / Discord stubs
  as skeletons — capability flags first, then lifecycle, send/edit/delete,
  optional reactions, `downloadFile`, and handler registration.
- Export both classes from `src/channel/index.ts` (follow the Telegram
  line pattern at `src/channel/index.ts:13`).
- Cut `src/execution/notify.ts` over to the adapter registry: replace the
  hard-coded `fetch` (`src/execution/notify.ts:78`) with a per-platform
  dispatch keyed on `task.channel`. This is the one required touch outside
  the `channel/` directory, and it is what actually puts the adapter on the
  live path.
- Stop hard-coding `"telegram"` in `bridge_dispatch`
  (`src/mcp/tool-handlers.ts:101`), `bridge_schedule_add`
  (`src/mcp/tool-handlers.ts:337`), and the `bridge_loop` `channel:
  chatId ? "telegram" : undefined` fallback
  (`src/mcp/tool-handlers.ts:239`). Pass the originating platform through
  from the inbound handler instead.
- Add an inbound adapter (mirroring `src/mcp/telegram-inbound.ts`) that
  produces `notifications/claude/channel` with `source: "<platform>"` in
  the meta (`src/mcp/channel-format.ts:33` takes an optional `source`
  already). Reuse `buildInboundMeta` and the queued notifier.
- Teach `src/mcp/server.ts:115` (auto-start block) to spin up the new
  inbound loop from its own env var. Each adapter should time-box its
  startup the same way `startTelegramInbound` does so a bad token cannot
  wedge the MCP server.

## 10. Gotchas

- **Notification interleaving.** MCP stdio multiplexes tool responses and
  server-initiated notifications on one stream. Always push inbound events
  through `getQueuedNotifier()` (`src/mcp/server.ts:110`) — direct
  `server.notification(...)` calls during a tool handler will corrupt the
  stream. This bit the legacy Python server hard; the queue in
  `src/mcp/server.ts:49-74` is the fix.
- **Fail-closed allowlist.** `isAllowed` at
  `src/mcp/telegram-inbound.ts:58` returns `false` when the allowlist is
  empty. A fresh install with no `config.json.allowFrom` ignores every
  message. `bridge doctor` should catch this; see `05-cli.md`.
- **20 MB attachment limit.** Telegram's Bot API caps file downloads at
  20 MB. Photos (pre-downloaded) and documents / voice / audio
  (on-demand via `download_attachment`) both enforce
  `FILE_SIZE_LIMIT = 20 * 1024 * 1024` at
  `src/mcp/telegram-inbound.ts:16` and `src/mcp/tool-handlers.ts:411`.
  Oversized files are silently skipped inbound and return an error string
  from the tool.
- **Message length limits differ wildly.** Telegram 4096, Discord 2000,
  Slack 40000. The current outbound sender does no chunking — messages
  longer than 4096 chars fail with a 400 from Telegram and the
  notification gets `markNotificationFailed`. Any real chunking must use
  the formatter's `chunkMessage` and send each chunk sequentially (and
  Telegram's naive split does not respect HTML tags — see
  `src/channel/telegram/format.ts:44`).
- **Rich formatting is not portable.** Telegram uses `parse_mode: "HTML"`
  hard-coded at `src/execution/notify.ts:86`. Discord wants standard
  Markdown; Slack wants mrkdwn (`*bold*` not `**bold**`). A multi-channel
  `Notifier` must pick the formatter by platform before constructing the
  message body, not after.
- **Rate limits.** Telegram's documented global limit is ~30 msg/sec and
  ~1 msg/sec per chat. `notify.ts` has no backoff — the notification loop
  runs every 5 s (`src/infra/startup.ts:20`) and drains all pending
  notifications per tick; a burst of completions to the same chat can
  trip 429s. The retry lives in the queue semantics, not in the sender.
- **Idempotency of notifications.** Notifications are at-least-once: a
  completion inserts one row via `handleCompletion` in `on-complete.ts`;
  the watcher may also observe the same exit and try to re-insert, which
  is guarded by DB state, not by a message-level dedupe. See
  `02-execution-pipeline.md` §5-6 for the authoritative discussion.
  Handlers that emit a notification directly (`bridge_reply`,
  `bridge_loop_notify`) bypass the queue and hit Telegram synchronously,
  so they get no retry at all.
- **`bridge_reply` has no queue.** `src/mcp/tool-handlers.ts:205` calls
  `Notifier.notify` inline and returns the boolean as success/failure.
  Transient HTTP failures lose the reply. This is acceptable because the
  bot can retry by re-invoking the tool, but it is worth knowing for
  anyone writing new user-facing tools.
- **`bridge_parse_loop_command` is a stub.** The arm at
  `src/mcp/tool-handlers.ts:320` just echoes its input. Natural-language
  loop parsing is currently done by the bot agent itself via prompts;
  don't build on this tool expecting real parsing.
- **Auto-start vs. orchestrator.** `src/mcp/server.ts:115`
  (`import.meta.main`) is the daemon entry. If you invoke `startServer()`
  directly from a test or elsewhere, nothing starts the Telegram inbound
  or the watcher — replicate `StartupOrchestrator.start`
  (`src/infra/startup.ts:30`) plus the inbound-boot block yourself.
