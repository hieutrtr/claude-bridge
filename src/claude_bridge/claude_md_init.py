"""CLAUDE.md initialization — purpose-driven project scanning."""

import os
import subprocess
import json

INIT_PROMPT_NEW = """Analyze this codebase thoroughly. Generate a CLAUDE.md file that includes:

1. PROJECT OVERVIEW
   - What this project does (infer from code, README, package.json, etc.)
   - Tech stack detected

2. BUILD & TEST COMMANDS
   - How to install dependencies
   - How to run tests
   - How to lint/format
   - How to build

3. PROJECT STRUCTURE
   - Key directories and what they contain
   - Important files and their purpose

4. CONVENTIONS
   - Coding style detected (from linter configs, existing code patterns)
   - Git workflow (branch naming, commit style)
   - Any patterns you notice

5. AGENT CONTEXT
   This project has a Bridge agent assigned with the following purpose:
   Purpose: {purpose}
   When working on tasks, keep this purpose in mind as your primary focus area.

Write the result to CLAUDE.md in the project root."""

INIT_PROMPT_APPEND = """Read the existing CLAUDE.md in this project. Append the following section
at the end. Do not modify any existing content.

## Agent Context

This project has a Bridge agent assigned:
- Agent: {agent_name}
- Purpose: {purpose}

Write the updated file back to CLAUDE.md."""


def init_claude_md(
    project_dir: str,
    agent_name: str,
    purpose: str,
    timeout: int = 120,
) -> dict:
    """Run CLAUDE.md initialization via claude -p.

    Returns dict with keys: success, message, error
    """
    expanded_dir = os.path.expanduser(project_dir)
    claude_md_path = os.path.join(expanded_dir, "CLAUDE.md")
    has_existing = os.path.isfile(claude_md_path)

    if has_existing:
        prompt = INIT_PROMPT_APPEND.format(agent_name=agent_name, purpose=purpose)
    else:
        prompt = INIT_PROMPT_NEW.format(purpose=purpose)

    try:
        result = subprocess.run(
            [
                "claude",
                "-p", prompt,
                "--allowedTools", "Read,Grep,Glob,Write",
                "--output-format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=expanded_dir,
        )

        if result.returncode == 0:
            try:
                output = json.loads(result.stdout)
                return {
                    "success": True,
                    "message": "CLAUDE.md initialized" if not has_existing else "CLAUDE.md updated",
                    "cost_usd": output.get("cost_usd", 0),
                }
            except json.JSONDecodeError:
                return {"success": True, "message": "CLAUDE.md initialized (no JSON output)"}
        else:
            return {
                "success": False,
                "error": result.stderr[:500] if result.stderr else "Unknown error",
            }

    except FileNotFoundError:
        return {"success": False, "error": "'claude' command not found. Install Claude Code first."}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"CLAUDE.md init timed out after {timeout}s"}
