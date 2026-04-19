# Claude Bridge

Dispatch Claude Code sessions from Telegram (and, in the future, Discord or Slack). Claude Bridge lets a single bot agent fan work out across multiple Claude Code agents — one per project — each running in an isolated git worktree, each with its own persistent session, cost history, and Auto Memory. You drive the whole thing from chat: create agents, dispatch tasks, run goal loops until a condition is met, schedule recurring work, and get push notifications back when tasks finish.

## How it works

```
  Telegram user
       |
       v
  Bridge Bot            <-- Claude Code session with Telegram MCP
       |                    (parses intent, calls MCP tools)
       |  bridge_dispatch(agent, prompt)
       v
  bridge (CLI)          <-- TypeScript CLI + MCP server
       |
       v
  claude --agent <bridge--agent> --session-id <uuid> -p "<task>"
       |
       v  (Stop hook fires on exit)
  bridge on-complete --session-id ...
       |
       v
  SQLite updated --> Notifier --> Telegram
```

- Built on native Claude Code: `--agent`, `--session-id`, `isolation: worktree`, Auto Memory, Stop hooks, prompt caching.
- Each session is a pairing of one agent and one project directory (e.g. `backend` + `~/projects/my-api` -> session id `backend--my-api`).
- Tasks spawn via `Bun.spawn` with a detached process group; completion is detected by the Stop hook, with a 30 s `ProcessWatcher` fallback for missed hooks and a 6 h timeout ceiling.
- All state lives in SQLite (`bridge.db` for tasks/agents/loops/schedules, `messages.db` for channel I/O), with WAL so the stop hook and the long-lived bridge process can share the database safely.
- The MCP server (`src/mcp/server.ts`) is what Claude Code talks to; launching it via `StartupOrchestrator` also starts the watcher and the 5 s notification delivery loop.

## Features

**Task dispatch**
- One-shot dispatch to a named agent, auto-queued when the agent is busy.
- Worktree isolation per task (handled by Claude Code natively, declared in agent frontmatter).
- Deterministic session UUID per `(session_id, task_id)` so Claude Code's own session continuity applies across related invocations.
- Model override per agent (`sonnet`, `opus`, `haiku`).

**Goal loops**
- Repeat a task until a done-condition is met. Condition types: `command:`, `file_exists:`, `file_contains:`, `llm_judge:`, `manual:`.
- Cost ceiling (`--max-cost`), max iterations, max consecutive failures.
- Two modes — `bridge` (one task per iteration, observable) and `agent` (agent self-retries inside a single task). `--type auto` picks for you.
- Human-in-the-loop: `loop-approve` / `loop-reject --feedback ...` for `manual:` conditions.

**Schedules**
- Fixed-interval recurring tasks (`--every <minutes>`).
- Exponential backoff on errors; auto-disabled after 5 consecutive failures.
- Note: `cron_expr` exists in the schema but the current scheduler only uses `interval_minutes`.

**Multi-channel**
- Telegram: live (formatter + direct Bot API delivery via `Notifier`).
- Discord / Slack: adapter and formatter stubs in `src/channel/discord` and `src/channel/slack` — planned, not yet functional.

**Operations**
- Permission relay via the `PreToolUse` hook (`src/infra/permissions.ts`) — approve / deny tool calls from the bot with a 300 s default timeout.
- Cost tracking per task, per loop, and per agent (`bridge cost`).
- Auto Memory inspection (`bridge memory <agent>`).
- Daemon integration: `bridge install` registers a launchd plist or systemd user unit so the bot survives reboots.
- Multi-instance isolation via `CLAUDE_BRIDGE_HOME` — separate DB, config, workspaces, daemon service name.

## Requirements

