# Bridge Bot Architecture

> Session #0 — The command router between Telegram and Claude Bridge agents.

---

## 1. What It Is

The Bridge Bot is not custom software. It is a standard Claude Code session launched with a Telegram MCP channel plugin and a CLAUDE.md file that tells it how to route commands.

```
Bridge Bot = Claude Code + Telegram MCP Channel + CLAUDE.md (routing rules)
```

There is no daemon, no server, no custom runtime. It is Claude Code running interactively with two additions:

1. **Telegram MCP Channel** -- an official Anthropic plugin that gives Claude Code bidirectional messaging with a Telegram bot.
2. **CLAUDE.md** -- a file in `~/.claude-bridge/` that instructs Claude Code to parse incoming messages as commands and execute `bridge-cli.py` via the Bash tool.

The Bridge Bot does not write code, edit files, or process data. It is a thin routing layer: read message, parse command, run CLI, relay output.

```
┌─────────────────────────────────────────────────────┐
│                   BRIDGE BOT                         │
│                                                     │
│   ┌───────────────┐    ┌──────────────────────┐     │
│   │  Telegram MCP │◄──►│  Claude Code Session │     │
│   │  Channel      │    │                      │     │
│   │               │    │  CLAUDE.md loaded     │     │
│   │  Reads msgs   │    │  Bash tool available  │     │
│   │  Sends replies│    │  bridge-cli.py path   │     │
│   └───────────────┘    └──────────────────────┘     │
│                                                     │
│   Session #0: routing only, no project work         │
└─────────────────────────────────────────────────────┘
```

---

## 2. How It Starts

### Launch Command

```bash
claude --channel telegram --project-dir ~/.claude-bridge
```

That is the entire startup. One command, one terminal.

### What Happens on Launch

1. Claude Code starts a new interactive session.
2. The `--channel telegram` flag activates the Telegram MCP channel plugin. Claude Code begins polling the Telegram Bot API for incoming messages.
3. The `--project-dir ~/.claude-bridge` flag tells Claude Code to load `~/.claude-bridge/CLAUDE.md` as its project instructions.
4. Claude Code is now listening for Telegram messages and knows how to route them.

### Requirements

- The Telegram MCP channel plugin must be installed and configured beforehand (bot token, allowed users).
- `~/.claude-bridge/` must contain `CLAUDE.md`, `bridge-cli.py`, `on-complete.py`, `watcher.py`, and `bridge.db`.
- The terminal running this command must stay open. If it closes, the Bridge Bot stops.

### Restarting

If the Bridge Bot crashes or the terminal is closed, re-run the same command. Claude Code sessions are stateless on restart -- CLAUDE.md is reloaded, and the bot resumes polling Telegram. No state is lost because all persistent state lives in SQLite (`bridge.db`).

---

## 3. Telegram MCP Channel

The Bridge Bot uses the official Anthropic Telegram MCP channel plugin: `telegram@claude-plugins-official`.

### How It Works

```
┌──────────────┐         ┌───────────────────┐         ┌──────────────┐
│  Your Phone  │         │  Telegram Bot API  │         │  Bridge Bot  │
│              │         │  (Telegram servers)│         │  (your Mac)  │
│  Telegram    │────────►│                    │◄────────│              │
│  App         │◄────────│  Messages stored   │────────►│  Outbound    │
│              │         │  until polled      │         │  polling     │
└──────────────┘         └───────────────────┘         └──────────────┘
                                                        No open ports
                                                        No webhooks
                                                        No inbound traffic
```

### Key Properties

| Property | Detail |
|----------|--------|
| **Connection model** | Outbound polling (long-poll). The Bridge Bot reaches out to Telegram servers. No inbound ports needed. |
| **Network security** | No webhooks, no exposed endpoints. Works behind NAT, firewalls, VPNs. |
| **Message direction** | Bidirectional. Bridge Bot receives messages and sends replies through the same channel. |
| **Rich UI** | Inline keyboard buttons supported. Can present options like `[View Diff]  [Approve]  [Reject]`. |
| **File support** | Can send and receive file attachments (logs, diffs, screenshots). |
| **Sender allowlist** | Only pre-configured Telegram user IDs can interact with the bot. All other messages are ignored. |

