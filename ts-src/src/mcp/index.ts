/**
 * MCP Layer — Model Context Protocol server and tool implementations.
 */

export { startServer } from "./server.js";
export type { ToolResult } from "./tools.js";
export { handleDispatch, handleStatus, handleListAgents } from "./tools.js";
