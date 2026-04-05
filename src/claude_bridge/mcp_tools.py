"""Bridge MCP tool implementations — business logic for each MCP tool.

Separated from mcp_server.py so tools can be tested without MCP transport.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from .db import BridgeDB
from .message_db import MessageDB
from .session import derive_session_id
from .agent_md import generate_agent_md, write_agent_md, install_stop_hook
from .claude_md_init import init_claude_md
from .dispatcher import spawn_task, get_result_file, kill_process
from .session import create_workspace


def _agent_file_name(session_id: str) -> str:
    return f"bridge--{session_id}"


def tool_agents(db: BridgeDB) -> str:
    """List all agents with state and project."""
    agents = db.list_agents()
    result = []
    for a in agents:
        result.append({
            "name": a["name"],
            "state": a["state"],
            "project": a["project_dir"],
            "purpose": a["purpose"],
            "model": a["model"],
            "total_tasks": a["total_tasks"],
        })
    return json.dumps({"agents": result})


def tool_status(db: BridgeDB, agent: str | None = None) -> str:
    """Get running tasks, optionally filtered by agent."""
    running = []
    if agent:
        a = db.get_agent(agent)
        if a:
            task = db.get_running_task(a["session_id"])
            if task:
                running.append({
                    "task_id": task["id"],
                    "agent": agent,
                    "prompt": task["prompt"][:100],
                    "pid": task["pid"],
                    "started_at": task["started_at"],
                })
    else:
        for a in db.list_agents():
            task = db.get_running_task(a["session_id"])
            if task:
                running.append({
                    "task_id": task["id"],
                    "agent": a["name"],
                    "prompt": task["prompt"][:100],
                    "pid": task["pid"],
                    "started_at": task["started_at"],
                })
    return json.dumps({"running": running})


def tool_dispatch(
    db: BridgeDB,
    agent: str,
    prompt: str,
    model: str | None = None,
    chat_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Dispatch a task to an agent.

    Args:
        db: BridgeDB instance.
        agent: Agent name to dispatch to.
        prompt: Task prompt.
        model: Optional model override.
        chat_id: Originating Telegram chat_id from inbound message. When provided,
            notifications will be routed back to this chat. If None, falls back to
            the default channel from config (backward-compatible for CLI dispatch).
        user_id: Originating Telegram user_id for multi-user tracking. Optional.
    """
    a = db.get_agent(agent)
    if not a:
        return json.dumps({"error": f"Agent '{agent}' not found"})

    session_id = a["session_id"]

    # Determine notification channel:
    # - If chat_id provided (Telegram inbound), use it directly for correct routing
    # - Otherwise fall back to default channel from config (CLI / single-user mode)
    if chat_id:
        channel = "telegram"
    else:
        from .notify import get_default_channel
        channel, chat_id = get_default_channel()

    # Queue if busy
    running = db.get_running_task(session_id)
    if running:
        task_id = db.create_task(session_id, prompt, channel=channel, channel_chat_id=chat_id, user_id=user_id)
        position = db.get_next_queue_position(session_id)
        db.update_task(task_id, status="queued", position=position)
        return json.dumps({"task_id": task_id, "status": "queued", "position": position})

    # Create and spawn
    task_id = db.create_task(session_id, prompt, channel=channel, channel_chat_id=chat_id, user_id=user_id)
    result_file = get_result_file(session_id, task_id)
    agent_file_name = _agent_file_name(session_id)
    task_model = model or a["model"]

    pid = spawn_task(agent_file_name, session_id, a["project_dir"], prompt, task_id, model=task_model)

    db.update_task(
        task_id, status="running", pid=pid, result_file=result_file,
        model=task_model, started_at=datetime.now().isoformat(),
    )
    db.update_agent_state(session_id, "running")

    return json.dumps({"task_id": task_id, "status": "running", "pid": pid, "agent": agent})


