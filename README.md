# Claude Bridge

Multi-session Claude Code dispatch from Telegram. Create agents, assign them to projects, dispatch tasks from your phone.

## How It Works

```
You (Telegram)
  |
  v
Bridge MCP Server                     <-- Polls Telegram, queues messages
  |                                       Sends replies, retries on failure
  | stdio (MCP protocol)
  v
Claude Code session (Bridge Bot)      <-- Reads messages via bridge_* tools
  |                                       CLAUDE.md for intent mapping
  | bridge_dispatch(agent, prompt)
  v
claude --agent --worktree -p "task"   <-- Each task = isolated Claude Code agent
  |
  v
Stop hook → on_complete.py           <-- Updates SQLite, queues notification
  |                                       Bridge MCP delivers to Telegram
```

The Bridge Bot is a Claude Code session with:
1. A **Bridge MCP server** that handles Telegram polling, message delivery, and bridge operations
2. A **CLAUDE.md** that tells it how to process messages and dispatch tasks

No `--channels` flag needed. No Telegram MCP plugin. Bridge MCP handles everything.

## Prerequisites

- macOS or Linux
- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and in PATH
- A Telegram account
- MCP SDK: `pip install mcp` (or use the venv at `~/.claude-bridge/venv`)

## Setup

### 1. Clone Claude Bridge

```bash
git clone <repo-url> ~/projects/claude-bridge
cd ~/projects/claude-bridge
```

### 2. Install MCP SDK

```bash
python3 -m venv ~/.claude-bridge/venv
~/.claude-bridge/venv/bin/pip install mcp
```

### 3. Create a Telegram bot

1. Open Telegram, search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts
3. Copy the bot token

### 4. Save the bot token

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup-telegram "<your-bot-token>"
```

### 5. Set up the Bridge Bot project

One command generates both CLAUDE.md and .mcp.json:

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup-bot ~/projects/bridge-bot
```

This creates:
- `~/projects/bridge-bot/CLAUDE.md` — routing rules and intent mapping
- `~/projects/bridge-bot/.mcp.json` — Bridge MCP server config with your bot token

### 6. Install the watcher cron

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup-cron
```

Runs every minute: cleans up dead tasks, retries failed notifications.

### 7. Pair your Telegram account

Start the Bridge Bot:

```bash
cd ~/projects/bridge-bot
claude --dangerously-skip-permissions
```

The Bridge MCP server starts automatically (via .mcp.json) and begins polling Telegram.

DM your bot on Telegram. The bot replies with a 6-character pairing code. In Claude Code:

```
/telegram:access pair <code>
```

Lock access:

```
/telegram:access policy allowlist
```

### 8. Create your first agent

From Telegram:

```
/create backend /path/to/your/project "API development"
```

### 9. Dispatch a task

```
dispatch backend add pagination to /users endpoint
```

The Bridge Bot receives via Bridge MCP, dispatches the task, and notifies you on Telegram when done.

## Starting the Bridge Bot (after first setup)

```bash
cd ~/projects/bridge-bot
claude --dangerously-skip-permissions
```

Bridge MCP reconnects to Telegram automatically. No `--channels` flag needed.

## All Commands

| Command | Description |
|---------|-------------|
| `/create <name> <path> "<purpose>"` | Register a new agent |
| `/delete <name>` | Remove an agent |
| `/agents` | List all agents |
| `/dispatch <agent> "<task>"` | Send a task to an agent |
| `/status [agent]` | Check running tasks |
| `/kill <agent>` | Stop a running task |
| `/history <agent>` | View task history |
| `/queue [agent]` | View queued tasks |
| `/cancel <task_id>` | Cancel a queued task |
| `/set-model <agent> <model>` | Change agent model (sonnet/opus/haiku) |
| `/cost [agent]` | Cost summary |
| `/create-team <name> --lead <agent> --members <a,b>` | Create agent team |
| `/team-dispatch <team> "<task>"` | Dispatch to team lead |
| `/team-status <team>` | Team task progress |

## Agent Teams

```
/create backend /projects/api "API development"
/create frontend /projects/web "React UI"
/create-team fullstack --lead backend --members frontend
/team-dispatch fullstack "build user profile page with API and UI"
```

The lead decomposes the task and dispatches sub-tasks to teammates. Costs are aggregated.

## Architecture

```
Bridge MCP Server (Python, stdio)
  ├── Telegram Poller (thread) — getUpdates + sendMessage
  ├── Message Queue (SQLite) — inbound + outbound with retry
  ├── Bridge Tools — dispatch, status, agents, history, kill
  └── Notification Queue — on_complete writes, poller delivers

Bridge Bot (Claude Code session)
  ├── CLAUDE.md — intent mapping, onboarding, error recovery
  └── Uses bridge_* MCP tools (no shell-outs)

Agents (Claude Code sessions)
  ├── Agent .md — role, tools, model, isolation: worktree
  ├── Stop hook — .claude/settings.local.json (not frontmatter)
  └── on_complete.py — updates SQLite, queues notification
```

Key details:
- **Stop hook must be in project `.claude/settings.local.json`** (frontmatter hooks don't fire in `--agent -p` mode)
- **Absolute python path** in hooks and cron (system Python may be 3.9)
- **`from __future__ import annotations`** in all modules for 3.9 compat
- **Unique UUID per task** (`uuid5(session_id + task_id)`) to avoid session lock conflicts

## Project Structure

```
src/claude_bridge/
  cli.py                CLI entry (all commands)
  mcp_server.py         Bridge MCP server (FastMCP, stdio)
  mcp_tools.py          MCP tool implementations
  telegram_poller.py    Telegram polling + outbound delivery
  message_db.py         Message queue (inbound, outbound, poller state)
  db.py                 Bridge DB (agents, tasks, teams, notifications)
  dispatcher.py         Task spawner (subprocess.Popen)
  on_complete.py        Stop hook handler
  notify.py             Notification formatting
  channel.py            Multi-channel formatting
  agent_md.py           Agent .md generator
  session.py            Session model
  watcher.py            Cron fallback (dead PIDs, retry notifications)
  bridge_bot_claude_md.py  CLAUDE.md generator
tests/                  pytest (330+ tests)
```

## Running Tests

```bash
# Core tests (no MCP dependency)
PYTHONPATH=src python3 -m pytest tests/ --ignore=tests/test_mcp_server.py -v

# MCP tests (needs mcp SDK)
PYTHONPATH=src ~/.claude-bridge/venv/bin/python3 -m pytest tests/test_mcp_server.py -v
```
