# Task Queue Implementation Guide

Complete, production-ready code examples for SQLite task queue in Claude Bridge.

---

## 1. Database Initialization

### `database.py`

```python
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Tasks written by Telegram channel
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL,

    -- Task content
    description TEXT NOT NULL,
    project_path TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    context TEXT,

    -- Dispatch state
    status TEXT DEFAULT 'pending',
    assigned_to TEXT,
    assigned_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    reported_at TIMESTAMP,

    -- Results
    output TEXT,
    files_changed TEXT,
    error_message TEXT,
    exit_code INTEGER,

    -- Metadata
    priority INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    CONSTRAINT valid_status CHECK (status IN (
        'pending', 'running', 'completed', 'failed', 'cancelled'
    )),
    CONSTRAINT agent_must_exist CHECK (agent_name IS NOT NULL),
    FOREIGN KEY (agent_name) REFERENCES agents(name) ON DELETE CASCADE
);

-- Sessions polling the database
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    state TEXT DEFAULT 'idle',
    last_heartbeat TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    current_task_id TEXT,

    FOREIGN KEY (agent_name) REFERENCES agents(name) ON DELETE CASCADE
);

-- Agents (spawned profiles)
CREATE TABLE IF NOT EXISTS agents (
    name TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    role TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,

    UNIQUE(project_path, role)
);

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event TEXT,
    task_id TEXT,
    session_id TEXT,
    details TEXT,

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_name, status);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_name);
CREATE INDEX IF NOT EXISTS idx_sessions_heartbeat ON sessions(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id);
"""


class TaskQueueDB:
    """SQLite task queue database with connection pooling"""

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = Path(db_path).expanduser()
        self.pool_size = pool_size
        self._local = threading.local()
        self._init_db()

    def _init_db(self):
        """Initialize database with schema"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA cache_size=-64000")
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        conn.close()
        logger.info(f"Initialized task queue at {self.db_path}")

    @contextmanager
    def get_connection(self, isolation_level=None):
        """Get a database connection with proper settings"""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=5.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        conn.isolation_level = isolation_level
        try:
            yield conn
        finally:
            conn.close()

    def atomic_query(self, query: str, params: tuple = ()):
        """Execute query in atomic transaction (automatic commit)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.fetchall()

    def atomic_execute(self, query: str, params: tuple = ()):
        """Execute query with commit, return rowcount"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount

    def transaction(self, func):
        """Run function in transaction, rollback on exception"""
        with self.get_connection(isolation_level=None) as conn:
            try:
                result = func(conn)
                conn.commit()
                return result
            except Exception as e:
                conn.rollback()
                raise


def init_task_queue(db_path: str = "~/.claude-bridge/tasks.db") -> TaskQueueDB:
    """Initialize and return task queue database"""
    return TaskQueueDB(db_path)
```

---

## 2. Task Poller

### `poller.py`

