# Claude Bridge

Multi-session Claude Code dispatch from Telegram. Each session = agent + project.

## Architecture

Bridge Bot (Claude Code + Telegram MCP) → bridge-cli → spawns `claude --agent --session-id --worktree -p "task"` → Stop hook fires on-complete → SQLite updated → Telegram notified.

Built on top of native Claude Code features: `--agent`, `--session-id`, `isolation: worktree`, Auto Memory, Stop hooks, prompt caching.

## Project Structure

```
src/                     TypeScript source (Bun runtime)
  cli/                   CLI entry point (bridge-cli command dispatcher)
    index.ts             Main CLI dispatcher
    agent-md.ts          Agent .md file generator
    claude-md.ts         CLAUDE.md initialization
    memory.ts            Auto Memory reader
  data/                  Data layer
    db.ts                SQLite database module (agents + tasks)
    session.ts           Session model (agent + project → session_id)
    message-db.ts        Message history DB
    interfaces.ts        Data interfaces
  execution/             Task execution
    dispatcher.ts        Task spawner (Bun.spawn + PID tracking)
    on-complete.ts       Stop hook handler
    watcher.ts           Fallback PID watcher
    notify.ts            Notification sender
  orchestration/         Advanced execution
    loop.ts              Loop orchestrator
    evaluator.ts         Loop evaluator
    scheduler.ts         Scheduled task runner
  infra/                 Infrastructure
    daemon.ts            Daemon lifecycle
    bridge-cmd.ts        Bridge shortcut command
    permissions.ts       Permission relay
  mcp/                   MCP server
    server.ts            MCP server entry point
    tools.ts             Tool definitions
    tool-handlers.ts     Tool implementations
    bridge-md.ts         Bridge markdown generator
  channel/               Channel adapters
    telegram/            Telegram adapter + formatter
    slack/               Slack adapter (stub)
    discord/             Discord adapter (stub)
  config.ts              Configuration
  types.ts               Shared types
  index.ts               Package entry point
tests/                   Bun test suite (36 files, 90%+ coverage)
  wave1/ ... wave7/      Feature wave tests
  coverage/              Extra coverage tests
legacy/                  Old Python/JS code (reference-only, deprecated)
plan/                    Architecture docs
specs/                   Task specifications
research/                Research notes
docs/                    Documentation
```

## Key Concepts

- **Session = Agent + Project**: `backend` + `/projects/my-api` → session_id `backend--my-api`
- **Agent .md files**: Generated in `{bot_dir}/.claude/agents/bridge--{session_id}.md` (project-level, per-instance isolated)
- **Stop hook**: Agent frontmatter includes Stop hook → calls on-complete.ts → updates SQLite
- **Worktree isolation**: Each task runs in isolated git worktree (no concurrent corruption)
- **Auto Memory**: Claude Code auto-learns patterns. Bridge reads via `/memory` command.

## Multi-Instance Setup

Claude Bridge supports multiple isolated instances using `CLAUDE_BRIDGE_HOME`:

**Main instance:**
```bash
bridge start              # Uses ~/.claude-bridge (default)
bridge stop
bridge status
```

**Additional instances (e.g., tam):**
```bash
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge start
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge stop
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge status
```

## Build & Test

```bash
# Install dependencies
bun install

# Run tests
bun test

# Typecheck
bun run typecheck    # or: tsc --noEmit

# Run CLI directly
bun run src/cli/index.ts create-agent backend /path/to/project --purpose "API dev"
bun run src/cli/index.ts dispatch backend "add pagination"
bun run src/cli/index.ts list-agents
bun run src/cli/index.ts status

# Build
bun run build
```

## Dependencies

Bun runtime. Dependencies: `@modelcontextprotocol/sdk`, `grammy`, `zod`.
`claude` CLI must be installed and in PATH.

## Conventions

- TypeScript with strict mode
- Bun runtime and test runner
- Single responsibility per module
- All state in SQLite (`~/.claude-bridge/bridge.db`)
- Agent .md files in native Claude Code format (YAML frontmatter + markdown)
- Error messages go to stderr, output goes to stdout
- Exit code 0 = success, non-zero = error
- Never call real `claude` CLI in tests — always mock subprocess

## Development Flow

```bash
# 1. Edit code in src/
# 2. Run tests: bun test
# 3. Typecheck: tsc --noEmit
# 4. Re-setup bot dirs
bun run src/cli/index.ts setup-bot ~/projects/bridge-bot
# 5. Restart instances
bridge stop && bridge start
# 6. Test on Telegram before pushing
# 7. Commit, tag, push, release
```

### Multi-instance
- Main: CLAUDE_BRIDGE_HOME=~/.claude-bridge (default)
- Tam: CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam
- Each instance has its own DB, agents, config

## Debugging Critical Bugs

When asked to fix a critical bug, DO NOT jump to conclusions. Follow this process:

1. **Reproduce first** — confirm the exact failure. What input, what expected, what actual?
2. **Challenge your first theory** — your first explanation is probably wrong or incomplete. Argue against it. Ask: "what else could cause this?"
3. **Check the environment, not just the code** — zombie processes, stale state, competing services, missing files. Most "code bugs" are environment bugs.
4. **Don't blame external systems too early** — "it's a Claude Code bug" or "it's a Telegram API issue" is lazy. Prove it by ruling out your own code first.
5. **Add observability before guessing** — add logging/stderr output at each step so you can see WHERE it fails, not guess.
6. **Test the actual integration, not just units** — mocked tests passing means your logic is correct, NOT that the system works. Test with real transports, real processes, real files.
7. **Look for the boring cause** — competing processes, wrong file paths, stale caches, permission issues. The exciting theory (protocol corruption, race conditions) is usually wrong. The boring theory (zombie process stealing messages) is usually right.
