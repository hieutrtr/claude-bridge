"""Bridge MCP server — messaging backbone for Claude Bridge.

Exposes bridge operations, message queue, and notifications as MCP tools.
Runs as stdio server, started via .mcp.json in the bridge-bot project.

Usage:
    python3 -m claude_bridge.mcp_server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .db import BridgeDB
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


def create_server(db: BridgeDB | None = None) -> FastMCP:
    """Create and configure the Bridge MCP server."""
    server = FastMCP("bridge")

    def _db() -> BridgeDB:
        return db if db else BridgeDB()

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
    def bridge_create_agent(name: str, path: str, purpose: str, model: str = "sonnet") -> str:
        """Create a new agent for a project directory."""
        return mcp_tools.tool_create_agent(_db(), name, path, purpose, model)

    # --- Message Tools (placeholders until M14) ---

    @server.tool()
    def bridge_get_messages() -> str:
        """Get pending inbound messages from users."""
        return '{"messages": []}'

    @server.tool()
    def bridge_acknowledge(message_id: int) -> str:
        """Acknowledge that a message was processed."""
        return '{"status": "not_implemented"}'

    @server.tool()
    def bridge_reply(chat_id: str, text: str, reply_to_message_id: str | None = None) -> str:
        """Send a reply to a user via Telegram."""
        return '{"status": "not_implemented"}'

    # --- Notification Tools (placeholder until M15) ---

    @server.tool()
    def bridge_get_notifications() -> str:
        """Get pending task completion notifications."""
        return '{"notifications": []}'

    return server


def main():
    """Run the Bridge MCP server on stdio."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
