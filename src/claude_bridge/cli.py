"""CLI entry point — bridge-cli.py command dispatcher."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from .db import BridgeDB
from .session import (
    derive_session_id,
    derive_agent_file_name,
    validate_agent_name,
    validate_project_dir,
    create_workspace,
    cleanup_workspace,
    get_agent_file_path,
)
from .agent_md import generate_agent_md, write_agent_md, delete_agent_md
from .claude_md_init import init_claude_md
from .dispatcher import spawn_task, get_result_file, pid_alive, kill_process
from .bridge_bot_claude_md import write_bridge_bot_claude_md
from .memory import format_memory_report


def build_parser() -> argparse.ArgumentParser:
    from . import __version__
    parser = argparse.ArgumentParser(prog="bridge-cli", description="Claude Bridge CLI")
    parser.add_argument("--version", action="version", version=f"claude-bridge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # create-agent
    p = sub.add_parser("create-agent", help="Register a new agent")
    p.add_argument("name", help="Agent name (e.g., backend)")
    p.add_argument("path", help="Project directory path")
    p.add_argument("--purpose", required=True, help="Agent purpose description")
    p.add_argument("--model", default=None, help="Model (sonnet/opus/haiku, default: sonnet)")

    # delete-agent
    p = sub.add_parser("delete-agent", help="Delete an agent")
    p.add_argument("name", help="Agent name")

    # dispatch
    p = sub.add_parser("dispatch", help="Dispatch a task to an agent")
    p.add_argument("name", help="Agent name")
    p.add_argument("prompt", help="Task prompt")
    p.add_argument("--model", default=None, help="Model override for this task")
    p.add_argument("--channel", default="cli", help="Source channel (cli/telegram/discord/slack)")
    p.add_argument("--chat-id", default=None, help="Channel chat/thread ID")
    p.add_argument("--message-id", default=None, help="Channel message ID")

    # list-agents
    sub.add_parser("list-agents", help="List all agents")

    # status
    p = sub.add_parser("status", help="Show agent status")
    p.add_argument("name", nargs="?", default=None, help="Agent name (optional)")

    # kill
    p = sub.add_parser("kill", help="Kill a running task")
    p.add_argument("name", help="Agent name")

    # history
    p = sub.add_parser("history", help="Show task history")
    p.add_argument("name", help="Agent name")
    p.add_argument("--limit", type=int, default=10, help="Number of tasks to show")

    # memory
    p = sub.add_parser("memory", help="Show agent Auto Memory")
    p.add_argument("name", help="Agent name")

    # queue
    p = sub.add_parser("queue", help="Show queued tasks")
    p.add_argument("name", nargs="?", default=None, help="Agent name (optional)")

    # cancel
    p = sub.add_parser("cancel", help="Cancel a queued task")
    p.add_argument("task_id", type=int, help="Task ID to cancel")

    # set-model
    p = sub.add_parser("set-model", help="Change agent default model")
    p.add_argument("name", help="Agent name")
    p.add_argument("model", help="Model (sonnet/opus/haiku)")

    # cost
    p = sub.add_parser("cost", help="Show cost summary")
    p.add_argument("name", nargs="?", default=None, help="Agent name (optional)")
    p.add_argument("--period", default="all", choices=["today", "week", "month", "all"])

    # permissions
    sub.add_parser("permissions", help="List pending permission requests")

    # approve
    p = sub.add_parser("approve", help="Approve a permission request")
    p.add_argument("request_id", help="Permission request ID")

    # deny
    p = sub.add_parser("deny", help="Deny a permission request")
    p.add_argument("request_id", help="Permission request ID")

    # create-team
    p = sub.add_parser("create-team", help="Create an agent team")
    p.add_argument("name", help="Team name")
    p.add_argument("--lead", required=True, help="Lead agent name")
    p.add_argument("--members", required=True, help="Comma-separated member agent names")

    # list-teams
    sub.add_parser("list-teams", help="List all teams")

    # delete-team
    p = sub.add_parser("delete-team", help="Delete a team")
    p.add_argument("name", help="Team name")

    # team-status
    p = sub.add_parser("team-status", help="Show team task status")
    p.add_argument("name", help="Team name")

    # team-dispatch
    p = sub.add_parser("team-dispatch", help="Dispatch a task to a team")
    p.add_argument("name", help="Team name")
    p.add_argument("prompt", help="Task prompt")
    p.add_argument("--channel", default="cli", help="Source channel")
    p.add_argument("--chat-id", default=None, help="Channel chat/thread ID")
    p.add_argument("--message-id", default=None, help="Channel message ID")

    # setup-telegram
    p = sub.add_parser("setup-telegram", help="Save Telegram bot token and chat ID")
    p.add_argument("token", help="Telegram bot token from @BotFather")
    p.add_argument("--chat-id", default=None, help="Your Telegram user/chat ID")

    # setup
    p = sub.add_parser("setup", help="Interactive setup wizard (or --no-prompt for scripted)")
    p.add_argument("--token", default=None, help="Telegram bot token")
    p.add_argument("--chat-id", default=None, help="Your Telegram user/chat ID")
    p.add_argument("--bot-dir", default=None, help="Bridge bot project directory")
    p.add_argument("--no-prompt", action="store_true", help="Non-interactive mode")

    # setup-bot
    p = sub.add_parser("setup-bot", help="Generate CLAUDE.md + .mcp.json in target directory")
    p.add_argument("path", help="Bridge bot project directory (e.g., ~/projects/bridge-bot)")

    # setup-cron
    sub.add_parser("setup-cron", help="Install watcher cron job (runs every minute)")

    # remove-cron
    sub.add_parser("remove-cron", help="Remove watcher cron job")

    # on-complete (called by Stop hook)
    p = sub.add_parser("on-complete", help="Stop hook handler (called by Claude Code)")
    p.add_argument("--session-id", required=True, help="Session ID")

    # watcher (called by cron)
    sub.add_parser("watcher", help="Run watcher (cron fallback for dead PIDs)")

    # doctor
    p = sub.add_parser("doctor", help="Diagnose installation health")
    p.add_argument("--fix", action="store_true", help="Attempt auto-repair")

    # uninstall
    p = sub.add_parser("uninstall", help="Remove claude-bridge data and config")
    p.add_argument("--force", action="store_true", help="Skip confirmation prompt")

    return parser


def cmd_create_agent(db: BridgeDB, args):
    # Validate
    err = validate_agent_name(args.name)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    project_dir = os.path.expanduser(args.path)
    err = validate_project_dir(project_dir)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    if db.get_agent(args.name):
        print(f"Error: Agent '{args.name}' already exists.", file=sys.stderr)
        return 1

    # Validate model
    VALID_MODELS = ("sonnet", "opus", "haiku")
    model = getattr(args, "model", None) or "sonnet"
    if model not in VALID_MODELS:
        print(f"Error: Invalid model '{model}'. Valid: {', '.join(VALID_MODELS)}", file=sys.stderr)
        return 1

    # Derive session identity
    session_id = derive_session_id(args.name, project_dir)
    agent_file_name = derive_agent_file_name(session_id)

    # Generate agent .md
    content = generate_agent_md(session_id, args.name, project_dir, args.purpose, model=model)
    agent_file_path = write_agent_md(session_id, content)

    # Install Stop hook in project settings (frontmatter hooks don't fire in -p mode)
    from .agent_md import install_stop_hook
    install_stop_hook(project_dir, session_id)

    # Create workspace
    create_workspace(session_id, args.name, project_dir, args.purpose)

    # Register in SQLite
    db.create_agent(args.name, project_dir, session_id, agent_file_path, args.purpose, model=model)

    # Init CLAUDE.md (async-ish — report result but don't block on failure)
    print(f"Agent '{args.name}' created for {project_dir}")
    print(f"  Session: {session_id}")
    print(f"  Purpose: {args.purpose}")
    print(f"  Agent file: {agent_file_path}")

    print("  Initializing CLAUDE.md (scanning project + injecting purpose)...")
    result = init_claude_md(project_dir, args.name, args.purpose)
    if result["success"]:
        cost_info = f" (cost: ${result.get('cost_usd', 0):.3f})" if result.get("cost_usd") else ""
        print(f"  CLAUDE.md: {result['message']}{cost_info}")
    else:
        print(f"  Warning: CLAUDE.md init failed: {result['error']}")
        print("  Agent is still usable — CLAUDE.md can be created manually.")

    print("Ready for tasks.")
    return 0


def cmd_delete_agent(db: BridgeDB, args):
    agent = db.get_agent(args.name)
    if not agent:
        print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
        return 1

    session_id = agent["session_id"]

    # Reject if agent has a running task
    running = db.get_running_task(session_id)
    if running:
        print(
            f"Error: Agent '{args.name}' has a running task (#{running['id']}). "
            f"Use 'kill {args.name}' first.",
            file=sys.stderr,
        )
        return 1

    # Clean up
    delete_agent_md(session_id)
    cleanup_workspace(session_id)
    db.delete_agent(args.name)

    print(f"Agent '{args.name}' deleted.")
    return 0


def cmd_dispatch(db: BridgeDB, args):
    agent = db.get_agent(args.name)
    if not agent:
        print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
        return 1

    session_id = agent["session_id"]

    channel = getattr(args, "channel", None)
    chat_id = getattr(args, "chat_id", None)
    message_id = getattr(args, "message_id", None)

    # Auto-detect notification channel if not specified
    if not channel or channel == "cli":
        from .notify import get_default_channel
        channel, default_chat_id = get_default_channel()
        if not chat_id:
            chat_id = default_chat_id

    # Check if busy — queue instead of reject
    running = db.get_running_task(session_id)
    if running:
        task_id = db.create_task(session_id, args.prompt, channel=channel, channel_chat_id=chat_id, channel_message_id=message_id)
        position = db.get_next_queue_position(session_id)
        db.update_task(task_id, status="queued", position=position)
        print(f"Agent '{args.name}' is busy. Task #{task_id} queued at position {position}.")
        return 0

    # Create task
    task_id = db.create_task(session_id, args.prompt, channel=channel, channel_chat_id=chat_id, channel_message_id=message_id)
    result_file = get_result_file(session_id, task_id)
    agent_file_name = derive_agent_file_name(session_id)

    # Determine model (override or agent default)
    model = getattr(args, "model", None) or agent["model"]

    # Spawn
    pid = spawn_task(agent_file_name, session_id, agent["project_dir"], args.prompt, task_id, model=model)

    # Update state
    db.update_task(
        task_id,
        status="running",
        pid=pid,
        result_file=result_file,
        model=model,
        started_at=datetime.now().isoformat(),
    )
    db.update_agent_state(session_id, "running")

    print(f"Task #{task_id} dispatched to '{args.name}' (PID {pid})")
    print(f"  Prompt: {args.prompt}")
    return 0


def cmd_list_agents(db: BridgeDB, args):
    agents = db.list_agents()
    if not agents:
        print("No agents registered. Use 'create-agent' to create one.")
        return 0

    print(f"{'NAME':<15} {'STATE':<10} {'PROJECT':<40} {'TASKS':<6} LAST TASK")
    for a in agents:
        last = a["last_task_at"][:16] if a["last_task_at"] else "never"
        project = a["project_dir"]
        if len(project) > 38:
            project = "..." + project[-35:]
        print(f"{a['name']:<15} {a['state']:<10} {project:<40} {a['total_tasks']:<6} {last}")
    return 0


def cmd_status(db: BridgeDB, args):
    if args.name:
        agent = db.get_agent(args.name)
        if not agent:
            print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
            return 1
        running = db.get_running_task(agent["session_id"])
        print(f"Agent: {args.name} ({agent['state'].upper()})")
        print(f"Project: {agent['project_dir']}")
        if running:
            print(f"Current task: #{running['id']} \"{running['prompt'][:60]}\" (PID {running['pid']})")
        else:
            print("No running task.")
        return 0

    # Show all running tasks
    tasks = db.get_running_tasks()
    if not tasks:
        print("No running tasks.")
        return 0

    print("RUNNING TASKS:")
    for t in tasks:
        prompt_short = t["prompt"][:50] + "..." if len(t["prompt"]) > 50 else t["prompt"]
        print(f"  #{t['id']}  {t['session_id']}  \"{prompt_short}\"  PID {t['pid']}")
    return 0


def cmd_kill(db: BridgeDB, args):
    agent = db.get_agent(args.name)
    if not agent:
        print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
        return 1

    running = db.get_running_task(agent["session_id"])
    if not running:
        print(f"Agent '{args.name}' has no running task.")
        return 0

    pid = running["pid"]
    kill_process(pid)

    db.update_task(
        running["id"],
        status="killed",
        completed_at=datetime.now().isoformat(),
    )
    db.update_agent_state(agent["session_id"], "idle")

    print(f"Killed task #{running['id']} on agent '{args.name}' (PID {pid})")
    return 0


def cmd_history(db: BridgeDB, args):
    agent = db.get_agent(args.name)
    if not agent:
        print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
        return 1

    tasks = db.get_task_history(agent["session_id"], args.limit)
    if not tasks:
        print(f"No tasks for agent '{args.name}'.")
        return 0

    print(f"Agent: {args.name} — last {len(tasks)} tasks\n")
    for t in tasks:
        prompt_short = t["prompt"][:50] + "..." if len(t["prompt"]) > 50 else t["prompt"]
        cost = f"${t['cost_usd']:.3f}" if t["cost_usd"] else ""
        duration = ""
        if t["duration_ms"]:
            mins = t["duration_ms"] // 60000
            secs = (t["duration_ms"] % 60000) // 1000
            duration = f"{mins}m {secs}s"
        ch = t["channel"] if t["channel"] != "cli" else ""
        print(f"  #{t['id']}  \"{prompt_short}\"  {t['status']:<8} {duration}  {cost}  {ch}")
    return 0


def cmd_memory(db: BridgeDB, args):
    agent = db.get_agent(args.name)
    if not agent:
        print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
        return 1

    report = format_memory_report(args.name, agent["project_dir"])
    print(report)
    return 0


def cmd_setup_telegram(db: BridgeDB, args):
    """Save Telegram bot token and chat ID to config."""
    import json
    config_path = os.path.expanduser("~/.claude-bridge/config.json")
    config = {}
    if os.path.isfile(config_path):
        with open(config_path) as f:
            try:
                config = json.load(f)
            except json.JSONDecodeError:
                pass
    config["telegram_bot_token"] = args.token
    chat_id = getattr(args, "chat_id", None)
    if chat_id:
        config["telegram_chat_id"] = chat_id
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"Telegram config saved to {config_path}")
    if chat_id:
        print(f"  Chat ID: {chat_id}")
    return 0


def cmd_setup(db: BridgeDB, args):
    """Interactive setup wizard. Orchestrates setup-telegram + setup-bot + setup-cron."""
    import json as _json
    import shutil
    from . import get_channel_server_path
    from .bridge_bot_claude_md import generate_bridge_bot_claude_md

    no_prompt = getattr(args, "no_prompt", False)
    bridge_home = os.path.expanduser("~/.claude-bridge")

    # Pre-flight: warn if tmux not installed (non-blocking)
    if not shutil.which("tmux"):
        print("⚠ tmux not found — 'bridge start' won't work without it.")
        print("  macOS: brew install tmux")
        print("  Linux: sudo apt install tmux")
        print()

    # --- Step 1: Telegram bot token ---
    token = getattr(args, "token", None)
    existing_token = _get_bot_token()

    if not token and not no_prompt:
        print("Step 1/4: Telegram Bot Token")
        if existing_token:
            masked = existing_token[:5] + "..." + existing_token[-4:] if len(existing_token) > 10 else existing_token
            print(f"  Current token: {masked}")
            new_token = input("  New token (Enter to keep current): ").strip()
            token = new_token if new_token else existing_token
        else:
            print("  Get one from @BotFather on Telegram (/newbot)")
            token = input("  Bot token: ").strip()
    elif not token and existing_token:
        token = existing_token
        if no_prompt:
            print(f"Step 1/4: Token already configured (skip)")

    if token and token != existing_token:
        config_path = os.path.join(bridge_home, "config.json")
        config = {}
        if os.path.isfile(config_path):
            try:
                with open(config_path) as f:
                    config = _json.load(f)
            except (_json.JSONDecodeError, IOError):
                pass
        config["telegram_bot_token"] = token
        os.makedirs(bridge_home, exist_ok=True)
        with open(config_path, "w") as f:
            _json.dump(config, f, indent=2)
        print(f"  Token saved to {config_path}")

    # --- Step 1b: Telegram chat ID ---
    chat_id = getattr(args, "chat_id", None)
    config_path = os.path.join(bridge_home, "config.json")
    existing_chat_id = None
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                existing_chat_id = _json.load(f).get("telegram_chat_id")
        except (_json.JSONDecodeError, IOError):
            pass

    if not chat_id and not no_prompt:
        if existing_chat_id:
            print(f"\n  Chat ID: {existing_chat_id}")
            new_id = input("  New chat ID (Enter to keep): ").strip()
            chat_id = new_id if new_id else existing_chat_id
        else:
            print("\n  Your Telegram user ID (send /start to @userinfobot to find it)")
            chat_id = input("  Chat ID: ").strip()
    elif not chat_id:
        chat_id = existing_chat_id

    if chat_id and chat_id != existing_chat_id:
        config = {}
        if os.path.isfile(config_path):
            try:
                with open(config_path) as f:
                    config = _json.load(f)
            except (_json.JSONDecodeError, IOError):
                pass
        config["telegram_chat_id"] = chat_id
        with open(config_path, "w") as f:
            _json.dump(config, f, indent=2)
        print(f"  Chat ID saved")

    # --- Step 2: Bridge Bot project directory ---
    bot_dir = getattr(args, "bot_dir", None)

    if not bot_dir and not no_prompt:
        default_dir = os.path.expanduser("~/projects/bridge-bot")
        print(f"\nStep 2/4: Bridge Bot Project Directory")
        user_input = input(f"  Directory [{default_dir}]: ").strip()
        bot_dir = user_input if user_input else default_dir
    elif not bot_dir:
        bot_dir = os.path.expanduser("~/projects/bridge-bot")

    bot_dir = os.path.expanduser(bot_dir)
    os.makedirs(bot_dir, exist_ok=True)

    # Detect mode
    has_bun = shutil.which("bun") is not None
    mode = "channel" if has_bun else "mcp"

    # Persist bot_dir and mode to config.json (used by `bridge start`)
    config = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = _json.load(f)
        except (_json.JSONDecodeError, IOError):
            pass
    config["bot_dir"] = bot_dir
    config["mode"] = mode
    with open(config_path, "w") as f:
        _json.dump(config, f, indent=2)

    # --- Step 2b: Deploy channel server FIRST (so .mcp.json uses stable path) ---
    bundled = get_channel_server_path()
    deployed_dir = os.path.join(bridge_home, "channel", "dist")
    deployed_path = os.path.join(deployed_dir, "server.js")

    if os.path.isfile(bundled):
        os.makedirs(deployed_dir, exist_ok=True)
        shutil.copy2(bundled, deployed_path)
        print(f"  Channel server → {deployed_path}")

    # Write CLAUDE.md
    claude_md_path = os.path.join(bot_dir, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(generate_bridge_bot_claude_md(mode=mode))

    # Write .mcp.json (uses deployed path at ~/.claude-bridge/channel/dist/server.js)
    mcp_json_path = os.path.join(bot_dir, ".mcp.json")
    with open(mcp_json_path, "w") as f:
        f.write(generate_mcp_json(mode=mode))

    # Write .claude/settings.local.json — auto-allow bridge tools + disable plugin
    settings_dir = os.path.join(bot_dir, ".claude")
    os.makedirs(settings_dir, exist_ok=True)
    settings_path = os.path.join(settings_dir, "settings.local.json")
    bot_settings = {
        "permissions": {
            "allow": [
                "mcp__bridge__reply",
                "mcp__bridge__bridge_acknowledge",
                "mcp__bridge__bridge_dispatch",
                "mcp__bridge__bridge_status",
                "mcp__bridge__bridge_agents",
                "mcp__bridge__bridge_history",
                "mcp__bridge__bridge_kill",
                "mcp__bridge__bridge_create_agent",
                "mcp__bridge__bridge_get_notifications",
                "mcp__bridge__bridge_check_messages",
            ]
        },
        "enabledPlugins": {},
    }
    with open(settings_path, "w") as f:
        _json.dump(bot_settings, f, indent=2)

    print(f"  CLAUDE.md → {claude_md_path}")
    print(f"  .mcp.json → {mcp_json_path}")
    print(f"  settings.local.json → {settings_path}")

    # --- Step 4: Cron ---
    print(f"\nStep 4/4: Watcher cron")
    cmd_setup_cron(db, args)

    # --- Done ---
    print(f"\n{'='*50}")
    print("Setup complete!")
    print()
    print("Start the Bridge Bot:")
    print(f"  bridge start")
    print()
    print("Other commands:")
    print(f"  bridge status   — check if bot is running")
    print(f"  bridge attach   — attach to tmux session")
    print(f"  bridge logs -f  — follow bot logs")
    print(f"  bridge stop     — stop the bot")
    print()
    print("Then DM your bot on Telegram to pair.")
    return 0


def _get_bot_token() -> str:
    """Read bot token from config."""
    import json as _json
    config_path = os.path.expanduser("~/.claude-bridge/config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                return _json.load(f).get("telegram_bot_token", "")
        except (_json.JSONDecodeError, IOError):
            pass
    return ""


def generate_mcp_json(mode: str = "channel") -> str:
    """Generate .mcp.json content."""
    import json as _json
    import shutil

    src_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bot_token = _get_bot_token()

    # Always use the deployed path (stable location, survives reinstall)
    deployed = os.path.expanduser("~/.claude-bridge/channel/dist/server.js")
    if os.path.isfile(deployed):
        channel_path = deployed
    else:
        # Fall back to bundled in package or source
        from . import get_channel_server_path
        bundled = get_channel_server_path()
        if os.path.isfile(bundled):
            channel_path = bundled
        else:
            channel_path = os.path.join(os.path.dirname(src_path), "channel", "server.ts")

    if mode == "channel":
        bun_path = shutil.which("bun") or "bun"
        mcp_config = {
            "mcpServers": {
                "bridge": {
                    "type": "stdio",
                    "command": bun_path,
                    "args": ["run", channel_path],
                    "env": {
                        "TELEGRAM_BOT_TOKEN": bot_token,
                        "MESSAGES_DB_PATH": os.path.expanduser("~/.claude-bridge/messages.db"),
                    },
                }
            }
        }
    else:
        python_path = shutil.which("python3") or sys.executable
        mcp_config = {
            "mcpServers": {
                "bridge": {
                    "type": "stdio",
                    "command": python_path,
                    "args": ["-m", "claude_bridge.mcp_server"],
                    "env": {
                        "PYTHONPATH": src_path,
                        "TELEGRAM_BOT_TOKEN": bot_token,
                    },
                }
            }
        }
    return _json.dumps(mcp_config, indent=2)


def cmd_setup_bot(db: BridgeDB, args):
    """Generate CLAUDE.md + .mcp.json in target directory."""
    import shutil
    from .bridge_bot_claude_md import generate_bridge_bot_claude_md

    target = os.path.expanduser(args.path)
    os.makedirs(target, exist_ok=True)

    # Detect mode: channel (TypeScript) if bun is available, else python MCP
    has_bun = shutil.which("bun") is not None
    mode = "channel" if has_bun else "mcp"

    import json as _json

    # Write CLAUDE.md
    claude_md_path = os.path.join(target, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(generate_bridge_bot_claude_md(mode=mode))
    print(f"CLAUDE.md → {claude_md_path}")

    # Write .mcp.json
    mcp_json_path = os.path.join(target, ".mcp.json")
    with open(mcp_json_path, "w") as f:
        f.write(generate_mcp_json(mode=mode))
    print(f".mcp.json → {mcp_json_path}")

    # Write .claude/settings.local.json — auto-allow all bridge tools
    settings_dir = os.path.join(target, ".claude")
    os.makedirs(settings_dir, exist_ok=True)
    settings_path = os.path.join(settings_dir, "settings.local.json")
    settings = {}
    if os.path.isfile(settings_path):
        try:
            with open(settings_path) as f:
                settings = _json.load(f)
        except (_json.JSONDecodeError, IOError):
            pass
    settings["permissions"] = settings.get("permissions", {})
    settings["permissions"]["allow"] = list(set(
        settings["permissions"].get("allow", []) + [
            "mcp__bridge__reply",
            "mcp__bridge__bridge_acknowledge",
            "mcp__bridge__bridge_dispatch",
            "mcp__bridge__bridge_status",
            "mcp__bridge__bridge_agents",
            "mcp__bridge__bridge_history",
            "mcp__bridge__bridge_kill",
            "mcp__bridge__bridge_create_agent",
            "mcp__bridge__bridge_get_notifications",
            "mcp__bridge__bridge_check_messages",
        ]
    ))
    # Disable official Telegram plugin
    settings["enabledPlugins"] = {}
    with open(settings_path, "w") as f:
        _json.dump(settings, f, indent=2)
    print(f".claude/settings.local.json → {settings_path}")

    # Check channel deps
    channel_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "channel")
    if mode == "channel" and not os.path.isdir(os.path.join(channel_dir, "node_modules")):
        print(f"\nInstall channel dependencies first:")
        print(f"  cd {os.path.abspath(channel_dir)} && bun install")

    print()
    if mode == "channel":
        print("Bridge Bot ready. Start with:")
        print(f"  cd {target}")
        print("  claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions")
    else:
        print("Bridge Bot ready (Python MCP mode). Start with:")
        print(f"  cd {target}")
        print("  claude --dangerously-skip-permissions")
    return 0


CRON_MARKER = "# claude-bridge-watcher"


def _get_cron_line() -> str:
    """Get the cron line for the watcher."""
    import shutil
    log_path = os.path.expanduser("~/.claude-bridge/watcher.log")
    bridge_cli = shutil.which("bridge-cli")
    if bridge_cli:
        return f"* * * * * {bridge_cli} watcher >> {log_path} 2>&1 {CRON_MARKER}"
    else:
        src_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        python_path = shutil.which("python3") or sys.executable
        return f"* * * * * PYTHONPATH={src_path} {python_path} -m claude_bridge.watcher >> {log_path} 2>&1 {CRON_MARKER}"


def cmd_setup_cron(db: BridgeDB, args):
    """Install the watcher cron job."""
    import subprocess

    cron_line = _get_cron_line()

    # Read existing crontab
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        print("Error: crontab not found.", file=sys.stderr)
        return 1

    # Check if already installed
    if CRON_MARKER in existing:
        print("Watcher cron already installed. Use 'remove-cron' first to reinstall.")
        return 0

    # Append our cron line
    new_crontab = existing.rstrip("\n") + "\n" + cron_line + "\n"
    result = subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error installing cron: {result.stderr}", file=sys.stderr)
        return 1

    print(f"Watcher cron installed (runs every minute).")
    print(f"  Log: ~/.claude-bridge/watcher.log")
    return 0


def cmd_remove_cron(db: BridgeDB, args):
    """Remove the watcher cron job."""
    import subprocess

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        print("Error: crontab not found.", file=sys.stderr)
        return 1

    if CRON_MARKER not in existing:
        print("No watcher cron found.")
        return 0

    # Remove our line
    lines = [l for l in existing.split("\n") if CRON_MARKER not in l]
    new_crontab = "\n".join(lines).strip() + "\n"
    subprocess.run(["crontab", "-"], input=new_crontab, capture_output=True, text=True)

    print("Watcher cron removed.")
    return 0


def cmd_set_model(db: BridgeDB, args):
    VALID_MODELS = ("sonnet", "opus", "haiku")
    if args.model not in VALID_MODELS:
        print(f"Error: Invalid model '{args.model}'. Valid: {', '.join(VALID_MODELS)}", file=sys.stderr)
        return 1

    agent = db.get_agent(args.name)
    if not agent:
        print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
        return 1

    db.update_agent_model(agent["session_id"], args.model)

    # Regenerate agent .md with new model
    content = generate_agent_md(
        agent["session_id"], args.name, agent["project_dir"],
        agent["purpose"], model=args.model,
    )
    write_agent_md(agent["session_id"], content)

    print(f"Agent '{args.name}' model changed to {args.model}.")
    return 0


def cmd_permissions(db: BridgeDB, args):
    pending = db.get_pending_permissions()
    if not pending:
        print("No pending permission requests.")
        return 0

    print("PENDING PERMISSIONS:")
    for p in pending:
        print(f"  [{p['id']}] {p['session_id']}: {p['tool_name']} {p['command']}")
        if p["description"]:
            print(f"         {p['description']}")
    return 0


def cmd_approve(db: BridgeDB, args):
    if db.respond_permission(args.request_id, approved=True):
        print(f"Permission {args.request_id} approved.")
        return 0
    else:
        print(f"Error: Permission '{args.request_id}' not found or already responded.", file=sys.stderr)
        return 1


def cmd_deny(db: BridgeDB, args):
    if db.respond_permission(args.request_id, approved=False):
        print(f"Permission {args.request_id} denied.")
        return 0
    else:
        print(f"Error: Permission '{args.request_id}' not found or already responded.", file=sys.stderr)
        return 1


def cmd_cost(db: BridgeDB, args):
    session_id = None
    if args.name:
        agent = db.get_agent(args.name)
        if not agent:
            print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
            return 1
        session_id = agent["session_id"]

    summary = db.get_cost_summary(session_id, args.period)
    scope = f"Agent: {args.name}" if args.name else "All agents"
    period = args.period if args.period != "all" else "all time"

    print(f"Cost Summary ({scope}, {period})")
    print(f"  Total:   ${summary['total']:.2f}")
    print(f"  Tasks:   {summary['count']}")
    print(f"  Average: ${summary['average']:.3f} per task")
    return 0


def cmd_queue(db: BridgeDB, args):
    if args.name:
        agent = db.get_agent(args.name)
        if not agent:
            print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
            return 1
        queued = db.get_queued_tasks(agent["session_id"])
    else:
        # All queued tasks across all agents
        queued = []
        for agent in db.list_agents():
            queued.extend(db.get_queued_tasks(agent["session_id"]))

    if not queued:
        print("No tasks in queue.")
        return 0

    print("QUEUED TASKS:")
    for t in queued:
        prompt_short = t["prompt"][:50] + "..." if len(t["prompt"]) > 50 else t["prompt"]
        print(f"  #{t['id']}  pos:{t['position']}  {t['session_id']}  \"{prompt_short}\"")
    return 0


def cmd_cancel(db: BridgeDB, args):
    task = db.get_task(args.task_id)
    if not task:
        print(f"Error: Task #{args.task_id} not found.", file=sys.stderr)
        return 1

    if db.cancel_queued_task(args.task_id):
        print(f"Task #{args.task_id} cancelled and removed from queue.")
        return 0
    else:
        print(f"Error: Task #{args.task_id} is not in the queue (status: {task['status']}).", file=sys.stderr)
        return 1


def cmd_create_team(db: BridgeDB, args):
    """Create a team with a lead agent and member agents."""
    members = [m.strip() for m in args.members.split(",") if m.strip()]

    # Validate lead exists
    if not db.get_agent(args.lead):
        print(f"Error: Lead agent '{args.lead}' does not exist.", file=sys.stderr)
        return 1

    # Validate lead not in members
    if args.lead in members:
        print(f"Error: Lead agent '{args.lead}' cannot also be a member.", file=sys.stderr)
        return 1

    # Validate all members exist
    for member in members:
        if not db.get_agent(member):
            print(f"Error: Member agent '{member}' does not exist.", file=sys.stderr)
            return 1

    # Check for duplicate team name
    if db.get_team(args.name):
        print(f"Error: Team '{args.name}' already exists.", file=sys.stderr)
        return 1

    db.create_team(args.name, args.lead, members)
    print(f"Team '{args.name}' created.")
    print(f"  Lead: {args.lead}")
    print(f"  Members: {', '.join(members)}")
    return 0


def cmd_list_teams(db: BridgeDB, args):
    """List all teams."""
    teams = db.list_teams()
    if not teams:
        print("No teams registered.")
        return 0

    print(f"{'NAME':<20} {'LEAD':<15} {'MEMBERS'}")
    for team in teams:
        members = db.get_team_members(team["name"])
        print(f"{team['name']:<20} {team['lead_agent']:<15} {', '.join(members)}")
    return 0


def cmd_delete_team(db: BridgeDB, args):
    """Delete a team (agents are preserved)."""
    if db.delete_team(args.name):
        print(f"Team '{args.name}' deleted. Agents preserved.")
        return 0
    else:
        print(f"Error: Team '{args.name}' not found.", file=sys.stderr)
        return 1


def _build_team_prompt(original_prompt: str, team_name: str, members: list[dict]) -> str:
    """Build augmented prompt for team lead with team context."""
    member_lines = []
    for m in members:
        member_lines.append(f"- {m['name']}: {m['purpose']} (project: {m['project_dir']})")

    return f"""TEAM TASK