```python
import sqlite3
import json
import logging
import time
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
import subprocess
import os

logger = logging.getLogger(__name__)


@dataclass
class Task:
    id: str
    agent_name: str
    description: str
    project_path: str
    context: Optional[str] = None
    priority: int = 0


@dataclass
class TaskResult:
    success: bool
    output: str
    files_changed: list
    error: Optional[str] = None
    exit_code: int = 0


class TaskPoller:
    """Poll task queue and execute tasks for a specific agent"""

    def __init__(
        self,
        db_path: str,
        agent_name: str,
        session_id: str,
        poll_interval: int = 5,
        task_timeout: int = 600
    ):
        self.db_path = db_path
        self.agent_name = agent_name
        self.session_id = session_id
        self.poll_interval = poll_interval
        self.task_timeout = task_timeout
        self.running = False
        self._thread = None
        self._last_successful_poll = time.time()

    def start(self):
        """Start polling in background thread"""
        if self.running:
            logger.warning(f"Poller for {self.agent_name} already running")
            return

        self.running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name=f"TaskPoller-{self.agent_name}",
            daemon=True
        )
        self._thread.start()
        logger.info(f"Started task poller for {self.agent_name}")

    def stop(self):
        """Stop polling gracefully"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info(f"Stopped task poller for {self.agent_name}")

    def _poll_loop(self):
        """Main polling loop"""
        while self.running:
            try:
                task = self._claim_pending_task()

                if task:
                    logger.info(f"Claimed task {task.id}")
                    self._last_successful_poll = time.time()

                    # Execute task
                    result = self._execute_task(task)
                    logger.info(
                        f"Task {task.id} completed with status: "
                        f"{'success' if result.success else 'failed'}"
                    )

                    # Update database
                    self._update_task_status(task.id, result)

                else:
                    # No tasks, sleep longer
                    time.sleep(self.poll_interval)

                # Update heartbeat
                self._update_heartbeat()

            except Exception as e:
                logger.error(f"Error in poll loop: {e}", exc_info=True)
                time.sleep(self.poll_interval)

    def _claim_pending_task(self) -> Optional[Task]:
        """Atomically claim next pending task for this agent"""
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Acquire exclusive lock immediately
            cursor.execute("BEGIN IMMEDIATE")

            # Get next highest-priority pending task
            cursor.execute("""
                SELECT id, description, project_path, context, priority
                FROM tasks
                WHERE status = 'pending' AND agent_name = ?
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            """, (self.agent_name,))

            row = cursor.fetchone()
            if not row:
                conn.commit()
                return None

            task_id = row["id"]

            # Claim it atomically
            cursor.execute("""
                UPDATE tasks
                SET status = 'running',
                    assigned_to = ?,
                    assigned_at = CURRENT_TIMESTAMP,
                    started_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (self.session_id, task_id))

            if cursor.rowcount == 0:
                # Another session claimed it first
                conn.commit()
                return None

            conn.commit()

            # Build Task object
            return Task(
                id=row["id"],
                agent_name=self.agent_name,
                description=row["description"],
                project_path=row["project_path"],
                context=row["context"],
                priority=row["priority"]
            )

        except Exception as e:
            conn.rollback()
            logger.error(f"Error claiming task: {e}")
            return None
        finally:
            conn.close()

    def _execute_task(self, task: Task) -> TaskResult:
        """Execute task using Claude Code"""
        try:
            # Build prompt from task description and context
            system_prompt = f"Execute the following task:\n{task.description}"
            if task.context:
                system_prompt += f"\n\nContext:\n{task.context}"

            # Spawn Claude Code process
            result = subprocess.run(
                [
                    "claude",
                    "--project", task.project_path,
                    "--print",
                    "-p", system_prompt
                ],
                capture_output=True,
                text=True,
                timeout=self.task_timeout
            )

            return TaskResult(
                success=result.returncode == 0,
                output=result.stdout[:5000],  # Truncate large outputs
                files_changed=[],  # TODO: parse from output
                error=result.stderr[:500] if result.stderr else None,
                exit_code=result.returncode
            )

        except subprocess.TimeoutExpired:
            return TaskResult(
                success=False,
                output="",
                files_changed=[],
                error=f"Task timeout after {self.task_timeout}s",
                exit_code=124
            )
        except Exception as e:
            return TaskResult(
                success=False,
                output="",
                files_changed=[],
                error=str(e),
                exit_code=1
            )

    def _update_task_status(self, task_id: str, result: TaskResult):
        """Update task in database with result"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        status = 'completed' if result.success else 'failed'

        cursor.execute("""
            UPDATE tasks
            SET status = ?,
                output = ?,
                error_message = ?,
                exit_code = ?,
                completed_at = CURRENT_TIMESTAMP,
                files_changed = ?
            WHERE id = ?
        """, (
            status,
            result.output,
            result.error or '',
            result.exit_code,
            json.dumps(result.files_changed),
            task_id
        ))

        conn.commit()
        conn.close()

    def _update_heartbeat(self):
        """Update session heartbeat"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE sessions
            SET last_heartbeat = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (self.session_id,))
        conn.commit()
        conn.close()
```

---

## 3. Cron Watchers

### `watchers.py`

