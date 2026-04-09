/**
 * MCP Tool Implementations — business logic behind each MCP tool.
 *
 * Separated from server.ts for testability.
 * Replaces Python's mcp_tools.py.
 *
 * TODO: Implement in Wave 7 migration.
 */

export interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
}

export async function handleDispatch(
  agent: string,
  prompt: string,
): Promise<ToolResult> {
  return {
    content: [{ type: "text", text: "Not implemented" }],
  };
}

export async function handleStatus(
  agent?: string,
): Promise<ToolResult> {
  return {
    content: [{ type: "text", text: "Not implemented" }],
  };
}

export async function handleListAgents(): Promise<ToolResult> {
  return {
    content: [{ type: "text", text: "Not implemented" }],
  };
}
