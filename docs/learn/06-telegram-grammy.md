# 06 — Telegram Bots and Grammy

This guide teaches you what you need to know to maintain the Telegram side
of claude-bridge. It assumes you have never written a Telegram bot and have
never used Grammy. By the end you will understand how the Bot API delivers
updates, how Grammy wraps it, and which pieces of that knowledge the bridge
leans on.

The bridge pins `grammy ^1.21.0` in `package.json`.

---

## 1. How Telegram bots work

A Telegram "bot" is a normal Telegram account whose messages are driven by
a program instead of a human. You don't ssh into it or host it on Telegram's
servers — your code runs wherever you like, and it talks to a REST-style
HTTPS API at `https://api.telegram.org`.

### BotFather

You create bots by talking to a meta-bot called `@BotFather` inside the
Telegram app. It's a conversational wizard:

1. Open Telegram, search for `@BotFather`, and start a chat.
2. Send `/newbot`.
3. Pick a display name (e.g. `My Bridge Bot`).
4. Pick a username (must end in `bot`, e.g. `my_bridge_bot`).
5. BotFather replies with an HTTP API token that looks like:

   ```
   123456789:AAE-abcDEFghijKLMnopQRStuvWXYz1234567
   ```

That token is the bot's identity. Anyone who has it can fully impersonate
your bot. Treat it like a password: never commit it, rotate via
BotFather's `/revoke` if it leaks. In the bridge it lives in `config.json`
under `telegram_token`, and each `CLAUDE_BRIDGE_HOME` has its own.

BotFather also configures the bot's description, profile picture, privacy
mode (what it can see in groups), and the slash-command menu. We'll come
back to the command menu in §8.

### What the Bot API lets you do

Once you have a token, you call methods like `sendMessage`, `getFile`,
`setMyCommands` by POSTing to `https://api.telegram.org/bot<TOKEN>/<method>`
with JSON. The response is always `{ ok: true, result: ... }` or
`{ ok: false, description: "..." }`.

### Rate limits

Roughly 30 messages/second globally per bot, ~1 per second per private
chat, ~20 per minute per group. Exceeding a limit returns HTTP 429 with a
`retry_after` hint. Grammy surfaces this as an error you can catch.

---

## 2. Update delivery: long polling vs webhooks

Your bot needs a way to find out that a user sent it a message. The Bot API
gives you two choices.

**Long polling.** Your program calls `getUpdates` over HTTPS. If there are
no new updates, the server holds the connection open (up to ~50 seconds),
then returns an empty array. If something happens, it returns immediately.
Your code loops: call, wait, handle, call again. No public URL needed.
Simple to run on a laptop, inside a home LAN, behind NAT, anywhere.

**Webhooks.** You tell Telegram "POST updates to `https://example.com/my-bot`"
via `setWebhook`, and Telegram calls you whenever something happens. No
polling loop, scales better, but you need a public HTTPS endpoint with a
valid certificate. You also need to be careful about concurrent requests
and retries.

### What the bridge uses

The bridge uses **long polling**. See `src/mcp/telegram-inbound.ts`:

```ts
const startPromise: Promise<void> = bot.start({
  drop_pending_updates: true,
  onStart: () => { /* ... */ },
});
```

`bot.start()` without a webhook config starts a long-polling loop.
`drop_pending_updates: true` tells Telegram to throw away anything queued
from a previous run — otherwise a bot that was offline for an hour would
wake up and replay an hour of backlog.

This choice is right for claude-bridge because:

- The bridge runs as a local daemon, often on a laptop. There's no public URL.
- Traffic is one user (you), not a million — the throughput cost of polling
  is invisible.
- Failover is trivial: kill the process, start it again, polling resumes.

The one constraint long polling imposes: **only one process can poll with
a given token at a time**. If you start two bridge instances with the same
token, Telegram will return 409 Conflict and both will misbehave. See §11.

---

## 3. Update types

Everything Telegram tells your bot arrives as an `Update` object. An Update
always has an `update_id` and then exactly one optional payload field. The
important ones:

- `message` — a new message sent to the bot (text, photo, voice, document, etc.).
- `edited_message` — an existing message was edited.
- `channel_post` / `edited_channel_post` — posts in a channel the bot is in.
- `callback_query` — a user pressed an inline-keyboard button.
- `inline_query` — someone typed `@your_bot query` in any chat (inline mode).
- `chosen_inline_result` — follow-up to an inline query.
- `my_chat_member` / `chat_member` — someone's bot-membership changed (added/removed).

claude-bridge only cares about **`message`** today, and specifically these
sub-kinds (see `src/mcp/telegram-inbound.ts`):

- `message:text`
- `message:photo`
- `message:document`
- `message:voice`
- `message:audio`

Everything else is ignored. No callback queries, no inline mode. That's
intentional: the bridge is a text-and-attachment pipe, not an interactive UI.

