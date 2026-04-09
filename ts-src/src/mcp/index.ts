/**
 * MCP Layer — Model Context Protocol server and tool implementations.
 */

export { startServer } from "./server.js";
export type { ToolResult, ToolDefinition } from "./tools.js";
export { TOOL_NAMES, TOOL_DEFINITIONS, buildCliArgs, executeTool } from "./tools.js";