- [Bun](https://bun.sh) — runtime, package manager, and test runner.
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) — `claude` must be on your `PATH`.
- macOS (launchd) or Linux (systemd user unit) — the daemon templates target these two.
- A Telegram bot token from [@BotFather](https://t.me/BotFather) if you want the Telegram channel.
- `tmux` when `bridge` falls back to a persistent session (no OS daemon installed).

## Installation

```bash
git clone https://github.com/hieutrtr/claude-bridge.git
cd claude-bridge
bun install
bun link             # make `bridge` available on your PATH
bun run build        # bundles src/index.ts to dist/index.js
```

The `package.json` `bin` entry publishes a single binary:

```bash
bridge               # dispatches all commands: create-agent, dispatch, loop, start, ...
```

Link it into your `PATH` during development:

```bash
bun link
# or run directly without linking:
bun run src/cli/index.ts <command>
```

### Run as a daemon (recommended for production)

```bash
bridge install --auto-start   # installs launchd (macOS) or systemd user unit (Linux) and starts it
bridge daemon-status          # platform, daemon state, session pid/uptime, log path
bridge uninstall              # remove the daemon
```

With a daemon installed, `bridge start / stop / restart` drive the OS service. Without one, they fall back to a managed tmux session.

## Setup

Claude Bridge needs a home directory (`~/.claude-bridge` by default, or `$CLAUDE_BRIDGE_HOME`) and a bridge-bot project directory containing `CLAUDE.md`, `.mcp.json`, and `.claude/agents/`. Use `bridge setup-bot` — it scaffolds everything and writes `config.json` for you.

```bash
# Interactive: prompts for a Telegram bot token (press Enter to skip)
bridge setup-bot ~/projects/bridge-bot

# Non-interactive
bridge setup-bot ~/projects/bridge-bot \
    --telegram-token "123456:ABC-your-bot-token" \
    --no-prompt
```

Flags:

- `--telegram-token TOKEN` — store the token in `~/.claude-bridge/config.json`.
- `--no-prompt` — never read from stdin; fail if required values are missing.
- `--force` — overwrite a non-empty bot directory.

Then launch the bot:

```bash
bridge start       # uses the daemon if installed, else a tmux session
bridge status      # agents + running tasks
bridge logs -f     # tail ~/.claude-bridge/bridge.log
```

> **Upgrading from a previous version?** The Stop hook command changed from `bridge-cli on-complete` to `bridge on-complete`. Regenerate any existing agent `.md` files: `bridge delete-agent <name> && bridge create-agent <name> <path> --purpose ...`. If `bridge daemon-status` shows the plist points at an old `bot_dir`, run `bridge uninstall && bridge install` to regenerate.

## Usage

All commands below are handlers registered in `src/cli/index.ts`. Run `bridge --help` for the complete list.

### Agents

```bash
bridge create-agent backend ~/projects/my-api --purpose "API development" --model sonnet
bridge list-agents
bridge status                 # global: agents + running tasks
bridge status backend         # single agent detail
bridge set-model backend opus
bridge delete-agent backend
```

### Tasks

```bash
bridge dispatch backend "add pagination to /users"
bridge history backend --limit 20
bridge cost                   # all agents, all time
bridge cost backend --period week
bridge kill backend           # SIGTERM -> SIGKILL the running task
bridge memory backend         # dump Auto Memory for this project
```

### Loops

```bash
# Repeat until tests pass (max 5 iterations)
bridge loop backend "Fix all failing tests" \
    --done-when "command:bun test" \
    --max 5

# Repeat until a file exists
bridge loop vn-trader "Generate morning market brief" \
    --done-when "file_exists:output/morning-brief.md"

# LLM-judged completion
bridge loop backend "Refactor auth module to production quality" \
    --done-when "llm_judge:Code has tests, error handling, and docs" \
    --max 8 --type bridge --max-cost 5.00

# Human-in-the-loop
bridge loop backend "Draft API spec" --done-when "manual:review before continuing"

bridge loop-list --active
bridge loop-list backend --limit 20
bridge loop-status --loop-id abc12345
bridge loop-history abc12345
bridge loop-cancel abc12345
bridge loop-approve abc12345
bridge loop-reject abc12345 --feedback "still failing in module X"
```

### Schedules

```bash
bridge schedule-add backend "Sweep linter warnings" --every 60 --name nightly-lint
bridge schedule-list
bridge schedule-list --agent backend --all
bridge schedule-pause nightly-lint
bridge schedule-resume nightly-lint
bridge schedule-remove nightly-lint
```

### Lifecycle

| Command                    | Purpose                                                       |
| -------------------------- | ------------------------------------------------------------- |
| `bridge setup-bot <dir>`   | Scaffold the bot directory (CLAUDE.md, .mcp.json, agents dir) |
| `bridge start`             | Launch the bot (daemon if installed, else tmux)               |
| `bridge stop`              | Stop the bot                                                  |
| `bridge restart`           | Stop + start                                                  |
| `bridge install [--auto-start]` | Install launchd plist or systemd user unit               |
| `bridge uninstall`         | Uninstall the daemon                                          |
| `bridge attach`            | Attach to the running bot tmux session (Ctrl-b d to detach)   |
| `bridge daemon-status`     | Platform, daemon installed/running, session PID, uptime, log  |
| `bridge doctor`            | Diagnose setup and report `[ok]` / `[warn]` / `[fail]` checks |
| `bridge logs [--tail N] [-f]` | Tail `~/.claude-bridge/bridge.log`                         |

### Stop hook

```bash
bridge on-complete --session-id backend--my-api
```

This is wired into each agent's `.claude/settings.local.json` by `cli/agent-md.ts` — you normally do not invoke it by hand. It updates the task row, enqueues a notification, and auto-dequeues the next queued task for the same session.

## From Telegram

Once the bot agent is paired with your Telegram chat, you can drive everything from DMs. The bot's `CLAUDE.md` routes natural language to MCP tool calls; you can also be explicit.

Examples:

```
dispatch backend add pagination to /users
loop backend fix failing tests until bun test passes, max 5
status
history backend
stop loop abc12345
```

The most useful MCP tools (defined in `src/mcp/tools.ts`):

| Tool                     | Purpose                                             |
| ------------------------ | --------------------------------------------------- |
| `bridge_dispatch`        | Send a task to an agent                             |
| `bridge_status`          | Running tasks, optionally filtered by agent         |
| `bridge_agents`          | List all registered agents                          |
| `bridge_history`         | Per-agent task history with costs                   |
| `bridge_kill`            | Kill the running task on an agent                   |
| `bridge_loop`            | Start a goal loop                                   |
| `bridge_loop_status`     | Inspect loop progress                               |
| `bridge_schedule_add`    | Register a recurring task                           |
| `bridge_reply`           | Post a message back to the user                     |
| `bridge_get_notifications` | Drain pending task-completion notifications       |

The complete registry (24 tools) lives in `TOOL_NAMES` / `TOOL_DEFINITIONS` in `src/mcp/tools.ts`.

## Multi-instance

Each instance is isolated by `CLAUDE_BRIDGE_HOME`. The config provider, SQLite databases (`bridge.db`, `messages.db`), workspaces directory, and generated daemon service name all derive from it.

```bash
# Default instance
bridge list-agents                                         # ~/.claude-bridge

# Separate instance named "tam"
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge setup-bot ~/projects/bridge-bot-tam
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge list-agents
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge create-agent \
    backend ~/projects/other-api --purpose "Separate workspace"
```

Give each instance its own Telegram bot token so their pollers do not race each other, and use distinct agent names or project basenames so the generated `.claude/agents/bridge--*.md` files do not collide.

## Project structure

```
src/
  cli/             bridge dispatcher (index.ts), setup-bot, agent-md generator, Auto Memory reader
  data/            SQLite stores, SessionManager, interfaces
  execution/       Dispatcher, CompletionHandler, ProcessWatcher, Notifier
  orchestration/   LoopOrchestrator, LoopEvaluator, Scheduler
  mcp/             MCP server, tool registry, native tool handlers
  infra/           StartupOrchestrator, daemon (launchd/systemd), tmux helpers, permission relay
  channel/         Telegram (formatter live), Discord/Slack (stubs)
  config.ts        CLAUDE_BRIDGE_HOME resolution, config.json loader
  types.ts         Domain model (Agent, Task, Loop, Schedule, ...)
  index.ts         Public API barrel

tests/             Bun test suite (wave1/ ... wave7/ + coverage/)
docs/              Deep docs (see ARCHITECTURE.md)
legacy/            Old Python/JS implementation — reference only, deprecated
```

## Development

```bash
bun install
bun test                            # full suite
bun test tests/wave1                # single directory
bun run typecheck                   # tsc --noEmit
bun run build                       # bundle to dist/index.js
```

For the detailed layer-by-layer architecture, data model, runtime flows (dispatch, stop hook, loop iteration, schedule tick, MCP call, startup), and extension points, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## License

MIT — see `package.json`. A standalone `LICENSE` file has not been added to the repository yet.
