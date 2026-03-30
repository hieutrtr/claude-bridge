# Claude Bridge

Multi-session Claude Code dispatch from Telegram. Each session = agent + project.

## Architecture

```
Telegram → Channel Server (TypeScript/Bun) → push notification → Claude Code session (Bridge Bot)
  → bridge_dispatch tool → bridge-cli (Python) → spawns claude --agent --worktree -p "task"
  → Stop hook → on_complete.py → SQLite updated → outbound queue → Channel Server → Telegram
```

Two runtimes:
- **Python** — bridge core (CLI, DB, dispatcher, on_complete, watcher)
- **TypeScript/Bun** — channel server (Telegram polling, MCP channel, push notifications)

## Project Structure

```
channel/                     TypeScript channel server
  server.ts                  Entry point (MCP channel + grammy bot)
  lib.ts                     Extracted testable functions
  __tests__/                 Bun tests (43 tests)
  package.json               Dependencies (grammy, @modelcontextprotocol/sdk)

src/claude_bridge/           Python package (the core)
  cli.py                     CLI entry (bridge-cli command, all subcommands)
  db.py                      SQLite database (agents, tasks, teams, notifications)
  message_db.py              Message queue SQLite (outbound for on_complete)
  session.py                 Session model (agent + project → session_id)
  agent_md.py                Agent .md generator + Stop hook installer
  claude_md_init.py          Purpose-driven CLAUDE.md initialization
  dispatcher.py              Task spawner (subprocess.Popen + PID tracking)
  on_complete.py             Stop hook handler (called by Claude Code)
  watcher.py                 Fallback PID watcher (cron, every 1 min)
  notify.py                  Notification formatting
  channel.py                 Multi-channel message formatting
  bridge_bot_claude_md.py    Bridge Bot CLAUDE.md generator (channel/mcp/shell modes)
  permission_relay.py        PreToolUse hook for dangerous commands
  memory.py                  Auto Memory reader
  mcp_server.py              Python MCP server (deprecated, replaced by channel/)
  mcp_tools.py               Python MCP tool implementations (deprecated)
  telegram_poller.py         Python Telegram poller (deprecated)
  channel_server/dist/       Bundled server.js (built by bun run build)

tests/                       Python tests (327 tests)
```

## Key Concepts

- **Session = Agent + Project**: `backend` + `/projects/my-api` → session_id `backend--my-api`
- **Agent .md files**: Generated in `~/.claude/agents/bridge--{session_id}.md`
- **Stop hook**: Installed in project's `.claude/settings.local.json` (NOT agent frontmatter — frontmatter hooks don't fire in --agent -p mode)
- **Stop hook format**: Nested `{hooks: [{hooks: [{type: command, command: ...}]}]}`
- **Worktree isolation**: Each task runs in isolated git worktree
- **Session UUID**: `uuid5(session_id + task_id)` — unique per task, not per agent
- **Channel server**: Pushes Telegram messages as `<channel>` tags via MCP `notifications/claude/channel`
- **Notification queue**: Prevents stdio interleaving during tool calls (`toolCallInFlight` flag)
- **Outbound delivery**: on_complete.py → messages.db → channel server polls every 2s → sends via grammy

## Build & Test

```bash
# Install for development
pip3 install -e . --break-system-packages

# Build channel server bundle
bun run build

# Run Python tests
python3 -m pytest tests/ --ignore=tests/test_mcp_server.py -v

# Run TypeScript tests
cd channel && bun test

# Run any CLI command
bridge-cli <command>

# Or from source without install
PYTHONPATH=src python3 -m claude_bridge.cli <command>

# Build for PyPI
./build.sh
./build.sh --publish
```

## Dependencies

**Python**: 3.11+ stdlib only (sqlite3, subprocess, argparse, json, os, signal)
**TypeScript**: Bun runtime + grammy + @modelcontextprotocol/sdk + zod
**CLI**: `claude` CLI must be in PATH
**Package**: `claude-agent-bridge` on PyPI

## Conventions

- Python: stdlib only — no pip dependencies for the core package
- TypeScript: channel/ directory, Bun runtime
- Single responsibility per module
- All state in SQLite (`~/.claude-bridge/bridge.db` + `~/.claude-bridge/messages.db`)
- Agent .md files in native Claude Code format (YAML frontmatter + markdown)
- Error messages go to stderr, output goes to stdout
- Exit code 0 = success, non-zero = error
- `from __future__ import annotations` in all Python modules (Python 3.9 compat for hooks/cron)
- Absolute python path in hooks and cron (system Python may differ)

## Development Workflow

Implementation follows a strict TDD process defined in `.claude/rules/phase-plan-approach.md`.

**Per task:** task spec → write tests → fix code → code review → commit
**Per milestone:** run full suite → write milestone report

Key rules:
- Task spec created BEFORE writing any code (specs/tasks/)
- Tests written BEFORE fixing code (TDD)
- Code review checklist applied after each task (`.claude/rules/code-review.md`)
- Commit format: `M{M}.T{T}: {description}` or `P{P}.T{T}: {description}`
- Never call real `claude` CLI in tests — always mock subprocess
- TypeScript tests: `bun test` in `channel/`

## Debugging Critical Bugs

When asked to fix a critical bug, DO NOT jump to conclusions. Follow this process:

1. **Reproduce first** — confirm the exact failure. What input, what expected, what actual?
2. **Challenge your first theory** — your first explanation is probably wrong or incomplete. Argue against it. Ask: "what else could cause this?"
3. **Check the environment, not just the code** — zombie processes, stale state, competing services, wrong python version, missing files. Most "code bugs" are environment bugs.
4. **Don't blame external systems too early** — "it's a Claude Code bug" or "it's a Telegram API issue" is lazy. Prove it by ruling out your own code first.
5. **Add observability before guessing** — add logging/stderr output at each step so you can see WHERE it fails, not guess.
6. **Test the actual integration, not just units** — mocked tests passing means your logic is correct, NOT that the system works. Test with real transports, real processes, real files.
7. **Look for the boring cause** — competing processes, wrong file paths, stale caches, permission issues. The exciting theory (protocol corruption, race conditions) is usually wrong. The boring theory (zombie process stealing messages) is usually right.

## Publishing

```bash
# Bump version in __init__.py + pyproject.toml
./build.sh --publish
git tag vX.Y.Z && git push origin main --tags
```

Package: https://pypi.org/project/claude-agent-bridge/
