# W1.2: MCP Server with Python Fallback

## Description
Implement MCP server that shells out to `bridge-cli` (Python) for all 24 tools.
This is the transitional layer — each tool calls `bridge-cli <command> [args]` via subprocess.

## Refs
- Architecture: ARCHITECTURE.md §3.6, §4.3.3
- Implementation Plan: IMPLEMENTATION_PLAN.md §2.2 (W1.2)
- Python source: `src/claude_bridge/mcp_server.py` (tool definitions)
- TS target: `src/mcp/server.ts`, `src/mcp/tools.ts`

## What This Task Does
Rewrites the MCP server to register all 24 tools with proper input schemas,
and implement each handler by shelling out to `bridge-cli` Python CLI.

## Acceptance Criteria
- [ ] All 24 tools registered with correct names and input schemas
- [ ] Each tool handler shells out to `bridge-cli` via Bun.spawn
- [ ] Tool results returned as MCP text content
- [ ] Errors from bridge-cli are captured and returned as isError: true
- [ ] Server starts via stdio transport
- [ ] TOOL_NAMES constant exported for testing

## Python Source Files
- `src/claude_bridge/mcp_server.py` — tool definitions (24 tools)
- `src/claude_bridge/mcp_tools.py` — tool implementations

## TS Target Files
- `src/mcp/server.ts` — MCP server with tool registration
- `src/mcp/tools.ts` — tool handler implementations (Python fallback)

## Tool List (24 tools)
bridge_dispatch, bridge_status, bridge_agents, bridge_history, bridge_kill,
bridge_create_agent, bridge_get_messages, bridge_acknowledge, bridge_reply,
bridge_get_notifications, bridge_loop, bridge_loop_status, bridge_loop_cancel,
bridge_loop_approve, bridge_loop_reject, bridge_loop_list, bridge_loop_history,
bridge_loop_notify, bridge_parse_loop_command, bridge_schedule_add,
bridge_schedule_remove, bridge_schedule_list, bridge_schedule_pause,
bridge_schedule_resume
