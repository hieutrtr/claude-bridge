"""Claude Bridge — Multi-session Claude Code dispatch from Telegram."""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "0.3.4"

# Paths that are too dangerous to use as CLAUDE_BRIDGE_HOME
_DANGEROUS_PREFIXES = (
    "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64",
    "/root", "/sys", "/proc", "/dev", "/boot", "/run",
)


def get_bridge_home() -> Path:
    """Get the bridge home directory.

    Override the default (~/.claude-bridge) by setting CLAUDE_BRIDGE_HOME env var.
    Example: CLAUDE_BRIDGE_HOME=/tmp/test-bridge bridge-cli setup

    WARNING: Changing CLAUDE_BRIDGE_HOME after initial setup will orphan existing data:
    - The SQLite database (bridge.db) will be at the new path (empty — no agents)
    - Workspaces at the old path will not be accessible
    - Agent .md files in ~/.claude/agents/ are NOT affected (they use a fixed path)
    To migrate: copy ~/.claude-bridge/ to the new location before changing the env var.

    Raises:
        ValueError: If CLAUDE_BRIDGE_HOME resolves to a dangerous system path.
    """
    custom = os.environ.get("CLAUDE_BRIDGE_HOME")
    if custom:
        # Resolve symlinks / relative components to get the real path
        resolved = Path(os.path.realpath(os.path.expanduser(custom)))
        resolved_str = str(resolved)
        for prefix in _DANGEROUS_PREFIXES:
            if resolved_str == prefix or resolved_str.startswith(prefix + "/"):
                raise ValueError(
                    f"CLAUDE_BRIDGE_HOME={custom!r} resolves to a dangerous system path "
                    f"({resolved_str}). Choose a path under your home directory, "
                    f"e.g. ~/.claude-bridge or /tmp/test-bridge."
                )
        return resolved
    return Path.home() / ".claude-bridge"


def get_channel_server_path() -> str:
    """Get the path to the bundled channel server.js."""
    return os.path.join(os.path.dirname(__file__), "channel_server", "dist", "server.js")