=========
{original_prompt}

TEAM CONTEXT
============
You are the lead of team '{team_name}'.
Your teammates:
{chr(10).join(member_lines)}

To dispatch sub-tasks to teammates, use the Bash tool:
  PYTHONPATH={os.path.dirname(os.path.dirname(os.path.abspath(__file__)))} python3 -m claude_bridge.cli dispatch <agent_name> "<sub-task prompt>"

To check teammate status:
  PYTHONPATH={os.path.dirname(os.path.dirname(os.path.abspath(__file__)))} python3 -m claude_bridge.cli status <agent_name>

INSTRUCTIONS
============
1. Decompose the task into sub-tasks for your teammates
2. Dispatch each sub-task using the commands above
3. Monitor progress with the status command
4. When all sub-tasks are done, aggregate results and provide a final summary
"""


def cmd_team_dispatch(db: BridgeDB, args):
    """Dispatch a task to a team's lead agent with augmented prompt."""
    team = db.get_team(args.name)
    if not team:
        print(f"Error: Team '{args.name}' not found.", file=sys.stderr)
        return 1

    lead = db.get_agent(team["lead_agent"])
    if not lead:
        print(f"Error: Lead agent '{team['lead_agent']}' not found.", file=sys.stderr)
        return 1

    # Get member info for prompt
    member_names = db.get_team_members(args.name)
    members = []
    for name in member_names:
        agent = db.get_agent(name)
        if agent:
            members.append({"name": name, "purpose": agent["purpose"], "project_dir": agent["project_dir"]})

    # Build augmented prompt
    augmented = _build_team_prompt(args.prompt, args.name, members)

    session_id = lead["session_id"]
    channel = getattr(args, "channel", None)
    chat_id = getattr(args, "chat_id", None)
    message_id = getattr(args, "message_id", None)

    if not channel or channel == "cli":
        from .notify import get_default_channel
        channel, default_chat_id = get_default_channel()
        if not chat_id:
            chat_id = default_chat_id

    # Check if busy — queue
    running = db.get_running_task(session_id)
    if running:
        task_id = db.create_task(session_id, augmented, task_type="team", channel=channel, channel_chat_id=chat_id, channel_message_id=message_id)
        position = db.get_next_queue_position(session_id)
        db.update_task(task_id, status="queued", position=position)
        print(f"Lead '{team['lead_agent']}' is busy. Team task #{task_id} queued at position {position}.")
        return 0

    # Create parent task
    task_id = db.create_task(session_id, augmented, task_type="team", channel=channel, channel_chat_id=chat_id, channel_message_id=message_id)
    result_file = get_result_file(session_id, task_id)
    agent_file_name = derive_agent_file_name(session_id)
    model = lead["model"]

    pid = spawn_task(agent_file_name, session_id, lead["project_dir"], augmented, task_id, model=model)

    db.update_task(
        task_id,
        status="running",
        pid=pid,
        result_file=result_file,
        model=model,
        started_at=datetime.now().isoformat(),
    )
    db.update_agent_state(session_id, "running")

    print(f"Team task #{task_id} dispatched to lead '{team['lead_agent']}' (PID {pid})")
    print(f"  Prompt: {args.prompt}")
    print(f"  Members: {', '.join(member_names)}")
    return 0


