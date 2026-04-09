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


class TestMigration:
    def test_reported_column_exists_on_new_db(self, tmp_path):
        """FIX-02: 'reported' column must exist on fresh DB (via schema)."""
        db_path = str(tmp_path / "fresh.db")
        db = BridgeDB(db_path)
        cursor = db.conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        db.close()
        assert "reported" in cols

    def test_reported_column_added_by_migration(self, tmp_path):
        """FIX-02: 'reported' column added to existing DB missing the column."""
        import sqlite3 as _sqlite3

        db_path = str(tmp_path / "old.db")
        # Create a legacy DB without 'reported' column
        conn = _sqlite3.connect(db_path)
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE agents (
                name TEXT NOT NULL,
                project_dir TEXT NOT NULL,
                session_id TEXT NOT NULL UNIQUE,
                agent_file TEXT NOT NULL,
                purpose TEXT,
                state TEXT DEFAULT 'created',
                PRIMARY KEY (name, project_dir)
            );
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES agents(session_id),
                prompt TEXT NOT NULL,
                status TEXT DEFAULT 'pending'
            );
        """)
        conn.close()

        # BridgeDB should migrate and add 'reported'
        db = BridgeDB(db_path)
        cursor = db.conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        db.close()
        assert "reported" in cols


class TestAtomicDispatch:
    def test_reserves_free_agent(self, db):
        """FIX-04: atomic check creates task with status 'running' when agent free."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        task_id, is_busy = db.atomic_check_and_create_task("backend--api", "fix bug")
        assert not is_busy
        assert task_id is not None
        task = db.get_task(task_id)
        assert task["status"] == "running"

    def test_detects_busy_agent(self, db):
        """FIX-04: atomic check returns is_busy=True when agent already running."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        # Put agent in running state
        t1 = db.create_task("backend--api", "first task")
        db.update_task(t1, status="running", pid=12345)

        task_id, is_busy = db.atomic_check_and_create_task("backend--api", "second task")
        assert is_busy
        assert task_id is None

    def test_exclusive_prevents_double_spawn(self, db):
        """FIX-04: sequential calls on same free agent — only first succeeds."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        # Simulate two rapid sequential calls (can't truly test concurrent in same thread)
        t1, b1 = db.atomic_check_and_create_task("backend--api", "task A")
        t2, b2 = db.atomic_check_and_create_task("backend--api", "task B")
        # First call reserves; second sees running task
        assert not b1 and t1 is not None
        assert b2 and t2 is None

    def test_preserves_channel_info(self, db):
        """FIX-04: channel metadata stored in atomically-created task."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        task_id, _ = db.atomic_check_and_create_task(
            "backend--api", "task", channel="telegram", channel_chat_id="123", channel_message_id="456"
        )
        task = db.get_task(task_id)
        assert task["channel"] == "telegram"
        assert task["channel_chat_id"] == "123"
        assert task["channel_message_id"] == "456"


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


class TestTeamCRUD:
    """Tests for team creation, listing, and deletion."""

    def _setup_agents(self, db):
        """Helper to create test agents."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "API dev")
        db.create_agent("frontend", "/p/web", "frontend--web", "/b.md", "UI dev")
        db.create_agent("devops", "/p/infra", "devops--infra", "/c.md", "Infra")

    def test_create_team(self, db):
        self._setup_agents(db)
        db.create_team("fullstack", "backend", ["frontend", "devops"])
        team = db.get_team("fullstack")
        assert team is not None
        assert team["name"] == "fullstack"
        assert team["lead_agent"] == "backend"

    def test_get_team_members(self, db):
        self._setup_agents(db)
        db.create_team("fullstack", "backend", ["frontend", "devops"])
        members = db.get_team_members("fullstack")
        assert sorted(members) == ["devops", "frontend"]

    def test_list_teams(self, db):
        self._setup_agents(db)
        db.create_team("fullstack", "backend", ["frontend"])
        db.create_team("infra", "devops", ["backend"])
        teams = db.list_teams()
        assert len(teams) == 2

    def test_delete_team(self, db):
        self._setup_agents(db)
        db.create_team("fullstack", "backend", ["frontend"])
        assert db.delete_team("fullstack") is True
        assert db.get_team("fullstack") is None

    def test_delete_team_preserves_agents(self, db):
        self._setup_agents(db)
        db.create_team("fullstack", "backend", ["frontend"])
        db.delete_team("fullstack")
        assert db.get_agent("backend") is not None
        assert db.get_agent("frontend") is not None

    def test_delete_nonexistent_team(self, db):
        assert db.delete_team("nope") is False

    def test_get_nonexistent_team(self, db):
        assert db.get_team("nope") is None

    def test_duplicate_team_name_raises(self, db):
        self._setup_agents(db)
        db.create_team("fullstack", "backend", ["frontend"])
        with pytest.raises(sqlite3.IntegrityError):
            db.create_team("fullstack", "devops", ["backend"])

    def test_team_with_single_member(self, db):
        self._setup_agents(db)
        db.create_team("solo", "backend", ["frontend"])
        members = db.get_team_members("solo")
        assert members == ["frontend"]

    def test_cascade_delete_team_members(self, db):
        """Deleting a team removes its member rows."""
        self._setup_agents(db)
        db.create_team("fullstack", "backend", ["frontend", "devops"])
        db.delete_team("fullstack")
        members = db.get_team_members("fullstack")
        assert members == []