### Plugin Configuration

The Telegram MCP channel plugin is configured during setup. The configuration includes:

- **Bot token** -- obtained from @BotFather on Telegram.
- **Allowed user IDs** -- Telegram user IDs permitted to send commands. This is the primary authentication layer.
- **Polling interval** -- how frequently the bot checks for new messages (typically a few seconds via long-polling).

---

## 4. CLAUDE.md (Command Router)

The CLAUDE.md file at `~/.claude-bridge/CLAUDE.md` is the "brain" of the Bridge Bot. It is loaded automatically by Claude Code when the session starts. It defines every command the Bridge Bot understands and how to execute each one.

### Full CLAUDE.md Content

```markdown
# Bridge Bot — Command Router

You are the Bridge Bot for Claude Bridge. You receive messages from Telegram
and route them to bridge-cli.py. You are a dispatcher, not a worker.

## Rules

1. **Relay output verbatim.** When bridge-cli.py prints output, send it back
   to Telegram exactly as-is. Do not summarize, reformat, or editorialize.
2. **Never modify projects directly.** You do not have access to user projects.
   You only call bridge-cli.py, which manages agents that do the actual work.
3. **Stay lightweight.** Do not perform analysis, research, or complex reasoning.
   Parse the command, run the CLI, relay the result.
4. **Unknown input → help.** If a message does not match any command or natural
   language pattern, respond with the help text.

## Commands

All commands are run via the Bash tool:

### /create-agent <name> <project_dir> "<purpose>"
Create a new agent session.
```
python3 ~/.claude-bridge/bridge-cli.py create-agent <name> <project_dir> "<purpose>"
```

### /delete-agent <name>
Delete an agent and its session data.
```
python3 ~/.claude-bridge/bridge-cli.py delete-agent <name>
```

### /task <agent_name> <prompt...>
Dispatch a task to an agent. Everything after the agent name is the prompt.
```
python3 ~/.claude-bridge/bridge-cli.py dispatch <agent_name> "<prompt>"
```

### /agents
List all registered agents and their current state.
```
python3 ~/.claude-bridge/bridge-cli.py list-agents
```

### /status [agent_name]
Show status of running tasks. If agent_name is provided, show only that agent.
```
python3 ~/.claude-bridge/bridge-cli.py status [agent_name]
```

### /kill <agent_name>
Kill a running task on the specified agent.
```
python3 ~/.claude-bridge/bridge-cli.py kill <agent_name>
```

### /history [agent_name] [--limit N]
Show task history. Defaults to last 10 tasks across all agents.
```
python3 ~/.claude-bridge/bridge-cli.py history [agent_name] [--limit N]
```

### /memory <agent_name>
Read the auto-memory files for an agent (what it has learned).
```
python3 ~/.claude-bridge/bridge-cli.py memory <agent_name>
```

### /help
Show available commands.
Print the command list below.

## Natural Language Parsing

Users may send messages without explicit slash commands. Parse the intent:

- "fix the login bug on backend" → /task backend fix the login bug
- "what agents do I have" → /agents
- "is backend busy" → /status backend
- "stop the frontend task" → /kill frontend
- "show me what backend remembers" → /memory backend
- "create a devops agent for /projects/infra" → prompt user for purpose, then /create-agent

When the intent is ambiguous, ask for clarification. When the intent maps clearly
to a command, execute it without asking.

## Help Text

When /help is called or a message is not understood, reply with:

```
Claude Bridge Commands:

/create-agent <name> <dir> "<purpose>"  — Create agent
/delete-agent <name>                    — Remove agent
/task <agent> <prompt>                  — Dispatch task
/agents                                 — List agents
/status [agent]                         — Task status
/kill <agent>                           — Stop task
/history [agent] [--limit N]            — Task history
/memory <agent>                         — Agent memory
/help                                   — This message
```
```

### Why CLAUDE.md Works Here

CLAUDE.md is a native Claude Code feature. It is loaded at session start and survives context compaction. This means:

