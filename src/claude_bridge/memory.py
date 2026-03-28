"""Auto Memory reader — reads Claude Code's native memory files."""

from __future__ import annotations

import os
from pathlib import Path


def find_memory_dir(project_dir: str) -> str | None:
    """Find the Auto Memory directory for a project.

    Claude Code stores memory in ~/.claude/projects/<encoded-path>/memory/
    The path encoding replaces / with - and prepends -.
    """
    expanded = os.path.expanduser(project_dir)
    normalized = os.path.normpath(expanded)

    # Claude Code encodes paths by replacing / with -
    # e.g., /Users/hieutran/projects/my-api → -Users-hieutran-projects-my-api
    encoded = normalized.replace("/", "-")

    memory_dir = os.path.expanduser(f"~/.claude/projects/{encoded}/memory")
    if os.path.isdir(memory_dir):
        return memory_dir

    # Fallback: search for matching directory
    projects_dir = os.path.expanduser("~/.claude/projects")
    if not os.path.isdir(projects_dir):
        return None

    # Try to find a directory that contains the project basename
    project_basename = os.path.basename(normalized)
    for entry in os.listdir(projects_dir):
        if project_basename in entry:
            candidate = os.path.join(projects_dir, entry, "memory")
            if os.path.isdir(candidate):
                return candidate

    return None


def read_memory(project_dir: str) -> dict:
    """Read Auto Memory files for a project.

    Returns dict with keys:
        found: bool
        memory_dir: str | None
        main: str (MEMORY.md content)
        topics: list[dict] (topic files with name and content)
    """
    memory_dir = find_memory_dir(project_dir)

    if not memory_dir:
        return {"found": False, "memory_dir": None, "main": "", "topics": []}

    result = {"found": True, "memory_dir": memory_dir, "main": "", "topics": []}

    # Read main MEMORY.md
    main_file = os.path.join(memory_dir, "MEMORY.md")
    if os.path.isfile(main_file):
        with open(main_file) as f:
            result["main"] = f.read()

    # Read topic files
    for entry in sorted(os.listdir(memory_dir)):
        if entry == "MEMORY.md":
            continue
        if entry.endswith(".md"):
            topic_path = os.path.join(memory_dir, entry)
            with open(topic_path) as f:
                result["topics"].append({"name": entry, "content": f.read()})

    return result


def format_memory_report(agent_name: str, project_dir: str) -> str:
    """Format a human-readable memory report."""
    mem = read_memory(project_dir)

    if not mem["found"]:
        return f"No Auto Memory found for agent '{agent_name}'.\nThe agent hasn't learned anything yet (or hasn't run any tasks)."

    lines = [f"Agent: {agent_name}", f"Memory directory: {mem['memory_dir']}", ""]

    if mem["main"]:
        lines.append("## Main Memory")
        lines.append(mem["main"])
        lines.append("")

    if mem["topics"]:
        lines.append(f"## Topic Files ({len(mem['topics'])})")
        for topic in mem["topics"]:
            lines.append(f"- {topic['name']}")

    return "\n".join(lines)
