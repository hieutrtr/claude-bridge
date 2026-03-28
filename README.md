# Claude Bridge

Multi-session Claude Code dispatch from Telegram. Create agents, assign them to projects, dispatch tasks from your phone.

## How It Works

```
You (Telegram)
  |
  v
Claude Code session (Bridge Bot)     <-- Telegram MCP plugin for messaging
  |                                       CLAUDE.md for command routing
  v
bridge-cli commands                   <-- Python CLI (stdlib only)
  |
  v
claude --agent --worktree -p "task"   <-- Each task = isolated Claude Code agent
  |
  v
Stop hook → on-complete.py           <-- Updates SQLite, notifies completion
```

The Bridge Bot is a normal Claude Code session with:
1. The **Telegram MCP plugin** installed (for receiving/sending messages)
2. A **CLAUDE.md** that tells it how to route commands to `bridge-cli`

That's it. No custom server, no daemon. Just Claude Code + MCP + routing rules.

## Prerequisites

- Python 3.11+
- `claude` CLI installed and in PATH
- Telegram bot token (from [@BotFather](https://t.me/BotFather))

## Setup

### 1. Clone and prepare

```bash
git clone <repo-url> claude-bridge
cd claude-bridge
```

### 2. Create a project folder for Bridge Bot

```bash
mkdir -p ~/bridge-bot
```

### 3. Generate the Bridge Bot CLAUDE.md

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup
```

This prints the CLAUDE.md content. Copy it to your bridge-bot project:

```bash
PYTHONPATH=src python3 -m claude_bridge.cli setup > ~/bridge-bot/CLAUDE.md
```

### 4. Create a Telegram bot

1. Open Telegram, search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot`, follow the prompts to name your bot
3. Copy the bot token (looks like `123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11`)

### 5. Install and configure the Telegram MCP plugin

Start Claude Code in the bridge-bot folder:

```bash
cd ~/bridge-bot
claude
```

Inside Claude Code, install the Telegram plugin:

```
/plugin install telegram@claude-plugins-official
```

Then configure your bot token:

```
/telegram:configure <your-bot-token>
```

This saves the token and starts the Telegram connection.

### 6. Pair your Telegram account

DM your bot on Telegram (send any message). The bot will reply with a 6-character pairing code. In the Claude Code session:

```
/telegram:access pair <code>
```

Lock it down so only you can use the bot:

```
/telegram:access policy allowlist
```

### 7. Create your first agent

From Telegram (or the Bridge Bot session):

```
/create-agent backend /path/to/your/project "API development"
```

### 8. Dispatch a task

```
/dispatch backend "add pagination to /users endpoint"
```

The Bridge Bot will:
- Run `bridge-cli dispatch backend "add pagination to /users endpoint"`
- Spawn a Claude Code agent in an isolated worktree
- The agent works autonomously with `--dangerously-skip-permissions`
- When done, the stop hook updates SQLite

### 9. Check status

```
/status
/history backend
```

## All Commands

| Command | Description |
|---------|-------------|
| `/create-agent <name> <path> "<purpose>"` | Register a new agent |
| `/delete-agent <name>` | Remove an agent |
| `/agents` | List all agents |
| `/dispatch <agent> "<task>"` | Send a task to an agent |
| `/status [agent]` | Check running tasks |
| `/kill <agent>` | Stop a running task |
| `/history <agent>` | View task history |
| `/queue [agent]` | View queued tasks |
| `/cancel <task_id>` | Cancel a queued task |
| `/set-model <agent> <model>` | Change agent model (sonnet/opus/haiku) |
| `/cost [agent] [--period today\|week\|month]` | Cost summary |
| `/create-team <name> --lead <agent> --members <a,b>` | Create agent team |
| `/team-dispatch <team> "<task>"` | Dispatch to team lead |
| `/team-status <team>` | Team task progress |

## Agent Teams

Teams let a lead agent decompose complex tasks and dispatch sub-tasks to teammates:

```
/create-agent backend /projects/api --purpose "API development"
/create-agent frontend /projects/web --purpose "React UI"
/create-team fullstack --lead backend --members frontend
/team-dispatch fullstack "build user profile page with API and UI"
```

The lead agent receives an augmented prompt with teammate info and dispatch commands. Sub-tasks are tracked with `parent_task_id` and costs are aggregated.

## Architecture

- **Session = Agent + Project**: `backend` + `/projects/my-api` = session `backend--my-api`
- **Agent .md files**: `~/.claude/agents/bridge--{session_id}.md` (Claude Code native format)
- **Worktree isolation**: Each task runs in `git worktree` (no conflicts)
- **Stop hook**: Agent frontmatter → `on_complete.py` → SQLite updated
- **Queue**: Dispatch to busy agent queues the task, auto-dequeues on completion
- **SQLite**: All state in `~/.claude-bridge/bridge.db` (WAL mode)

## Project Structure

```
src/claude_bridge/
  cli.py              CLI entry (all commands)
  db.py               SQLite (agents, tasks, teams, permissions)
  session.py           Session model (agent + project → session_id)
  agent_md.py          Agent .md file generator
  claude_md_init.py    CLAUDE.md initialization for agent projects
  dispatcher.py        Task spawner (subprocess.Popen)
  on_complete.py       Stop hook handler
  channel.py           Multi-channel formatting (telegram/discord/slack/cli)
  permission_relay.py  PreToolUse hook for dangerous commands
  bridge_bot_claude_md.py  Bridge Bot CLAUDE.md generator
  memory.py            Auto Memory reader
  watcher.py           Fallback PID watcher
tests/                 pytest (260+ tests)
```

## Running Tests

```bash
PYTHONPATH=src python3 -m pytest tests/ -v
```

No external dependencies. No pip install needed. Just Python 3.11+ stdlib.

## How bridge-cli Works (for contributors)

All commands go through `python3 -m claude_bridge.cli`. The Bridge Bot CLAUDE.md tells Claude Code to run these via Bash. Example flow:

```
User on Telegram: "/dispatch backend add pagination"
  → Telegram MCP delivers message to Bridge Bot session
  → Bridge Bot reads CLAUDE.md routing rules
  → Runs: PYTHONPATH=src python3 -m claude_bridge.cli dispatch backend "add pagination"
  → bridge-cli creates task in SQLite, spawns: claude --agent bridge--backend--my-api --session-id <uuid> --dangerously-skip-permissions -p "add pagination"
  → Agent works in isolated worktree
  → Stop hook fires on_complete.py → marks task done in SQLite
  → Bridge Bot checks for unreported tasks, sends result to Telegram
```
