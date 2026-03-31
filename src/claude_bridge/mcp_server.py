"""Bridge MCP server — messaging backbone for Claude Bridge.

Exposes bridge operations, message queue, and notifications as MCP tools.
Runs as stdio server, started via .mcp.json in the bridge-bot project.

Usage:
    python3 -m claude_bridge.mcp_server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .db import BridgeDB
from .message_db import MessageDB
from . import mcp_tools

# Tool names registry (for testing)
TOOL_NAMES = [
    "bridge_dispatch",
    "bridge_status",
    "bridge_agents",
    "bridge_history",
    "bridge_kill",
    "bridge_create_agent",
    "bridge_get_messages",
    "bridge_acknowledge",
    "bridge_reply",
    "bridge_get_notifications",
]


def create_server(db: BridgeDB | None = None, msg_db: MessageDB | None = None) -> FastMCP:
    """Create and configure the Bridge MCP server."""
    server = FastMCP("bridge")

    def _db() -> BridgeDB:
        return db if db else BridgeDB()

    def _msg_db() -> MessageDB:
        return msg_db if msg_db else MessageDB()

    # --- Bridge Operation Tools ---

    @server.tool()
    def bridge_dispatch(agent: str, prompt: str, model: str | None = None) -> str:
        """Dispatch a task to an agent. Returns task ID and PID."""
        return mcp_tools.tool_dispatch(_db(), agent, prompt, model)

    @server.tool()
    def bridge_status(agent: str | None = None) -> str:
        """Get status of running tasks. Optionally filter by agent name."""
        return mcp_tools.tool_status(_db(), agent)

    @server.tool()
    def bridge_agents() -> str:
        """List all registered agents with their state and project."""
        return mcp_tools.tool_agents(_db())

    @server.tool()
    def bridge_history(agent: str, limit: int = 10) -> str:
        """Get task history for an agent."""
        return mcp_tools.tool_history(_db(), agent, limit)

    @server.tool()
    def bridge_kill(agent: str) -> str:
        """Kill a running task on an agent."""
        return mcp_tools.tool_kill(_db(), agent)

    @server.tool()
    def bridge_create_agent(name: str, path: str, purpose: str, model: str = "opus") -> str:
        """Create a new agent for a project directory."""
        return mcp_tools.tool_create_agent(_db(), name, path, purpose, model)

    # --- Message Tools ---

    @server.tool()
    def bridge_get_messages() -> str:
        """Get pending inbound messages from users."""
        return mcp_tools.tool_get_messages(_msg_db())

    @server.tool()
    def bridge_acknowledge(message_id: int) -> str:
        """Acknowledge that a message was processed."""
        return mcp_tools.tool_acknowledge(_msg_db(), message_id)

    @server.tool()
    def bridge_reply(chat_id: str, text: str, reply_to_message_id: str | None = None) -> str:
        """Send a reply to a user via Telegram. Queues in outbound for delivery."""
        return mcp_tools.tool_reply(_msg_db(), chat_id, text, reply_to_message_id)

    # --- Notification Tools ---

    @server.tool()
    def bridge_get_notifications() -> str:
        """Get pending task completion notifications. Marks them as reported."""
        return mcp_tools.tool_get_notifications(_db())

    return server


def main():
    """Run the Bridge MCP server on stdio."""
    import os
    from .telegram_poller import TelegramPoller
    from .notify import get_bot_token

    msg_db = MessageDB()
    server = create_server(msg_db=msg_db)

    # Start Telegram poller if token is available
    token = get_bot_token()
    poller = None
    if token:
        poller = TelegramPoller(token, msg_db)
        poller.start()
        import sys
        print("[bridge-mcp] Telegram poller started", file=sys.stderr)

    try:
        server.run(transport="stdio")
    finally:
        if poller:
            poller.stop()
        msg_db.close()


if __name__ == "__main__":
    main()
