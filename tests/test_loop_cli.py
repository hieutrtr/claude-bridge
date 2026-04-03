"""Tests for loop CLI commands: loop, loop-status, loop-cancel."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from claude_bridge.cli import build_parser, cmd_loop, cmd_loop_cancel, cmd_loop_status
from claude_bridge.db import BridgeDB


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BridgeDB(db_path)
    yield database
    database.close()


@pytest.fixture
def agent(db, tmp_path):
    """Create a test agent."""
    project_dir = str(tmp_path / "project")
    import os
    os.makedirs(project_dir, exist_ok=True)
    db.create_agent(
        "backend",
        project_dir,
        "backend--project",
        "/path/to/agent.md",
        "API development",
        model="sonnet",
    )
    return db.get_agent("backend")


def make_args(**kwargs):
    """Create a simple namespace for CLI args."""
    from argparse import Namespace
    defaults = {
        "name": "backend",
        "goal": "Fix all failing tests",
        "done_when": "command:pytest tests/",
        "max_iterations": 10,
        "max_consecutive_failures": 3,
        "loop_type": "bridge",
        "loop_id": None,
    }
    defaults.update(kwargs)
    return Namespace(**defaults)


# ── cmd_loop ───────────────────────────────────────────────────────────────────

class TestCmdLoop:
    def test_happy_path(self, db, agent, monkeypatch, capsys):
        monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", MagicMock(return_value=99))
        monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", MagicMock(return_value="/tmp/r.json"))

        args = make_args()
        result = cmd_loop(db, args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Loop started:" in captured.out
        assert "--loop--" in captured.out

    def test_agent_not_found(self, db, capsys):
        args = make_args(name="nonexistent")
        result = cmd_loop(db, args)
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_invalid_done_when(self, db, agent, capsys):
        args = make_args(done_when="invalid_condition_without_colon")
        result = cmd_loop(db, args)
        assert result == 1
        captured = capsys.readouterr()
        assert "Invalid" in captured.err

    def test_concurrent_loop_rejected(self, db, agent, monkeypatch, capsys):
        monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", MagicMock(return_value=99))
        monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", MagicMock(return_value="/tmp/r.json"))

        # Start first loop
        args = make_args()
        cmd_loop(db, args)

        # Second loop should fail
        result = cmd_loop(db, args)
        assert result == 1
        captured = capsys.readouterr()
        assert "active loop" in captured.err

    def test_agent_loop_type(self, db, agent, monkeypatch, capsys):
        monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", MagicMock(return_value=99))
        monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", MagicMock(return_value="/tmp/r.json"))

        args = make_args(loop_type="agent")
        result = cmd_loop(db, args)

        assert result == 0
        captured = capsys.readouterr()
        assert "agent" in captured.out

    def test_max_iterations_param(self, db, agent, monkeypatch, capsys):
        monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", MagicMock(return_value=99))
        monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", MagicMock(return_value="/tmp/r.json"))

        args = make_args(max_iterations=5)
        result = cmd_loop(db, args)

        assert result == 0
        loops = db.list_loops(agent="backend")
        assert loops[0]["max_iterations"] == 5

    def test_output_shows_loop_id(self, db, agent, monkeypatch, capsys):
        monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", MagicMock(return_value=99))
        monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", MagicMock(return_value="/tmp/r.json"))

        args = make_args()
        cmd_loop(db, args)

        captured = capsys.readouterr()
        assert "backend--project--loop--" in captured.out


# ── cmd_loop_status ────────────────────────────────────────────────────────────

class TestCmdLoopStatus:
    def _start_loop(self, db, agent, monkeypatch) -> str:
        monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", MagicMock(return_value=99))
        monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", MagicMock(return_value="/tmp/r.json"))
        args = make_args()
        cmd_loop(db, args)
        loops = db.list_loops(agent="backend")
        return loops[0]["loop_id"]

    def test_status_with_loop_id(self, db, agent, monkeypatch, capsys):
        loop_id = self._start_loop(db, agent, monkeypatch)

        from argparse import Namespace
        args = Namespace(loop_id=loop_id, name=None)
        result = cmd_loop_status(db, args)

        assert result == 0
        captured = capsys.readouterr()
        assert loop_id in captured.out
        assert "running" in captured.out

    def test_status_without_loop_id_shows_latest(self, db, agent, monkeypatch, capsys):
        self._start_loop(db, agent, monkeypatch)

        from argparse import Namespace
        args = Namespace(loop_id=None, name=None)
        result = cmd_loop_status(db, args)

        assert result == 0
        captured = capsys.readouterr()
        assert "running" in captured.out

    def test_status_with_agent_name_filter(self, db, agent, monkeypatch, capsys):
        self._start_loop(db, agent, monkeypatch)

        from argparse import Namespace
        args = Namespace(loop_id=None, name="backend")
        result = cmd_loop_status(db, args)

        assert result == 0
        captured = capsys.readouterr()
        assert "backend" in captured.out

    def test_status_nonexistent_loop_id(self, db, capsys):
        from argparse import Namespace
        args = Namespace(loop_id="does-not-exist", name=None)
        result = cmd_loop_status(db, args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_status_no_loops(self, db, capsys):
        from argparse import Namespace
        args = Namespace(loop_id=None, name=None)
        result = cmd_loop_status(db, args)

        assert result == 0
        captured = capsys.readouterr()
        assert "No loops" in captured.out

    def test_status_shows_iterations(self, db, agent, monkeypatch, capsys):
        loop_id = self._start_loop(db, agent, monkeypatch)

        from argparse import Namespace
        args = Namespace(loop_id=loop_id, name=None)
        cmd_loop_status(db, args)

        captured = capsys.readouterr()
        assert "Iteration" in captured.out or "iteration" in captured.out.lower()


# ── cmd_loop_cancel ────────────────────────────────────────────────────────────

class TestCmdLoopCancel:
    def _start_loop(self, db, agent, monkeypatch) -> str:
        monkeypatch.setattr("claude_bridge.dispatcher.spawn_task", MagicMock(return_value=99))
        monkeypatch.setattr("claude_bridge.dispatcher.get_result_file", MagicMock(return_value="/tmp/r.json"))
        args = make_args()
        cmd_loop(db, args)
        loops = db.list_loops(agent="backend")
        return loops[0]["loop_id"]

    def test_cancel_running_loop(self, db, agent, monkeypatch, capsys):
        loop_id = self._start_loop(db, agent, monkeypatch)

        from argparse import Namespace
        args = Namespace(loop_id=loop_id)
        result = cmd_loop_cancel(db, args)

        assert result == 0
        captured = capsys.readouterr()
        assert "cancelled" in captured.out

        loop = db.get_loop(loop_id)
        assert loop["status"] == "cancelled"

    def test_cancel_nonexistent_loop(self, db, capsys):
        from argparse import Namespace
        args = Namespace(loop_id="does-not-exist")
        result = cmd_loop_cancel(db, args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_cancel_already_done_loop(self, db, agent, monkeypatch, capsys):
        loop_id = self._start_loop(db, agent, monkeypatch)
        db.update_loop(loop_id, status="done")

        from argparse import Namespace
        args = Namespace(loop_id=loop_id)
        result = cmd_loop_cancel(db, args)

        assert result == 1
        captured = capsys.readouterr()
        assert "not running" in captured.err


# ── Parser integration ─────────────────────────────────────────────────────────

class TestLoopParser:
    def test_loop_subparser_exists(self):
        parser = build_parser()
        args = parser.parse_args([
            "loop", "myagent", "Fix all tests",
            "--done-when", "command:pytest tests/",
        ])
        assert args.command == "loop"
        assert args.name == "myagent"
        assert args.goal == "Fix all tests"
        assert args.done_when == "command:pytest tests/"
        assert args.max_iterations == 10
        assert args.max_consecutive_failures == 3
        assert args.loop_type == "bridge"

    def test_loop_max_flag(self):
        parser = build_parser()
        args = parser.parse_args([
            "loop", "myagent", "goal",
            "--done-when", "file_exists:done.txt",
            "--max", "5",
        ])
        assert args.max_iterations == 5

    def test_loop_type_agent(self):
        parser = build_parser()
        args = parser.parse_args([
            "loop", "myagent", "goal",
            "--done-when", "file_exists:done.txt",
            "--type", "agent",
        ])
        assert args.loop_type == "agent"

    def test_loop_status_subparser(self):
        parser = build_parser()
        args = parser.parse_args(["loop-status"])
        assert args.command == "loop-status"

    def test_loop_status_with_loop_id(self):
        parser = build_parser()
        args = parser.parse_args(["loop-status", "--loop-id", "abc--loop--123"])
        assert args.loop_id == "abc--loop--123"

    def test_loop_cancel_subparser(self):
        parser = build_parser()
        args = parser.parse_args(["loop-cancel", "myloop--123"])
        assert args.command == "loop-cancel"
        assert args.loop_id == "myloop--123"
