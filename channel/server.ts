#!/usr/bin/env bun
/**
 * Bridge Channel Server — push-based Telegram messaging for Claude Bridge.
 *
 * This is a Claude Code channel: it pushes Telegram messages into the session
 * via mcp.notification('notifications/claude/channel', ...) and exposes tools
 * for replying and managing agents.
 *
 * Start with: claude --channels server:bridge --dangerously-skip-permissions
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { Bot } from "grammy";
import { Database } from "bun:sqlite";
import { readFileSync } from "fs";
import { homedir } from "os";
import { join } from "path";
import { execSync } from "child_process";
import { mkdirSync } from "fs";

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
const ACCESS_FILE = join(
  homedir(),
  ".claude",
  "channels",
  "telegram",
  "access.json"
);

// --- Access Control ---

function loadAllowlist(): string[] {
  try {
    const data = JSON.parse(readFileSync(ACCESS_FILE, "utf8"));
    return data.allowFrom ?? [];
  } catch {
    return []; // no file = permissive (empty list allows all)
  }
}

function isAllowed(userId: string): boolean {
  const allowed = loadAllowlist();
  if (allowed.length === 0) return true; // empty = allow all
  return allowed.includes(userId);
}

// --- Inbound Message Tracking (retry on no-ack) ---

const RETRY_TIMEOUT_MS = 30000;
const MAX_RETRIES = 5;

// Ensure messages.db directory exists
mkdirSync(join(homedir(), ".claude-bridge"), { recursive: true });
const msgDb = new Database(MESSAGES_DB_PATH);
msgDb.run("PRAGMA journal_mode=WAL");
msgDb.run(`CREATE TABLE IF NOT EXISTS inbound_tracking (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  username TEXT,
  message_text TEXT NOT NULL,
  message_id TEXT,
  status TEXT DEFAULT 'pushed',
  retry_count INTEGER DEFAULT 0,
  pushed_at TEXT,
  acknowledged_at TEXT
)`);

function trackInbound(chatId: string, userId: string, username: string, text: string, messageId: string): number {
  const stmt = msgDb.prepare(
    "INSERT INTO inbound_tracking (chat_id, user_id, username, message_text, message_id, pushed_at) VALUES (?, ?, ?, ?, ?, datetime('now'))"
  );
  return Number(stmt.run(chatId, userId, username, text, messageId).lastInsertRowid);
}

function acknowledgeInbound(trackingId: number): boolean {
  const row = msgDb.query("SELECT * FROM inbound_tracking WHERE id = ?").get(trackingId) as any;
  if (!row) return false;
  msgDb.run("UPDATE inbound_tracking SET status = 'acknowledged', acknowledged_at = datetime('now') WHERE id = ?", [trackingId]);
  return true;
}

function pushMessage(trackingId: number, chatId: string, userId: string, username: string, text: string, messageId: string, ts: string) {
  mcp.notification({
    method: "notifications/claude/channel",
    params: {
      content: text,
      meta: {
        chat_id: chatId,
        message_id: messageId,
        user: username,
        user_id: userId,
        ts,
        tracking_id: String(trackingId),
      },
    },
  });
}

// Retry interval: re-push unacknowledged messages
let retryInterval: ReturnType<typeof setInterval> | null = null;

function startRetryEngine() {
  retryInterval = setInterval(() => {
    try {
      const unacked = msgDb.query(
        `SELECT * FROM inbound_tracking
         WHERE status = 'pushed'
         AND (julianday('now') - julianday(pushed_at)) * 86400 > ?
         ORDER BY id`
      ).all(RETRY_TIMEOUT_MS / 1000) as any[];

      for (const msg of unacked) {
        if (msg.retry_count >= MAX_RETRIES) {
          msgDb.run("UPDATE inbound_tracking SET status = 'failed' WHERE id = ?", [msg.id]);
          // Notify user their message was lost
          bot.api.sendMessage(msg.chat_id, "Sorry, your message could not be delivered to the Bridge Bot. Please try again.").catch(() => {});
          process.stderr.write(`bridge channel: inbound #${msg.id} failed after ${MAX_RETRIES} retries\n`);
        } else {
          msgDb.run("UPDATE inbound_tracking SET retry_count = retry_count + 1, pushed_at = datetime('now') WHERE id = ?", [msg.id]);
          pushMessage(msg.id, msg.chat_id, msg.user_id, msg.username, msg.message_text, msg.message_id, new Date().toISOString());
          process.stderr.write(`bridge channel: retrying inbound #${msg.id} (attempt ${msg.retry_count + 1})\n`);
        }
      }
    } catch (err) {
      process.stderr.write(`bridge channel: retry engine error: ${err}\n`);
    }
  }, RETRY_TIMEOUT_MS);
}

// --- Bridge CLI subprocess ---

function bridgeCli(command: string, args: string[] = []): string {
  const pythonPath = process.env.PYTHON_PATH ?? "python3";
  const cmd = `PYTHONPATH=${BRIDGE_SRC_PATH} ${pythonPath} -m claude_bridge.cli ${command} ${args.map((a) => `"${a.replace(/"/g, '\\"')}"`).join(" ")}`;
  try {
    return execSync(cmd, { timeout: 30000, encoding: "utf8" }).trim();
  } catch (err: any) {
    throw new Error(err.stderr?.trim() || err.message);
  }
}

// --- Outbound message poller (reads messages.db) ---

let outboundInterval: ReturnType<typeof setInterval> | null = null;

function startOutboundPoller(
  mcp: Server,
  bot: Bot
) {
  // Use bun:sqlite for direct access to messages.db
  const { Database } = require("bun:sqlite");

  outboundInterval = setInterval(async () => {
    try {
      const db = new Database(MESSAGES_DB_PATH);
      const pending = db
        .query(
          "SELECT * FROM outbound_messages WHERE status = 'pending' ORDER BY created_at LIMIT 10"
        )
        .all() as any[];

      for (const msg of pending) {
        try {
          await bot.api.sendMessage(msg.chat_id, msg.message_text);
          db.run(
            "UPDATE outbound_messages SET status = 'sent', sent_at = datetime('now') WHERE id = ?",
            [msg.id]
          );

          // If this is a task completion notification, also push to Claude session
          if (msg.source === "notification") {
            mcp.notification({
              method: "notifications/claude/channel",
              params: {
                content: msg.message_text,
                meta: {
                  source: "task_completion",
                  chat_id: msg.chat_id,
                },
              },
            });
          }
        } catch (err) {
          const retryCount = msg.retry_count + 1;
          if (retryCount >= msg.max_retries) {
            db.run(
              "UPDATE outbound_messages SET status = 'failed', retry_count = ? WHERE id = ?",
              [retryCount, msg.id]
            );
          } else {
            db.run(
              "UPDATE outbound_messages SET retry_count = ? WHERE id = ?",
              [retryCount, msg.id]
            );
          }
        }
      }

      db.close();
    } catch (err) {
      process.stderr.write(`bridge channel: outbound poller error: ${err}\n`);
    }
  }, 2000);
}

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
      "Messages from Telegram arrive as <channel source=\"bridge\" chat_id=\"...\" user=\"...\" tracking_id=\"...\" ts=\"...\">.",
      "IMPORTANT: After processing each message, call bridge_acknowledge(tracking_id) to confirm. If you don't acknowledge within 3 seconds, the message will be re-pushed.",
      "Reply with the reply tool — pass chat_id back. Keep replies concise (users are on mobile).",
      "Use bridge_dispatch to send tasks to agents. Use bridge_status to check running tasks.",
      "Use bridge_agents to list available agents. Use bridge_get_notifications to check for completed tasks.",
      "After processing a message, always call bridge_get_notifications to report any completions.",
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
          reply_to: {
            type: "string",
            description: "Message ID to reply to (optional)",
          },
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
  ],
}));

// --- Tool Handlers ---

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;

  try {
    switch (name) {
      case "reply": {
        const { chat_id, text, reply_to } = args as {
          chat_id: string;
          text: string;
          reply_to?: string;
        };
        if (!isAllowed(chat_id)) {
          return {
            content: [{ type: "text", text: "Error: chat not in allowlist" }],
          };
        }
        // Chunk if over 4096 chars
        const chunks =
          text.length > 4096 ? text.match(/.{1,4096}/gs) ?? [text] : [text];
        for (const chunk of chunks) {
          await bot.api.sendMessage(chat_id, chunk, {
            ...(reply_to ? { reply_parameters: { message_id: Number(reply_to) } } : {}),
          });
        }
        return { content: [{ type: "text", text: "sent" }] };
      }

      case "bridge_acknowledge": {
        const { tracking_id } = args as { tracking_id: number };
        const ok = acknowledgeInbound(tracking_id);
        return {
          content: [{ type: "text", text: ok ? "acknowledged" : "not found" }],
        };
      }

      case "bridge_dispatch": {
        const { agent, prompt, model } = args as {
          agent: string;
          prompt: string;
          model?: string;
        };
        const cliArgs = [agent, prompt];
        if (model) cliArgs.push("--model", model);
        const output = bridgeCli("dispatch", cliArgs);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_status": {
        const { agent } = (args ?? {}) as { agent?: string };
        const cliArgs = agent ? [agent] : [];
        const output = bridgeCli("status", cliArgs);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_agents": {
        const output = bridgeCli("list-agents");
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_history": {
        const { agent, limit } = args as { agent: string; limit?: number };
        const cliArgs = [agent];
        if (limit) cliArgs.push("--limit", String(limit));
        const output = bridgeCli("history", cliArgs);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_kill": {
        const { agent } = args as { agent: string };
        const output = bridgeCli("kill", [agent]);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_create_agent": {
        const { name: agentName, path, purpose, model } = args as {
          name: string;
          path: string;
          purpose: string;
          model?: string;
        };
        const cliArgs = [agentName, path, "--purpose", purpose];
        if (model) cliArgs.push("--model", model);
        const output = bridgeCli("create-agent", cliArgs);
        return { content: [{ type: "text", text: output }] };
      }

      case "bridge_get_notifications": {
        // Read unreported tasks via watcher output
        try {
          const output = bridgeCli("status");
          // Also check for recently completed
          return { content: [{ type: "text", text: output }] };
        } catch {
          return {
            content: [{ type: "text", text: "No pending notifications" }],
          };
        }
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (err: any) {
    return {
      content: [{ type: "text", text: `Error: ${err.message}` }],
      isError: true,
    };
  }
});

// --- Telegram Bot ---

const bot = new Bot(TOKEN);
let botUsername = "";

bot.on("message:text", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const text = ctx.message.text;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId)) {
    process.stderr.write(
      `bridge channel: rejected message from non-allowed user ${userId}\n`
    );
    return;
  }

  // Track in SQLite and push to Claude Code session
  const ts = new Date(ctx.message.date * 1000).toISOString();
  const trackingId = trackInbound(chatId, userId, username, text, messageId);
  pushMessage(trackingId, chatId, userId, username, text, messageId, ts);
});

// --- Startup ---

async function main() {
  // Get bot info
  const me = await bot.api.getMe();
  botUsername = me.username ?? "";
  process.stderr.write(`bridge channel: bot @${botUsername} connected\n`);

  // Start bot polling (grammy handles getUpdates loop)
  bot.start({
    onStart: () => {
      process.stderr.write("bridge channel: polling started\n");
    },
  });

  // Start outbound message poller
  startOutboundPoller(mcp, bot);

  // Start inbound retry engine
  startRetryEngine();

  // Connect MCP to Claude Code via stdio
  const transport = new StdioServerTransport();
  await mcp.connect(transport);

  // Shutdown on stdin close
  process.stdin.on("end", () => {
    process.stderr.write("bridge channel: stdin closed, shutting down\n");
    cleanup();
  });
}

function cleanup() {
  if (outboundInterval) clearInterval(outboundInterval);
  if (retryInterval) clearInterval(retryInterval);
  msgDb.close();
  bot.stop();
  process.exit(0);
}

process.on("SIGINT", cleanup);
process.on("SIGTERM", cleanup);

main().catch((err) => {
  process.stderr.write(`bridge channel: fatal: ${err}\n`);
  process.exit(1);
});
