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
const ACCESS_FILE = join(
  homedir(),
  ".claude",
  "channels",
  "telegram",
  "access.json"
);

const RETRY_TIMEOUT_MS = 30000;
const MAX_RETRIES = 5;

// --- Database ---

mkdirSync(join(homedir(), ".claude-bridge"), { recursive: true });
const msgDb = new Database(MESSAGES_DB_PATH);
initInboundTracking(msgDb);

// --- Intervals ---

let outboundInterval: ReturnType<typeof setInterval> | null = null;
let retryInterval: ReturnType<typeof setInterval> | null = null;

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
  ],
}));

// --- Tool Handlers ---

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;

  try {
    switch (name) {
      case "reply": {
        const { chat_id, text, reply_to } = args as { chat_id: string; text: string; reply_to?: string };
        const result = await handleReply(
          async (cid, txt, opts) => { await bot.api.sendMessage(cid, txt, opts ?? {}); },
          chat_id, text, reply_to, ACCESS_FILE
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
        // Re-push any pending messages that Claude might have missed
        const messages = pending.map((m) => ({
          tracking_id: m.id,
          chat_id: m.chat_id,
          user: m.username,
          text: m.message_text,
        }));
        // Also try pushing them again
        for (const msg of pending) {
          try {
            pushMessage(mcp, msg.id, msg.chat_id, msg.user_id, msg.username, msg.message_text, msg.message_id, new Date().toISOString());
          } catch {
            // Push failed, but we return the messages as text so Claude sees them
          }
        }
        return {
          content: [{
            type: "text",
            text: JSON.stringify({ pending_count: pending.length, messages }),
          }],
        };
      }

      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (err: any) {
    return { content: [{ type: "text", text: `Error: ${err.message}` }], isError: true };
  }
});

// --- Telegram Bot ---

const bot = new Bot(TOKEN);
let botUsername = "";

bot.catch((err) => {
  process.stderr.write(`bridge channel: grammy error: ${err.message}\n`);
});

bot.on("message:text", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const text = ctx.message.text;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, ACCESS_FILE)) {
    process.stderr.write(`bridge channel: rejected message from non-allowed user ${userId}\n`);
    return;
  }

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    pushMessage(mcp, trackingId, chatId, userId, username, text, messageId, ts);
  } catch (err) {
    process.stderr.write(`bridge channel: message handler error: ${err}\n`);
  }
});

// --- Startup ---

async function main() {
  const me = await bot.api.getMe();
  botUsername = me.username ?? "";
  process.stderr.write(`bridge channel: bot @${botUsername} connected\n`);

  bot.start({
    drop_pending_updates: true,
    onStart: () => {
      process.stderr.write("bridge channel: polling started\n");
    },
  });

  // Outbound poller
  outboundInterval = setInterval(async () => {
    try {
      await processOutbound(
        msgDb, mcp,
        async (chatId, text) => { await bot.api.sendMessage(chatId, text); }
      );
    } catch (err) {
      process.stderr.write(`bridge channel: outbound poller error: ${err}\n`);
    }
  }, 2000);

  // Inbound retry engine
  retryInterval = setInterval(() => {
    try {
      processRetries(
        msgDb, mcp,
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