def cmd_team_status(db: BridgeDB, args):
    """Show team task status with sub-task progress."""
    team = db.get_team(args.name)
    if not team:
        print(f"Error: Team '{args.name}' not found.", file=sys.stderr)
        return 1

    lead = db.get_agent(team["lead_agent"])
    if not lead:
        print(f"Error: Lead agent '{team['lead_agent']}' not found.", file=sys.stderr)
        return 1

    # Find latest team task for this lead
    history = db.get_task_history(lead["session_id"], limit=20)
    team_task = None
    for t in history:
        if t["task_type"] == "team":
            team_task = t
            break

    if not team_task:
        print(f"No active team task for '{args.name}'.")
        return 0

    print(f"Team: {args.name}")
    print(f"Lead: {team['lead_agent']} — {team_task['status']}")
    prompt_short = team_task["prompt"][:80].split("\n")[0]
    print(f"  Task #{team_task['id']}: {prompt_short}")
    print()

    # Show sub-tasks
    subtasks = db.get_subtasks(team_task["id"])
    if subtasks:
        done = sum(1 for s in subtasks if s["status"] in ("done", "failed"))
        total = len(subtasks)
        print(f"Sub-tasks: {done}/{total} complete")
        for s in subtasks:
            agent = db.get_agent_by_session(s["session_id"])
            agent_name = agent["name"] if agent else s["session_id"]
            prompt_short = s["prompt"][:50]
            print(f"  #{s['id']} {agent_name:<15} {s['status']:<10} {prompt_short}")
    else:
        print("Sub-tasks: none yet (lead is still decomposing)")

    return 0


