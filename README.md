# Claude Bridge

Dispatch Claude Code agents from your phone via Telegram. Create agents, assign them to projects, dispatch tasks, get notified when done.

## How It Works

```
You (Telegram)
  │
  ▼
Bridge Channel Server (TypeScript)     Polls Telegram via grammy
  │                                    Pushes messages into Claude session
  │ mcp.notification (push)            Retries if not acknowledged in 3s
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

**Bridge Bot** = Claude Code session + Bridge Channel server + CLAUDE.md routing rules.
No custom daemon. No Telegram plugin. The channel server pushes messages directly into the session.

## Prerequisites

| What | Why |
|------|-----|
| macOS or Linux | Runs on your machine |
| Python 3.11+ | Bridge core (stdlib only, no pip deps) |
| [Bun](https://bun.sh) | Channel server runtime (TypeScript) |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | Must be in PATH — `claude --version` to verify |
| Telegram account | Control plane — you send commands from your phone |

## Installation

### Step 1: Clone the repo

```bash
git clone https://github.com/hieutrtr/claude-bridge.git ~/projects/claude-bridge
cd ~/projects/claude-bridge
```

### Step 2: Install Bun (if you don't have it)

The channel server runs on Bun (TypeScript runtime):

```bash
curl -fsSL https://bun.sh/install | bash
exec $SHELL
bun --version
```

### Step 3: Install channel server dependencies

```bash
cd ~/projects/claude-bridge/channel
bun install
```

This installs `@modelcontextprotocol/sdk`, `grammy`, and `zod`.

### Step 4: Create a Telegram bot

1. Open Telegram on your phone
2. Search for [@BotFather](https://t.me/BotFather) and start a chat
3. Send `/newbot`
4. Follow the prompts — pick a name and username for your bot
5. BotFather gives you a token like `7123456789:AAH1bGcK9...`
6. Copy this token — you'll need it in the next step

### Step 5: Save the bot token

```bash
cd ~/projects/claude-bridge
PYTHONPATH=src python3 -m claude_bridge.cli setup-telegram "<your-bot-token>"
```

Output:
```
Telegram bot token saved to ~/.claude-bridge/config.json
Default notification target: chat_id 8137063402
```

The token is saved to `~/.claude-bridge/config.json` (local, not committed to git).

### Step 6: Generate the Bridge Bot project

This creates a separate project folder for the Bridge Bot with everything configured:

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup-bot ~/projects/bridge-bot
```

Output:
```
CLAUDE.md → ~/projects/bridge-bot/CLAUDE.md
.mcp.json → ~/projects/bridge-bot/.mcp.json

Bridge Bot ready. Start with:
  cd ~/projects/bridge-bot
  claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions
```

What was created:

| File | What it does |
|------|-------------|
| `CLAUDE.md` | Tells the Bridge Bot how to parse commands, dispatch tasks, handle errors |
| `.mcp.json` | Configures Bridge MCP server — auto-starts when Claude Code opens this project |

The `.mcp.json` contains your bot token and the path to Claude Bridge source. If you move the claude-bridge repo, re-run `setup-bot`.

