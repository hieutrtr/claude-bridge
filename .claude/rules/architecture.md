---
description: Architecture rules and boundaries for Claude Bridge
paths: ["src/**/*.py"]
---

# Architecture Rules

## Ownership Boundaries
- Bridge OWNS: `~/.claude-bridge/*` (db, workspaces, scripts)
- Bridge GENERATES: `~/.claude/agents/bridge--*.md` (agent definitions), project `CLAUDE.md` (on create)
- Bridge READS ONLY: `~/.claude/projects/*/memory/` (Auto Memory) — never write to Auto Memory
- Claude Code OWNS: session JSONL, worktrees, Auto Memory

## Session Model
- Session identity: `session_id = "{agent_name}--{project_basename}"`
- Double-dash `--` is the separator (agent names use single dashes only)
- Primary key: `(name, project_dir)` — not just name
- One agent .md file per session, one workspace per session

## Database
- SQLite with WAL mode, always
- Foreign keys ON
- CASCADE delete: deleting agent deletes its tasks
- All timestamps as ISO8601 strings

## Subprocess Management
- Always use `start_new_session=True` when spawning claude
- Track PIDs in SQLite
- Graceful kill: SIGTERM → wait 10s → SIGKILL
- Never use SIGKILL directly
