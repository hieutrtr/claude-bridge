# W1.3: Skills & Smoke Test

## Description
Create slash command skills for dispatch and status, and a smoke test
verifying the plugin structure is complete and the MCP server can start.

## Refs
- Architecture: ARCHITECTURE.md §7.2 (Plugin packaging)
- Implementation Plan: IMPLEMENTATION_PLAN.md §2.2 (W1.3)
- Files: `skills/dispatch.md`, `skills/status.md`

## Acceptance Criteria
- [ ] skills/dispatch.md has valid frontmatter (name, description)
- [ ] skills/status.md has valid frontmatter (name, description)
- [ ] MCP server module can be imported without errors
- [ ] MCP server exports startServer function
- [ ] All Wave 1 tests pass together (regression check)

## TS Target Files
- `skills/dispatch.md` (exists, verify)
- `skills/status.md` (exists, verify)
- `tests/wave1/smoke.test.ts` (new)