def _cmd_doctor(args) -> int:
    """Diagnose installation health."""
    import shutil
    import json as _json
    from . import __version__, get_channel_server_path

    issues = 0
    warnings = 0

    print(f"Claude Bridge Doctor v{__version__}\n")

    # Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):
        print(f"  ✓ Python {py_ver}")
    else:
        print(f"  ✗ Python {py_ver} (need ≥3.11)")
        issues += 1

    # Bun
    bun = shutil.which("bun")
    if bun:
        print(f"  ✓ Bun found at {bun}")
    else:
        print(f"  ✗ Bun not found")
        issues += 1

    # Claude CLI
    claude = shutil.which("claude")
    if claude:
        print(f"  ✓ Claude CLI found")
    else:
        print(f"  ✗ Claude CLI not found")
        issues += 1

    # bridge-cli
    bridge = shutil.which("bridge-cli")
    if bridge:
        print(f"  ✓ bridge-cli at {bridge}")
    else:
        print(f"  ⚠ bridge-cli not in PATH")
        warnings += 1

    # Data directory
    bridge_home = os.path.expanduser("~/.claude-bridge")
    if os.path.isdir(bridge_home):
        print(f"  ✓ Data dir: {bridge_home}")
    else:
        print(f"  ✗ Data dir missing: {bridge_home}")
        issues += 1

    # Config
    config_path = os.path.join(bridge_home, "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = _json.load(f)
            token = config.get("telegram_bot_token", "")
            masked = token[:5] + "..." + token[-4:] if len(token) > 10 else "(empty)"
            print(f"  ✓ Config: token {masked}")
        except Exception:
            print(f"  ⚠ Config: malformed")
            warnings += 1
    else:
        print(f"  ✗ Config missing (run: bridge-cli setup)")
        issues += 1

    # Channel server
    bundled = get_channel_server_path()
    deployed = os.path.join(bridge_home, "channel", "dist", "server.js")
    if os.path.isfile(deployed):
        print(f"  ✓ Channel server deployed")
    elif os.path.isfile(bundled):
        print(f"  ⚠ Channel server bundled but not deployed (run: bridge-cli setup)")
        warnings += 1
        if getattr(args, "fix", False):
            os.makedirs(os.path.dirname(deployed), exist_ok=True)
            shutil.copy2(bundled, deployed)
            print(f"    → Fixed: deployed to {deployed}")
    else:
        print(f"  ✗ Channel server not found")
        issues += 1

    # Database
    db_path = os.path.join(bridge_home, "bridge.db")
    if os.path.isfile(db_path):
        try:
            db = BridgeDB(db_path)
            agents = db.list_agents()
            tasks = db.conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            db.close()
            print(f"  ✓ Database: {len(agents)} agents, {tasks} tasks")
        except Exception as e:
            print(f"  ⚠ Database error: {e}")
            warnings += 1
    else:
        print(f"  ⚠ Database not created yet")
        warnings += 1

    # Cron
    import subprocess
    try:
        crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if CRON_MARKER in (crontab.stdout or ""):
            print(f"  ✓ Watcher cron installed")
        else:
            print(f"  ⚠ Watcher cron not installed (run: bridge-cli setup-cron)")
            warnings += 1
            if getattr(args, "fix", False):
                cmd_setup_cron(None, args)
                print(f"    → Fixed: cron installed")
    except Exception:
        print(f"  ⚠ Cannot check crontab")
        warnings += 1

    # Tmux
    tmux = shutil.which("tmux")
    if tmux:
        print(f"  ✓ tmux found at {tmux}")
    else:
        print(f"  ⚠ tmux not found (optional, needed for 'bridge start')")
        print(f"    macOS: brew install tmux")
        print(f"    Linux: sudo apt install tmux")
        warnings += 1

    # Bridge Bot session
    from .tmux_session import session_running, get_session_pid, get_session_uptime, TMUX_SESSION_NAME
    if tmux and session_running():
        pid = get_session_pid()
        uptime = get_session_uptime()
        pid_str = f", PID {pid}" if pid else ""
        uptime_str = f", uptime {uptime}" if uptime else ""
        print(f"  ✓ Bridge Bot running (session '{TMUX_SESSION_NAME}'{pid_str}{uptime_str})")
    elif tmux:
        print(f"  ⚠ Bridge Bot not running (run: bridge start)")
        warnings += 1

    # Agent .md files
    agents_dir = os.path.expanduser("~/.claude/agents")
    if os.path.isdir(agents_dir):
        bridge_agents = [f for f in os.listdir(agents_dir) if f.startswith("bridge--")]
        print(f"  ✓ Agent files: {len(bridge_agents)}")
    else:
        print(f"  ⚠ No agent files yet")
        warnings += 1

    # Summary
    print()
    if issues == 0 and warnings == 0:
        print("All checks passed ✓")
        return 0
    elif issues == 0:
        print(f"{warnings} warning(s), no critical issues")
        return 1
    else:
        print(f"{issues} critical issue(s), {warnings} warning(s)")
        return 2


def _cmd_uninstall(args) -> int:
    """Remove claude-bridge data and config."""
    import glob
    import subprocess

    bridge_home = os.path.expanduser("~/.claude-bridge")
    agents_dir = os.path.expanduser("~/.claude/agents")

    # Summary
    items = []
    if os.path.isdir(bridge_home):
        items.append(f"  ~/.claude-bridge/ (data, config, databases)")
    agent_files = glob.glob(os.path.join(agents_dir, "bridge--*.md")) if os.path.isdir(agents_dir) else []
    if agent_files:
        items.append(f"  {len(agent_files)} agent .md files in ~/.claude/agents/")
    try:
        crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if CRON_MARKER in (crontab.stdout or ""):
            items.append(f"  Watcher cron job")
    except Exception:
        pass

    if not items:
        print("Nothing to uninstall.")
        return 0

    print("Will remove:")
    for item in items:
        print(item)
    print("\nWill NOT remove:")
    print("  Bot project directory (your CLAUDE.md + .mcp.json)")
    print("  Python/Bun packages (uninstall manually)")

    if not getattr(args, "force", False):
        confirm = input("\nContinue? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Cancelled.")
            return 0

    # Remove cron
    try:
        crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if CRON_MARKER in (crontab.stdout or ""):
            lines = [l for l in crontab.stdout.split("\n") if CRON_MARKER not in l]
            subprocess.run(["crontab", "-"], input="\n".join(lines).strip() + "\n", capture_output=True, text=True)
            print("  ✓ Cron removed")
    except Exception:
        pass

    # Remove agent files
    for f in agent_files:
        os.remove(f)
    if agent_files:
        print(f"  ✓ {len(agent_files)} agent files removed")

    # Remove data dir
    if os.path.isdir(bridge_home):
        import shutil
        shutil.rmtree(bridge_home)
        print(f"  ✓ {bridge_home} removed")

    print("\nUninstall complete.")
    print("To remove the package: pip uninstall claude-bridge")
    return 0


COMMANDS = {
    "create-agent": cmd_create_agent,
    "delete-agent": cmd_delete_agent,
    "dispatch": cmd_dispatch,
    "list-agents": cmd_list_agents,
    "status": cmd_status,
    "kill": cmd_kill,
    "history": cmd_history,
    "memory": cmd_memory,
    "queue": cmd_queue,
    "cancel": cmd_cancel,
    "set-model": cmd_set_model,
    "cost": cmd_cost,
    "create-team": cmd_create_team,
    "list-teams": cmd_list_teams,
    "delete-team": cmd_delete_team,
    "team-dispatch": cmd_team_dispatch,
    "team-status": cmd_team_status,
    "permissions": cmd_permissions,
    "approve": cmd_approve,
    "deny": cmd_deny,
    "setup": cmd_setup,
    "setup-bot": cmd_setup_bot,
    "setup-telegram": cmd_setup_telegram,
    "setup-cron": cmd_setup_cron,
    "remove-cron": cmd_remove_cron,
    "on-complete": None,  # handled specially below
    "watcher": None,  # handled specially below
    "doctor": None,  # handled specially below
    "uninstall": None,  # handled specially below
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Special commands that don't use the standard db + handler pattern
    if args.command == "on-complete":
        from .on_complete import main as on_complete_main
        # on_complete parses its own --session-id from sys.argv
        sys.argv = ["on-complete", "--session-id", args.session_id]
        on_complete_main()
        return
    if args.command == "watcher":
        from .watcher import main as watcher_main
        watcher_main()
        return
    if args.command == "doctor":
        sys.exit(_cmd_doctor(args))
    if args.command == "uninstall":
        sys.exit(_cmd_uninstall(args))

    db = BridgeDB()
    try:
        handler = COMMANDS[args.command]
        exit_code = handler(db, args)
        sys.exit(exit_code or 0)
    finally:
        db.close()


if __name__ == "__main__":
    main()
