# Claude Bridge

Multi-session Claude Code dispatch from Telegram. Each session = agent + project.

## Architecture

Bridge Bot (Claude Code + Telegram MCP) → bridge-cli.py → spawns `claude --agent --session-id --worktree -p "task"` → Stop hook fires on-complete.py → SQLite updated → Telegram notified.

Built on top of native Claude Code features: `--agent`, `--session-id`, `isolation: worktree`, Auto Memory, Stop hooks, prompt caching.

## Project Structure

```
src/claude_bridge/       Python package (the core)
  cli.py                 CLI entry point (bridge-cli command dispatcher)
  db.py                  SQLite database module (agents + tasks)
  session.py             Session model (agent + project → session_id)
  agent_md.py            Native Claude Code agent .md file generator
  claude_md_init.py      Purpose-driven CLAUDE.md initialization
  dispatcher.py          Task spawner (subprocess.Popen + PID tracking)
  memory.py              Auto Memory reader
  on_complete.py         Stop hook handler (called by Claude Code)
  watcher.py             Fallback PID watcher (cron)
tests/                   pytest tests
plan/                    Architecture docs + implementation tasks
specs/                   Technical specifications
research/                Research from architecture exploration
```

## Key Concepts

- **Session = Agent + Project**: `backend` + `/projects/my-api` → session_id `backend--my-api`
- **Agent .md files**: Generated in `~/.claude/agents/bridge--{session_id}.md` (native Claude Code format)
- **Stop hook**: Agent frontmatter includes Stop hook → calls on-complete.py → updates SQLite
- **Worktree isolation**: Each task runs in isolated git worktree (no concurrent corruption)
- **Auto Memory**: Claude Code auto-learns patterns. Bridge reads via `/memory` command.

## Build & Test

```bash
# Install in dev mode
pip install -e .

# Run tests
pytest

# Run CLI directly
python -m claude_bridge.cli create-agent backend /path/to/project --purpose "API dev"
python -m claude_bridge.cli dispatch backend "add pagination"
python -m claude_bridge.cli list-agents
python -m claude_bridge.cli status
```

## Dependencies

Python 3.11+ with stdlib only (sqlite3, subprocess, argparse, json, os, signal).
No pip dependencies for the core package.
`claude` CLI must be installed and in PATH.

## Conventions

- Pure Python, stdlib only — no external dependencies
- Single responsibility per module
- All state in SQLite (`~/.claude-bridge/bridge.db`)
- Agent .md files in native Claude Code format (YAML frontmatter + markdown)
- Error messages go to stderr, output goes to stdout
- Exit code 0 = success, non-zero = error
