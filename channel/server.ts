#!/usr/bin/env bun
/**
 * Bridge Channel Server — push-based Telegram messaging for Claude Bridge.
 *
 * This is a Claude Code channel: it pushes Telegram messages into the session
 * via mcp.notification('notifications/claude/channel', ...) and exposes tools
 * for replying and managing agents.
 *
 * Start with: claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { Bot } from "grammy";
import { Database } from "bun:sqlite";
import { homedir } from "os";
import { join } from "path";
import { mkdirSync } from "fs";

import {
  initInboundTracking,
  isAllowed,
  trackInbound,
  acknowledgeInbound,
  getPendingInbound,
  pushMessage,
  downloadTelegramFile,
  safeName,
  cleanupInbox,
  FILE_SIZE_LIMIT,
  processRetries,
  processOutbound,
  bridgeCli,
  handleReply,
} from "./lib";

// --- Configuration ---

const TOKEN = process.env.TELEGRAM_BOT_TOKEN;
if (!TOKEN) {
  process.stderr.write(
    "bridge channel: TELEGRAM_BOT_TOKEN required\n" +
      "  set via env or ~/.claude-bridge/config.json\n"
  );
  process.exit(1);
}

const BRIDGE_SRC_PATH = process.env.BRIDGE_SRC_PATH ?? process.env.PYTHONPATH ?? "";
const MESSAGES_DB_PATH =
  process.env.MESSAGES_DB_PATH ??
  join(homedir(), ".claude-bridge", "messages.db");
const CONFIG_FILE = join(homedir(), ".claude-bridge", "config.json");
const INBOX_DIR = join(homedir(), ".claude-bridge", "inbox");

const RETRY_TIMEOUT_MS = 30000;
const MAX_RETRIES = 5;

// --- Database ---

mkdirSync(join(homedir(), ".claude-bridge"), { recursive: true });
mkdirSync(INBOX_DIR, { recursive: true });
const msgDb = new Database(MESSAGES_DB_PATH);
initInboundTracking(msgDb);

// --- Intervals ---

let outboundInterval: ReturnType<typeof setInterval> | null = null;
let retryInterval: ReturnType<typeof setInterval> | null = null;
let cleanupInterval: ReturnType<typeof setInterval> | null = null;

// --- MCP Server ---

const mcp = new Server(
  { name: "bridge", version: "1.0.0" },
  {
    capabilities: {
      tools: {},
      experimental: {
        "claude/channel": {},
      },
    },
    instructions: [
      'Messages from Telegram arrive as <channel source="bridge" chat_id="..." user="..." tracking_id="..." ts="...">.',
      'If the tag has an image_path attribute, Read that file — it is a photo the sender attached.',
      'If the tag has attachment_file_id, call download_attachment with that file_id to fetch the file, then Read the returned path.',
      "After processing each message: call bridge_acknowledge(tracking_id), then bridge_get_notifications(), then bridge_check_messages().",
      "bridge_check_messages catches any messages that push notifications missed while you were busy.",
      "Reply with the reply tool — pass chat_id back. Keep replies concise (users are on mobile).",
      "Use bridge_dispatch to send tasks to agents. Use bridge_status to check running tasks.",
      "Use bridge_agents to list available agents.",
    ].join("\n"),
  }
);

// --- Tool Definitions ---

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "reply",
      description: "Send a reply to a Telegram chat",
      inputSchema: {
        type: "object" as const,
        properties: {
          chat_id: { type: "string", description: "Telegram chat ID" },
          text: { type: "string", description: "Message text" },
          reply_to: { type: "string", description: "Message ID to reply to (optional)" },
        },
        required: ["chat_id", "text"],
      },
    },
    {
      name: "bridge_acknowledge",
      description: "Acknowledge that a Telegram message was processed. Call this after handling each <channel> message.",
      inputSchema: {
        type: "object" as const,
        properties: {
          tracking_id: { type: "number", description: "Tracking ID from the channel tag's tracking_id attribute" },
        },
        required: ["tracking_id"],
      },
    },
    {
      name: "bridge_dispatch",
      description: "Dispatch a task to an agent",
      inputSchema: {
        type: "object" as const,
        properties: {
          agent: { type: "string", description: "Agent name" },
          prompt: { type: "string", description: "Task prompt" },
          model: { type: "string", description: "Model override (optional)" },
        },
        required: ["agent", "prompt"],
      },
    },
    {
      name: "bridge_status",
      description: "Get status of running tasks",
      inputSchema: {
        type: "object" as const,
        properties: {
          agent: { type: "string", description: "Agent name (optional)" },
        },
      },
    },
    {
      name: "bridge_agents",
      description: "List all registered agents",
      inputSchema: { type: "object" as const, properties: {} },
    },
    {
      name: "bridge_history",
      description: "Get task history for an agent",
      inputSchema: {
        type: "object" as const,
        properties: {
          agent: { type: "string", description: "Agent name" },
          limit: { type: "number", description: "Number of tasks (default 10)" },
        },
        required: ["agent"],
      },
    },
    {
      name: "bridge_kill",
      description: "Kill a running task on an agent",
      inputSchema: {
        type: "object" as const,
        properties: {
          agent: { type: "string", description: "Agent name" },
        },
        required: ["agent"],
      },
    },
    {
      name: "bridge_create_agent",
      description: "Create a new agent for a project",
      inputSchema: {
        type: "object" as const,
        properties: {
          name: { type: "string", description: "Agent name" },
          path: { type: "string", description: "Project directory path" },
          purpose: { type: "string", description: "Agent purpose" },
          model: { type: "string", description: "Model (default: sonnet)" },
        },
        required: ["name", "path", "purpose"],
      },
    },
    {
      name: "bridge_get_notifications",
      description: "Get pending task completion notifications",
      inputSchema: { type: "object" as const, properties: {} },
    },
    {
      name: "bridge_check_messages",
      description: "Check for any pending Telegram messages that may have been missed by push. Call this after completing each response as a safety net.",
      inputSchema: { type: "object" as const, properties: {} },
    },
    {
      name: "download_attachment",
      description: "Download a file attachment from Telegram. Returns the local file path. Use when a channel message has attachment_file_id.",
      inputSchema: {
        type: "object" as const,
        properties: {
          file_id: {
            type: "string",
            description: "The attachment_file_id from the channel message meta",
          },
        },
        required: ["file_id"],
      },
    },
  ],
}));

// --- Notification Queue (prevent interleaving with tool responses) ---

let toolCallInFlight = false;
const pendingNotifications: Array<{ method: string; params: any }> = [];

function queuedNotification(msg: { method: string; params: any }) {
  if (toolCallInFlight) {
    // Don't write to stdout while a tool response is pending
    pendingNotifications.push(msg);
    process.stderr.write(`bridge channel: queued notification (tool call in flight)\n`);
  } else {
    // Fire-and-forget but catch errors to prevent unhandled rejections
    // that can kill grammY's polling loop
    Promise.resolve(mcp.notification(msg)).catch((err) => {
      process.stderr.write(`bridge channel: notification error: ${err}\n`);
    });
  }
}

function flushPendingNotifications() {
  while (pendingNotifications.length > 0) {
    const msg = pendingNotifications.shift()!;
    // Catch both sync throws and async rejections
    try {
      Promise.resolve(mcp.notification(msg)).catch((err) => {
        process.stderr.write(`bridge channel: flush notification error: ${err}\n`);
      });
    } catch (err) {
      process.stderr.write(`bridge channel: flush notification error: ${err}\n`);
    }
  }
}

// --- Tool Handlers ---

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  toolCallInFlight = true;
  const { name, arguments: args } = req.params;

  try {
    switch (name) {
      case "reply": {
        const { chat_id, text, reply_to } = args as { chat_id: string; text: string; reply_to?: string };
        const result = await handleReply(
          async (cid, txt, opts) => { await bot.api.sendMessage(cid, txt, opts ?? {}); },
          chat_id, text, reply_to, CONFIG_FILE
        );
        return { content: [{ type: "text", text: result }] };
      }

      case "bridge_acknowledge": {
        const { tracking_id } = args as { tracking_id: number };
        const ok = acknowledgeInbound(msgDb, tracking_id);
        return { content: [{ type: "text", text: ok ? "acknowledged" : "not found" }] };
      }

      case "bridge_dispatch": {
        const { agent, prompt, model } = args as { agent: string; prompt: string; model?: string };
        const cliArgs = [agent, prompt];
        if (model) cliArgs.push("--model", model);
        const output = bridgeCli(BRIDGE_SRC_PATH, "dispatch", cliArgs);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_status": {
        const { agent } = (args ?? {}) as { agent?: string };
        const output = bridgeCli(BRIDGE_SRC_PATH, "status", agent ? [agent] : []);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_agents": {
        const output = bridgeCli(BRIDGE_SRC_PATH, "list-agents");
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_history": {
        const { agent, limit } = args as { agent: string; limit?: number };
        const cliArgs = [agent];
        if (limit) cliArgs.push("--limit", String(limit));
        const output = bridgeCli(BRIDGE_SRC_PATH, "history", cliArgs);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_kill": {
        const { agent } = args as { agent: string };
        const output = bridgeCli(BRIDGE_SRC_PATH, "kill", [agent]);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_create_agent": {
        const { name: agentName, path, purpose, model } = args as { name: string; path: string; purpose: string; model?: string };
        const cliArgs = [agentName, path, "--purpose", purpose];
        if (model) cliArgs.push("--model", model);
        const output = bridgeCli(BRIDGE_SRC_PATH, "create-agent", cliArgs);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_get_notifications": {
        try {
          const output = bridgeCli(BRIDGE_SRC_PATH, "status");
          return { content: [{ type: "text", text: output }] };
        } catch {
          return { content: [{ type: "text", text: "No pending notifications" }] };
        }
      }

      case "bridge_check_messages": {
        const pending = getPendingInbound(msgDb);
        if (pending.length === 0) {
          return { content: [{ type: "text", text: "No pending messages" }] };
        }
        // Return pending messages as tool output so Claude sees them directly
        const messages = pending.map((m) => ({
          tracking_id: m.id,
          chat_id: m.chat_id,
          user: m.username,
          text: m.message_text,
        }));
        // NOTE: Don't re-push here — we're inside a tool call.
        // The messages are returned as text. Notifications will flush after this tool returns.
        return {
          content: [{
            type: "text",
            text: JSON.stringify({ pending_count: pending.length, messages }),
          }],
        };
      }

      case "download_attachment": {
        const { file_id } = args as { file_id: string };
        if (!file_id) {
          return { content: [{ type: "text", text: "Error: file_id is required" }], isError: true };
        }

        const localPath = await downloadTelegramFile(
          (fid) => bot.api.getFile(fid),
          TOKEN,
          file_id,
          INBOX_DIR
        );

        if (!localPath) {
          return {
            content: [{
              type: "text",
              text: "Error: failed to download file. Possible causes:\n" +
                    "- File has expired (Telegram files expire after ~1 hour)\n" +
                    "- File exceeds 20MB size limit\n" +
                    "- Network error or timeout"
            }],
            isError: true,
          };
        }

        return { content: [{ type: "text", text: localPath }] };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (err: any) {
    return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
  } finally {
    toolCallInFlight = false;
    // Flush any notifications that arrived during the tool call
    flushPendingNotifications();
  }
});

// --- Telegram Bot ---

const bot = new Bot(TOKEN);
let botUsername = "";

bot.catch((err) => {
  // Log but don't rethrow — prevents polling loop from dying on transient errors
  process.stderr.write(`bridge channel: grammy error: ${err.message}\n`);
  process.stderr.write(`bridge channel: grammy error stack: ${err.stack}\n`);
});

bot.on("message:text", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const text = ctx.message.text;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) {
    process.stderr.write(`bridge channel: rejected message from non-allowed user ${userId}\n`);
    return;
  }

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    // Use queued notification to avoid interleaving with tool responses
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts);
  } catch (err) {
    process.stderr.write(`bridge channel: message handler error: ${err}\n`);
  }
});

bot.on("message:photo", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const caption = ctx.message.caption ?? "(photo)";
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) {
    process.stderr.write(`bridge channel: rejected photo from non-allowed user ${userId}\n`);
    return;
  }

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();

    // Download highest resolution photo (last element = largest)
    const photos = ctx.message.photo;
    const best = photos[photos.length - 1];
    const imagePath = await downloadTelegramFile(
      (fid) => ctx.api.getFile(fid),
      TOKEN,
      best.file_id,
      INBOX_DIR,
      undefined,
      best.file_size  // Pass file size for pre-download limit check
    );

    // Notify user if photo was rejected due to size
    if (!imagePath && best.file_size && best.file_size > FILE_SIZE_LIMIT) {
      await bot.api.sendMessage(chatId,
        `Photo too large (${(best.file_size / 1024 / 1024).toFixed(1)}MB). ` +
        `Maximum: ${FILE_SIZE_LIMIT / 1024 / 1024}MB.`
      );
      return;
    }

    const trackingId = trackInbound(msgDb, chatId, userId, username, caption, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, caption, messageId, ts, {
      image_path: imagePath,
    });

    process.stderr.write(`bridge channel: photo received from ${username}, path=${imagePath}\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: photo handler error: ${err}\n`);
  }
});

bot.on("message:document", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) {
    process.stderr.write(`bridge channel: rejected document from non-allowed user ${userId}\n`);
    return;
  }

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const doc = ctx.message.document;
    const name = safeName(doc.file_name);

    // Reject oversized documents before processing
    if (doc.file_size && doc.file_size > FILE_SIZE_LIMIT) {
      await bot.api.sendMessage(chatId,
        `File "${name ?? "file"}" too large (${(doc.file_size / 1024 / 1024).toFixed(1)}MB). ` +
        `Maximum: ${FILE_SIZE_LIMIT / 1024 / 1024}MB.`
      );
      return;
    }

    const text = ctx.message.caption ?? `(document: ${name ?? "file"})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "document",
      attachment_file_id: doc.file_id,
      attachment_size: doc.file_size ? String(doc.file_size) : undefined,
      attachment_mime: doc.mime_type,
      attachment_name: name,
    });

    process.stderr.write(
      `bridge channel: document received from ${username}: ${name ?? "unnamed"} ` +
      `(${doc.mime_type}, ${doc.file_size} bytes)\n`
    );
  } catch (err) {
    process.stderr.write(`bridge channel: document handler error: ${err}\n`);
  }
});

bot.on("message:voice", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const voice = ctx.message.voice;
    const duration = voice.duration;
    const text = ctx.message.caption ?? `(voice message, ${duration}s)`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "voice",
      attachment_file_id: voice.file_id,
      attachment_size: voice.file_size ? String(voice.file_size) : undefined,
      attachment_mime: voice.mime_type ?? "audio/ogg",
    });

    process.stderr.write(`bridge channel: voice received from ${username} (${duration}s)\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: voice handler error: ${err}\n`);
  }
});

bot.on("message:audio", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const audio = ctx.message.audio;
    const name = safeName(audio.file_name);
    const title = audio.title ?? name ?? "audio";
    const text = ctx.message.caption ?? `(audio: ${title})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "audio",
      attachment_file_id: audio.file_id,
      attachment_size: audio.file_size ? String(audio.file_size) : undefined,
      attachment_mime: audio.mime_type,
      attachment_name: name,
    });

    process.stderr.write(`bridge channel: audio received from ${username}: ${title}\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: audio handler error: ${err}\n`);
  }
});

bot.on("message:video", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const video = ctx.message.video;
    const name = safeName(video.file_name);
    const text = ctx.message.caption ?? `(video: ${name ?? "video"}, ${video.duration}s)`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "video",
      attachment_file_id: video.file_id,
      attachment_size: video.file_size ? String(video.file_size) : undefined,
      attachment_mime: video.mime_type,
      attachment_name: name,
    });

    process.stderr.write(`bridge channel: video received from ${username}: ${name ?? "video"} (${video.duration}s)\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: video handler error: ${err}\n`);
  }
});

bot.on("message:video_note", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const vn = ctx.message.video_note;
    const text = `(video note, ${vn.duration}s)`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "video_note",
      attachment_file_id: vn.file_id,
      attachment_size: vn.file_size ? String(vn.file_size) : undefined,
    });

    process.stderr.write(`bridge channel: video_note received from ${username} (${vn.duration}s)\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: video_note handler error: ${err}\n`);
  }
});

bot.on("message:sticker", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const sticker = ctx.message.sticker;
    const emoji = sticker.emoji ?? "";
    const setName = sticker.set_name ?? "";
    const text = `(sticker ${emoji}${setName ? ` from ${setName}` : ""})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts);
    // Sticker: text only, NO attachment meta — emoji is sufficient context

    process.stderr.write(`bridge channel: sticker received from ${username}: ${emoji}\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: sticker handler error: ${err}\n`);
  }
});

bot.on("message:animation", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const anim = ctx.message.animation;
    const name = safeName(anim.file_name);
    const text = ctx.message.caption ?? `(GIF: ${name ?? "animation"})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "animation",
      attachment_file_id: anim.file_id,
      attachment_size: anim.file_size ? String(anim.file_size) : undefined,
      attachment_mime: anim.mime_type,
      attachment_name: name,
    });
  } catch (err) {
    process.stderr.write(`bridge channel: animation handler error: ${err}\n`);
  }
});

// --- Polling with auto-restart ---

let pollingActive = false;

function startPolling(dropPending = true) {
  pollingActive = true;
  bot.start({
    drop_pending_updates: dropPending,
    onStart: () => {
      process.stderr.write("bridge channel: polling started\n");
    },
  }).then(() => {
    // bot.start() resolves when polling stops (e.g. bot.stop() called)
    // If we didn't intend to stop, restart
    if (pollingActive && !cleanedUp) {
      process.stderr.write("bridge channel: polling stopped unexpectedly, restarting in 3s...\n");
      setTimeout(() => {
        if (pollingActive && !cleanedUp) {
          startPolling(false);
        }
      }, 3000);
    }
  }).catch((err) => {
    process.stderr.write(`bridge channel: polling error: ${err}\n`);
    // Restart after error
    if (pollingActive && !cleanedUp) {
      process.stderr.write("bridge channel: restarting polling in 5s...\n");
      setTimeout(() => {
        if (pollingActive && !cleanedUp) {
          startPolling(false);
        }
      }, 5000);
    }
  });
}

// --- Startup ---

async function main() {
  const me = await bot.api.getMe();
  botUsername = me.username ?? "";
  process.stderr.write(`bridge channel: bot @${botUsername} connected\n`);

  startPolling();

  // Queued notifier for background tasks (avoids interleaving with tool responses)
  const bgNotifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };

  // Outbound poller
  outboundInterval = setInterval(async () => {
    try {
      await processOutbound(
        msgDb, bgNotifier,
        async (chatId, text) => { await bot.api.sendMessage(chatId, text); }
      );
    } catch (err) {
      process.stderr.write(`bridge channel: outbound poller error: ${err}\n`);
    }
  }, 2000);

  // Cleanup inbox on startup
  cleanupInbox(INBOX_DIR);

  // Periodic cleanup every 6 hours
  cleanupInterval = setInterval(() => {
    try {
      const deleted = cleanupInbox(INBOX_DIR);
      if (deleted > 0) {
        process.stderr.write(`bridge channel: inbox cleanup: ${deleted} files removed\n`);
      }
    } catch (err) {
      process.stderr.write(`bridge channel: cleanup interval error: ${err}\n`);
    }
  }, 6 * 60 * 60 * 1000);

  // Inbound retry engine
  retryInterval = setInterval(() => {
    try {
      processRetries(
        msgDb, bgNotifier,
        async (chatId, text) => { await bot.api.sendMessage(chatId, text); },
        RETRY_TIMEOUT_MS, MAX_RETRIES
      );
    } catch (err) {
      process.stderr.write(`bridge channel: retry engine error: ${err}\n`);
    }
  }, RETRY_TIMEOUT_MS);

  // Connect MCP
  const transport = new StdioServerTransport();
  await mcp.connect(transport);

  process.stdin.on("end", () => {
    process.stderr.write("bridge channel: stdin closed, shutting down\n");
    cleanup();
  });
  process.stdin.on("close", () => {
    process.stderr.write("bridge channel: stdin close event, shutting down\n");
    cleanup();
  });
}

let cleanedUp = false;
function cleanup() {
  if (cleanedUp) return;
  cleanedUp = true;
  pollingActive = false;
  if (outboundInterval) clearInterval(outboundInterval);
  if (retryInterval) clearInterval(retryInterval);
  if (cleanupInterval) clearInterval(cleanupInterval);
  try { msgDb.close(); } catch {}
  // Force exit after 3s if bot.stop() hangs
  const exitTimer = setTimeout(() => process.exit(1), 3000);
  if (typeof (exitTimer as any).unref === "function") (exitTimer as any).unref();
  // Await bot.stop() properly so it can flush pending messages before exit
  Promise.resolve(
    (async () => { try { await bot.stop(); } catch {} })()
  ).then(() => {
    clearTimeout(exitTimer);
    process.exit(0);
  });
}

process.on("SIGINT", cleanup);
process.on("SIGTERM", cleanup);
process.on("unhandledRejection", (err) => {
  process.stderr.write(`bridge channel: unhandled rejection: ${err}\n`);
});
process.on("uncaughtException", (err) => {
  process.stderr.write(`bridge channel: uncaught exception: ${err}\n`);
});

main().catch((err) => {
  process.stderr.write(`bridge channel: fatal: ${err}\n`);
  process.exit(1);
});
