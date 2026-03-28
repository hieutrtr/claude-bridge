"""Bridge MCP tool implementations — business logic for each MCP tool.

Separated from mcp_server.py so tools can be tested without MCP transport.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from .db import BridgeDB
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


def tool_dispatch(db: BridgeDB, agent: str, prompt: str, model: str | None = None) -> str:
    """Dispatch a task to an agent."""
    a = db.get_agent(agent)
    if not a:
        return json.dumps({"error": f"Agent '{agent}' not found"})

    session_id = a["session_id"]

    # Auto-detect notification channel
    from .notify import get_default_channel
    channel, chat_id = get_default_channel()

    # Queue if busy
    running = db.get_running_task(session_id)
    if running:
        task_id = db.create_task(session_id, prompt, channel=channel, channel_chat_id=chat_id)
        position = db.get_next_queue_position(session_id)
        db.update_task(task_id, status="queued", position=position)
        return json.dumps({"task_id": task_id, "status": "queued", "position": position})

    # Create and spawn
    task_id = db.create_task(session_id, prompt, channel=channel, channel_chat_id=chat_id)
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
    db: BridgeDB, name: str, path: str, purpose: str, model: str = "sonnet",
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
