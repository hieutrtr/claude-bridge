"""Agent .md file generator — creates native Claude Code agent definitions."""

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
  Stop:
    - hooks:
        - type: command
          command: "python3 {on_complete_path} --session-id {session_id}"
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
    on_complete_path = os.path.expanduser("~/.claude-bridge/on-complete.py")

    return AGENT_TEMPLATE.format(
        agent_file_name=agent_file_name,
        session_id=session_id,
        agent_name=agent_name,
        project_dir=project_dir,
        purpose=purpose,
        model=model,
        on_complete_path=on_complete_path,
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