```python
import sqlite3
import logging
from datetime import datetime, timedelta
import json

logger = logging.getLogger(__name__)


class StaleTaskRecovery:
    """Monitor for stale (crashed) tasks and reset them to pending"""

    def __init__(self, db_path: str, stale_timeout: int = 300):
        self.db_path = db_path
        self.stale_timeout = stale_timeout

    def check_and_recover(self) -> dict:
        """
        Find tasks that have been running too long (session crashed).
        Return statistics.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Find stale running tasks
        cutoff = datetime.utcnow() - timedelta(seconds=self.stale_timeout)

        cursor.execute("""
            SELECT id, assigned_to, retry_count, max_retries
            FROM tasks
            WHERE status = 'running'
              AND started_at < ?
        """, (cutoff.isoformat(),))

        stale_tasks = cursor.fetchall()
        recovered = 0
        max_retries_exceeded = 0

        for task_id, session_id, retry_count, max_retries in stale_tasks:
            # Check if session still exists and is alive
            cursor.execute("""
                SELECT last_heartbeat FROM sessions WHERE id = ?
            """, (session_id,))

            session_row = cursor.fetchone()

            if not session_row:
                # Session doesn't exist
                is_alive = False
            else:
                # Check if heartbeat is recent
                last_beat = session_row[0]
                last_beat_dt = datetime.fromisoformat(last_beat)
                is_alive = (datetime.utcnow() - last_beat_dt).seconds < 30

            if not is_alive:
                if retry_count < max_retries:
                    # Reset to pending for retry
                    cursor.execute("""
                        UPDATE tasks
                        SET status = 'pending',
                            assigned_to = NULL,
                            assigned_at = NULL,
                            retry_count = retry_count + 1
                        WHERE id = ?
                    """, (task_id,))
                    recovered += 1
                    logger.info(f"Recovered task {task_id} (retry {retry_count + 1}/{max_retries})")

                else:
                    # Max retries exceeded
                    cursor.execute("""
                        UPDATE tasks
                        SET status = 'failed',
                            error_message = 'Exceeded max retries after session crash'
                        WHERE id = ?
                    """, (task_id,))
                    max_retries_exceeded += 1
                    logger.warning(f"Task {task_id} max retries exceeded")

        conn.commit()
        conn.close()

        return {
            'checked': len(stale_tasks),
            'recovered': recovered,
            'max_retries_exceeded': max_retries_exceeded
        }


class CompletionReporter:
    """Monitor for completed tasks and report results"""

    def __init__(self, db_path: str, telegram_channel=None):
        self.db_path = db_path
        self.telegram_channel = telegram_channel

    def report_completed(self, minutes_back: int = 5) -> dict:
        """
        Find recently completed tasks and report them.
        Return statistics.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cutoff = datetime.utcnow() - timedelta(minutes=minutes_back)

        cursor.execute("""
            SELECT id, agent_name, description, output, completed_at, exit_code
            FROM tasks
            WHERE status IN ('completed', 'failed')
              AND completed_at > ?
              AND reported_at IS NULL
            ORDER BY completed_at DESC
        """, (cutoff.isoformat(),))

        tasks = cursor.fetchall()
        reported = 0

        for task in tasks:
            message = self._format_message(task)

            if self.telegram_channel:
                try:
                    self.telegram_channel.send_message(message)
                except Exception as e:
                    logger.error(f"Failed to send Telegram message: {e}")
                    continue

            # Mark as reported
            cursor.execute("""
                UPDATE tasks SET reported_at = CURRENT_TIMESTAMP WHERE id = ?
            """, (task['id'],))

            reported += 1
            logger.info(f"Reported task {task['id']}")

        conn.commit()
        conn.close()

        return {'reported': reported, 'total': len(tasks)}

    def _format_message(self, task) -> str:
        """Format task result as message"""
        status_emoji = "✅" if task['exit_code'] == 0 else "❌"

        message = f"{status_emoji} **Task {task['id'][:8]}** completed\n"
        message += f"Agent: `{task['agent_name']}`\n"
        message += f"Task: {task['description'][:100]}\n"

        if task['output']:
            output_preview = task['output'][:300]
            if len(task['output']) > 300:
                output_preview += "..."
            message += f"\nOutput:\n```\n{output_preview}\n```\n"

        return message


class SessionHealthMonitor:
    """Monitor for dead sessions and clean them up"""

    def __init__(self, db_path: str, heartbeat_timeout: int = 300):
        self.db_path = db_path
        self.heartbeat_timeout = heartbeat_timeout

    def cleanup_dead_sessions(self) -> dict:
        """Remove sessions that haven't had heartbeat"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cutoff = datetime.utcnow() - timedelta(seconds=self.heartbeat_timeout)

        cursor.execute("""
            SELECT id, agent_name FROM sessions
            WHERE last_heartbeat < ?
        """, (cutoff.isoformat(),))

        dead_sessions = cursor.fetchall()
        removed = 0

        for session_id, agent_name in dead_sessions:
            cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            removed += 1
            logger.warning(f"Removed dead session {session_id} ({agent_name})")

        conn.commit()
        conn.close()

        return {'removed': removed, 'total': len(dead_sessions)}
```

