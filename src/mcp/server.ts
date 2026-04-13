/**
 * MCP Server — exposes bridge tools to Claude Code.
 *
 * Wave 7: All tools use native TS implementations.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { TOOL_DEFINITIONS, TOOL_NAMES } from "./tools.js";
import { executeToolNative } from "./tool-handlers.js";

const server = new Server(
  { name: "claude-bridge", version: "0.6.0" },
  { capabilities: { tools: {} } },
);

// --- Tool Definitions ---

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: TOOL_DEFINITIONS };
});

// --- Tool Handlers ---

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (!TOOL_NAMES.includes(name as (typeof TOOL_NAMES)[number])) {
    throw new Error(`Unknown tool: ${name}`);
  }

  const result = await executeToolNative(name, (args ?? {}) as Record<string, unknown>);
  return { ...result };
});

// --- Start ---

export async function startServer(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write("claude-bridge MCP server started\n");
}

// Auto-start when run directly — uses StartupOrchestrator to wire all services
if (import.meta.main) {
  (async () => {
    const { StartupOrchestrator } = await import("../infra/startup.js");
    const orchestrator = new StartupOrchestrator();
    await orchestrator.start();
  })().catch((err) => {
    process.stderr.write(`Failed to start: ${err}\n`);
    process.exit(1);
  });
}
