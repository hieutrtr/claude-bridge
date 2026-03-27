"""CLI entry point — bridge-cli.py command dispatcher."""

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
    parser = argparse.ArgumentParser(prog="bridge-cli", description="Claude Bridge CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # create-agent
    p = sub.add_parser("create-agent", help="Register a new agent")
    p.add_argument("name", help="Agent name (e.g., backend)")
    p.add_argument("path", help="Project directory path")
    p.add_argument("--purpose", required=True, help="Agent purpose description")

    # delete-agent
    p = sub.add_parser("delete-agent", help="Delete an agent")
    p.add_argument("name", help="Agent name")

    # dispatch
    p = sub.add_parser("dispatch", help="Dispatch a task to an agent")
    p.add_argument("name", help="Agent name")
    p.add_argument("prompt", help="Task prompt")

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

    # setup
    sub.add_parser("setup", help="Generate Bridge Bot CLAUDE.md and print setup instructions")

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

    # Derive session identity
    session_id = derive_session_id(args.name, project_dir)
    agent_file_name = derive_agent_file_name(session_id)

    # Generate agent .md
    content = generate_agent_md(session_id, args.name, project_dir, args.purpose)
    agent_file_path = write_agent_md(session_id, content)

    # Create workspace
    create_workspace(session_id, args.name, project_dir, args.purpose)

    # Register in SQLite
    db.create_agent(args.name, project_dir, session_id, agent_file_path, args.purpose)

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

    # Check not busy
    running = db.get_running_task(session_id)
    if running:
        print(
            f"Error: Agent '{args.name}' is busy with task #{running['id']}. "
            f"Use 'kill {args.name}' to cancel.",
            file=sys.stderr,
        )
        return 1

    # Create task
    task_id = db.create_task(session_id, args.prompt)
    result_file = get_result_file(session_id, task_id)
    agent_file_name = derive_agent_file_name(session_id)

    # Spawn
    pid = spawn_task(agent_file_name, session_id, agent["project_dir"], args.prompt, task_id)

    # Update state
    db.update_task(
        task_id,
        status="running",
        pid=pid,
        result_file=result_file,
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
        print(f"  #{t['id']}  \"{prompt_short}\"  {t['status']:<8} {duration}  {cost}")
    return 0


def cmd_memory(db: BridgeDB, args):
    agent = db.get_agent(args.name)
    if not agent:
        print(f"Error: Agent '{args.name}' not found.", file=sys.stderr)
        return 1

    report = format_memory_report(args.name, agent["project_dir"])
    print(report)
    return 0


def cmd_setup(db: BridgeDB, args):
    bridge_home = os.path.expanduser("~/.claude-bridge")
    claude_md_path = os.path.join(bridge_home, "CLAUDE.md")

    write_bridge_bot_claude_md(claude_md_path)
    print(f"Bridge Bot CLAUDE.md written to {claude_md_path}")
    print()
    print("=== Setup Instructions ===")
    print()
    print("1. Install the Telegram channel plugin (inside Claude Code):")
    print("   /plugin install telegram@claude-plugins-official")
    print()
    print("2. Create a Telegram bot via @BotFather → copy the bot token")
    print()
    print("3. Configure the token (inside Claude Code):")
    print("   /telegram:configure <your-bot-token>")
    print()
    print("4. Start the Bridge Bot with Telegram channel:")
    print(f"   cd {bridge_home} && claude --channels plugin:telegram@claude-plugins-official")
    print()
    print("5. Pair your Telegram account:")
    print("   - Send any message to your bot in Telegram")
    print("   - Copy the pairing code the bot sends back")
    print("   - In Claude Code: /telegram:access pair <code>")
    print("   - Lock access: /telegram:access policy allowlist")
    print()
    print("6. Send /help to your Telegram bot to verify it works")
    print()
    print("7. (Optional) Set up the fallback watcher cron:")
    print("   crontab -e")
    print(f"   */5 * * * * PYTHONPATH={os.path.dirname(os.path.dirname(__file__))} "
          f"python3 -m claude_bridge.watcher >> {bridge_home}/watcher.log 2>&1")
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
    "setup": cmd_setup,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    db = BridgeDB()
    try:
        handler = COMMANDS[args.command]
        exit_code = handler(db, args)
        sys.exit(exit_code or 0)
    finally:
        db.close()


if __name__ == "__main__":
    main()