- If the Bridge Bot runs for hours and its context window fills up, Claude Code will compact the conversation but keep CLAUDE.md intact.
- The routing rules are never lost, even in long-running sessions.
- No code is needed to implement the routing logic -- it is entirely expressed as natural language instructions that Claude Code follows.

---

## 5. Message Flow

### End-to-End: User sends a command

```
┌─────────┐    ┌──────────┐    ┌─────────────┐    ┌─────────────┐    ┌────────────┐
│ Telegram │    │ Telegram │    │  Bridge Bot  │    │ bridge-cli  │    │ Claude Code│
│ App      │    │ Bot API  │    │  (Session 0) │    │   .py       │    │  Agent     │
│ (phone)  │    │ (cloud)  │    │  (your Mac)  │    │  (your Mac) │    │ (your Mac) │
└────┬─────┘    └────┬─────┘    └──────┬──────┘    └──────┬──────┘    └─────┬──────┘
     │               │                 │                   │                 │
     │  User types:  │                 │                   │                 │
     │  /task backend│                 │                   │                 │
     │  add pagination                 │                   │                 │
     │──────────────►│                 │                   │                 │
     │               │                 │                   │                 │
     │               │  MCP delivers   │                   │                 │
     │               │  message        │                   │                 │
     │               │────────────────►│                   │                 │
     │               │                 │                   │                 │
     │               │                 │  Parse: /task     │                 │
     │               │                 │  agent=backend    │                 │
     │               │                 │  prompt="add      │                 │
     │               │                 │   pagination"     │                 │
     │               │                 │                   │                 │
     │               │                 │  Bash tool:       │                 │
     │               │                 │  python3 bridge-  │                 │
     │               │                 │  cli.py dispatch  │                 │
     │               │                 │  backend "add     │                 │
     │               │                 │  pagination"      │                 │
     │               │                 │──────────────────►│                 │
     │               │                 │                   │                 │
     │               │                 │                   │  Look up agent  │
     │               │                 │                   │  Check not busy │
     │               │                 │                   │  Insert task row│
     │               │                 │                   │  Spawn process  │
     │               │                 │                   │────────────────►│
     │               │                 │                   │  claude --agent │
     │               │                 │                   │  --session-id   │
     │               │                 │                   │  -p "prompt"    │
     │               │                 │                   │                 │
     │               │                 │  stdout:          │                 │
     │               │                 │  "Task #7         │                 │
     │               │                 │◄──────────────────│                 │
     │               │                 │   dispatched to   │                 │
     │               │                 │   backend"        │                 │
     │               │                 │                   │                 │
     │               │  MCP sends      │                   │                 │
     │               │  reply          │                   │                 │
     │               │◄────────────────│                   │                 │
     │               │                 │                   │                 │
     │  "Task #7     │                 │                   │                 │
     │◄──────────────│                 │                   │                 │
     │  dispatched   │                 │                   │                 │
     │  to backend"  │                 │                   │                 │
     │               │                 │                   │                 │
```

### Natural Language Flow

When the user sends `"fix the bug in the login flow on backend"` instead of a slash command:

1. Telegram MCP delivers the message to the Bridge Bot.
2. The Bridge Bot's CLAUDE.md includes natural language parsing rules.
3. Claude Code (the LLM powering the Bridge Bot) interprets the message and maps it to: `/task backend fix the bug in the login flow`.
4. The rest of the flow is identical -- Bash tool call to `bridge-cli.py dispatch backend "fix the bug in the login flow"`.

---

## 6. Completion Reports

When an agent finishes a task, the result must get back to the user on Telegram. There are two mechanisms.

### Primary: Stop Hook (immediate)

```
Agent finishes task
        │
        ▼
Stop hook fires (defined in agent .md frontmatter)
        │
        ▼
on-complete.py runs
        │
        ├── 1. Parses result JSON from Claude Code
        ├── 2. Updates task row in bridge.db (status, summary, cost, duration)
        ├── 3. Sets agent state back to "idle"
        └── 4. Writes completion report to stdout
                │
                ▼
        Bridge Bot picks up the output
                │
                ▼
        Sends report to Telegram via MCP channel
```