class TestTaskParentChild:
    """Tests for parent_task_id and task_type columns."""

    def test_task_default_type_is_standard(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "normal task")
        task = db.get_task(tid)
        assert task["task_type"] == "standard"

    def test_create_team_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        parent_id = db.create_task("backend--api", "team task", task_type="team")
        task = db.get_task(parent_id)
        assert task["task_type"] == "team"

    def test_create_subtask_with_parent(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        db.create_agent("frontend", "/p/web", "frontend--web", "/b.md", "UI")
        parent_id = db.create_task("backend--api", "team task", task_type="team")
        sub_id = db.create_task("frontend--web", "sub task", parent_task_id=parent_id)
        sub = db.get_task(sub_id)
        assert sub["parent_task_id"] == parent_id

    def test_get_subtasks(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        db.create_agent("frontend", "/p/web", "frontend--web", "/b.md", "UI")
        db.create_agent("devops", "/p/infra", "devops--infra", "/c.md", "Infra")
        parent_id = db.create_task("backend--api", "team task", task_type="team")
        db.create_task("frontend--web", "sub 1", parent_task_id=parent_id)
        db.create_task("devops--infra", "sub 2", parent_task_id=parent_id)
        subtasks = db.get_subtasks(parent_id)
        assert len(subtasks) == 2

    def test_get_subtasks_empty(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "no children")
        assert db.get_subtasks(tid) == []

    def test_parent_task_id_null_by_default(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "normal task")
        task = db.get_task(tid)
        assert task["parent_task_id"] is None


class TestMultiUserSupport:
    """Tests for multi-user user_id tracking in tasks."""

    def test_user_id_column_exists(self, db):
        """tasks table must have a user_id column."""
        cursor = db.conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "user_id" in cols

    def test_user_id_defaults_to_null(self, db):
        """Tasks created without user_id should have user_id=None."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid = db.create_task("backend--api", "fix bug")
        task = db.get_task(tid)
        assert task["user_id"] is None

    def test_create_task_with_user_id(self, db):
        """Tasks can be created with an explicit user_id."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid = db.create_task("backend--api", "fix bug", user_id="456789")
        task = db.get_task(tid)
        assert task["user_id"] == "456789"

    def test_create_task_with_channel_and_user_id(self, db):
        """Tasks created with full routing context store all fields."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid = db.create_task(
            "backend--api", "fix bug",
            channel="telegram",
            channel_chat_id="111222333",
            user_id="456789",
        )
        task = db.get_task(tid)
        assert task["channel"] == "telegram"
        assert task["channel_chat_id"] == "111222333"
        assert task["user_id"] == "456789"

    def test_multiple_users_different_user_ids(self, db):
        """Multiple tasks from different users store distinct user_ids."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid_alice = db.create_task("backend--api", "alice task", channel="telegram",
                                   channel_chat_id="111", user_id="AAA")
        tid_bob = db.create_task("backend--api", "bob task", channel="telegram",
                                 channel_chat_id="222", user_id="BBB")
        alice_task = db.get_task(tid_alice)
        bob_task = db.get_task(tid_bob)
        assert alice_task["user_id"] == "AAA"
        assert alice_task["channel_chat_id"] == "111"
        assert bob_task["user_id"] == "BBB"
        assert bob_task["channel_chat_id"] == "222"

    def test_update_task_user_id(self, db):
        """user_id can be updated via update_task()."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "")
        tid = db.create_task("backend--api", "fix bug")
        db.update_task(tid, user_id="987654")
        task = db.get_task(tid)
        assert task["user_id"] == "987654"

    def test_migration_adds_user_id_to_existing_db(self, tmp_path):
        """Existing DB without user_id column gets it added via migration."""
        import sqlite3 as _sqlite3
        db_path = str(tmp_path / "old.db")

        # Create a DB with the old schema (no user_id column)
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

        # Now open with BridgeDB — migration should add user_id
        from claude_bridge.db import BridgeDB
        db = BridgeDB(db_path)
        cursor = db.conn.execute("PRAGMA table_info(tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "user_id" in cols
        db.close()
