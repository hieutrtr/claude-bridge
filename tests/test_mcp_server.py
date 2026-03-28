"""Tests for Bridge MCP server."""

from __future__ import annotations

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from claude_bridge.mcp_server import create_server, TOOL_NAMES
from claude_bridge.mcp_tools import (
    tool_agents, tool_status, tool_dispatch, tool_history,
    tool_kill, tool_create_agent,
    tool_get_messages, tool_acknowledge, tool_get_notifications,
)
from claude_bridge.message_db import MessageDB
from claude_bridge.db import BridgeDB


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    agents_dir = home / ".claude" / "agents"
    agents_dir.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()  # fake git repo
    db = BridgeDB(str(home / ".claude-bridge" / "bridge.db"))
    return {"db": db, "home": home, "project": project, "agents_dir": agents_dir}


class TestServerCreation:
    def test_creates_server_with_name(self):
        server = create_server()
        assert server.name == "bridge"

    def test_registers_tools(self):
        assert len(TOOL_NAMES) > 0

    def test_has_all_tool_names(self):
        expected = [
            "bridge_dispatch", "bridge_status", "bridge_agents",
            "bridge_history", "bridge_kill", "bridge_create_agent",
            "bridge_get_messages", "bridge_acknowledge",
            "bridge_reply", "bridge_get_notifications",
        ]
        for name in expected:
            assert name in TOOL_NAMES


class TestToolAgents:
    def test_no_agents(self, env):
        result = json.loads(tool_agents(env["db"]))
        assert result["agents"] == []

    def test_with_agents(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "API dev")
        result = json.loads(tool_agents(db))
        assert len(result["agents"]) == 1
        assert result["agents"][0]["name"] == "backend"
        assert result["agents"][0]["purpose"] == "API dev"


class TestToolStatus:
    def test_no_running(self, env):
        result = json.loads(tool_status(env["db"]))
        assert result["running"] == []

    def test_with_running(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "dev")
        tid = db.create_task("backend--project", "fix bug")
        db.update_task(tid, status="running", pid=12345)
        db.update_agent_state("backend--project", "running")

        result = json.loads(tool_status(db))
        assert len(result["running"]) == 1
        assert result["running"][0]["agent"] == "backend"
        assert result["running"][0]["pid"] == 12345

    def test_filter_by_agent(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "dev")
        tid = db.create_task("backend--project", "fix bug")
        db.update_task(tid, status="running", pid=12345)
        db.update_agent_state("backend--project", "running")

        result = json.loads(tool_status(db, agent="backend"))
        assert len(result["running"]) == 1

        result = json.loads(tool_status(db, agent="frontend"))
        assert result["running"] == []


class TestToolHistory:
    def test_returns_tasks(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "dev")
        tid = db.create_task("backend--project", "fix bug")
        db.update_task(tid, status="done", cost_usd=0.04)

        result = json.loads(tool_history(db, "backend"))
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["status"] == "done"

    def test_nonexistent_agent(self, env):
        result = json.loads(tool_history(env["db"], "nope"))
        assert "error" in result


class TestToolDispatch:
    @patch("claude_bridge.mcp_tools.spawn_task", return_value=99999)
    def test_dispatches_task(self, mock_spawn, env):
        db = env["db"]
        with patch("claude_bridge.mcp_tools.init_claude_md", return_value={"success": True, "message": "ok"}):
            tool_create_agent(db, "backend", str(env["project"]), "API dev")

        result = json.loads(tool_dispatch(db, "backend", "add pagination"))
        assert result["task_id"] > 0
        assert result["pid"] == 99999
        assert result["status"] == "running"

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=99999)
    def test_queues_when_busy(self, mock_spawn, env):
        db = env["db"]
        with patch("claude_bridge.mcp_tools.init_claude_md", return_value={"success": True, "message": "ok"}):
            tool_create_agent(db, "backend", str(env["project"]), "API dev")

        tool_dispatch(db, "backend", "task 1")
        result = json.loads(tool_dispatch(db, "backend", "task 2"))
        assert result["status"] == "queued"

    def test_nonexistent_agent(self, env):
        result = json.loads(tool_dispatch(env["db"], "nope", "do stuff"))
        assert "error" in result


