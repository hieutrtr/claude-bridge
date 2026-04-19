/**
 * MCP Server — exposes bridge tools to Claude Code.
 *
 * Wave 7: All tools use native TS implementations.
 * Plus (new): Telegram push-channel support via `notifications/claude/channel`.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { TOOL_DEFINITIONS, TOOL_NAMES } from "./tools.js";
import { executeToolNative } from "./tool-handlers.js";

const CHANNEL_INSTRUCTIONS = [
  'Messages from Telegram arrive as <channel source="bridge" chat_id="..." user="..." tracking_id="..." ts="...">.',
  "If the tag has an image_path attribute, Read that file — it is a photo the sender attached.",
  "If the tag has attachment_file_id, call download_attachment with that file_id to fetch the file, then Read the returned path.",
  "After processing each message: call bridge_acknowledge(tracking_id), then bridge_get_notifications(), then bridge_check_messages().",
  'When bridge_get_notifications() returns queued notifications, they arrive as <channel source="task_completion" chat_id="..." task_id="..."> tags — use bridge_reply to forward the completion message to the chat_id.',
  "bridge_check_messages catches any messages that push notifications missed while you were busy.",
  "Reply with bridge_reply — pass chat_id back. (Legacy tool name `reply` maps to bridge_reply here.) Keep replies concise (users are on mobile).",
  "Use bridge_dispatch to send tasks to agents. Use bridge_status to check running tasks. Use bridge_agents to list available agents.",
].join("\n");

const server = new Server(
  { name: "claude-bridge", version: "1.0.0-beta" },
  {
    capabilities: {
      tools: {},
      experimental: { "claude/channel": {} },
    },
    instructions: CHANNEL_INSTRUCTIONS,
  },
);

// --- Queued Notification (prevents interleaving with pending tool responses) ---
//
// MCP stdio multiplexes tool responses and notifications on a single stream.
// If we emit a notification while a tool handler is serializing its response,
// grammy's polling loop has already written to stdout — the client sees an
// interleaved JSON-RPC frame and the whole session dies.
//
// Adapted from legacy/channel/server.ts: track tool-call in-flight and queue
// notifications until the handler returns, then flush.

let toolCallInFlight = false;
const pendingNotifications: Array<{ method: string; params: Record<string, unknown> }> = [];

function queuedNotification(msg: { method: string; params: Record<string, unknown> }): void {
  if (toolCallInFlight) {
    pendingNotifications.push(msg);
    process.stderr.write("[server] queued notification (tool call in flight)\n");
  } else {
    Promise.resolve(server.notification(msg)).catch((err) =>
      process.stderr.write(`[server] notification error: ${err}\n`),
    );
  }
}

function flushPendingNotifications(): void {
  while (pendingNotifications.length > 0) {
    const msg = pendingNotifications.shift()!;
    try {
      Promise.resolve(server.notification(msg)).catch((err) =>
        process.stderr.write(`[server] flush notification error: ${err}\n`),
      );
    } catch (err) {
      process.stderr.write(`[server] flush notification threw: ${err}\n`);
    }
  }
}

// --- Tool Definitions ---

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: TOOL_DEFINITIONS };
});

// --- Tool Handlers ---

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  toolCallInFlight = true;
  try {
    if (!TOOL_NAMES.includes(name as (typeof TOOL_NAMES)[number])) {
      throw new Error(`Unknown tool: ${name}`);
    }

    const result = await executeToolNative(name, (args ?? {}) as Record<string, unknown>);
    return { ...result };
  } finally {
    toolCallInFlight = false;
    flushPendingNotifications();
  }
});

// --- Start ---

export async function startServer(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write("claude-bridge MCP server started\n");
}

/** Exposed for the startup orchestrator + tests. */
export function getQueuedNotifier(): { notification: (msg: { method: string; params: Record<string, unknown> }) => void } {
  return { notification: (msg) => queuedNotification(msg) };
}

// Auto-start when run directly — uses StartupOrchestrator to wire all services
if (import.meta.main) {
  (async () => {
    const { StartupOrchestrator } = await import("../infra/startup.js");
    const orchestrator = new StartupOrchestrator();
    await orchestrator.start();

    // Optionally start Telegram inbound if token is set.
    let inboundHandle: { stop: () => Promise<void> } | null = null;
    const token = process.env["TELEGRAM_BOT_TOKEN"];
    if (token) {
      try {
        const { startTelegramInbound } = await import("./telegram-inbound.js");
        const { MessageDatabase } = await import("../data/message-db.js");
        const { join } = await import("path");
        const { homedir } = await import("os");
        const bridgeHome = process.env["CLAUDE_BRIDGE_HOME"] ?? join(homedir(), ".claude-bridge");
        const messageDb = new MessageDatabase(join(bridgeHome, "messages.db"));
        inboundHandle = await startTelegramInbound({
          token,
          notifier: getQueuedNotifier(),
          messageDb,
          bridgeHome,
        });
        process.stderr.write("[server] Telegram inbound started\n");
      } catch (err) {
        process.stderr.write(`[server] Telegram inbound failed: ${(err as Error).message}\n`);
      }
    }

    const shutdown = async (sig: string) => {
      process.stderr.write(`[server] ${sig} — shutting down\n`);
      if (inboundHandle) {
        try { await inboundHandle.stop(); } catch { /* ignore */ }
      }
      orchestrator.stop();
      process.exit(0);
    };
    process.on("SIGTERM", () => void shutdown("SIGTERM"));
    process.on("SIGINT", () => void shutdown("SIGINT"));
  })().catch((err) => {
    process.stderr.write(`Failed to start: ${err}\n`);
    process.exit(1);
  });
}