The stop hook output mechanism works as follows: `on-complete.py` prints a formatted completion report to stdout. The Bridge Bot, being a long-running Claude Code session in the same `~/.claude-bridge/` project directory, can detect completed tasks by periodically running a status check.

However, stop hooks run in the agent's process, not the Bridge Bot's process. The Bridge Bot does not automatically see their stdout. This is where the SQLite bridge comes in:

1. `on-complete.py` writes the completion data to `bridge.db` (sets `tasks.status = 'done'` and `tasks.reported = 0`).
2. The Bridge Bot periodically runs `python3 ~/.claude-bridge/bridge-cli.py check-completed` via the Bash tool.
3. `check-completed` queries for tasks where `status = 'done' AND reported = 0`, prints their reports, and sets `reported = 1`.
4. The Bridge Bot relays those reports to Telegram.

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  Agent       │       │  bridge.db   │       │  Bridge Bot  │
│  (Session N) │       │  (SQLite)    │       │  (Session 0) │
│              │       │              │       │              │
│  Task done   │       │              │       │              │
│  Stop hook   │──────►│  status=done │       │              │
│  on-complete │       │  reported=0  │       │              │
│              │       │              │       │              │
│              │       │              │◄──────│ check-       │
│              │       │              │       │ completed    │
│              │       │              │──────►│              │
│              │       │  reported=1  │       │ Relay to     │
│              │       │              │       │ Telegram     │
└──────────────┘       └──────────────┘       └──────────────┘
```

### Fallback: Watcher (cron-based)

`watcher.py` runs on a cron schedule (every 5 minutes) and catches edge cases the stop hook misses:

- Agent process was killed externally (SIGKILL).
- The stop hook script itself failed.
- A task has been running longer than the timeout threshold (default: 30 minutes).

```
watcher.py logic:
    SELECT * FROM tasks WHERE status = 'running'
    For each task:
        if PID is dead AND reported = 0:
            → mark status = 'failed', reported = 0
            → Bridge Bot will pick up on next check-completed cycle
        if running > 30 minutes:
            → kill process, mark status = 'timeout'
```

The watcher does not send Telegram messages directly. It updates `bridge.db`, and the Bridge Bot picks up the changes on its next `check-completed` call.

### Bridge Bot Polling Loop

The Bridge Bot's CLAUDE.md instructs it to run `check-completed` at a reasonable interval. Because the Bridge Bot is a Claude Code session driven by incoming Telegram messages, the natural trigger is:

- Run `check-completed` before processing each incoming message.
- This ensures the user sees completion reports as soon as they interact with the bot.
- For proactive notifications, the CLAUDE.md can instruct the Bridge Bot to periodically check even without incoming messages (depends on how the Telegram MCP channel handles idle periods).

---

## 7. Error Handling

### Unknown Commands

If a Telegram message does not match any known command or natural language pattern, the Bridge Bot replies with the help text. This is defined in CLAUDE.md under the "Unknown input -> help" rule.

### Invalid Arguments

```
User: /task
Bot:  Missing arguments. Usage: /task <agent_name> <prompt>

User: /task nonexistent-agent do something
Bot:  [relay bridge-cli.py error output verbatim]
      Error: Agent "nonexistent-agent" not found. Run /agents to see available agents.

User: /create-agent backend /nonexistent/path "purpose"
Bot:  [relay bridge-cli.py error output verbatim]
      Error: Directory "/nonexistent/path" does not exist.
```

The Bridge Bot does minimal validation itself. It passes arguments to `bridge-cli.py` and relays whatever output comes back -- including error messages. `bridge-cli.py` is responsible for validating inputs and returning clear error messages.

### bridge-cli.py Errors

If `bridge-cli.py` exits with a non-zero status code or prints to stderr, the Bridge Bot relays the error output to Telegram. Common scenarios:

| Scenario | bridge-cli.py Output | Bridge Bot Action |
|----------|---------------------|-------------------|
| Agent not found | `Error: Agent "X" not found` | Relay verbatim |
| Agent busy | `Error: Agent "X" is running task #5. /kill first or wait.` | Relay verbatim |
| SQLite locked | `Error: Database locked, retry in a moment` | Relay verbatim |
| Python exception | Traceback to stderr | Relay stderr to user |
| Script not found | `bash: python3: command not found` | Relay bash error |

