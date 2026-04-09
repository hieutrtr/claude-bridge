"""Tests for multi-user support — end-to-end routing, backward compat, notifications, edge cases.

Covers the changes from the Phase 1 multi-user plan:
  - chat_id/user_id propagation through dispatch chain
  - Notification routing to correct user per task
  - Backward compatibility (CLI dispatch, NULL user_id)
  - DB migration (user_id column)
  - Edge cases (partial context, concurrent dispatches)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_bridge.db import BridgeDB
from claude_bridge.message_db import MessageDB
from claude_bridge.mcp_tools import tool_dispatch, tool_create_agent
from claude_bridge.on_complete import main as on_complete_main


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    database = BridgeDB(str(tmp_path / "test.db"))
    yield database
    database.close()


@pytest.fixture
def msg_db(tmp_path):
    mdb = MessageDB(str(tmp_path / "messages.db"))
    yield mdb
    mdb.close()


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "my-api"
    p.mkdir()
    (p / ".git").mkdir()
    return p


@pytest.fixture
def project2(tmp_path):
    p = tmp_path / "my-ui"
    p.mkdir()
    (p / ".git").mkdir()
    return p


def _make_agent(db, name, project_dir):
    with patch("claude_bridge.mcp_tools.init_claude_md", return_value={"success": True, "message": "ok"}):
        tool_create_agent(db, name, str(project_dir), f"{name} dev")


def _make_result_file(tmp_path, task_id, *, error=False, summary="done"):
    rf = str(tmp_path / f"task-{task_id}-result.json")
    with open(rf, "w") as f:
        json.dump({
            "is_error": error,
            "result": summary,
            "total_cost_usd": 0.01,
            "duration_ms": 5000,
            "num_turns": 1,
        }, f)
    return rf


# ===========================================================================
# 1. Integration tests — Multi-user dispatch routing
# ===========================================================================


class TestMultiUserDispatchRouting:
    """End-to-end: different users dispatch tasks, each task gets the correct chat_id."""

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=11111)
    def test_alice_task_has_alice_chat_id(self, mock_spawn, db, project):
        """ALICE dispatch → task.channel_chat_id = 111."""
        _make_agent(db, "backend", project)

        result = json.loads(tool_dispatch(db, "backend", "fix auth", chat_id="111", user_id="AAA"))
        assert result["status"] == "running"
        task = db.get_task(result["task_id"])
        assert task["channel_chat_id"] == "111"
        assert task["user_id"] == "AAA"
        assert task["channel"] == "telegram"

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=22222)
    def test_bob_task_has_bob_chat_id(self, mock_spawn, db, project2):
        """BOB dispatch → task.channel_chat_id = 222."""
        _make_agent(db, "frontend", project2)

        result = json.loads(tool_dispatch(db, "frontend", "fix ui", chat_id="222", user_id="BBB"))
        assert result["status"] == "running"
        task = db.get_task(result["task_id"])
        assert task["channel_chat_id"] == "222"
        assert task["user_id"] == "BBB"

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=33333)
    def test_same_agent_different_users_no_mixing(self, mock_spawn, db, project, project2):
        """Alice and Bob dispatch to DIFFERENT agents — no cross-contamination."""
        _make_agent(db, "backend", project)
        _make_agent(db, "frontend", project2)

        r_alice = json.loads(tool_dispatch(db, "backend", "alice task", chat_id="111", user_id="AAA"))
        r_bob = json.loads(tool_dispatch(db, "frontend", "bob task", chat_id="222", user_id="BBB"))

        t_alice = db.get_task(r_alice["task_id"])
        t_bob = db.get_task(r_bob["task_id"])

        assert t_alice["channel_chat_id"] == "111"
        assert t_alice["user_id"] == "AAA"
        assert t_bob["channel_chat_id"] == "222"
        assert t_bob["user_id"] == "BBB"

        # Verify no mixing
        assert t_alice["channel_chat_id"] != t_bob["channel_chat_id"]
        assert t_alice["user_id"] != t_bob["user_id"]

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=44444)
    def test_alice_then_bob_queued_correct_ids(self, mock_spawn, db, project):
        """Alice runs, Bob queues — Bob's queued task has Bob's chat_id, not Alice's."""
        _make_agent(db, "backend", project)

        # Alice dispatches first (runs)
        r_alice = json.loads(tool_dispatch(db, "backend", "alice task", chat_id="111", user_id="AAA"))
        assert r_alice["status"] == "running"

        # Bob dispatches second (queued, agent busy)
        r_bob = json.loads(tool_dispatch(db, "backend", "bob task", chat_id="222", user_id="BBB"))
        assert r_bob["status"] == "queued"

        t_alice = db.get_task(r_alice["task_id"])
        t_bob = db.get_task(r_bob["task_id"])

        assert t_alice["channel_chat_id"] == "111"
        assert t_bob["channel_chat_id"] == "222"
        assert t_bob["user_id"] == "BBB"


