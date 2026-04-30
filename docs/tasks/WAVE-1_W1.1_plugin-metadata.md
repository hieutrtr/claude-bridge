# W1.1: Plugin Metadata & Structure

## Description
Create/validate plugin.json, mcp.json, and package.json for Claude Code plugin install.

## Refs
- Architecture: ARCHITECTURE.md §7.2 (Plugin packaging)
- Implementation Plan: IMPLEMENTATION_PLAN.md §2.2 (Wave 1)
- Files: `.claude-plugin/plugin.json`, `mcp.json`, `package.json`

## What This Task Does
Ensures the plugin shell is correct and complete — plugin.json has required fields,
mcp.json points to the MCP server entry point, package.json has correct metadata.
This is the foundation for `plugin install claude-bridge` to work.

## Acceptance Criteria
- [x] `.claude-plugin/plugin.json` has all required fields: name, version, description, authors, keywords, homepage, license
- [x] `mcp.json` correctly references `src/mcp/server.ts` as MCP entry with CLAUDE_BRIDGE_HOME env
- [x] `package.json` has correct bin entry, scripts, and dependencies
- [x] Version is consistent across all three files (0.6.0)
- [x] Plugin structure matches Claude Code plugin spec

## Architecture References
- §7.2: Plugin structure requires `.claude-plugin/plugin.json` + `mcp.json`
- §7.2: MCP server started via stdio transport

## TS Target Files
- `.claude-plugin/plugin.json` (exists, verify)
- `mcp.json` (exists, verify)
- `package.json` (exists, verify)

## Interface Changes
None — this is static metadata.
