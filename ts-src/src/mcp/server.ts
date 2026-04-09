/**
 * MCP Server — exposes bridge tools to Claude Code.
 *
 * This is the main entry point when running as a plugin.
 * Consolidates Python mcp_server.py + mcp_tools.py + channel/server.ts.
 *
 * TODO: Implement in Wave 7 migration.
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  { name: "claude-bridge", version: "0.6.0" },
  { capabilities: { tools: {} } },
);

// --- Tool Definitions ---

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "bridge_dispatch",
        description: "Dispatch a task to a Claude Bridge agent",
        inputSchema: {
          type: "object" as const,
          properties: {
            agent: { type: "string", description: "Agent name" },
            prompt: { type: "string", description: "Task prompt" },
          },
          required: ["agent", "prompt"],
        },
      },
      {
        name: "bridge_status",
        description: "Get status of agents and tasks",
        inputSchema: {
          type: "object" as const,
          properties: {
            agent: { type: "string", description: "Optional agent name filter" },
          },
        },
      },
      {
        name: "bridge_list_agents",
        description: "List all configured agents",
        inputSchema: { type: "object" as const, properties: {} },
      },
    ],
  };
});

// --- Tool Handlers ---

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  switch (name) {
    case "bridge_dispatch":
    case "bridge_status":
    case "bridge_list_agents":
      return {
        content: [
          { type: "text" as const, text: `Tool ${name} not yet implemented` },
        ],
      };
    default:
      throw new Error(`Unknown tool: ${name}`);
  }
});

// --- Start ---

export async function startServer(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write("claude-bridge MCP server started\n");
}

// Auto-start when run directly
if (import.meta.main) {
  startServer().catch((err) => {
    process.stderr.write(`Failed to start: ${err}\n`);
    process.exit(1);
  });
}
