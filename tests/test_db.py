"""Tests for SQLite database operations."""

import sqlite3

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


class TestSchemaIntegrity:
    def test_idempotent_init(self, tmp_path):
        """Schema init can be called multiple times without error."""
        db_path = str(tmp_path / "test.db")
        db1 = BridgeDB(db_path)
        db1.close()
        db2 = BridgeDB(db_path)  # second init on same file
        agents = db2.list_agents()
        assert agents == []
        db2.close()

    def test_wal_mode_active(self, db):
        """WAL journal mode must be enabled."""
        result = db.conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0] == "wal"

    def test_foreign_keys_enabled(self, db):
        """Foreign keys must be enforced."""
        result = db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1

    def test_duplicate_agent_name_raises(self, db):
        """Same (name, project_dir) should raise IntegrityError."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        with pytest.raises(sqlite3.IntegrityError):
            db.create_agent("backend", "/p/api", "backend--api2", "/b.md", "")

    def test_duplicate_session_id_raises(self, db):
        """Duplicate session_id should raise IntegrityError."""
        db.create_agent("a", "/p/a", "same-session", "/a.md", "")
        with pytest.raises(sqlite3.IntegrityError):
            db.create_agent("b", "/p/b", "same-session", "/b.md", "")

    def test_fk_invalid_session_id_raises(self, db):
        """Task with non-existent session_id should raise."""
        with pytest.raises(sqlite3.IntegrityError):
            db.create_task("nonexistent-session", "fix bug")

    def test_get_nonexistent_agent_returns_none(self, db):
        assert db.get_agent("nope") is None

    def test_get_nonexistent_agent_by_session_returns_none(self, db):
        assert db.get_agent_by_session("nope") is None

    def test_empty_list(self, db):
        assert db.list_agents() == []

    def test_empty_history(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        assert db.get_task_history("backend--api") == []


class TestTaskAdvanced:
    def test_increment_agent_tasks(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        db.increment_agent_tasks("backend--api")
        db.increment_agent_tasks("backend--api")
        agent = db.get_agent("backend")
        assert agent["total_tasks"] == 2
        assert agent["last_task_at"] is not None

    def test_get_unreported_tasks(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid = db.create_task("backend--api", "fix bug")
        db.update_task(tid, status="done", reported=0)
        unreported = db.get_unreported_tasks()
        assert len(unreported) == 1
        assert unreported[0]["id"] == tid

    def test_mark_task_reported(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid = db.create_task("backend--api", "fix bug")
        db.update_task(tid, status="done")
        db.mark_task_reported(tid)
        unreported = db.get_unreported_tasks()
        assert len(unreported) == 0

    def test_get_running_tasks_multiple(self, db):
        db.create_agent("a", "/p/a", "a--a", "/a.md", "")
        db.create_agent("b", "/p/b", "b--b", "/b.md", "")
        t1 = db.create_task("a--a", "task 1")
        t2 = db.create_task("b--b", "task 2")
        db.update_task(t1, status="running", pid=111)
        db.update_task(t2, status="running", pid=222)
        running = db.get_running_tasks()
        assert len(running) == 2

    def test_get_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid = db.create_task("backend--api", "fix bug")
        task = db.get_task(tid)
        assert task is not None
        assert task["prompt"] == "fix bug"
        assert task["status"] == "pending"

    def test_get_nonexistent_task(self, db):
        assert db.get_task(9999) is None


class TestTaskQueue:
    def test_create_queued_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "queued task")
        db.update_task(tid, status="queued", position=1)
        task = db.get_task(tid)
        assert task["status"] == "queued"
        assert task["position"] == 1

    def test_get_queued_tasks(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        t1 = db.create_task("backend--api", "task 1")
        t2 = db.create_task("backend--api", "task 2")
        t3 = db.create_task("backend--api", "task 3")
        db.update_task(t1, status="queued", position=1)
        db.update_task(t2, status="queued", position=2)
        db.update_task(t3, status="queued", position=3)

        queued = db.get_queued_tasks("backend--api")
        assert len(queued) == 3
        assert queued[0]["position"] == 1
        assert queued[1]["position"] == 2
        assert queued[2]["position"] == 3

    def test_get_queued_tasks_empty(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        assert db.get_queued_tasks("backend--api") == []

    def test_get_next_queue_position(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        assert db.get_next_queue_position("backend--api") == 1

        t1 = db.create_task("backend--api", "task 1")
        db.update_task(t1, status="queued", position=1)
        assert db.get_next_queue_position("backend--api") == 2

    def test_dequeue_next_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        t1 = db.create_task("backend--api", "task 1")
        t2 = db.create_task("backend--api", "task 2")
        db.update_task(t1, status="queued", position=1)
        db.update_task(t2, status="queued", position=2)

        next_task = db.dequeue_next_task("backend--api")
        assert next_task is not None
        assert next_task["id"] == t1
        # Task should now be pending (ready to dispatch)
        task = db.get_task(t1)
        assert task["status"] == "pending"
        assert task["position"] is None

    def test_dequeue_empty_queue(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        assert db.dequeue_next_task("backend--api") is None

    def test_cancel_queued_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        t1 = db.create_task("backend--api", "task 1")
        t2 = db.create_task("backend--api", "task 2")
        db.update_task(t1, status="queued", position=1)
        db.update_task(t2, status="queued", position=2)

        result = db.cancel_queued_task(t1)
        assert result is True

        task = db.get_task(t1)
        assert task["status"] == "cancelled"

        # t2 position should shift down
        remaining = db.get_queued_tasks("backend--api")
        assert len(remaining) == 1
        assert remaining[0]["position"] == 1

    def test_cancel_nonqueued_task_fails(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "running task")
        db.update_task(tid, status="running")
        assert db.cancel_queued_task(tid) is False

    def test_position_null_for_nonqueued(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "normal task")
        task = db.get_task(tid)
        assert task["position"] is None


class TestModelRouting:
    def test_default_model_is_sonnet(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        agent = db.get_agent("backend")
        assert agent["model"] == "sonnet"

    def test_create_agent_with_model(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev", model="opus")
        agent = db.get_agent("backend")
        assert agent["model"] == "opus"

    def test_update_model(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        db.update_agent_model("backend--api", "opus")
        agent = db.get_agent("backend")
        assert agent["model"] == "opus"

    def test_task_records_model(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug")
        db.update_task(tid, model="opus")
        task = db.get_task(tid)
        assert task["model"] == "opus"