---

## 4. What Grammy is

Grammy (`grammy.dev`) is a TypeScript Telegram bot framework. Three things
make it nice:

1. **Type safety.** Its types are generated from the official Bot API schema.
   `ctx.message.photo` is strongly typed as `PhotoSize[]`. No guessing what
   fields exist on what update kind.
2. **Middleware model.** Like Express: you register handlers with
   `bot.use`, `bot.on`, `bot.command`, and Grammy runs them in order,
   each calling `next()` to pass control on.
3. **Actively maintained.** One lead maintainer, fast releases, good docs.

### Why Grammy, not telegraf?

`telegraf` is the other major Node Telegram library. It predates Grammy,
but its types are hand-maintained and lag the API. Grammy's type quality
and its first-class TypeScript story were the tiebreaker for this project.
Both libraries use the same middleware shape, so the concepts you learn
here mostly transfer.

---

## 5. Hello world Grammy bot

Let's build the smallest thing that works. You'll DM your bot `/ping`
and it'll reply `pong`.

### Step 1 — Install

In an empty directory:

```bash
bun init -y
bun add grammy
```

### Step 2 — Get a token

In Telegram, talk to `@BotFather`, send `/newbot`, and copy the token it
gives you. Put it in an env var so you don't paste it into your source:

```bash
export TELEGRAM_BOT_TOKEN="123456789:AAE-abc..."
```

### Step 3 — Write the bot

Create `bot.ts`:

```ts
import { Bot } from "grammy";

const token = process.env.TELEGRAM_BOT_TOKEN;
if (!token) throw new Error("TELEGRAM_BOT_TOKEN is required");

const bot = new Bot(token);

bot.command("ping", async (ctx) => {
  await ctx.reply("pong");
});

bot.catch((err) => {
  console.error("grammy error:", err);
});

await bot.start({
  onStart: (info) => console.log(`started as @${info.username}`),
});
```

### Step 4 — Run it

```bash
bun run bot.ts
```

You should see `started as @my_bridge_bot`. Open Telegram, find your bot
by username, tap Start, send `/ping`. You'll get `pong` back. If you
Ctrl-C the process, the bot goes silent.

### What each line did

- `new Bot(token)` — construct a client. No network yet.
- `bot.command("ping", handler)` — handle `/ping`. Grammy parses
  `/<name>` out of message text and dispatches.
- `ctx.reply("pong")` — send text back to the same chat. Sugar for
  `ctx.api.sendMessage(ctx.chat.id, "pong")`.
- `bot.catch(fn)` — global error handler. Without it, errors crash the
  polling loop.
- `await bot.start(...)` — begin long polling. Does not return until the
  bot is stopped; it awaits the polling loop itself.

---

## 6. Core concepts

### Context (`ctx`)

Every handler gets a `Context` bundling the update and shortcuts:

- `ctx.update` — the raw `Update`.
- `ctx.message` — `ctx.update.message`, if any.
- `ctx.from` — sender (`User`: `id`, `username`, `first_name`).
- `ctx.chat` — chat (`id`, `type`, etc.).
- `ctx.api` — fully-typed client for every Bot API method.
- `ctx.reply(text, opts?)` — send to `ctx.chat`.
- `ctx.replyWithPhoto`, `ctx.replyWithDocument`, etc.

You never construct a `Context` yourself; Grammy makes one per update.

### Middleware

Grammy is middleware-based:

```ts
bot.use(async (ctx, next) => {
  const start = Date.now();
  await next();
  console.log(`handled update in ${Date.now() - start}ms`);
});

bot.use(async (ctx, next) => {
  if (ctx.from?.id !== 12345) return; // silently drop
  await next();
});

bot.command("ping", (ctx) => ctx.reply("pong"));
```

Each middleware decides whether to call `next()`. If it doesn't,
downstream middleware never runs. This is how the bridge enforces its
allowlist — a "not allowed" message just returns without calling `next`.
(Today the bridge's allowlist check is inlined in each handler, but the
same pattern works as middleware.)

Order matters: register the logger first, auth second, feature handlers
last.

### Filters

Rather than `if (ctx.message?.text === "/ping")` everywhere, Grammy lets
you declare what you care about:

```ts
bot.command("help", ...)          // /help
bot.hears(/^hello/i, ...)         // regex on text
bot.on("message:text", ...)       // any text message
bot.on("message:photo", ...)      // any photo
bot.on(":text", ...)              // text in any update kind
bot.on("callback_query:data", ...)
```

Filter strings combine with `:`. `message:photo` narrows to updates that
are messages and contain a photo. Under the hood, a filter is just a
middleware that calls `next()` only on matching updates.

### Sending messages

Three common ways:

```ts
await ctx.reply("hi");                          // to current chat
await ctx.api.sendMessage(chatId, "hi");        // to any chat
await bot.api.sendMessage(chatId, "hi");        // outside a handler
```