def tool_history(db: BridgeDB, agent: str, limit: int = 10) -> str:
    """Get task history for an agent."""
    a = db.get_agent(agent)
    if not a:
        return json.dumps({"error": f"Agent '{agent}' not found"})

    tasks = db.get_task_history(a["session_id"], limit)
    result = []
    for t in tasks:
        result.append({
            "task_id": t["id"],
            "prompt": t["prompt"][:100],
            "status": t["status"],
            "cost_usd": t["cost_usd"],
            "duration_ms": t["duration_ms"],
            "result_summary": (t["result_summary"] or "")[:200],
            "created_at": t["created_at"],
        })
    return json.dumps({"tasks": result, "agent": agent})


def tool_kill(db: BridgeDB, agent: str) -> str:
    """Kill a running task on an agent."""
    a = db.get_agent(agent)
    if not a:
        return json.dumps({"error": f"Agent '{agent}' not found"})

    running = db.get_running_task(a["session_id"])
    if not running:
        return json.dumps({"message": f"No running task on '{agent}'"})

    pid = running["pid"]
    kill_process(pid)
    db.update_task(running["id"], status="killed", completed_at=datetime.now().isoformat())
    db.update_agent_state(a["session_id"], "idle")

    return json.dumps({"status": "killed", "task_id": running["id"], "pid": pid})


def tool_create_agent(
    db: BridgeDB, name: str, path: str, purpose: str, model: str = "opus",
) -> str:
    """Create a new agent."""
    if db.get_agent(name):
        return json.dumps({"error": f"Agent '{name}' already exists"})

    project_dir = os.path.expanduser(path)
    if not os.path.isdir(project_dir):
        return json.dumps({"error": f"Path '{path}' does not exist"})

    session_id = derive_session_id(name, project_dir)

    # Generate agent .md
    content = generate_agent_md(session_id, name, project_dir, purpose, model=model)
    agent_file_path = write_agent_md(session_id, content)

    # Install stop hook
    install_stop_hook(project_dir, session_id)

    # Create workspace
    create_workspace(session_id, name, project_dir, purpose)

    # Register
    db.create_agent(name, project_dir, session_id, agent_file_path, purpose, model=model)

    # Init CLAUDE.md
    init_result = init_claude_md(project_dir, name, purpose)

    return json.dumps({
        "name": name,
        "session_id": session_id,
        "project": project_dir,
        "purpose": purpose,
        "claude_md": init_result.get("message", ""),
    })


# --- Message Tools ---

def tool_get_messages(msg_db: MessageDB) -> str:
    """Get pending inbound messages and mark them as delivered."""
    pending = msg_db.get_pending_inbound()
    messages = []
    for msg in pending:
        messages.append({
            "id": msg["id"],
            "chat_id": msg["chat_id"],
            "user_id": msg["user_id"],
            "username": msg["username"],
            "text": msg["message_text"],
            "platform": msg["platform"],
            "created_at": msg["created_at"],
        })
        msg_db.mark_inbound_delivered(msg["id"])
    return json.dumps({"messages": messages})


def tool_acknowledge(msg_db: MessageDB, message_id: int) -> str:
    """Acknowledge that a message was processed."""
    msg = msg_db.get_inbound(message_id)
    if not msg:
        return json.dumps({"status": "not_found", "error": f"Message {message_id} not found"})
    msg_db.mark_inbound_acknowledged(message_id)
    return json.dumps({"status": "acknowledged", "message_id": message_id})


def tool_get_notifications(db: BridgeDB) -> str:
    """Get unreported task completion notifications and mark them reported."""
    unreported = db.get_unreported_tasks()
    notifications = []
    for task in unreported:
        agent = db.get_agent_by_session(task["session_id"])
        agent_name = agent["name"] if agent else task["session_id"]
        notifications.append({
            "task_id": task["id"],
            "agent": agent_name,
            "status": task["status"],
            "summary": (task["result_summary"] or "")[:200],
            "error": (task["error_message"] or "")[:200],
            "cost_usd": task["cost_usd"],
            "duration_ms": task["duration_ms"],
        })
        db.mark_task_reported(task["id"])
    return json.dumps({"notifications": notifications})