# ===========================================================================
# 2. Backward compatibility
# ===========================================================================


class TestBackwardCompatibility:
    """Existing CLI dispatch and tasks without user_id must keep working."""

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=55555)
    def test_cli_dispatch_no_chat_id_fallback(self, mock_spawn, db, project):
        """CLI dispatch (no chat_id) → falls back to get_default_channel()."""
        _make_agent(db, "backend", project)

        with patch("claude_bridge.notify.get_default_channel", return_value=("cli", None)):
            result = json.loads(tool_dispatch(db, "backend", "fix bug"))

        assert result["status"] == "running"
        task = db.get_task(result["task_id"])
        assert task["channel"] == "cli"
        assert task["channel_chat_id"] is None
        assert task["user_id"] is None

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=55556)
    def test_existing_tasks_null_user_id_still_readable(self, mock_spawn, db, project):
        """Tasks with user_id=NULL (old records) must still be queryable."""
        _make_agent(db, "backend", project)

        # Create a task without user_id (legacy style)
        tid = db.create_task("backend--my-api", "old task", channel="cli")
        task = db.get_task(tid)
        assert task is not None
        assert task["user_id"] is None
        assert task["prompt"] == "old task"

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=55557)
    def test_bridge_dispatch_no_user_id_still_works(self, mock_spawn, db, project):
        """bridge_dispatch with chat_id but without user_id should not error."""
        _make_agent(db, "backend", project)

        result = json.loads(tool_dispatch(db, "backend", "no user_id task", chat_id="999"))
        assert result["status"] == "running"
        task = db.get_task(result["task_id"])
        assert task["channel_chat_id"] == "999"
        assert task["user_id"] is None  # not provided, should be NULL

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=55558)
    def test_cli_dispatch_default_channel_chat_id(self, mock_spawn, db, project):
        """CLI dispatch with a configured default chat_id still routes to it."""
        _make_agent(db, "backend", project)

        with patch("claude_bridge.notify.get_default_channel", return_value=("telegram", "DEFAULT_CHAT")):
            result = json.loads(tool_dispatch(db, "backend", "cli task"))

        task = db.get_task(result["task_id"])
        assert task["channel"] == "telegram"
        assert task["channel_chat_id"] == "DEFAULT_CHAT"


# ===========================================================================
# 3. Notification routing
# ===========================================================================