`ctx.api` and `bot.api` are the same `Api` client; use whichever is
reachable in scope.

**Formatting modes.** Pass `parse_mode` in the send options:

```ts
await ctx.reply("*bold*", { parse_mode: "MarkdownV2" });
await ctx.reply("<b>bold</b>", { parse_mode: "HTML" });
await ctx.reply("plain text");                          // no parsing
```

MarkdownV2 requires you to escape a *lot* of characters (see §11). HTML
is much easier to get right — you only need to escape `<`, `>`, and `&`.
**The bridge uses HTML** for outbound messages. See
`src/channel/telegram/format.ts` and `src/execution/notify.ts` — both
set `parse_mode: "HTML"`.

### Session plugin

Grammy's `session` middleware stores per-user state keyed by
`ctx.chat.id` — handy for wizards. **The bridge does not use it.** All
state lives in SQLite (`bridge.db`, `messages.db`), which is durable
across restarts and shared across processes. You don't need to learn
session to maintain the bridge, but it's the first thing to reach for if
you add a short-lived conversational flow.

### Error handling

If any middleware throws, Grammy routes the error through the handler
registered with `bot.catch`:

```ts
bot.catch((err) => {
  console.error("handler for", err.ctx.update.update_id, "failed:", err.error);
});
```

Without this, the polling loop crashes on the first unhandled exception.
`src/mcp/telegram-inbound.ts` registers a `bot.catch` that writes to
stderr and continues.

---

## 7. Files, photos, and attachments

Telegram never sends file bytes in an update. Every uploaded file gets a
`file_id` (an opaque string) and you download on demand:

1. `getFile(fileId)` returns `{ file_path, file_size, file_unique_id }`.
2. `GET https://api.telegram.org/file/bot<TOKEN>/<file_path>` returns bytes.

Gotchas:

- `file_id` is **bot-scoped**. A file_id from bot A isn't valid for bot B.
- `file_id` can change across uploads of the "same" file. For stable
  identity, use `file_unique_id`.
- Downloads cap at 20 MB. The bridge hard-codes `FILE_SIZE_LIMIT` in
  `telegram-inbound.ts`.
- Photos arrive as an **array** of `PhotoSize`, one per resolution. The
  last element is the original; the bridge picks that one:
  ```ts
  const best = ctx.message.photo[ctx.message.photo.length - 1];
  ```

To upload back, use Grammy's `InputFile`, or reuse an existing `file_id`
(free and instant, Telegram just moves a reference):

```ts
import { InputFile } from "grammy";
await ctx.replyWithPhoto(new InputFile("./cat.jpg"));
```

---

## 8. Commands and the slash-menu

When a user types `/` in a chat with your bot, Telegram pops up a menu
suggesting commands. That menu is populated from whatever you've set with
`setMyCommands`.

```ts
await bot.api.setMyCommands([
  { command: "ping", description: "health check" },
  { command: "time", description: "current UTC time" },
]);
```

Do this **once at startup** (or after you change the command list). Cached
menus update within a few minutes on clients.

`bot.command("ping", handler)` handles the incoming `/ping`, but it does
*not* automatically register the command in the menu. The two steps are
independent: you can have commands that show up in the menu but aren't
handled (ghosts), or commands that are handled but hidden from the menu
(debug/secret commands).

Some commands are conventional:

- `/start` — the first message a user sends after tapping "Start" on your
  bot's profile. Good place to say hello and explain what the bot does.
- `/help` — show help.
- `/cancel` — abort a multi-step flow (if you have one).

---

## 9. Deploying a bot

A few production notes:

- **One poller per token.** Two processes `bot.start()`-ing with the same
  token gives 409 Conflict. The bridge's `daemon.ts` owns the lifecycle
  so this can't happen accidentally.
- **Restart semantics.** `drop_pending_updates: true` (the bridge's
  choice) skips anything queued during downtime. Without it, a bot that
  was down for an hour wakes up and replays an hour of backlog.
- **Long-polling failover.** Telegram queues missed updates for ~24
  hours. You only lose messages if you stay down longer or deliberately
  drop pending updates.
- **Log `update_id`** on every handler — it's the key you'll need to
  debug "why didn't my bot reply?"
- **Secrets.** Don't bake the token into CI logs or Docker layers. Mount
  it as a runtime secret.

---

## 10. How claude-bridge uses Grammy

Two files to know: `src/mcp/telegram-inbound.ts` (the only place Grammy
is used as a framework) and `src/execution/notify.ts` (outbound replies
via raw `fetch`).

### Inbound

When the MCP server starts, it calls `startTelegramInbound`, which:

1. Loads an allowlist from `config.json` (fail-closed: empty allowlist
   means ignore everyone).
