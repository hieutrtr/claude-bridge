# Wave 7: MCP Consolidation (W7.1-W7.4)

## W7.1: MCP tool registry — native TS implementation
- Replace Python CLI fallback with native TS tool handlers
- Each tool delegates to appropriate TS layer (DB, CLI commands, orchestration)
- 24 tools: agent CRUD, task dispatch, messaging, loop mgmt, schedules

## W7.2: MCP server with native handlers
- Update executeTool to use native TS instead of bridge-cli subprocess
- Maintain same MCP protocol (stdio transport, tool definitions)

## W7.3: BridgeBotMdGenerator
- Generate Bridge Bot CLAUDE.md with tool documentation
- Behavior rules and channel instructions

## W7.4: Full E2E integration test
- End-to-end: create agent → dispatch → complete → verify state
- All native TS, no Python dependency
