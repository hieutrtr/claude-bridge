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

- macOS or Linux
- Python 3.11+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and in PATH
- [Bun](https://bun.sh) runtime (for the Telegram MCP plugin)
- A Telegram account

## Setup

### 1. Install Bun (if you don't have it)

The Telegram MCP plugin runs on Bun. Install it:

```bash
curl -fsSL https://bun.sh/install | bash
exec $SHELL   # reload your shell so `bun` is in PATH
```

Verify:

```bash
bun --version
```

### 2. Clone Claude Bridge

```bash
git clone <repo-url> ~/projects/claude-bridge
cd ~/projects/claude-bridge
```

### 3. Create a Telegram bot

1. Open Telegram on your phone
2. Search for [@BotFather](https://t.me/BotFather) and start a chat
3. Send `/newbot`
4. Follow the prompts to pick a name and username
5. BotFather gives you a token like `7123456789:AAH1bGcK9...` — save it

### 4. Create the Bridge Bot project folder

This is a separate folder where you'll run the Bridge Bot session:

```bash
mkdir -p ~/projects/bridge-bot
cd ~/projects/bridge-bot
git init
```

### 5. Generate the Bridge Bot CLAUDE.md

From the claude-bridge repo, generate the routing rules:

```bash
cd ~/projects/claude-bridge
PYTHONPATH=src python3 -m claude_bridge.cli setup > ~/projects/bridge-bot/CLAUDE.md
```

This creates a CLAUDE.md that tells the Bridge Bot how to parse Telegram commands and run bridge-cli.

### 6. Install the Telegram MCP plugin

Start Claude Code inside the bridge-bot folder:

```bash
cd ~/projects/bridge-bot
claude
```

Inside the Claude Code session, install the official Telegram plugin:

```
/plugin install telegram@claude-plugins-official
```

Claude Code downloads the plugin to `~/.claude/plugins/` and installs its dependencies automatically.

Then configure your bot token:

```
/telegram:configure <your-bot-token>
```

Replace `<your-bot-token>` with the token from step 3.

This saves the token and connects to Telegram. You should see the plugin status change to connected.

> **What just happened:** Claude Code installed the Telegram plugin source to
> `~/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/telegram/`,
> ran `bun install` to fetch its dependencies, and saved your bot token.
> The plugin is now available in this project. You only need to do this once.

### 7. Pair your Telegram account

On your phone, open Telegram and DM your bot (send any message like "hello"). The bot replies with a 6-character pairing code.

Back in the Claude Code session, approve the pairing:

```
/telegram:access pair <code>
```

Then lock access so only you can use the bot:

```
/telegram:access policy allowlist
```

### 8. Verify it works

Send `/help` to your bot on Telegram. The Bridge Bot should reply with available commands.

### 9. Create your first agent

From Telegram:

```
/create-agent backend /path/to/your/project "API development"
```

The project path must be an existing directory with a git repo on the machine running Claude Code.

### 10. Dispatch a task

```
/dispatch backend "add pagination to /users endpoint"
```

The Bridge Bot will:
- Spawn a Claude Code agent in an isolated git worktree
- The agent works autonomously with full permissions
- When done, the stop hook updates SQLite

### 11. Check status

```
/status
/history backend
```

## Starting the Bridge Bot (after first setup)

After the initial setup, start the Bridge Bot any time with:

```bash
cd ~/projects/bridge-bot
claude
```

The Telegram MCP plugin reconnects automatically. The CLAUDE.md routing rules load on session start.

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
cd ~/projects/claude-bridge
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
  → bridge-cli creates task in SQLite, spawns:
      claude --agent bridge--backend--my-api \
             --session-id <uuid> \
             --dangerously-skip-permissions \
             -p "add pagination"
  → Agent works in isolated worktree
  → Stop hook fires on_complete.py → marks task done in SQLite
  → Bridge Bot checks for unreported tasks, sends result to Telegram
```
