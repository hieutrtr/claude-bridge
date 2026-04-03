"""Message queue database — inbound/outbound message persistence.

Separate from bridge.db to avoid write contention between
the Telegram poller thread and bridge operations.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone


def _utcnow() -> str:
    """UTC now as ISO string without timezone suffix (for SQLite comparison)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _utcnow_offset(seconds: int) -> str:
    """UTC now offset by seconds, as ISO string."""
    from datetime import timedelta
    t = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")

def _default_messages_db_path() -> str:
    """Compute default messages DB path respecting CLAUDE_BRIDGE_HOME env var."""
    from . import get_bridge_home
    return str(get_bridge_home() / "messages.db")


DEFAULT_MESSAGES_DB_PATH = None  # Use _default_messages_db_path() at runtime

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS inbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'telegram',
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT,
    message_text TEXT NOT NULL,
    message_id TEXT,
    status TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 5,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP,
    acknowledged_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outbound_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL DEFAULT 'telegram',
    chat_id TEXT NOT NULL,
    message_text TEXT NOT NULL,
    reply_to_message_id TEXT,
    source TEXT DEFAULT 'bot',
    status TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS poller_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_inbound_status ON inbound_messages(status);
CREATE INDEX IF NOT EXISTS idx_outbound_status ON outbound_messages(status);
"""


class MessageDB:
    """SQLite database for message queue."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = _default_messages_db_path()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # --- Inbound ---

    def create_inbound(
        self, platform: str, chat_id: str, user_id: str,
        message_text: str, message_id: str | None = None,
        username: str | None = None,
    ) -> int:
        """Create a pending inbound message."""
        cursor = self.conn.execute(
            "INSERT INTO inbound_messages (platform, chat_id, user_id, message_text, message_id, username) VALUES (?, ?, ?, ?, ?, ?)",
            (platform, chat_id, user_id, message_text, message_id, username),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_inbound(self, msg_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM inbound_messages WHERE id = ?", (msg_id,)
        ).fetchone()

    def get_pending_inbound(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM inbound_messages WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()

    def get_unacknowledged_inbound(self, timeout_seconds: int = 3) -> list[sqlite3.Row]:
        """Get delivered but unacknowledged messages past timeout."""
        cutoff = _utcnow_offset(-timeout_seconds)
        return self.conn.execute(
            """SELECT * FROM inbound_messages
               WHERE status = 'delivered'
               AND delivered_at IS NOT NULL
               AND delivered_at <= ?
               ORDER BY created_at""",
            (cutoff,),
        ).fetchall()

    def mark_inbound_delivered(self, msg_id: int):
        self.conn.execute(
            "UPDATE inbound_messages SET status = 'delivered', delivered_at = ? WHERE id = ?",
            (_utcnow(), msg_id),
        )
        self.conn.commit()

    def mark_inbound_acknowledged(self, msg_id: int):
        self.conn.execute(
            "UPDATE inbound_messages SET status = 'acknowledged', acknowledged_at = ? WHERE id = ?",
            (_utcnow(), msg_id),
        )
        self.conn.commit()

    def mark_inbound_failed(self, msg_id: int):
        self.conn.execute(
            "UPDATE inbound_messages SET status = 'failed' WHERE id = ?", (msg_id,),
        )
        self.conn.commit()

    def increment_inbound_retry(self, msg_id: int):
        """Increment retry count and reset to pending."""
        self.conn.execute(
            "UPDATE inbound_messages SET retry_count = retry_count + 1, status = 'pending', delivered_at = NULL WHERE id = ?",
            (msg_id,),
        )
        self.conn.commit()

    # --- Outbound ---

    def create_outbound(
        self, platform: str, chat_id: str, message_text: str,
        reply_to_message_id: str | None = None, source: str = "bot",
    ) -> int:
        """Create a pending outbound message."""
        cursor = self.conn.execute(
            "INSERT INTO outbound_messages (platform, chat_id, message_text, reply_to_message_id, source) VALUES (?, ?, ?, ?, ?)",
            (platform, chat_id, message_text, reply_to_message_id, source),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_outbound(self, msg_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM outbound_messages WHERE id = ?", (msg_id,)
        ).fetchone()

    def get_pending_outbound(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM outbound_messages WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()

    def mark_outbound_sent(self, msg_id: int):
        self.conn.execute(
            "UPDATE outbound_messages SET status = 'sent', sent_at = ? WHERE id = ?",
            (_utcnow(), msg_id),
        )
        self.conn.commit()

    def mark_outbound_failed(self, msg_id: int):
        self.conn.execute(
            "UPDATE outbound_messages SET status = 'failed' WHERE id = ?", (msg_id,),
        )
        self.conn.commit()

    def increment_outbound_retry(self, msg_id: int):
        self.conn.execute(
            "UPDATE outbound_messages SET retry_count = retry_count + 1 WHERE id = ?",
            (msg_id,),
        )
        self.conn.commit()

    # --- Poller State ---

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute(
            "SELECT value FROM poller_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO poller_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        self.conn.commit()
