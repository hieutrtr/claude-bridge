# Claude Bridge — Setup Guideline

## Prerequisites

| Requirement | Purpose |
|-------------|---------|
| Python 3.11+ | Core package |
| [Bun](https://bun.sh) | Channel server runtime |
| Claude Code CLI | Run `claude --version` to verify |
| Telegram account | Send commands from phone |

## Step 1: Create a Telegram Bot

1. Open Telegram, search **@BotFather**
2. Send `/newbot`, follow prompts
3. Choose a display name (unicode/emoji allowed)
4. Choose a username (`a-z`, `0-9`, `_` only, must end in `bot`, 5–32 chars)
5. Copy the bot token

Get your Telegram user ID:
1. Search **@getidsbot** or **@RawDataBot**
2. Send any message → copy your numeric user ID

## Step 2: Install

```bash
git clone https://github.com/hieutrtr/claude-bridge.git ~/projects/claude-bridge
cd ~/projects/claude-bridge

# Install Python package (pick one)
pipx install -e .                          # recommended
# or: pip3 install -e . --break-system-packages
# or: uv pip install -e .  (then use .venv/bin/bridge-cli)

# Install Bun dependencies and build channel server
cd channel && bun install && cd ..
bun run build
```

## Step 3: Run Setup Wizard

```bash
bridge-cli setup
# or if using uv: .venv/bin/bridge-cli setup
```

The wizard will:
1. Ask for your bot token → saved to `~/.claude-bridge/config.json`
2. Ask for bridge-bot directory → creates `~/projects/bridge-bot/` with `CLAUDE.md`, `.mcp.json`, `settings.local.json`
3. Deploy channel server to `~/.claude-bridge/channel/dist/server.js`
4. Install watcher cron

## Step 4: Start the Bridge Bot

```bash
bridge start
```

This runs Claude Code in a tmux session. Other useful commands:

```bash
bridge attach     # attach to the session
bridge logs -f    # follow logs
bridge stop       # stop the bot
bridge status     # check if running
```

> **Note:** On first start you may see a development channel warning — press **Enter** to accept it.

## Step 5: Pair Telegram

1. DM your bot on Telegram (send `hello`)
2. Run `bridge attach` to open the Claude Code session
3. Watch for the 6-digit pairing code
4. In that session, type:
   ```
   /telegram:access pair <6-digit-code>
   /telegram:access policy allowlist
   ```
5. Bot replies on Telegram: "✅ Paired"

## Step 6: Create an Agent

From CLI:
```bash
bridge-cli create-agent myagent /path/to/project --purpose "dev"
```

Or from Telegram after pairing:
```
/create myagent /path/to/project "dev"
```

## Step 7: Dispatch a Task

From Telegram:
```
dispatch myagent fix the login bug
```

Agent runs in an isolated git worktree. You get a Telegram notification when done.

## Useful Commands

```bash
bridge-cli status          # running tasks
bridge-cli list-agents     # all agents
bridge-cli doctor          # health check
bridge-cli doctor --fix    # auto-fix issues
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Bot not responding | `bridge attach` — check for warning prompt, press Enter |
| Channel server build fails | `cd channel && bun install && cd .. && bun run build` |
| `bridge-cli` not found | Use `.venv/bin/bridge-cli` or run `pipx ensurepath` |
| Task stuck at "running" | Watcher cron auto-fixes within 1 minute; or `bridge-cli watcher` |
| Need to pair again | In Claude session: `/telegram:access reset` then re-pair |