def tool_reply(msg_db: MessageDB, chat_id: str, text: str, reply_to_message_id: str | None = None) -> str:
    """Queue a reply for delivery via Telegram."""
    mid = msg_db.create_outbound("telegram", chat_id, text, reply_to_message_id=reply_to_message_id, source="bot")
    return json.dumps({"status": "queued", "outbound_id": mid})


# --- Loop tool implementations ---

def tool_loop(
    db: BridgeDB,
    agent: str,
    goal: str,
    done_when: str,
    max_iterations: int = 10,
    loop_type: str = "bridge",
    max_cost_usd: float | None = None,
) -> str:
    """Start a goal loop for an agent."""
    from .loop_orchestrator import start_loop

    agent_record = db.get_agent(agent)
    if not agent_record:
        return json.dumps({"error": f"Agent '{agent}' not found"})

    try:
        loop_id = start_loop(
            db=db,
            agent=agent,
            project=agent_record["project_dir"],
            goal=goal,
            done_when=done_when,
            max_iterations=max_iterations,
            loop_type=loop_type,
            max_cost_usd=max_cost_usd,
        )
    except (ValueError, RuntimeError) as e:
        return json.dumps({"error": str(e)})

    return json.dumps({
        "loop_id": loop_id,
        "agent": agent,
        "goal": goal,
        "done_when": done_when,
        "max_iterations": max_iterations,
        "loop_type": loop_type,
        "max_cost_usd": max_cost_usd,
        "status": "running",
    })


def tool_loop_status(
    db: BridgeDB,
    loop_id: str | None = None,
    agent: str | None = None,
) -> str:
    """Get loop status."""
    from .loop_orchestrator import get_loop_status

    if loop_id:
        loop = get_loop_status(db, loop_id)
        if not loop:
            return json.dumps({"error": f"Loop '{loop_id}' not found"})
        loops = [loop]
    else:
        loops_raw = db.list_loops(agent=agent, limit=5)
        if not loops_raw:
            return json.dumps({"loops": []})
        loops = []
        for l in loops_raw[:1]:
            full = get_loop_status(db, l["loop_id"])
            if full:
                loops.append(full)

    # Serialize: iterations may contain non-JSON-native types
    result = []
    for loop in loops:
        entry = dict(loop)
        # Truncate long fields for readability
        if "goal" in entry and len(entry["goal"]) > 200:
            entry["goal"] = entry["goal"][:200] + "...[truncated]"
        iterations = entry.get("iterations", [])
        entry["iterations"] = [
            {
                "iteration_num": it["iteration_num"],
                "status": it["status"],
                "done_check_passed": bool(it.get("done_check_passed")),
                "cost_usd": it.get("cost_usd", 0),
                "result_summary": (it.get("result_summary") or "")[:200],
            }
            for it in iterations
        ]
        result.append(entry)

    return json.dumps({"loops": result})


def tool_loop_cancel(db: BridgeDB, loop_id: str) -> str:
    """Cancel a running loop."""
    from .loop_orchestrator import cancel_loop

    cancelled = cancel_loop(db, loop_id)
    if cancelled:
        return json.dumps({"status": "cancelled", "loop_id": loop_id})

    loop = db.get_loop(loop_id)
    if not loop:
        return json.dumps({"error": f"Loop '{loop_id}' not found"})
    return json.dumps({
        "error": f"Loop is not running (status: {loop['status']})",
        "loop_id": loop_id,
    })


