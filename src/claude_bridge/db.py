"""SQLite database module for Claude Bridge.

Manages agents and tasks tables. Uses WAL mode for safe concurrent reads.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

def _default_db_path() -> str:
    """Compute default DB path respecting CLAUDE_BRIDGE_HOME env var."""
    from . import get_bridge_home
    return str(get_bridge_home() / "bridge.db")


DEFAULT_DB_PATH = None  # Use _default_db_path() at runtime

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS agents (
    name TEXT NOT NULL,
    project_dir TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    agent_file TEXT NOT NULL,
    purpose TEXT,
    state TEXT DEFAULT 'created',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_task_at TIMESTAMP,
    total_tasks INTEGER DEFAULT 0,
    model TEXT DEFAULT 'sonnet',
    PRIMARY KEY (name, project_dir)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES agents(session_id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    position INTEGER,
    pid INTEGER,
    result_file TEXT,
    result_summary TEXT,
    cost_usd REAL,
    duration_ms INTEGER,
    num_turns INTEGER,
    exit_code INTEGER,
    error_message TEXT,
    model TEXT,
    task_type TEXT DEFAULT 'standard',
    parent_task_id INTEGER REFERENCES tasks(id),
    channel TEXT DEFAULT 'cli',
    channel_chat_id TEXT,
    channel_message_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    reported INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS permissions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    command TEXT,
    description TEXT,
    status TEXT DEFAULT 'pending',
    response TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    responded_at TIMESTAMP,
    timeout_seconds INTEGER DEFAULT 300
);

CREATE TABLE IF NOT EXISTS teams (
    name TEXT PRIMARY KEY,
    lead_agent TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_members (
    team_name TEXT NOT NULL REFERENCES teams(name) ON DELETE CASCADE,
    agent_name TEXT NOT NULL,
    PRIMARY KEY (team_name, agent_name)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id),
    channel TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
CREATE INDEX IF NOT EXISTS idx_permissions_status ON permissions(status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_unreported ON tasks(status, reported)
    WHERE status IN ('done', 'failed', 'timeout') AND reported = 0;
"""