---

## 4. Telegram Integration

### `telegram_adapter.py`

```python
import sqlite3
import uuid
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class TelegramTaskCreator:
    """Create tasks from Telegram messages"""

    def __init__(self, db_path: str, profile_manager):
        self.db_path = db_path
        self.profile_manager = profile_manager

    def create_task_from_message(
        self,
        user_id: str,
        agent_name: str,
        description: str,
        context: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Create task from user message.

        Returns: (success, message_to_user)
        """
        # Validate agent exists
        try:
            profile = self.profile_manager.load(agent_name)
        except FileNotFoundError:
            return False, f"❌ Agent '{agent_name}' not found. Use /list to see available agents."

        # Validate project path exists
        import os
        if not os.path.exists(profile.identity.project):
            return False, f"❌ Project path {profile.identity.project} not found."

        # Create task in database
        task_id = f"task_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Register task
            cursor.execute("""
                INSERT INTO tasks (
                    id, created_by, agent_name, description,
                    project_path, context, status, priority
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0)
            """, (
                task_id,
                user_id,
                agent_name,
                description,
                profile.identity.project,
                context or ''
            ))

            conn.commit()
            conn.close()

            logger.info(f"Created task {task_id} for agent {agent_name}")
            return True, f"✅ Task queued (ID: {task_id[:12]})"

        except Exception as e:
            logger.error(f"Failed to create task: {e}")
            return False, f"❌ Error: {str(e)}"

    def cancel_task(self, task_id: str) -> tuple[bool, str]:
        """Cancel a pending or running task"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT status FROM tasks WHERE id = ?
        """, (task_id,))

        row = cursor.fetchone()
        if not row:
            return False, f"❌ Task {task_id} not found"

        status = row[0]
        if status not in ('pending', 'running'):
            return False, f"❌ Can only cancel pending/running tasks (current: {status})"

        cursor.execute("""
            UPDATE tasks SET status = 'cancelled' WHERE id = ?
        """, (task_id,))

        conn.commit()
        conn.close()

        logger.info(f"Cancelled task {task_id}")
        return True, f"✅ Task {task_id[:12]} cancelled"
```

---

## 5. Cron Job Setup

### `cron_schedule.py`

