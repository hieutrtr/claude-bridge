# Claude Bridge

Multi-session Claude Code dispatch from Telegram. Each session = agent + project.

## Architecture

Bridge Bot (Claude Code + Telegram MCP) → `bridge` CLI → spawns `claude --agent --session-id --worktree -p "task"` → Stop hook fires `bridge on-complete` → SQLite updated → Telegram notified.

Built on top of native Claude Code features: `--agent`, `--session-id`, `isolation: worktree`, Auto Memory, Stop hooks, prompt caching.

## Project Structure

```
src/                     TypeScript source (Bun runtime)
  cli/                   CLI entry point (bridge command dispatcher)
    index.ts             Main CLI dispatcher + lifecycle commands
    setup-bot.ts         `bridge setup-bot` scaffolder (CLAUDE.md, .mcp.json, agents dir, config.json)
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
    daemon.ts            Daemon lifecycle (launchd/systemd)
    bridge-cmd.ts        tmux session helpers + config validation
    permissions.ts       Permission relay
    startup.ts           StartupOrchestrator (watcher + notify loop + MCP)
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
- **Stop hook**: Agent frontmatter includes Stop hook → calls `bridge on-complete` → updates SQLite
- **Worktree isolation**: Each task runs in isolated git worktree (no concurrent corruption)
- **Auto Memory**: Claude Code auto-learns patterns. Bridge reads via `/memory` command.

## CLI commands

The `bridge` binary groups commands by concern. Run `bridge --help` for the authoritative list.

- **Agent lifecycle:** `create-agent`, `delete-agent`, `list-agents`, `set-model`, `memory`, `status`
- **Task execution:** `dispatch`, `kill`, `history`, `cost`, `on-complete` (stop-hook callback)
- **Loops:** `loop`, `loop-status`, `loop-cancel`, `loop-approve`, `loop-reject`, `loop-list`, `loop-history`
- **Schedules:** `schedule-add`, `schedule-remove`, `schedule-list`, `schedule-pause`, `schedule-resume`
- **Bot lifecycle:** `start`, `stop`, `restart`, `attach`, `daemon-status`, `logs`
- **Setup / daemon:** `setup-bot`, `install`, `uninstall`
- **Diagnostics:** `doctor`

## Multi-Instance Setup

Claude Bridge supports multiple isolated instances using `CLAUDE_BRIDGE_HOME`:

**Main instance:**
```bash
bridge start              # Uses ~/.claude-bridge (default)
bridge stop
bridge status             # agents + running tasks
bridge daemon-status      # platform, daemon state, session pid/uptime, log path
```

**Additional instances (e.g., tam):**
```bash
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge start
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge stop
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge daemon-status
```

## Build & Test

After `bun install`, the `bridge` binary declared in `package.json` (`bin`) is available on `PATH` (via `bun link` or your package manager's shim). For contributors working in the repo, the dev-invocation form `bun run src/cli/index.ts <command>` is equivalent.

```bash
# Install dependencies
bun install

# Make 'bridge' available on PATH
bun link

# Run tests
bun test

# Typecheck
bun run typecheck    # or: tsc --noEmit

# Run via the installed binary
bridge create-agent backend /path/to/project --purpose "API dev"
bridge dispatch backend "add pagination"
bridge list-agents
bridge status

# Run directly from source (no link needed)
bun run src/cli/index.ts list-agents

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
# 4. Scaffold / re-scaffold the bot dir (interactive; prompts for Telegram token)
bridge setup-bot ~/projects/bridge-bot
#    or non-interactive:
bridge setup-bot ~/projects/bridge-bot --telegram-token "$TELEGRAM_TOKEN" --no-prompt
bridge doctor  # verify everything wired up
# 5. Restart instances
bridge restart
# 6. Test on Telegram before pushing
# 7. Commit, tag, push, release
```

### Multi-instance
- Main: CLAUDE_BRIDGE_HOME=~/.claude-bridge (default)
- Tam: CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam
- Each instance has its own DB, agents, config, and daemon service name

## Debugging Critical Bugs

When asked to fix a critical bug, DO NOT jump to conclusions. Follow this process:

1. **Reproduce first** — confirm the exact failure. What input, what expected, what actual?
2. **Challenge your first theory** — your first explanation is probably wrong or incomplete. Argue against it. Ask: "what else could cause this?"
3. **Check the environment, not just the code** — zombie processes, stale state, competing services, missing files. Most "code bugs" are environment bugs.
4. **Don't blame external systems too early** — "it's a Claude Code bug" or "it's a Telegram API issue" is lazy. Prove it by ruling out your own code first.
5. **Add observability before guessing** — add logging/stderr output at each step so you can see WHERE it fails, not guess.
6. **Test the actual integration, not just units** — mocked tests passing means your logic is correct, NOT that the system works. Test with real transports, real processes, real files.
7. **Look for the boring cause** — competing processes, wrong file paths, stale caches, permission issues. The exciting theory (protocol corruption, race conditions) is usually wrong. The boring theory (zombie process stealing messages) is usually right.
