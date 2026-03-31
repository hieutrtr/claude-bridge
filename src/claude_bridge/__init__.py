"""Claude Bridge — Multi-session Claude Code dispatch from Telegram."""

from __future__ import annotations

import os

__version__ = "0.1.4"


def get_channel_server_path() -> str:
    """Get the path to the bundled channel server.js."""
    return os.path.join(os.path.dirname(__file__), "channel_server", "dist", "server.js")
