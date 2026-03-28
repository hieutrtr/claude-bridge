# Claude Bridge

Dispatch Claude Code agents from your phone via Telegram. Create agents, assign them to projects, dispatch tasks, get notified when done.

## How It Works

```
You (Telegram)
  │
  ▼
Bridge MCP Server                      Polls Telegram, queues messages
  │                                    Sends replies, retries on failure
  │ stdio (MCP protocol)
  ▼
Claude Code session (Bridge Bot)       Reads messages via bridge_* tools
  │                                    CLAUDE.md for intent mapping
  │ bridge_dispatch(agent, prompt)
  ▼
claude --agent --worktree -p "task"    Each task = isolated Claude Code agent
  │
  ▼
Stop hook → on_complete.py             Updates SQLite, queues notification
                                       Bridge MCP delivers to Telegram
```

**Bridge Bot** = Claude Code session + Bridge MCP server + CLAUDE.md routing rules.
No custom daemon. No Telegram plugin. Just Claude Code with an MCP server.

## Prerequisites

| What | Why |
|------|-----|
| macOS or Linux | Runs on your machine |
| Python 3.11+ | Bridge core (stdlib only, no pip deps except MCP SDK) |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | Must be in PATH — `claude --version` to verify |
| Telegram account | Control plane — you send commands from your phone |

## Installation

### Step 1: Clone the repo

```bash
git clone https://github.com/hieutrtr/claude-bridge.git ~/projects/claude-bridge
cd ~/projects/claude-bridge
```

### Step 2: Install the MCP SDK

The Bridge MCP server needs the `mcp` Python package. Install it in an isolated venv:

```bash
python3 -m venv ~/.claude-bridge/venv
~/.claude-bridge/venv/bin/pip install mcp
```

This venv is only used by the Bridge MCP server. The rest of Claude Bridge is pure stdlib.

### Step 3: Create a Telegram bot

1. Open Telegram on your phone
2. Search for [@BotFather](https://t.me/BotFather) and start a chat
3. Send `/newbot`
4. Follow the prompts — pick a name and username for your bot
5. BotFather gives you a token like `7123456789:AAH1bGcK9...`
6. Copy this token — you'll need it in the next step

### Step 4: Save the bot token

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

### Step 5: Generate the Bridge Bot project

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
  claude --dangerously-skip-permissions
```

What was created:

| File | What it does |
|------|-------------|
| `CLAUDE.md` | Tells the Bridge Bot how to parse commands, dispatch tasks, handle errors |
| `.mcp.json` | Configures Bridge MCP server — auto-starts when Claude Code opens this project |

The `.mcp.json` contains your bot token and the path to Claude Bridge source. If you move the claude-bridge repo, re-run `setup-bot`.

### Step 6: Install the watcher cron

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup-cron
```

This adds a cron job that runs every minute:
- Detects tasks where the Stop hook didn't fire (process died)
- Cleans up stale `running` state in SQLite
- Queues missed notifications for delivery

To remove later: `PYTHONPATH=src python3 -m claude_bridge.cli remove-cron`

### Step 7: Start the Bridge Bot

```bash
cd ~/projects/bridge-bot
claude --dangerously-skip-permissions
```

What happens:
1. Claude Code reads `.mcp.json` → starts Bridge MCP server as a subprocess
2. Bridge MCP starts the Telegram poller thread → your bot comes online
3. Claude Code reads `CLAUDE.md` → knows how to route Telegram commands
4. The Bridge Bot calls `bridge_get_messages()` to check for your messages

### Step 8: Pair your Telegram account

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

### Step 9: Verify

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
claude --dangerously-skip-permissions
```

- Bridge MCP reconnects to Telegram automatically
- No `--channels` flag needed
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
1. **Stop hook** fires `on_complete.py` → writes to `outbound_messages` queue
2. **Bridge MCP poller** picks up the message → sends to Telegram
3. If send fails, retries up to 3 times
4. **Watcher cron** (every minute) catches cases where the Stop hook didn't fire

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
| Stop hook location | Project's `.claude/settings.local.json`, NOT agent .md frontmatter |
| Stop hook format | Nested: `{hooks: [{hooks: [{type: command, command: ...}]}]}` |
| Python path | Absolute path in all hooks and cron (system Python may be 3.9) |
| Python 3.9 compat | `from __future__ import annotations` in all modules |
| Session UUID | Unique per task: `uuid5(session_id + task_id)` |
| Message retry | Inbound: 5 retries, 3s timeout. Outbound: 3 retries |
| Worktree | Each task runs in isolated `git worktree` |
| Queue | Dispatch to busy agent auto-queues, auto-dequeues on completion |

## Project Structure

```
src/claude_bridge/
  cli.py                CLI entry point (all commands + setup)
  mcp_server.py         Bridge MCP server (FastMCP, stdio transport)
  mcp_tools.py          MCP tool implementations (dispatch, status, etc.)
  telegram_poller.py    Telegram polling thread + outbound delivery
  message_db.py         Message queue SQLite (inbound, outbound, poller state)
  db.py                 Bridge SQLite (agents, tasks, teams, notifications)
  dispatcher.py         Task spawner (subprocess.Popen + PID tracking)
  on_complete.py        Stop hook handler (updates DB, queues notification)
  notify.py             Notification formatting + Telegram delivery
  channel.py            Multi-channel message formatting
  agent_md.py           Agent .md generator + Stop hook installer
  session.py            Session model (agent + project → session_id)
  watcher.py            Cron fallback (dead PID cleanup, notification retry)
  bridge_bot_claude_md.py  CLAUDE.md generator (MCP mode + shell fallback)
  claude_md_init.py     Purpose-driven CLAUDE.md for agent projects
  permission_relay.py   PreToolUse hook for dangerous commands
  memory.py             Auto Memory reader
```

## Development

```bash
# Run core tests (no external deps)
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
| Bot doesn't respond | Check Claude Code session is running in bridge-bot folder |
| "Session ID already in use" | Previous task's session wasn't cleaned up. Run watcher: `PYTHONPATH=src python3 -m claude_bridge.watcher` |
| Stop hook not firing | Check `.claude/settings.local.json` exists in the agent's project. Re-run: `PYTHONPATH=src python3 -m claude_bridge.cli create-agent ...` |
| Cron errors in watcher.log | Check absolute python path. Re-run: `setup-cron` after `remove-cron` |
| Double notifications | Update to latest — `on_complete.py` now marks tasks as reported |
| Task stuck as "running" | Process died without hook. Watcher cron catches this within 1 minute |
| Multiple bots conflict | Only one Claude Code session can poll a bot token. Stop other sessions first |