2. Creates `new Bot(token)`.
3. Registers handlers for `message:text`, `message:photo`,
   `message:document`, `message:voice`, `message:audio`.
4. Each handler rejects non-allowlisted users, downloads any attachment
   into `{bridgeHome}/inbox/`, and emits an MCP notification
   `notifications/claude/channel` with the content and metadata.
5. Calls `bot.start({ drop_pending_updates: true })` (long polling)
   racing a 3-second timeout so a bad token doesn't block MCP startup.

Claude Code, subscribed to that notification, decides what to do next.

### Outbound

When Claude Code wants to reply, it writes a notification to SQLite. A
loop in `src/execution/notify.ts` picks it up and POSTs directly to the
Bot API:

```ts
await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ chat_id, text: message, parse_mode: "HTML" }),
});
```

This bypasses Grammy. It's deliberate: outbound doesn't need middleware
or typed contexts, just a JSON POST. Keeping it as raw `fetch` decouples
the notify loop from Grammy's lifecycle and makes it trivially mockable
in tests.

### Token and isolation

The token comes from `config.json` (`telegram_token`), falling back to
`TELEGRAM_BOT_TOKEN`. Each `CLAUDE_BRIDGE_HOME` has its own config, so
running a second instance alongside the main one requires a **different**
BotFather bot — same-token double polling gives 409.

For the full wiring diagram, see `docs/specs/04-mcp-and-channels.md`.

---

## 11. Pitfalls

- **The token is a god key.** A leak means someone else owns your bot.
  Rotate immediately via `@BotFather` → `/revoke`.
- **Two pollers at once = 409 Conflict.** Usually a stale daemon from a
  crashed previous run. `bridge stop && bridge start`, or check
  `bridge daemon-status` for zombies.
- **MarkdownV2 escaping is a minefield.** Any of
  `_ * [ ] ( ) ~ \` > # + - = | { } . !` must be backslash-escaped, even
  inside some code spans. This is why the bridge uses HTML — you only
  escape `<`, `>`, and `&`.
- **Network flakiness.** `api.telegram.org` will occasionally hiccup.
  Grammy retries polling internally; for your own `fetch` outbound calls,
  wrap in a retry with backoff.
- **Groups vs private chats.** `ctx.chat.type` is `"private"`, `"group"`,
  `"supergroup"`, or `"channel"`. In groups the bot may not see every
  message (Privacy Mode). In channels it posts *as* the channel.
  Permissions differ.
- **`ctx.message` can be undefined** on non-message updates. For
  `callback_query`, the real payload is `ctx.callbackQuery.data`.

---

## 12. Exercises

Do these after reading §5. They're small and they exercise the exact
concepts the bridge uses.

### Exercise 1 — echo in uppercase

Write a bot that replies to every text message with the same text in
uppercase.

```ts
bot.on("message:text", async (ctx) => {
  await ctx.reply(ctx.message.text.toUpperCase());
});
```

Run it, DM the bot `hello world`, expect `HELLO WORLD`. Now send a photo
with no caption — notice your handler doesn't fire, because
`message:text` doesn't match photos.

### Exercise 2 — `/time` command with menu entry

Add a `/time` command that replies with the current UTC time:

```ts
bot.command("time", async (ctx) => {
  await ctx.reply(`UTC: ${new Date().toISOString()}`);
});
```

Then teach the client to suggest it:

```ts
await bot.api.setMyCommands([
  { command: "time", description: "current UTC time" },
]);
```

Restart the bot, then in the Telegram app close and reopen the chat. Type
`/` — you should see `time` in the menu. Tap it.

### Exercise 3 — branch on chat type

Make the bot respond differently depending on where it was addressed:

```ts
bot.command("hi", async (ctx) => {
  if (ctx.chat.type === "private") {
    await ctx.reply("hi, just the two of us");
  } else {
    await ctx.reply(`hi everyone in ${ctx.chat.title ?? "this group"}`);
  }
});
```

To test the group path you'll need to add your bot to a group (Telegram →
group → Members → Add → search for your bot). In BotFather, you may also
need to disable Privacy Mode (`/setprivacy` → `Disable`) so the bot sees
non-command messages — commands themselves it always sees.

---

## 13. Further reading

Canonical sources only.

- Grammy home: https://grammy.dev
- Grammy getting started: https://grammy.dev/guide/getting-started
- Grammy context: https://grammy.dev/guide/context
- Grammy middleware: https://grammy.dev/guide/middleware
- Telegram Bot API reference: https://core.telegram.org/bots/api
- Telegram bot platform overview: https://core.telegram.org/bots
- Telegram bot features (menu, commands, etc.): https://core.telegram.org/bots/features

When Grammy's docs and the Bot API docs disagree, the Bot API is the
source of truth — Grammy is a wrapper. When your types say one thing and
Grammy's docs say another, trust the generated types.