class TestNotificationRouting:
    """on_complete must route notifications to the task's channel_chat_id."""

    def _setup_running_task(self, db, tmp_path, session_id, chat_id, user_id=None):
        """Create a running task with a result file."""
        tid = db.create_task(
            session_id, "fix bug",
            channel="telegram",
            channel_chat_id=chat_id,
            user_id=user_id,
        )
        result_file = _make_result_file(tmp_path, tid, summary="All done")
        db.update_task(tid, status="running", pid=12345, result_file=result_file)
        db.update_agent_state(session_id, "running")
        return tid

    def test_alice_completion_notifies_alice(self, db, tmp_path, monkeypatch):
        """Task complete for ALICE → outbound message sent to chat_id=111."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = self._setup_running_task(db, tmp_path, "backend--api", "111", user_id="AAA")

        msg_db_path = str(tmp_path / "messages.db")
        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])
        on_complete_main(db=db, msg_db_path=msg_db_path)

        mdb = MessageDB(msg_db_path)
        rows = mdb.conn.execute("SELECT chat_id FROM outbound_messages").fetchall()
        mdb.close()

        assert len(rows) == 1
        assert rows[0]["chat_id"] == "111"

    def test_bob_completion_notifies_bob(self, db, tmp_path, monkeypatch):
        """Task complete for BOB → outbound message sent to chat_id=222."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = self._setup_running_task(db, tmp_path, "backend--api", "222", user_id="BBB")

        msg_db_path = str(tmp_path / "messages.db")
        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])
        on_complete_main(db=db, msg_db_path=msg_db_path)

        mdb = MessageDB(msg_db_path)
        rows = mdb.conn.execute("SELECT chat_id FROM outbound_messages").fetchall()
        mdb.close()

        assert len(rows) == 1
        assert rows[0]["chat_id"] == "222"

    def test_no_cross_notification(self, db, tmp_path, monkeypatch):
        """Alice's task completion must NOT create outbound to Bob's chat_id."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        db.create_agent("frontend", "/p/web", "frontend--web", "/b.md", "dev")

        # Alice's task on backend
        tid_alice = self._setup_running_task(db, tmp_path, "backend--api", "111", user_id="AAA")

        # Bob has a task too (queued, not running) — should NOT get notification
        tid_bob = db.create_task(
            "backend--api", "bob task",
            channel="telegram", channel_chat_id="222", user_id="BBB",
        )
        db.update_task(tid_bob, status="queued", position=1)

        msg_db_path = str(tmp_path / "messages.db")
        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])

        with patch("claude_bridge.dispatcher.spawn_task", return_value=99999):
            on_complete_main(db=db, msg_db_path=msg_db_path)

        mdb = MessageDB(msg_db_path)
        rows = mdb.conn.execute("SELECT chat_id FROM outbound_messages WHERE source='notification'").fetchall()
        mdb.close()

        chat_ids = {r["chat_id"] for r in rows}
        # Alice's completion notification goes to 111 only
        assert "111" in chat_ids
        assert "222" not in chat_ids  # Bob's task didn't complete yet

    def test_cli_task_no_notification(self, db, tmp_path, monkeypatch):
        """CLI task completion (channel='cli') never creates outbound messages."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "cli task")  # default channel='cli'
        rf = _make_result_file(tmp_path, tid)
        db.update_task(tid, status="running", pid=111, result_file=rf)
        db.update_agent_state("backend--api", "running")

        msg_db_path = str(tmp_path / "messages.db")
        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])
        on_complete_main(db=db, msg_db_path=msg_db_path)

        mdb = MessageDB(msg_db_path)
        rows = mdb.conn.execute("SELECT * FROM outbound_messages").fetchall()
        mdb.close()
        assert len(rows) == 0

    def test_notification_includes_user_id_context(self, db, tmp_path, monkeypatch):
        """Outbound notification is created with correct source='notification'."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = self._setup_running_task(db, tmp_path, "backend--api", "111", user_id="AAA")

        msg_db_path = str(tmp_path / "messages.db")
        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])
        on_complete_main(db=db, msg_db_path=msg_db_path)

        mdb = MessageDB(msg_db_path)
        rows = mdb.conn.execute("SELECT * FROM outbound_messages").fetchall()
        mdb.close()

        assert rows[0]["source"] == "notification"
        assert rows[0]["platform"] == "telegram"


# ===========================================================================
# 4. DB migration
# ===========================================================================


class TestDBMigration:
    """user_id column added via migration to existing databases."""

    def test_new_db_has_user_id_column(self, db):
        """Fresh DB must have user_id column in tasks."""
        cursor = db.conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "user_id" in cols

    def test_old_db_migration_adds_user_id(self, tmp_path):
        """Legacy DB (no user_id column) gets column added on first open."""
        import sqlite3 as _sqlite3
        db_path = str(tmp_path / "legacy.db")

        # Build a DB resembling the old schema (no user_id)
        conn = _sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE agents (
                name TEXT NOT NULL,
                project_dir TEXT NOT NULL,
                session_id TEXT NOT NULL UNIQUE,
                agent_file TEXT NOT NULL,
                purpose TEXT,
                state TEXT DEFAULT 'created',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (name, project_dir)
            )
        """)
        conn.execute("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                channel TEXT DEFAULT 'cli',
                channel_chat_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()

        # Open with BridgeDB — migration should add user_id
        migrated = BridgeDB(db_path)
        cursor = migrated.conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        migrated.close()

        assert "user_id" in cols

    def test_migrated_old_rows_have_null_user_id(self, tmp_path):
        """Existing rows in a migrated DB all have user_id=NULL."""
        import sqlite3 as _sqlite3
        db_path = str(tmp_path / "legacy2.db")

        conn = _sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE agents (
            name TEXT NOT NULL, project_dir TEXT NOT NULL,
            session_id TEXT NOT NULL UNIQUE, agent_file TEXT NOT NULL,
            purpose TEXT, state TEXT DEFAULT 'created',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (name, project_dir))""")
        conn.execute("""CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, prompt TEXT NOT NULL,
            status TEXT DEFAULT 'pending', channel TEXT DEFAULT 'cli',
            channel_chat_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        # Insert a legacy row
        conn.execute("INSERT INTO agents VALUES ('backend','/p/api','backend--api','/a.md','dev','idle', datetime('now'))")
        conn.execute("INSERT INTO tasks (session_id, prompt) VALUES ('backend--api', 'old task')")
        conn.commit()
        conn.close()

        migrated = BridgeDB(db_path)
        cursor = migrated.conn.execute("SELECT user_id FROM tasks")
        rows = cursor.fetchall()
        migrated.close()

        assert len(rows) == 1
        assert rows[0][0] is None  # user_id is NULL

    def test_insert_with_user_id_after_migration(self, tmp_path):
        """After migration, new tasks with user_id are stored correctly."""
        import sqlite3 as _sqlite3
        db_path = str(tmp_path / "legacy3.db")

        conn = _sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE agents (
            name TEXT NOT NULL, project_dir TEXT NOT NULL,
            session_id TEXT NOT NULL UNIQUE, agent_file TEXT NOT NULL,
            purpose TEXT, state TEXT DEFAULT 'created',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (name, project_dir))""")
        conn.execute("""CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL, prompt TEXT NOT NULL,
            status TEXT DEFAULT 'pending', channel TEXT DEFAULT 'cli',
            channel_chat_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("INSERT INTO agents VALUES ('backend','/p/api','backend--api','/a.md','dev','idle', datetime('now'))")
        conn.commit()
        conn.close()

        migrated = BridgeDB(db_path)
        tid = migrated.create_task(
            "backend--api", "new task",
            channel="telegram", channel_chat_id="111", user_id="AAA",
        )
        task = migrated.get_task(tid)
        migrated.close()

        assert task["user_id"] == "AAA"
        assert task["channel_chat_id"] == "111"


# ===========================================================================
# 5. Edge cases
# ===========================================================================


class TestMultiUserEdgeCases:
    """Partial context, fallback behavior, concurrent dispatches."""

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=77777)
    def test_chat_id_without_user_id_routes_correctly(self, mock_spawn, db, project):
        """chat_id provided but user_id omitted → channel=telegram, user_id=NULL."""
        _make_agent(db, "backend", project)

        result = json.loads(tool_dispatch(db, "backend", "task", chat_id="555"))
        task = db.get_task(result["task_id"])
        assert task["channel"] == "telegram"
        assert task["channel_chat_id"] == "555"
        assert task["user_id"] is None

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=88888)
    def test_user_id_without_chat_id_falls_back_to_default(self, mock_spawn, db, project):
        """user_id provided but chat_id omitted → falls back to get_default_channel()."""
        _make_agent(db, "backend", project)

        with patch("claude_bridge.notify.get_default_channel", return_value=("cli", None)):
            result = json.loads(tool_dispatch(db, "backend", "task", user_id="ORPHAN"))

        # chat_id not provided, so default channel is used
        task = db.get_task(result["task_id"])
        assert task["channel"] == "cli"
        assert task["channel_chat_id"] is None
        # user_id is still stored even without chat_id
        assert task["user_id"] == "ORPHAN"

    @patch("claude_bridge.mcp_tools.spawn_task", side_effect=[11111, 22222])
    def test_concurrent_dispatch_two_agents_no_race(self, mock_spawn, db, project, project2):
        """Two concurrent dispatches to different agents — no state leakage."""
        _make_agent(db, "backend", project)
        _make_agent(db, "frontend", project2)

        r1 = json.loads(tool_dispatch(db, "backend", "task1", chat_id="111", user_id="AAA"))
        r2 = json.loads(tool_dispatch(db, "frontend", "task2", chat_id="222", user_id="BBB"))

        assert r1["status"] == "running"
        assert r2["status"] == "running"
        assert r1["task_id"] != r2["task_id"]

        t1 = db.get_task(r1["task_id"])
        t2 = db.get_task(r2["task_id"])
        assert t1["user_id"] == "AAA"
        assert t2["user_id"] == "BBB"
        assert t1["channel_chat_id"] == "111"
        assert t2["channel_chat_id"] == "222"

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=99999)
    def test_multiple_queued_tasks_each_keep_own_chat_id(self, mock_spawn, db, project):
        """Queue with 3 tasks from 3 users — each keeps its own chat_id."""
        _make_agent(db, "backend", project)

        users = [("111", "AAA"), ("222", "BBB"), ("333", "CCC")]
        task_ids = []

        for chat_id, user_id in users:
            r = json.loads(tool_dispatch(db, "backend", f"task from {user_id}",
                                          chat_id=chat_id, user_id=user_id))
            task_ids.append(r["task_id"])

        # First is running, rest are queued
        tasks = [db.get_task(tid) for tid in task_ids]
        assert tasks[0]["status"] == "running"
        assert tasks[1]["status"] == "queued"
        assert tasks[2]["status"] == "queued"

        for task, (expected_chat, expected_user) in zip(tasks, users):
            assert task["channel_chat_id"] == expected_chat
            assert task["user_id"] == expected_user

    def test_dispatch_unknown_agent_returns_error(self, db):
        """Dispatching to a non-existent agent returns an error (not crash)."""
        result = json.loads(tool_dispatch(db, "ghost-agent", "task"))
        assert "error" in result

    @patch("claude_bridge.mcp_tools.spawn_task", return_value=12121)
    def test_empty_user_id_treated_as_none(self, mock_spawn, db, project):
        """Passing user_id='' (empty string) is stored as-is — not coerced."""
        _make_agent(db, "backend", project)

        result = json.loads(tool_dispatch(db, "backend", "task", chat_id="111", user_id=""))
        task = db.get_task(result["task_id"])
        # Empty string is falsy but should be stored as-is (caller's responsibility)
        assert task["channel_chat_id"] == "111"