```python
import logging
import threading
import time
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    name: str
    interval_seconds: int
    func: callable
    enabled: bool = True


class CronScheduler:
    """Simple cron-like scheduler for background jobs"""

    def __init__(self):
        self.jobs = []
        self._thread = None
        self.running = False

    def add_job(self, name: str, interval: int, func: callable):
        """Add a job to run every interval seconds"""
        self.jobs.append(CronJob(name, interval, func))
        logger.info(f"Registered cron job: {name} (every {interval}s)")

    def start(self):
        """Start scheduler in background thread"""
        if self.running:
            return

        self.running = True
        self._thread = threading.Thread(
            target=self._schedule_loop,
            name="CronScheduler",
            daemon=True
        )
        self._thread.start()
        logger.info("Started cron scheduler")

    def stop(self):
        """Stop scheduler"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Stopped cron scheduler")

    def _schedule_loop(self):
        """Main scheduler loop"""
        last_run = {job.name: datetime.utcnow() for job in self.jobs}

        while self.running:
            now = datetime.utcnow()

            for job in self.jobs:
                if not job.enabled:
                    continue

                if (now - last_run[job.name]).seconds >= job.interval_seconds:
                    try:
                        logger.debug(f"Running job: {job.name}")
                        job.func()
                        last_run[job.name] = now
                    except Exception as e:
                        logger.error(f"Job {job.name} failed: {e}", exc_info=True)

            time.sleep(1)  # Check every second


def setup_default_watchers(scheduler: CronScheduler, db_path: str):
    """Setup default cron jobs"""
    from watchers import StaleTaskRecovery, CompletionReporter, SessionHealthMonitor

    recovery = StaleTaskRecovery(db_path)
    reporter = CompletionReporter(db_path)
    monitor = SessionHealthMonitor(db_path)

    scheduler.add_job(
        "stale_task_recovery",
        interval=60,  # Every minute
        func=lambda: recovery.check_and_recover()
    )

    scheduler.add_job(
        "completion_reporter",
        interval=300,  # Every 5 minutes
        func=lambda: reporter.report_completed()
    )

    scheduler.add_job(
        "session_health",
        interval=300,  # Every 5 minutes
        func=lambda: monitor.cleanup_dead_sessions()
    )

    logger.info("Initialized default cron watchers")
```

---

## 6. Complete Integration Example

### `main.py` (Bridge daemon sketch)

```python
import logging
import sys
from pathlib import Path

from database import init_task_queue
from poller import TaskPoller
from cron_schedule import CronScheduler, setup_default_watchers
from telegram_adapter import TelegramTaskCreator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    # Initialize
    db_path = Path.home() / ".claude-bridge" / "tasks.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = init_task_queue(str(db_path))
    logger.info("Initialized task queue database")

    # Start cron scheduler
    scheduler = CronScheduler()
    setup_default_watchers(scheduler, str(db_path))
    scheduler.start()

    # Register agent and start polling
    agent_name = "coder-my-app"
    session_id = "session-abc123"

    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO sessions (id, agent_name, state)
        VALUES (?, ?, 'idle')
    """, (session_id, agent_name))
    conn.commit()
    conn.close()

    # Start task poller (runs in background)
    poller = TaskPoller(str(db_path), agent_name, session_id)
    poller.start()

    logger.info("Bridge daemon started. Use Telegram to queue tasks.")
    logger.info("Press Ctrl+C to stop.")

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        poller.stop()
        scheduler.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
```

---

## 7. Configuration File

### `~/.claude-bridge/config.yaml`

```yaml
# Task Queue Configuration
task_queue:
  db_path: "~/.claude-bridge/tasks.db"

  # Polling settings
  polling:
    interval_seconds: 5
    empty_queue_backoff_seconds: 30
    heartbeat_timeout_seconds: 300

  # Task settings
  task_limits:
    max_retries: 3
    stale_timeout_seconds: 300
    max_concurrent_per_agent: 1
    task_timeout_seconds: 600

  # Watchers (cron jobs)
  watchers:
    stale_task_recovery:
      enabled: true
      interval_seconds: 60

    completion_reporter:
      enabled: true
      interval_seconds: 300
      report_to_telegram: true

    session_health:
      enabled: true
      interval_seconds: 300

# Telegram
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  admin_users: [123456789]
  allowed_users: [123456789, 987654321]
  poll_interval_seconds: 2

# Logging
logging:
  level: INFO
  file: "~/.claude-bridge/logs/bridge.log"
  max_size_mb: 100
  backup_count: 5
```

---

## 8. Testing

### `test_task_queue.py`