### Bridge Bot Session Errors

The Bridge Bot itself is a Claude Code session and can encounter issues:

| Issue | What Happens | Recovery |
|-------|-------------|----------|
| Context window fills up | Claude Code compacts conversation. CLAUDE.md survives. Routing rules intact. | Automatic -- no action needed. |
| Telegram MCP disconnects | Claude Code will attempt to reconnect (plugin behavior). | Automatic reconnect. If persistent, restart the session. |
| Terminal closes | Bridge Bot process dies. No Telegram messages are processed. | Re-run `claude --channel telegram --project-dir ~/.claude-bridge`. |
| bridge-cli.py crash | Bash tool returns error output. | Bridge Bot relays the error. User can retry. |

---

## 8. Limitations

### Context Window

The Bridge Bot is a Claude Code session with a finite context window. Every message received and every CLI output adds to the context. Over time, the context will fill and Claude Code will compact it.

**Mitigation:** CLAUDE.md survives compaction (native Claude Code behavior). The routing rules are never lost. Conversation history may be summarized, but the bot continues to function correctly.

**Best practice:** Keep interactions short. The Bridge Bot should not be used for long conversations or complex reasoning. Parse command, run CLI, relay output, done.

### No Parallel Message Processing

The Bridge Bot processes one Telegram message at a time. If two users send commands simultaneously (or one user sends commands rapidly), they are handled sequentially.

**Mitigation:** Each command is fast (parse + CLI call + relay). The bottleneck is never the Bridge Bot itself -- it is the agent tasks, which run asynchronously.

### No Direct Project Access

The Bridge Bot runs in `~/.claude-bridge/`, not in any user project directory. It cannot read or modify project files. All project interaction goes through `bridge-cli.py` which manages agent sessions that operate in their respective project directories.

This is by design. The Bridge Bot should never have project access -- it is a command router, not a worker.

### Single Instance

Only one Bridge Bot should run at a time. Running multiple instances would cause:
- Duplicate Telegram message processing.
- SQLite write conflicts on `bridge.db`.
- Duplicate completion reports.

### Depends on Terminal Session

The Bridge Bot runs in a terminal and dies if the terminal closes. It is not daemonized.

**Mitigation options for production use:**
- Run in `tmux` or `screen` session: `tmux new -s bridge-bot -d 'claude --channel telegram --project-dir ~/.claude-bridge'`
- Use a process manager like `launchd` (macOS native).
- Wrap in a simple shell script that restarts on exit.

### No State Persistence Across Restarts

When the Bridge Bot restarts, it loses its conversation context. It does not remember previous Telegram messages. However, all important state is in SQLite (`bridge.db`), so no data is lost -- only the conversational context of the Bridge Bot session resets.

---

## Appendix: Relationship to Other Components

```
┌───────────────────────────────────────────────────────────────────┐
│                        BRIDGE BOT                                  │
│                     (this document)                                │
│                                                                   │
│  Depends on:                                                      │
│  ├── Telegram MCP Channel plugin (official Anthropic)             │
│  ├── bridge-cli.py (command execution)                            │
│  ├── bridge.db / SQLite (state storage)                           │
│  └── CLAUDE.md (routing rules)                                    │
│                                                                   │
│  Interacts with:                                                  │
│  ├── on-complete.py (reads completion data from bridge.db)        │
│  ├── watcher.py (reads failure/timeout data from bridge.db)       │
│  └── Agent sessions #1..N (indirectly, via bridge-cli.py)         │
│                                                                   │
│  Does NOT interact with:                                          │
│  ├── User project files (no access)                               │
│  ├── Agent .md files (bridge-cli.py manages those)                │
│  └── Claude Code internals (sessions, worktrees, memory)          │
└───────────────────────────────────────────────────────────────────┘
```
