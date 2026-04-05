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
    "bridge_loop",
    "bridge_loop_status",
    "bridge_loop_cancel",
    "bridge_loop_approve",
    "bridge_loop_reject",
    "bridge_loop_list",
    "bridge_loop_history",
    "bridge_loop_notify",
    "bridge_parse_loop_command",
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
    def bridge_dispatch(
        agent: str,
        prompt: str,
        model: str | None = None,
        chat_id: str | None = None,
        user_id: str | None = None,
    ) -> str:
        """Dispatch a task to an agent. Returns task ID and PID.

        Args:
            agent: Agent name to dispatch to.
            prompt: Task prompt.
            model: Optional model override.
            chat_id: Originating Telegram chat_id from the inbound message.
                ALWAYS pass this when dispatching from a Telegram message so that
                completion notifications are routed back to the correct user.
            user_id: Originating Telegram user_id for multi-user tracking.
        """
        return mcp_tools.tool_dispatch(_db(), agent, prompt, model, chat_id, user_id)

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

    # --- Loop Tools ---

    @server.tool()
    def bridge_loop(
        agent: str,
        goal: str,
        done_when: str,
        max_iterations: int = 10,
        loop_type: str = "bridge",
        max_cost_usd: float | None = None,
    ) -> str:
        """Start a goal loop for an agent. Repeats tasks until done_when condition is met.

        Args:
            agent: Agent name.
            goal: Goal description (what you want to achieve).
            done_when: Done condition string. Formats:
                command:<CMD>              — run CMD, success = exit code 0
                file_exists:<PATH>         — check if file exists
                file_contains:<PATH>:<PAT> — check if file contains pattern
                llm_judge:<RUBRIC>         — call Claude to judge result against rubric
                manual:<MSG>               — pause and wait for user approval
            max_iterations: Maximum iterations (default 10).
            loop_type: 'bridge', 'agent', or 'auto'.
            max_cost_usd: Optional cost ceiling in USD.
        """
        return mcp_tools.tool_loop(_db(), agent, goal, done_when, max_iterations, loop_type, max_cost_usd)

    @server.tool()
    def bridge_loop_status(loop_id: str | None = None, agent: str | None = None) -> str:
        """Get goal loop status. Shows current iteration, cost, and recent iterations.

        Args:
            loop_id: Specific loop ID (optional).
            agent: Filter by agent name (optional, shows latest loop for agent).
        """
        return mcp_tools.tool_loop_status(_db(), loop_id, agent)

    @server.tool()
    def bridge_loop_cancel(loop_id: str) -> str:
        """Cancel a running goal loop.

        Args:
            loop_id: The loop ID to cancel.
        """
        return mcp_tools.tool_loop_cancel(_db(), loop_id)

    @server.tool()
    def bridge_loop_approve(loop_id: str) -> str:
        """Approve a loop waiting for manual done condition — marks it as done.

        Use this when a 'manual' done condition loop has completed successfully
        and you want to confirm the goal is met.

        Args:
            loop_id: The loop ID to approve.
        """
        return mcp_tools.tool_loop_approve(_db(), loop_id)

    @server.tool()
    def bridge_loop_reject(loop_id: str, feedback: str = "") -> str:
        """Reject a loop approval — continue to next iteration with optional feedback.

        Use this when a 'manual' done condition loop has NOT met the goal yet
        and should try again with feedback.

        Args:
            loop_id: The loop ID to reject.
            feedback: Optional feedback to inject into the next iteration prompt.
        """
        return mcp_tools.tool_loop_reject(_db(), loop_id, feedback)

    @server.tool()
    def bridge_loop_list(
        agent: str | None = None,
        limit: int = 10,
        active_only: bool = False,
    ) -> str:
        """List goal loops with their status and progress.

        Args:
            agent: Filter by agent name (optional).
            limit: Maximum number of loops to show (default 10).
            active_only: If True, show only running loops.
        """
        return mcp_tools.tool_loop_list(_db(), agent, limit, active_only)

    @server.tool()
    def bridge_loop_history(loop_id: str) -> str:
        """Get full iteration history for a loop.

        Shows each iteration's status, done check result, cost, duration,
        and result summary.

        Args:
            loop_id: The loop ID to inspect.
        """
        return mcp_tools.tool_loop_history(_db(), loop_id)

    @server.tool()
    def bridge_loop_notify(loop_id: str, chat_id: str) -> str:
        """Send a Telegram notification about the current loop status.

        Formats the loop state as a human-readable Telegram message and
        queues it for delivery via the message outbound queue.

        Args:
            loop_id: Loop to report on.
            chat_id: Telegram chat_id to send to.
        """
        return mcp_tools.tool_loop_notify(_db(), _msg_db(), loop_id, chat_id)

    @server.tool()
    def bridge_parse_loop_command(text: str) -> str:
        """Parse a natural language loop command or approval reply from Telegram.

        Translates user messages like:
          'loop backend fix tests until pytest passes'
          'approve'
          'reject: tests still failing'
          'stop loop 42'

        into structured commands the bridge bot can execute.

        Args:
            text: Raw Telegram message text from user.
        """
        return mcp_tools.tool_parse_loop_command(text)

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