```python
import unittest
import sqlite3
import tempfile
from pathlib import Path

from database import init_task_queue
from poller import TaskPoller


class TestTaskQueue(unittest.TestCase):

    def setUp(self):
        """Create temporary database for each test"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test.db")
        self.db = init_task_queue(self.db_path)

    def tearDown(self):
        """Clean up"""
        self.temp_dir.cleanup()

    def test_create_task(self):
        """Test creating a task"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Insert agent first
        cursor.execute("""
            INSERT INTO agents (name, project_path) VALUES (?, ?)
        """, ("test-agent", "/tmp/project"))

        # Insert task
        cursor.execute("""
            INSERT INTO tasks (
                id, agent_name, description, project_path, created_by
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            "task_001",
            "test-agent",
            "Test task",
            "/tmp/project",
            "user_123"
        ))

        conn.commit()
        conn.close()

        # Verify
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tasks")
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 1)

    def test_claim_task_atomically(self):
        """Test atomic task claiming"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        # Setup
        cursor.execute("INSERT INTO agents (name, project_path) VALUES (?, ?)",
                      ("agent1", "/tmp"))
        cursor.execute("INSERT INTO sessions (id, agent_name) VALUES (?, ?)",
                      ("session1", "agent1"))
        cursor.execute("""
            INSERT INTO tasks (
                id, agent_name, description, project_path, created_by, status
            ) VALUES (?, ?, ?, ?, ?, 'pending')
        """, ("task1", "agent1", "Test", "/tmp", "user1"))

        conn.commit()
        conn.close()

        # Claim task
        poller = TaskPoller(self.db_path, "agent1", "session1")
        task = poller._claim_pending_task()

        self.assertIsNotNone(task)
        self.assertEqual(task.id, "task1")

        # Verify status updated
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, assigned_to FROM tasks WHERE id = ?",
                      ("task1",))
        status, assigned = cursor.fetchone()
        conn.close()

        self.assertEqual(status, "running")
        self.assertEqual(assigned, "session1")

    def test_no_duplicate_claim(self):
        """Test that second session can't claim already-claimed task"""
        # ... (similar setup)
        pass


if __name__ == "__main__":
    unittest.main()
```

---

## 9. Deployment Checklist

- [ ] Create `~/.claude-bridge/tasks.db` with proper schema
- [ ] Set `PRAGMA journal_mode=WAL` for crash safety
- [ ] Start TaskPoller in each Claude Code session
- [ ] Start CronScheduler for background jobs
- [ ] Configure Telegram channel to write tasks
- [ ] Test atomic claiming (two sessions simultaneously)
- [ ] Test failure recovery (kill session mid-task)
- [ ] Test completion reporting
- [ ] Monitor database size (WAL growth)
- [ ] Setup log rotation

---

## 10. Monitoring & Debugging

### Check Queue Status

```python
def show_queue_status(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("\n=== TASK QUEUE STATUS ===\n")

    # Pending tasks
    cursor.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status='pending'")
    print(f"Pending: {cursor.fetchone()['cnt']}")

    # Running tasks
    cursor.execute("""
        SELECT id, assigned_to, agent_name, started_at
        FROM tasks WHERE status='running'
    """)
    for row in cursor.fetchall():
        print(f"  Running: {row['id']} ({row['agent_name']}) → {row['assigned_to']}")

    # Sessions
    cursor.execute("""
        SELECT id, agent_name, last_heartbeat
        FROM sessions ORDER BY agent_name
    """)
    print(f"\nActive Sessions:")
    for row in cursor.fetchall():
        print(f"  {row['id'][:16]}... ({row['agent_name']})")

    # Failed tasks
    cursor.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status='failed'")
    print(f"\nFailed: {cursor.fetchone()['cnt']}")

    conn.close()
```

### Query Task History

```sql
-- Find all tasks for an agent
SELECT id, status, created_at, completed_at
FROM tasks
WHERE agent_name = 'coder-my-app'
ORDER BY created_at DESC;

-- Find longest-running tasks
SELECT id, agent_name, started_at,
       CAST((julianday('now') - julianday(started_at)) * 86400 AS INTEGER) as seconds_running
FROM tasks
WHERE status='running'
ORDER BY seconds_running DESC;

-- Find tasks that failed
SELECT id, agent_name, error_message, retry_count
FROM tasks
WHERE status='failed'
ORDER BY completed_at DESC;
```

