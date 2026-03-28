"""Bridge MCP server — messaging backbone for Claude Bridge.

Exposes bridge operations, message queue, and notifications as MCP tools.
Runs as stdio server, started via .mcp.json in the bridge-bot project.

Usage:
    python3 -m claude_bridge.mcp_server
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .db import BridgeDB

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


def create_server() -> FastMCP:
    """Create and configure the Bridge MCP server."""
    server = FastMCP("bridge")

    # --- Bridge Operation Tools ---

    @server.tool()
    def bridge_dispatch(agent: str, prompt: str, model: str | None = None) -> str:
        """Dispatch a task to an agent. Returns task ID and PID."""
        # Placeholder — will be implemented in M13.T3
        return f"bridge_dispatch not yet implemented"

    @server.tool()
    def bridge_status(agent: str | None = None) -> str:
        """Get status of running tasks. Optionally filter by agent name."""
        return f"bridge_status not yet implemented"

    @server.tool()
    def bridge_agents() -> str:
        """List all registered agents with their state and project."""
        return f"bridge_agents not yet implemented"

    @server.tool()
    def bridge_history(agent: str, limit: int = 10) -> str:
        """Get task history for an agent."""
        return f"bridge_history not yet implemented"

    @server.tool()
    def bridge_kill(agent: str) -> str:
        """Kill a running task on an agent."""
        return f"bridge_kill not yet implemented"

    @server.tool()
    def bridge_create_agent(name: str, path: str, purpose: str, model: str = "sonnet") -> str:
        """Create a new agent for a project directory."""
        return f"bridge_create_agent not yet implemented"

    # --- Message Tools ---

    @server.tool()
    def bridge_get_messages() -> str:
        """Get pending inbound messages from users."""
        return f"bridge_get_messages not yet implemented"

    @server.tool()
    def bridge_acknowledge(message_id: int) -> str:
        """Acknowledge that a message was processed."""
        return f"bridge_acknowledge not yet implemented"

    @server.tool()
    def bridge_reply(chat_id: str, text: str, reply_to_message_id: str | None = None) -> str:
        """Send a reply to a user via Telegram."""
        return f"bridge_reply not yet implemented"

    # --- Notification Tools ---

    @server.tool()
    def bridge_get_notifications() -> str:
        """Get pending task completion notifications."""
        return f"bridge_get_notifications not yet implemented"

    return server


def main():
    """Run the Bridge MCP server on stdio."""
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
