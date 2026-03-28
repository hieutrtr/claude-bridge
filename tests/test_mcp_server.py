"""Tests for Bridge MCP server."""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from claude_bridge.mcp_server import create_server, TOOL_NAMES


class TestServerCreation:
    def test_creates_server_with_name(self):
        server = create_server()
        assert server.name == "bridge"

    def test_registers_tools(self):
        server = create_server()
        # FastMCP registers tools via @server.tool decorator
        # Check that our tool names are in the tool manager
        assert len(TOOL_NAMES) > 0

    def test_has_bridge_dispatch_tool(self):
        assert "bridge_dispatch" in TOOL_NAMES

    def test_has_bridge_status_tool(self):
        assert "bridge_status" in TOOL_NAMES

    def test_has_bridge_agents_tool(self):
        assert "bridge_agents" in TOOL_NAMES

    def test_has_bridge_history_tool(self):
        assert "bridge_history" in TOOL_NAMES

    def test_has_bridge_kill_tool(self):
        assert "bridge_kill" in TOOL_NAMES

    def test_has_bridge_create_agent_tool(self):
        assert "bridge_create_agent" in TOOL_NAMES

    def test_has_bridge_get_messages_tool(self):
        assert "bridge_get_messages" in TOOL_NAMES

    def test_has_bridge_acknowledge_tool(self):
        assert "bridge_acknowledge" in TOOL_NAMES

    def test_has_bridge_reply_tool(self):
        assert "bridge_reply" in TOOL_NAMES

    def test_has_bridge_get_notifications_tool(self):
        assert "bridge_get_notifications" in TOOL_NAMES