def tool_loop_approve(db: BridgeDB, loop_id: str) -> str:
    """Approve a loop waiting for manual done condition — marks it as done."""
    from .loop_orchestrator import approve_loop

    approved = approve_loop(db, loop_id)
    if approved:
        return json.dumps({"status": "done", "loop_id": loop_id, "finish_reason": "manual_approved"})

    loop = db.get_loop(loop_id)
    if not loop:
        return json.dumps({"error": f"Loop '{loop_id}' not found"})
    if loop["status"] != "running":
        return json.dumps({"error": f"Loop is not running (status: {loop['status']})", "loop_id": loop_id})
    return json.dumps({"error": f"Loop '{loop_id}' is not waiting for approval", "loop_id": loop_id})


def tool_loop_reject(db: BridgeDB, loop_id: str, feedback: str = "") -> str:
    """Reject a loop approval — continue to next iteration with optional feedback."""
    from .loop_orchestrator import reject_loop

    rejected = reject_loop(db, loop_id, feedback=feedback)
    if rejected:
        return json.dumps({"status": "running", "loop_id": loop_id, "action": "next_iteration_dispatched"})

    loop = db.get_loop(loop_id)
    if not loop:
        return json.dumps({"error": f"Loop '{loop_id}' not found"})
    if loop["status"] != "running":
        return json.dumps({"error": f"Loop is not running (status: {loop['status']})", "loop_id": loop_id})
    return json.dumps({"error": f"Loop '{loop_id}' is not waiting for approval", "loop_id": loop_id})


def tool_loop_list(
    db: BridgeDB,
    agent: str | None = None,
    limit: int = 10,
    active_only: bool = False,
) -> str:
    """List goal loops with their status and progress."""
    from .loop_orchestrator import format_loop_list

    status_filter = "running" if active_only else None
    loops_raw = db.list_loops(agent=agent, limit=limit, status=status_filter)

    formatted = format_loop_list(loops_raw)
    result = []
    for loop in loops_raw:
        result.append({
            "loop_id": loop.get("loop_id"),
            "agent": loop.get("agent"),
            "status": loop.get("status"),
            "goal": (loop.get("goal") or "")[:100],
            "current_iteration": loop.get("current_iteration", 0),
            "max_iterations": loop.get("max_iterations"),
            "total_cost_usd": loop.get("total_cost_usd", 0),
            "started_at": loop.get("started_at"),
        })
    return json.dumps({"loops": result, "formatted": formatted})


def tool_loop_history(db: BridgeDB, loop_id: str) -> str:
    """Get full iteration history for a loop."""
    from .loop_orchestrator import get_loop_status, format_loop_history

    loop = get_loop_status(db, loop_id)
    if not loop:
        return json.dumps({"error": f"Loop '{loop_id}' not found"})

    formatted = format_loop_history(loop)
    iterations = [
        {
            "iteration_num": it.get("iteration_num"),
            "status": it.get("status"),
            "done_check_passed": bool(it.get("done_check_passed")),
            "cost_usd": it.get("cost_usd", 0),
            "duration_ms": it.get("duration_ms"),
            "result_summary": (it.get("result_summary") or "")[:200],
            "created_at": it.get("created_at"),
            "finished_at": it.get("finished_at"),
        }
        for it in loop.get("iterations", [])
    ]
    return json.dumps({
        "loop_id": loop_id,
        "agent": loop.get("agent"),
        "status": loop.get("status"),
        "goal": loop.get("goal"),
        "total_cost_usd": loop.get("total_cost_usd", 0),
        "finish_reason": loop.get("finish_reason"),
        "iterations": iterations,
        "formatted": formatted,
    })


