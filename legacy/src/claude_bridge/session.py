"""Session model — derives session identity from agent + project."""

from __future__ import annotations

import os
import re
import json
from datetime import datetime, timezone
from pathlib import Path


def get_instance_prefix() -> str:
    """Derive a short instance prefix from CLAUDE_BRIDGE_HOME.

    Returns empty string for the default home (~/.claude-bridge), ensuring
    backward compatibility for single-instance setups.  For non-default
    homes, returns a sanitized basename so that agent .md files placed in
    the shared ~/.claude/agents/ directory don't collide across instances.

    Examples:
        ~/.claude-bridge          → ""
        ~/.claude-bridge-prod     → "prod"
        ~/.claude-bridge-staging  → "staging"
        /tmp/test-bridge          → "test-bridge"
    """
    from . import get_bridge_home
    home = get_bridge_home()
    default = Path.home() / ".claude-bridge"
    if home == default:
        return ""

    name = home.name  # basename of the path
    # Strip common prefixes to get a short, meaningful identifier
    for strip in (".claude-bridge-", "claude-bridge-", ".bridge-", "bridge-"):
        if name.startswith(strip):
            name = name[len(strip):]
            break
    # Sanitize: keep only alphanumeric and hyphens
    name = re.sub(r"[^a-zA-Z0-9-]", "-", name).strip("-")
    return (name or "custom")[:20]


def derive_session_id(agent_name: str, project_dir: str) -> str:
    """Derive session ID from agent name and project basename.

    Uses double-dash separator (agent names use single dashes).
    Example: backend + /projects/my-api → backend--my-api
    """
    project_basename = os.path.basename(os.path.normpath(project_dir))
    return f"{agent_name}--{project_basename}"


def derive_agent_file_name(session_id: str) -> str:
    """Derive the native Claude Code agent .md filename (slug only, no path/extension).

    Always returns "bridge--{session_id}" — isolation across instances is achieved
    by writing to each instance's bot_dir/.claude/agents/ rather than a shared
    global directory.

    Naming convention:
    - agent_file_name / agent_slug: just the name, e.g. "bridge--backend--my-api"
    - agent_file_path / agent_md_path: full path with .md
    - db.agents.agent_file column: stores the full path (agent_md_path)
    Use get_agent_file_path(session_id) for the full path.

    Example:
        backend--my-api → "bridge--backend--my-api"
    """
    return f"bridge--{session_id}"


def validate_agent_name(name: str) -> str | None:
    """Validate agent name. Returns error message or None if valid."""
    if not name:
        return "Agent name cannot be empty."
    if len(name) > 30:
        return "Agent name must be 30 characters or less."
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$", name):
        return "Agent name must be alphanumeric + hyphens, starting with a letter or digit."
    if "--" in name:
        return "Agent name cannot contain double-dash (--)."
    return None


def validate_project_dir(path: str) -> str | None:
    """Validate project directory. Returns error message or None if valid."""
    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        return f"Directory '{path}' does not exist."
    return None


def get_workspace_dir(session_id: str) -> str:
    """Get workspace directory path for a session."""
    from . import get_bridge_home
    return str(get_bridge_home() / "workspaces" / session_id)


def get_tasks_dir(session_id: str) -> str:
    """Get tasks output directory path for a session."""
    return os.path.join(get_workspace_dir(session_id), "tasks")


def get_agent_file_path(session_id: str, bot_dir: str | None = None) -> str:
    """Get the full path to the agent .md file.

    When bot_dir is provided, returns {bot_dir}/.claude/agents/{name}.md.
    Otherwise falls back to the global ~/.claude/agents/{name}.md.
    """
    name = derive_agent_file_name(session_id)
    if bot_dir:
        return os.path.join(bot_dir, ".claude", "agents", f"{name}.md")
    return os.path.join(os.path.expanduser("~/.claude/agents"), f"{name}.md")


def create_workspace(session_id: str, agent_name: str, project_dir: str, purpose: str):
    """Create workspace directory and metadata file."""
    workspace = get_workspace_dir(session_id)
    tasks_dir = get_tasks_dir(session_id)
    os.makedirs(tasks_dir, exist_ok=True)

    metadata = {
        "agent_name": agent_name,
        "project_dir": project_dir,
        "session_id": session_id,
        "purpose": purpose,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = os.path.join(workspace, "metadata.json")
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)


def cleanup_workspace(session_id: str):
    """Remove workspace directory for a session."""
    import shutil

    workspace = get_workspace_dir(session_id)
    if os.path.isdir(workspace):
        shutil.rmtree(workspace)