### Step 7: Install the watcher cron

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup-cron
```

This adds a cron job that runs every minute:
- Detects tasks where the Stop hook didn't fire (process died)
- Cleans up stale `running` state in SQLite
- Queues missed notifications for delivery

To remove later: `PYTHONPATH=src python3 -m claude_bridge.cli remove-cron`

### Step 8: Start the Bridge Bot

```bash
cd ~/projects/bridge-bot
claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions
```

What happens:
1. Claude Code reads `.mcp.json` → starts Bridge Channel server as a subprocess
2. Channel server starts grammy bot → your Telegram bot comes online
3. Channel server starts retry engine + outbound poller
4. Claude Code reads `CLAUDE.md` → knows how to handle `<channel>` tags
5. Messages from Telegram are pushed directly into the session — no polling needed

### Step 9: Pair your Telegram account

This is a one-time step. DM your bot on Telegram — send any message (e.g., "hello").

The bot replies with instructions and a 6-character pairing code. In the Claude Code session, type:

```
/telegram:access pair <code>
```

Then lock access so only you can use the bot:

```
/telegram:access policy allowlist
```

Your Telegram user ID is now saved in `~/.claude/channels/telegram/access.json`.

### Step 10: Verify

Send `/help` to your bot on Telegram. The Bridge Bot should reply with available commands.

If it doesn't respond:
- Check the Claude Code session is still running
- Check for errors in the session output
- Make sure no other Claude Code session is polling the same bot token

## Usage

### Create an agent

From Telegram:
```
/create backend ~/projects/my-api "REST API development"
```

Or natural language:
```
set up an agent called backend for ~/projects/my-api, it does API development
```

What happens:
- Generates `~/.claude/agents/bridge--backend--my-api.md` (agent definition)
- Installs Stop hook in `~/projects/my-api/.claude/settings.local.json`
- Scans the project and generates a purpose-driven `CLAUDE.md`
- Registers the agent in SQLite

### Dispatch a task

```
/dispatch backend "add pagination to /users endpoint"
```

Or natural language:
```
tell backend to add pagination to /users
```

What happens:
- Creates a task in SQLite
- Spawns: `claude --agent bridge--backend--my-api --session-id <uuid> --dangerously-skip-permissions -p "add pagination"`
- Agent works in an isolated git worktree (no conflicts with your working copy)
- When done, Stop hook fires → `on_complete.py` → SQLite updated → notification queued
- Bridge MCP delivers the notification to your Telegram

If the agent is busy, the task is **queued** automatically and runs when the current task finishes.

### Check status

```
/status              — all running tasks
/status backend      — specific agent
/agents              — list all agents
/history backend     — past tasks with cost
```

### Kill a task

```
/kill backend
```

Sends SIGTERM → waits 10s → SIGKILL. Marks task as `killed` in SQLite.

### Agent teams

Create agents, group them into a team, dispatch a complex task:

```
/create backend ~/projects/api "API development"
/create frontend ~/projects/web "React UI"
/create-team fullstack --lead backend --members frontend
/team-dispatch fullstack "build user profile page with API and UI"
```

The lead agent receives an augmented prompt with teammate info. It decomposes the task and dispatches sub-tasks. When all sub-tasks complete, costs are aggregated and you get a single report.

## Restarting

After the initial setup, start the Bridge Bot any time with:

```bash
cd ~/projects/bridge-bot
claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions
```

- Channel server reconnects to Telegram automatically
- Your agents, tasks, and history are preserved in SQLite
- Pairing is persistent (no need to re-pair)

## Notification System

When a task completes, you get a Telegram message like:

```
✓ Task #18 (backend) done in 2m 15s
  Added pagination to /users endpoint with cursor-based paging
  Cost: $0.040
```

Or for failures:
```
✗ Task #19 (backend) failed after 45s
  Error: npm test failed with exit code 1
  Cost: $0.020
```

How notifications work:
1. **Stop hook** fires `on_complete.py` → writes to `outbound_messages` queue in SQLite
2. **Channel server** outbound poller picks up the message → sends to Telegram via grammy
3. Channel server also pushes a `<channel source="task_completion">` notification into the Claude session
4. If send fails, retries up to 3 times
5. **Watcher cron** (every minute) catches cases where the Stop hook didn't fire

## All Commands

| Command | Description |
|---------|-------------|
| `/create <name> <path> "<purpose>"` | Register a new agent for a project |
| `/delete <name>` | Remove an agent and its workspace |
| `/agents` | List all agents with state and project |
| `/dispatch <agent> "<task>"` | Send a task to an agent (queues if busy) |
| `/status [agent]` | Show running tasks |
| `/kill <agent>` | Stop a running task |
| `/history <agent>` | View task history with cost |
| `/queue [agent]` | Show queued tasks |
| `/cancel <task_id>` | Cancel a queued task |
| `/set-model <agent> <model>` | Change default model (sonnet/opus/haiku) |
| `/cost [agent]` | Cost summary |
| `/create-team <name> --lead <a> --members <b,c>` | Create an agent team |
| `/team-dispatch <team> "<task>"` | Dispatch to team lead |
| `/team-status <team>` | Show team task progress |
| `/help` | Show available commands |

Natural language also works — "tell backend to fix the bug", "what's running?", "stop frontend".

## Architecture

```
~/.claude-bridge/
├── bridge.db          SQLite: agents, tasks, teams, notifications
├── messages.db        SQLite: inbound/outbound message queue
├── config.json        Bot token, settings
├── watcher.log        Cron output
└── workspaces/        Per-agent task results and logs