class BridgeDB:
    """SQLite database for agent and task tracking."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = _default_db_path()
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        # Migrate first so new columns exist before CREATE INDEX references them
        self._migrate()
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _migrate(self):
        """Add columns that may be missing from older databases."""
        existing = {
            "tasks": set(),
            "agents": set(),
        }
        for table in existing:
            cursor = self.conn.execute(f"PRAGMA table_info({table})")
            cols = {row[1] for row in cursor.fetchall()}
            existing[table] = cols
        # Skip migration if tables don't exist yet (fresh DB)
        if not existing["tasks"] and not existing["agents"]:
            return

        migrations = [
            ("tasks", "position", "INTEGER"),
            ("tasks", "model", "TEXT"),
            ("tasks", "task_type", "TEXT DEFAULT 'standard'"),
            ("tasks", "parent_task_id", "INTEGER REFERENCES tasks(id)"),
            ("tasks", "channel", "TEXT DEFAULT 'cli'"),
            ("tasks", "channel_chat_id", "TEXT"),
            ("tasks", "channel_message_id", "TEXT"),
            ("tasks", "reported", "INTEGER DEFAULT 0"),
            ("agents", "model", "TEXT DEFAULT 'sonnet'"),
        ]
        for table, column, col_type in migrations:
            if column not in existing[table]:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def close(self):
        self.conn.close()

    def atomic_check_and_create_task(
        self,
        session_id: str,
        prompt: str,
        channel: str = "cli",
        channel_chat_id: str | None = None,
        channel_message_id: str | None = None,
    ) -> tuple[int | None, bool]:
        """Atomically check for running task and create new task if agent is free.

        Uses BEGIN EXCLUSIVE to prevent race conditions when concurrent dispatches
        both check for a running task and both try to spawn.

        Creates task with status='running' so subsequent exclusive checks see it as busy.

        Returns:
            (task_id, False) — dispatch reserved, caller should spawn and update task
            (None, True)     — agent is busy, caller should queue instead
        """
        # Switch to manual transaction mode to use BEGIN EXCLUSIVE
        old_isolation = self.conn.isolation_level
        self.conn.isolation_level = None  # autocommit
        try:
            self.conn.execute("BEGIN EXCLUSIVE")
            running = self.conn.execute(
                "SELECT id FROM tasks WHERE session_id = ? AND status = 'running' LIMIT 1",
                (session_id,),
            ).fetchone()
            if running:
                self.conn.execute("COMMIT")
                return None, True
            cursor = self.conn.execute(
                """INSERT INTO tasks (session_id, prompt, status, channel, channel_chat_id, channel_message_id)
                   VALUES (?, ?, 'running', ?, ?, ?)""",
                (session_id, prompt, channel, channel_chat_id, channel_message_id),
            )
            task_id = cursor.lastrowid
            self.conn.execute("COMMIT")
            return task_id, False
        except Exception:
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            self.conn.isolation_level = old_isolation

    # --- Agent operations ---

    def create_agent(
        self,
        name: str,
        project_dir: str,
        session_id: str,
        agent_file: str,
        purpose: str = "",
        model: str = "sonnet",
    ) -> sqlite3.Row:
        self.conn.execute(
            """INSERT INTO agents (name, project_dir, session_id, agent_file, purpose, model)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, project_dir, session_id, agent_file, purpose, model),
        )
        self.conn.commit()
        return self.get_agent(name)

    def get_agent(self, name: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM agents WHERE name = ?", (name,)
        ).fetchone()

    def get_agent_by_session(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM agents WHERE session_id = ?", (session_id,)
        ).fetchone()

    def list_agents(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM agents ORDER BY created_at DESC"
        ).fetchall()

    def delete_agent(self, name: str) -> bool:
        cursor = self.conn.execute("DELETE FROM agents WHERE name = ?", (name,))
        self.conn.commit()
        return cursor.rowcount > 0

    def update_agent_state(self, session_id: str, state: str):
        self.conn.execute(
            "UPDATE agents SET state = ? WHERE session_id = ?",
            (state, session_id),
        )
        self.conn.commit()

    def increment_agent_tasks(self, session_id: str):
        self.conn.execute(
            """UPDATE agents SET total_tasks = total_tasks + 1,
               last_task_at = ? WHERE session_id = ?""",
            (datetime.now().isoformat(), session_id),
        )
        self.conn.commit()

    def update_agent_model(self, session_id: str, model: str):
        self.conn.execute(
            "UPDATE agents SET model = ? WHERE session_id = ?",
            (model, session_id),
        )
        self.conn.commit()

    # --- Task operations ---

    def create_task(
        self,
        session_id: str,
        prompt: str,
        task_type: str = "standard",
        parent_task_id: int | None = None,
        channel: str = "cli",
        channel_chat_id: str | None = None,
        channel_message_id: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            "INSERT INTO tasks (session_id, prompt, task_type, parent_task_id, channel, channel_chat_id, channel_message_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, prompt, task_type, parent_task_id, channel, channel_chat_id, channel_message_id),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_task(self, task_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()

    def get_running_task(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? AND status = 'running' LIMIT 1",
            (session_id,),
        ).fetchone()

    def get_running_tasks(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE status = 'running'"
        ).fetchall()

    def get_unreported_tasks(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT t.*, a.name as agent_name, a.project_dir
               FROM tasks t JOIN agents a ON t.session_id = a.session_id
               WHERE t.status IN ('done', 'failed', 'timeout') AND t.reported = 0"""
        ).fetchall()

    def get_task_history(self, session_id: str, limit: int = 10) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()

    # Allowed column names for update_task() — prevents typos and injection
    _TASK_UPDATABLE_COLUMNS = frozenset({
        "status", "pid", "result_file", "result_summary", "cost_usd",
        "duration_ms", "num_turns", "exit_code", "error_message", "model",
        "task_type", "parent_task_id", "channel", "channel_chat_id",
        "channel_message_id", "started_at", "completed_at", "reported", "position",
    })

    def update_task(self, task_id: int, **kwargs):
        """Update task fields by ID. Only whitelisted column names are accepted."""
        invalid = set(kwargs) - self._TASK_UPDATABLE_COLUMNS
        if invalid:
            raise ValueError(f"update_task: invalid column(s): {sorted(invalid)}")
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        self.conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", values)
        self.conn.commit()

    def mark_task_reported(self, task_id: int):
        self.conn.execute(
            "UPDATE tasks SET reported = 1 WHERE id = ?", (task_id,)
        )
        self.conn.commit()

    def get_cost_summary(self, session_id: str | None = None, period: str = "all") -> dict:
        """Get aggregated cost summary. Returns dict with total, count, average."""
        where_clauses = ["status IN ('done', 'failed')"]
        params = []

        if session_id:
            where_clauses.append("session_id = ?")
            params.append(session_id)

        if period == "today":
            where_clauses.append("DATE(completed_at) = DATE('now')")
        elif period == "week":
            where_clauses.append("completed_at >= DATE('now', '-7 days')")
        elif period == "month":
            where_clauses.append("completed_at >= DATE('now', '-30 days')")

        where = " AND ".join(where_clauses)
        row = self.conn.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) as total, COUNT(*) as count FROM tasks WHERE {where}",
            params,
        ).fetchone()

        total = row["total"] or 0
        count = row["count"] or 0
        avg = total / count if count > 0 else 0
        return {"total": total, "count": count, "average": avg}

    # --- Permission operations ---

    def create_permission(
        self, request_id: str, session_id: str, tool_name: str,
        command: str = "", description: str = "", timeout_seconds: int = 300,
    ) -> str:
        self.conn.execute(
            """INSERT INTO permissions (id, session_id, tool_name, command, description, timeout_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (request_id, session_id, tool_name, command, description, timeout_seconds),
        )
        self.conn.commit()
        return request_id

    def get_permission(self, request_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM permissions WHERE id = ?", (request_id,)
        ).fetchone()

    def get_pending_permissions(self, session_id: str | None = None) -> list[sqlite3.Row]:
        if session_id:
            return self.conn.execute(
                "SELECT * FROM permissions WHERE status = 'pending' AND session_id = ? ORDER BY created_at",
                (session_id,),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM permissions WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()

    def respond_permission(self, request_id: str, approved: bool) -> bool:
        """Respond to a permission request. Returns True if found and updated."""
        response = "approved" if approved else "denied"
        cursor = self.conn.execute(
            "UPDATE permissions SET status = ?, response = ?, responded_at = ? WHERE id = ? AND status = 'pending'",
            (response, response, datetime.now().isoformat(), request_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def timeout_permissions(self) -> int:
        """Auto-deny permissions that exceeded their timeout. Returns count."""
        cursor = self.conn.execute(
            """UPDATE permissions SET status = 'denied', response = 'timeout',
               responded_at = ? WHERE status = 'pending'
               AND (julianday('now') - julianday(created_at)) * 86400 > timeout_seconds""",
            (datetime.now().isoformat(),),
        )
        self.conn.commit()
        return cursor.rowcount

    # --- Queue operations ---

    def get_queued_tasks(self, session_id: str) -> list[sqlite3.Row]:
        """Get queued tasks for a session, ordered by position."""
        return self.conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? AND status = 'queued' ORDER BY position",
            (session_id,),
        ).fetchall()

    def get_next_queue_position(self, session_id: str) -> int:
        """Get the next queue position for a session (1-indexed)."""
        result = self.conn.execute(
            "SELECT MAX(position) FROM tasks WHERE session_id = ? AND status = 'queued'",
            (session_id,),
        ).fetchone()
        max_pos = result[0] if result[0] is not None else 0
        return max_pos + 1

    def dequeue_next_task(self, session_id: str) -> sqlite3.Row | None:
        """Dequeue the next task (lowest position). Returns the task row or None."""
        task = self.conn.execute(
            "SELECT * FROM tasks WHERE session_id = ? AND status = 'queued' ORDER BY position LIMIT 1",
            (session_id,),
        ).fetchone()
        if not task:
            return None
        self.conn.execute(
            "UPDATE tasks SET status = 'pending', position = NULL WHERE id = ?",
            (task["id"],),
        )
        # Shift remaining positions down
        self.conn.execute(
            "UPDATE tasks SET position = position - 1 WHERE session_id = ? AND status = 'queued'",
            (session_id,),
        )
        self.conn.commit()
        return task

    def cancel_queued_task(self, task_id: int) -> bool:
        """Cancel a queued task. Returns True if cancelled, False if not queued."""
        task = self.get_task(task_id)
        if not task or task["status"] != "queued":
            return False

        session_id = task["session_id"]
        position = task["position"]

        self.conn.execute(
            "UPDATE tasks SET status = 'cancelled', position = NULL WHERE id = ?",
            (task_id,),
        )
        # Shift remaining positions down
        if position is not None:
            self.conn.execute(
                "UPDATE tasks SET position = position - 1 WHERE session_id = ? AND status = 'queued' AND position > ?",
                (session_id, position),
            )
        self.conn.commit()
        return True

    # --- Team operations ---

    def create_team(self, name: str, lead_agent: str, members: list[str]):
        """Create a team with a lead agent and member agents."""
        self.conn.execute(
            "INSERT INTO teams (name, lead_agent) VALUES (?, ?)",
            (name, lead_agent),
        )
        for member in members:
            self.conn.execute(
                "INSERT INTO team_members (team_name, agent_name) VALUES (?, ?)",
                (name, member),
            )
        self.conn.commit()

    def get_team(self, name: str) -> sqlite3.Row | None:
        """Get a team by name."""
        return self.conn.execute(
            "SELECT * FROM teams WHERE name = ?", (name,)
        ).fetchone()

    def get_team_members(self, team_name: str) -> list[str]:
        """Get member agent names for a team."""
        rows = self.conn.execute(
            "SELECT agent_name FROM team_members WHERE team_name = ? ORDER BY agent_name",
            (team_name,),
        ).fetchall()
        return [row["agent_name"] for row in rows]

    def list_teams(self) -> list[sqlite3.Row]:
        """List all teams."""
        return self.conn.execute(
            "SELECT * FROM teams ORDER BY created_at DESC"
        ).fetchall()

    def delete_team(self, name: str) -> bool:
        """Delete a team. Returns True if it existed."""
        cursor = self.conn.execute("DELETE FROM teams WHERE name = ?", (name,))
        self.conn.commit()
        return cursor.rowcount > 0

    # --- Sub-task operations ---

    def get_subtasks(self, parent_task_id: int) -> list[sqlite3.Row]:
        """Get all sub-tasks for a parent task."""
        return self.conn.execute(
            "SELECT * FROM tasks WHERE parent_task_id = ? ORDER BY id",
            (parent_task_id,),
        ).fetchall()

    # --- Notification operations ---

    def create_notification(
        self, task_id: int, channel: str, chat_id: str, message: str,
    ) -> int:
        """Create a pending notification."""
        cursor = self.conn.execute(
            "INSERT INTO notifications (task_id, channel, chat_id, message) VALUES (?, ?, ?, ?)",
            (task_id, channel, chat_id, message),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_notification(self, notification_id: int) -> sqlite3.Row | None:
        """Get a notification by ID."""
        return self.conn.execute(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,),
        ).fetchone()

    def get_pending_notifications(self) -> list[sqlite3.Row]:
        """Get all pending notifications."""
        return self.conn.execute(
            "SELECT * FROM notifications WHERE status = 'pending' ORDER BY created_at",
        ).fetchall()

    def mark_notification_sent(self, notification_id: int):
        """Mark a notification as sent."""
        self.conn.execute(
            "UPDATE notifications SET status = 'sent', sent_at = ? WHERE id = ?",
            (datetime.now().isoformat(), notification_id),
        )
        self.conn.commit()

    def mark_notification_failed(self, notification_id: int):
        """Mark a notification as failed."""
        self.conn.execute(
            "UPDATE notifications SET status = 'failed' WHERE id = ?",
            (notification_id,),
        )
        self.conn.commit()
