"""SQLite database module for Claude Bridge.

Manages agents and tasks tables. Uses WAL mode for safe concurrent reads.
"""

import os
import sqlite3
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = os.path.expanduser("~/.claude-bridge/bridge.db")

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    reported INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_unreported ON tasks(status, reported)
    WHERE status IN ('done', 'failed', 'timeout') AND reported = 0;
"""


class BridgeDB:
    """SQLite database for agent and task tracking."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

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

    def create_task(self, session_id: str, prompt: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO tasks (session_id, prompt) VALUES (?, ?)",
            (session_id, prompt),
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

    def update_task(self, task_id: int, **kwargs):
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [task_id]
        self.conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", values)
        self.conn.commit()

    def mark_task_reported(self, task_id: int):
        self.conn.execute(
            "UPDATE tasks SET reported = 1 WHERE id = ?", (task_id,)
        )
        self.conn.commit()

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
