"""Agent .md file generator — creates native Claude Code agent definitions."""

from __future__ import annotations

import os
from pathlib import Path

AGENT_TEMPLATE = """---
name: {agent_file_name}
description: "{purpose}"
tools: Read, Edit, Write, Bash, Grep, Glob
model: {model}
isolation: worktree
memory: project
hooks:
  PreToolUse:
    - matcher: "Bash(git push *)"
      hooks:
        - type: command
          command: "PYTHONPATH={src_path} python3 -m claude_bridge.permission_relay --session-id {session_id} --tool Bash --command 'git push'"
    - matcher: "Bash(rm -rf *)"
      hooks:
        - type: command
          command: "PYTHONPATH={src_path} python3 -m claude_bridge.permission_relay --session-id {session_id} --tool Bash --command 'rm -rf'"
  Stop:
    - type: command
      command: "PYTHONPATH={src_path} python3 -m claude_bridge.on_complete --session-id {session_id}"
---

# Agent: {agent_name}
Project: {project_dir}
Purpose: {purpose}

You are a {agent_name} agent working on this project.
Your focus: {purpose}

## Working Style
- Complete the task fully before stopping
- Run tests if the project has them
- Summarize what you changed when done
"""


def generate_agent_md(
    session_id: str,
    agent_name: str,
    project_dir: str,
    purpose: str,
    model: str = "sonnet",
) -> str:
    """Generate agent .md file content in native Claude Code format."""
    agent_file_name = f"bridge--{session_id}"
    src_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    return AGENT_TEMPLATE.format(
        agent_file_name=agent_file_name,
        session_id=session_id,
        agent_name=agent_name,
        project_dir=project_dir,
        purpose=purpose,
        model=model,
        src_path=src_path,
    ).lstrip()


def write_agent_md(session_id: str, content: str) -> str:
    """Write agent .md file to ~/.claude/agents/. Returns the file path."""
    agent_file_name = f"bridge--{session_id}"
    agents_dir = os.path.expanduser("~/.claude/agents")
    os.makedirs(agents_dir, exist_ok=True)

    file_path = os.path.join(agents_dir, f"{agent_file_name}.md")
    with open(file_path, "w") as f:
        f.write(content)

    return file_path


def delete_agent_md(session_id: str) -> bool:
    """Delete agent .md file. Returns True if file existed."""
    agent_file_name = f"bridge--{session_id}"
    file_path = os.path.expanduser(f"~/.claude/agents/{agent_file_name}.md")
    if os.path.isfile(file_path):
        os.remove(file_path)
        return True
    return False
