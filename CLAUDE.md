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

## Development Workflow

Implementation follows a strict TDD process defined in `.claude/rules/phase-plan-approach.md`.
This process is reusable across all phases (1, 2, 3).

**Per task:** task spec → write tests → fix code → code review → commit
**Per milestone:** run full suite → write milestone report

Key rules:
- Task spec created BEFORE writing any code (specs/tasks/M{M}-T{T}.md)
- Tests written BEFORE fixing code (TDD)
- Code review checklist applied after each task (`.claude/rules/code-review.md`)
- Milestone report after each milestone (specs/reports/milestone-{N}-report.md)
- Commit format: `M{M}.T{T}: {description}`
- Never call real `claude` CLI in tests — always mock subprocess

## Debugging Critical Bugs

When asked to fix a critical bug, DO NOT jump to conclusions. Follow this process:

1. **Reproduce first** — confirm the exact failure. What input, what expected, what actual?
2. **Challenge your first theory** — your first explanation is probably wrong or incomplete. Argue against it. Ask: "what else could cause this?"
3. **Check the environment, not just the code** — zombie processes, stale state, competing services, wrong python version, missing files. Most "code bugs" are environment bugs.
4. **Don't blame external systems too early** — "it's a Claude Code bug" or "it's a Telegram API issue" is lazy. Prove it by ruling out your own code first.
5. **Add observability before guessing** — add logging/stderr output at each step so you can see WHERE it fails, not guess.
6. **Test the actual integration, not just units** — mocked tests passing means your logic is correct, NOT that the system works. Test with real transports, real processes, real files.
7. **Look for the boring cause** — competing processes, wrong file paths, stale caches, permission issues. The exciting theory (protocol corruption, race conditions) is usually wrong. The boring theory (zombie process stealing messages) is usually right.
