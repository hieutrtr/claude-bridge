"""Tests for SQLite database operations."""

import os
import tempfile

import pytest

from claude_bridge.db import BridgeDB


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BridgeDB(db_path)
    yield database
    database.close()


class TestAgentCRUD:
    def test_create_and_get(self, db):
        db.create_agent("backend", "/projects/api", "backend--api", "/path/to/agent.md", "API dev")
        agent = db.get_agent("backend")
        assert agent is not None
        assert agent["name"] == "backend"
        assert agent["session_id"] == "backend--api"
        assert agent["purpose"] == "API dev"
        assert agent["state"] == "created"

    def test_list_agents(self, db):
        db.create_agent("a", "/p/a", "a--a", "/a.md", "")
        db.create_agent("b", "/p/b", "b--b", "/b.md", "")
        agents = db.list_agents()
        assert len(agents) == 2

    def test_delete_agent(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        assert db.delete_agent("backend") is True
        assert db.get_agent("backend") is None

    def test_delete_nonexistent(self, db):
        assert db.delete_agent("nope") is False

    def test_update_state(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        db.update_agent_state("backend--api", "running")
        agent = db.get_agent("backend")
        assert agent["state"] == "running"


class TestTaskCRUD:
    def test_create_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        task_id = db.create_task("backend--api", "fix bug")
        assert task_id > 0

    def test_get_running_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        task_id = db.create_task("backend--api", "fix bug")
        db.update_task(task_id, status="running", pid=12345)
        running = db.get_running_task("backend--api")
        assert running is not None
        assert running["pid"] == 12345

    def test_no_running_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        assert db.get_running_task("backend--api") is None

    def test_task_history(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        db.create_task("backend--api", "task 1")
        db.create_task("backend--api", "task 2")
        history = db.get_task_history("backend--api")
        assert len(history) == 2

    def test_cascade_delete(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        db.create_task("backend--api", "task 1")
        db.delete_agent("backend")
        # Tasks should be deleted via CASCADE
        history = db.get_task_history("backend--api")
        assert len(history) == 0