class TestToolKill:
    @patch("claude_bridge.mcp_tools.kill_process", return_value=True)
    @patch("claude_bridge.mcp_tools.spawn_task", return_value=99999)
    def test_kills_running(self, mock_spawn, mock_kill, env):
        db = env["db"]
        with patch("claude_bridge.mcp_tools.init_claude_md", return_value={"success": True, "message": "ok"}):
            tool_create_agent(db, "backend", str(env["project"]), "dev")
        tool_dispatch(db, "backend", "fix bug")

        result = json.loads(tool_kill(db, "backend"))
        assert "killed" in result.get("status", "").lower() or "killed" in json.dumps(result).lower()

    def test_no_running_task(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "dev")
        result = json.loads(tool_kill(db, "backend"))
        assert "no running" in json.dumps(result).lower()


class TestToolCreateAgent:
    def test_creates_agent(self, env):
        db = env["db"]
        with patch("claude_bridge.mcp_tools.init_claude_md", return_value={"success": True, "message": "ok"}):
            result = json.loads(tool_create_agent(db, "backend", str(env["project"]), "API dev"))
        assert result["name"] == "backend"
        assert "session_id" in result
        agent = db.get_agent("backend")
        assert agent is not None

    def test_duplicate_name(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "dev")
        result = json.loads(tool_create_agent(db, "backend", str(env["project"]), "dev"))
        assert "error" in result


@pytest.fixture
def msg_env(tmp_path):
    msg_db = MessageDB(str(tmp_path / "messages.db"))
    yield msg_db
    msg_db.close()


class TestToolGetMessages:
    def test_returns_pending(self, msg_env):
        msg_env.create_inbound("telegram", "12345", "u1", "hello", username="hieu")
        msg_env.create_inbound("telegram", "12345", "u1", "world")

        result = json.loads(tool_get_messages(msg_env))
        assert len(result["messages"]) == 2
        assert result["messages"][0]["text"] == "hello"
        assert result["messages"][0]["chat_id"] == "12345"

    def test_marks_delivered(self, msg_env):
        mid = msg_env.create_inbound("telegram", "12345", "u1", "hello")
        tool_get_messages(msg_env)

        msg = msg_env.get_inbound(mid)
        assert msg["status"] == "delivered"

    def test_no_pending(self, msg_env):
        result = json.loads(tool_get_messages(msg_env))
        assert result["messages"] == []

    def test_skips_already_delivered(self, msg_env):
        mid = msg_env.create_inbound("telegram", "12345", "u1", "hello")
        tool_get_messages(msg_env)  # marks delivered

        result = json.loads(tool_get_messages(msg_env))
        assert result["messages"] == []  # already delivered, not pending


class TestToolAcknowledge:
    def test_acknowledges(self, msg_env):
        mid = msg_env.create_inbound("telegram", "12345", "u1", "hello")
        msg_env.mark_inbound_delivered(mid)

        result = json.loads(tool_acknowledge(msg_env, mid))
        assert result["status"] == "acknowledged"

        msg = msg_env.get_inbound(mid)
        assert msg["status"] == "acknowledged"

    def test_nonexistent(self, msg_env):
        result = json.loads(tool_acknowledge(msg_env, 9999))
        assert "error" in result or result.get("status") == "not_found"


class TestToolGetNotifications:
    def test_returns_unreported(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "dev")
        tid = db.create_task("backend--project", "fix bug")
        db.update_task(tid, status="done", cost_usd=0.04, result_summary="Fixed it")

        result = json.loads(tool_get_notifications(db))
        assert len(result["notifications"]) == 1
        assert result["notifications"][0]["agent"] == "backend"
        assert result["notifications"][0]["status"] == "done"
        assert result["notifications"][0]["cost_usd"] == 0.04

    def test_marks_reported(self, env):
        db = env["db"]
        db.create_agent("backend", str(env["project"]), "backend--project", "/a.md", "dev")
        tid = db.create_task("backend--project", "fix bug")
        db.update_task(tid, status="done")

        tool_get_notifications(db)
        # Second call should return empty
        result = json.loads(tool_get_notifications(db))
        assert result["notifications"] == []

    def test_no_unreported(self, env):
        result = json.loads(tool_get_notifications(env["db"]))
        assert result["notifications"] == []
