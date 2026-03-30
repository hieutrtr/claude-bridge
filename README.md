# Claude Bridge

Dispatch Claude Code agents from your phone via Telegram. Create agents, assign them to projects, dispatch tasks, get notified when done.

## How It Works

```
You (Telegram)
  │
  ▼
Bridge Channel Server (TypeScript)     Polls Telegram via grammy
  │                                    Pushes messages into Claude session
  │ mcp.notification (push)            Retries if not acknowledged in 30s
  ▼
Claude Code session (Bridge Bot)       Messages arrive as <channel> tags
  │                                    CLAUDE.md for intent mapping
  │ bridge_dispatch(agent, prompt)     reply(chat_id, text) sends back
  ▼
claude --agent --worktree -p "task"    Each task = isolated Claude Code agent
  │
  ▼
Stop hook → on_complete.py             Updates SQLite, queues notification
                                       Channel server delivers to Telegram
```

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/hieutrtr/claude-bridge.git ~/projects/claude-bridge
cd ~/projects/claude-bridge
pipx install -e .   # or: pip3 install -e . --break-system-packages

# 2. Install Bun (channel server runtime)
curl -fsSL https://bun.sh/install | bash

# 3. Build channel server
bun run build

# 4. Run setup wizard
bridge-cli setup
```

The wizard asks for your Telegram bot token, creates the bridge-bot project, deploys the channel server, and installs the watcher cron. Done in under 2 minutes.

## Prerequisites

| What | Why |
|------|-----|
| Python 3.11+ | Bridge core |
| [Bun](https://bun.sh) | Channel server runtime |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | `claude --version` to verify |
| Telegram account | You send commands from your phone |

## Installation

### Step 1: Clone and install

```bash
git clone https://github.com/hieutrtr/claude-bridge.git ~/projects/claude-bridge
cd ~/projects/claude-bridge

# Option A: pipx (recommended — isolated, clean)
brew install pipx
pipx install -e .

# Option B: pip with --break-system-packages (Homebrew Python)
pip3 install -e . --break-system-packages

# Option C: venv
python3 -m venv ~/.claude-bridge/venv
~/.claude-bridge/venv/bin/pip install -e .
# Then use: ~/.claude-bridge/venv/bin/bridge-cli (or add to PATH)
```

This gives you the `bridge-cli` command.

### Step 2: Install Bun and build

```bash
curl -fsSL https://bun.sh/install | bash
exec $SHELL
bun run build
```

This bundles `channel/server.ts` into a single JS file included in the package.

### Step 3: Create a Telegram bot

1. Open Telegram, search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts
3. Copy the bot token

### Step 4: Run the setup wizard

```bash
bridge-cli setup
```

The wizard:
1. Asks for your bot token → saves to `~/.claude-bridge/config.json`
2. Asks for bridge-bot directory → creates `CLAUDE.md` + `.mcp.json`
3. Deploys the channel server to `~/.claude-bridge/channel/dist/`
4. Installs the watcher cron (runs every minute)
5. Prints the startup command

Or non-interactive:
```bash
bridge-cli setup --token "<your-token>" --bot-dir ~/projects/bridge-bot --no-prompt
```

### Step 5: Start the Bridge Bot

```bash
cd ~/projects/bridge-bot
claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions
```

### Step 6: Pair your Telegram account

DM your bot on Telegram (send any message). In the Claude Code session:

```
/telegram:access pair <code>
/telegram:access policy allowlist
```

### Step 7: Verify

```bash
bridge-cli doctor
```

All checks should pass. Send `/help` to your bot on Telegram.

## Usage

### Create an agent

From Telegram:
```
/create backend ~/projects/my-api "API development"
```

Or natural language:
```
set up an agent called backend for ~/projects/my-api, it does API development
```

### Dispatch a task

```
dispatch backend add pagination to /users endpoint
```

The agent works in an isolated git worktree. When done, you get a Telegram notification.

### Check status

```
/status              — all running tasks
/agents              — list all agents
/history backend     — past tasks with cost
/kill backend        — stop a running task
```

### Agent teams

```
/create backend ~/projects/api "API development"
/create frontend ~/projects/web "React UI"
/create-team fullstack --lead backend --members frontend
/team-dispatch fullstack "build user profile page with API and UI"
```

## Restarting

```bash
cd ~/projects/bridge-bot
claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions
```

## All Commands

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/create <name> <path> "<purpose>"` | Register a new agent |
| `/delete <name>` | Remove an agent |
| `/agents` | List all agents |
| `/dispatch <agent> "<task>"` | Send a task (queues if busy) |
| `/status [agent]` | Show running tasks |
| `/kill <agent>` | Stop a running task |
| `/history <agent>` | Task history with cost |
| `/queue [agent]` | Show queued tasks |
| `/cancel <task_id>` | Cancel a queued task |
| `/set-model <agent> <model>` | Change model (sonnet/opus/haiku) |
| `/cost [agent]` | Cost summary |
| `/create-team <name> --lead <a> --members <b,c>` | Create team |
| `/team-dispatch <team> "<task>"` | Dispatch to team |
| `/team-status <team>` | Team progress |

### CLI Commands

| Command | Description |
|---------|-------------|
| `bridge-cli setup` | Interactive setup wizard |
| `bridge-cli doctor` | Check installation health |
| `bridge-cli doctor --fix` | Auto-repair issues |
| `bridge-cli uninstall` | Remove data, config, cron |
| `bridge-cli setup-cron` | Install watcher cron |
| `bridge-cli remove-cron` | Remove watcher cron |
| `bridge-cli --version` | Print version |

## Architecture

```
~/.claude-bridge/
├── config.json        Bot token, settings
├── bridge.db          SQLite: agents, tasks, teams
├── messages.db        SQLite: message queue
├── channel/dist/      Deployed channel server
├── watcher.log        Cron output
└── workspaces/        Per-agent task results

~/projects/bridge-bot/
├── CLAUDE.md          Bridge Bot routing rules
└── .mcp.json          Channel server config

~/.claude/agents/
└── bridge--*.md       Agent definitions
```

### Key Details

| What | Detail |
|------|--------|
| Channel server | TypeScript/Bun, push via `notifications/claude/channel` |
| Message delivery | Push + 30s retry (5 retries max) |
| Notification queue | Prevents stdio interleaving during tool calls |
| Stop hook | In project's `.claude/settings.local.json` (not frontmatter) |
| Session UUID | Unique per task: `uuid5(session_id + task_id)` |
| Worktree | Each task in isolated `git worktree` |
| Queue | Auto-queue when busy, auto-dequeue on completion |

## Development

```bash
# Python tests (370+ tests)
pipx install -e .   # or: pip3 install -e . --break-system-packages
python3 -m pytest tests/ --ignore=tests/test_mcp_server.py -v

# TypeScript tests (43 tests)
cd channel && bun test

# Build channel server
bun run build

# Run any CLI command
bridge-cli <command>
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot doesn't respond | `bridge-cli doctor` to check. Kill zombie processes: `ps aux \| grep "bun.*server"` |
| Stop hook not firing | `bridge-cli doctor --fix` redeploys channel server |
| Task stuck as "running" | Watcher cron catches within 1 minute. Or: `bridge-cli watcher` |
| Multiple bots conflict | Only one session can poll a bot token. Kill old processes first |
| Double notifications | Already fixed — `on_complete.py` marks tasks as reported |
| Clean removal | `bridge-cli uninstall --force` |