~/projects/bridge-bot/
├── CLAUDE.md          Bridge Bot routing rules (generated)
└── .mcp.json          Bridge MCP server config (generated)

~/.claude/agents/
└── bridge--*.md       Agent definitions (generated per agent)

~/projects/your-project/
├── CLAUDE.md          Purpose-driven project instructions (generated)
└── .claude/
    └── settings.local.json   Stop hook (generated per agent)
```

### Key Technical Details

| What | Detail |
|------|--------|
| Channel server | TypeScript/Bun (`channel/server.ts`), push-based via `notifications/claude/channel` |
| Message delivery | Push + retry: if not acknowledged in 3s, re-push up to 5 times |
| Outbound delivery | Channel server polls `messages.db`, sends via grammy, retries 3x |
| Stop hook location | Project's `.claude/settings.local.json`, NOT agent .md frontmatter |
| Stop hook format | Nested: `{hooks: [{hooks: [{type: command, command: ...}]}]}` |
| Python path | Absolute path in all hooks and cron (system Python may be 3.9) |
| Python 3.9 compat | `from __future__ import annotations` in all modules |
| Session UUID | Unique per task: `uuid5(session_id + task_id)` |
| Worktree | Each task runs in isolated `git worktree` |
| Queue | Dispatch to busy agent auto-queues, auto-dequeues on completion |

## Project Structure

```
channel/
  server.ts             Bridge Channel server (TypeScript/Bun)
                        grammy bot, MCP channel push, bridge tools,
                        inbound retry engine, outbound poller

src/claude_bridge/
  cli.py                CLI entry (all commands + setup-bot)
  db.py                 Bridge SQLite (agents, tasks, teams, notifications)
  message_db.py         Outbound message queue (for on_complete notifications)
  dispatcher.py         Task spawner (subprocess.Popen + PID tracking)
  on_complete.py        Stop hook handler (updates DB, queues notification)
  notify.py             Notification formatting
  agent_md.py           Agent .md generator + Stop hook installer
  session.py            Session model (agent + project → session_id)
  watcher.py            Cron fallback (dead PID cleanup)
  bridge_bot_claude_md.py  CLAUDE.md generator (channel/mcp/shell modes)
  claude_md_init.py     Purpose-driven CLAUDE.md for agent projects
  channel.py            Multi-channel message formatting
  permission_relay.py   PreToolUse hook for dangerous commands
  memory.py             Auto Memory reader
```

## Development

```bash
# Run core tests
cd ~/projects/claude-bridge
PYTHONPATH=src python3 -m pytest tests/ --ignore=tests/test_mcp_server.py -v

# Run MCP server tests (needs mcp SDK)
PYTHONPATH=src ~/.claude-bridge/venv/bin/python3 -m pytest tests/test_mcp_server.py -v

# Run a specific CLI command
PYTHONPATH=src python3 -m claude_bridge.cli <command>
```

340+ tests. Pure Python stdlib (except `mcp` SDK for the MCP server).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot doesn't respond | Check Claude Code session is running with `--channels server:bridge` |
| "Session ID already in use" | Previous task's session wasn't cleaned up. Run watcher: `PYTHONPATH=src python3 -m claude_bridge.watcher` |
| Stop hook not firing | Check `.claude/settings.local.json` exists in the agent's project. Re-run: `PYTHONPATH=src python3 -m claude_bridge.cli create-agent ...` |
| Cron errors in watcher.log | Check absolute python path. Re-run: `setup-cron` after `remove-cron` |
| Double notifications | Update to latest — `on_complete.py` now marks tasks as reported |
| Task stuck as "running" | Process died without hook. Watcher cron catches this within 1 minute |
| Multiple bots conflict | Only one Claude Code session can poll a bot token. Stop other sessions first |