def tool_loop_notify(
    db: BridgeDB,
    msg_db,
    loop_id: str,
    chat_id: str,
) -> str:
    """Send a Telegram notification about the current loop status.

    Formats the current loop state as a human-readable message and queues
    it for delivery via the bridge reply tool.

    Args:
        db: BridgeDB instance.
        msg_db: MessageDB instance for outbound messages.
        loop_id: Loop to report on.
        chat_id: Telegram chat_id to send to.
    """
    from .loop_orchestrator import get_loop_status
    from .telegram_loop import (
        format_loop_done,
        format_loop_started,
        format_loop_progress,
        format_loop_approval_request,
    )

    loop = get_loop_status(db, loop_id)
    if not loop:
        return json.dumps({"error": f"Loop '{loop_id}' not found"})

    status = loop.get("status", "unknown")
    agent = loop.get("agent", "?")
    goal = loop.get("goal", "")
    current = loop.get("current_iteration", 0)
    max_iter = loop.get("max_iterations", 10)
    cost = loop.get("total_cost_usd") or 0.0
    finish_reason = loop.get("finish_reason") or ""
    pending_approval = bool(loop.get("pending_approval"))
    done_when = loop.get("done_when", "")
    iterations = loop.get("iterations", [])

    # Get last iteration summary
    last_summary = ""
    if iterations:
        last_it = iterations[-1]
        last_summary = (last_it.get("result_summary") or "")[:300]

    if pending_approval:
        text = format_loop_approval_request(
            loop_id=loop_id,
            agent=agent,
            goal=goal,
            iteration_num=current,
            result_summary=last_summary,
        )
    elif status in ("done", "failed", "cancelled", "max_reached"):
        # Compute duration_ms from started_at and finished_at
        duration_ms = None
        started_at = loop.get("started_at")
        finished_at = loop.get("finished_at")
        if started_at and finished_at:
            try:
                from datetime import datetime as _dt
                fmt = "%Y-%m-%dT%H:%M:%S.%f"
                t_start = _dt.fromisoformat(started_at)
                t_end = _dt.fromisoformat(finished_at)
                duration_ms = int((t_end - t_start).total_seconds() * 1000)
            except Exception:
                pass

        text = format_loop_done(
            loop_id=loop_id,
            agent=agent,
            goal=goal,
            iterations_completed=current,
            total_cost_usd=cost,
            duration_ms=duration_ms,
            finish_reason=finish_reason,
        )
    elif status == "running" and current > 0:
        last_done = False
        if iterations:
            last_done = bool(iterations[-1].get("done_check_passed"))
        text = format_loop_progress(
            loop_id=loop_id,
            agent=agent,
            goal=goal,
            iteration_num=current,
            max_iterations=max_iter,
            result_summary=last_summary,
            done=last_done,
            cost_usd=cost,
        )
    else:
        # Just started
        loop_type = loop.get("loop_type", "bridge")
        text = format_loop_started(
            loop_id=loop_id,
            agent=agent,
            goal=goal,
            done_when=done_when,
            max_iterations=max_iter,
            loop_type=loop_type,
        )

    # Queue outbound message
    mid = msg_db.create_outbound("telegram", chat_id, text, source="loop")
    return json.dumps({"status": "queued", "outbound_id": mid, "message": text})


def tool_parse_loop_command(text: str) -> str:
    """Parse a natural language loop command from Telegram.

    Translates phrases like "loop backend fix tests until pytest passes"
    into a structured LoopCommand for the bridge bot to execute.

    Args:
        text: Raw Telegram message text from user.

    Returns:
        JSON with parsed command fields.
    """
    from .telegram_loop import parse_loop_command, parse_approval_reply

    # Check if it's an approval reply first
    approval = parse_approval_reply(text)
    if approval.action != "unknown":
        return json.dumps({
            "type": "approval",
            "action": approval.action,
            "feedback": approval.feedback,
            "loop_id": approval.loop_id,
        })

    # Try loop command
    cmd = parse_loop_command(text)
    return json.dumps({
        "type": "loop_command",
        "command": cmd.command,
        "agent": cmd.agent,
        "goal": cmd.goal,
        "done_when": cmd.done_when,
        "loop_id": cmd.loop_id,
        "max_iterations": cmd.max_iterations,
    })
