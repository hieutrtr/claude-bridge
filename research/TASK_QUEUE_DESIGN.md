# Task Queue Architecture for Claude Bridge

## Executive Summary

This document proposes a **Telegram MCP channel → Shared SQLite database → Multiple Claude Code sessions → Cron watchers** architecture for managing task queues in Claude Bridge. The goal is to enable:

1. **Single Telegram channel** writes tasks to a shared database
2. **Multiple Claude Code sessions** independently poll and execute tasks
3. **Task status tracking** (pending, running, completed, failed)
4. **Cron-based monitoring** for completion reporting and retries

This design prioritizes **simplicity + reliability** over absolute responsiveness for the MVP phase.

---

## 1. SQLite vs YAML for Task Queue

### Comparison Matrix

| Aspect | YAML Files | SQLite Database |
|--------|-----------|-----------------|
| **Locking/Concurrency** | File-level locks (fcntl), race conditions possible | ACID transactions, built-in locking |
| **Query Flexibility** | Grep/parse entire file | SQL queries (fast filtering) |
| **Transaction Safety** | Manual (complex) | Native (ACID guarantees) |
| **Performance (1000s tasks)** | Degradation (O(n) reads) | Optimized (indexed queries) |
| **Durability** | Good if fsync used | Excellent (WAL mode) |
| **Simplicity** | Very simple initially | Slightly more complex setup |
| **Multi-session safety** | ⚠️ High contention | ✅ Excellent isolation |
| **Atomic updates** | Manual/unreliable | ✅ Native transactions |
| **Recovery from crashes** | Good (human readable) | ✅ Excellent (journal recovery) |

### Recommendation: **SQLite with WAL mode**

**Why:**
1. **Concurrency safety**: Multiple sessions can safely poll/update simultaneously without file corruption
2. **Atomic operations**: Task status updates cannot partially complete
3. **Query efficiency**: Filtering by `status='pending' AND assigned_to IS NULL` is instant
4. **Built-in locking**: Reader-writer locks prevent simultaneous writes
5. **Mature**: Extensively tested for concurrent access (used in browsers, mobile OS)
6. **Light footprint**: Single file, no server process needed
7. **Easy recovery**: If process crashes, database auto-recovers with no manual intervention

**Trade-off:** Slightly more code than YAML, but pays off immediately with reliability.

### YAML Alternative (Not Recommended)

If using YAML for MVP speed:
- Use **file-level locks** via `fcntl.flock()` or `portalocker`
- Implement **pessimistic locking**: Sessions lock file before reading
- Accept **slower startup** (must reload entire task file each poll)
- High risk of **corruption** if process crashes mid-write

---

## 2. Database Schema

### Core Tables

```sql
-- Tasks written by Telegram channel
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,              -- UUID (task_20260326_abc123)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT NOT NULL,         -- Telegram user ID

    -- Task content
    description TEXT NOT NULL,        -- "Fix login bug"
    project_path TEXT NOT NULL,       -- ~/my-app (validated)
    agent_name TEXT NOT NULL,         -- coder-my-app (agent must exist)
    context TEXT,                     -- Additional context/files to include

    -- Dispatch state
    status TEXT DEFAULT 'pending',    -- pending | running | completed | failed | cancelled
    assigned_to TEXT,                 -- Session ID that picked this up (nullable)
    assigned_at TIMESTAMP,            -- When assigned
    started_at TIMESTAMP,             -- When session started working
    completed_at TIMESTAMP,

    -- Results
    output TEXT,                      -- Agent's output/summary
    files_changed TEXT,               -- JSON array of modified files
    error_message TEXT,               -- If failed, what went wrong
    exit_code INTEGER,                -- 0=success, 1+=error

    -- Metadata
    priority INTEGER DEFAULT 0,       -- Higher = execute first (future)
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,

    CONSTRAINT valid_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    CONSTRAINT agent_must_exist CHECK (agent_name IS NOT NULL),
    FOREIGN KEY (agent_name) REFERENCES agents(name) ON DELETE CASCADE
);

-- Sessions polling the database
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,              -- UUID or hostname-pid
    agent_name TEXT NOT NULL,         -- Which agent this session runs
    state TEXT DEFAULT 'idle',        -- idle | working | stopped
    last_heartbeat TIMESTAMP,         -- When last activity occurred
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    current_task_id TEXT,             -- Task currently being executed (nullable)

    FOREIGN KEY (agent_name) REFERENCES agents(name) ON DELETE CASCADE
);

-- Agents (spawned profiles)
CREATE TABLE agents (
    name TEXT PRIMARY KEY,            -- coder-my-app
    project_path TEXT NOT NULL,
    role TEXT,                        -- coder | researcher | reviewer | devops
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used TIMESTAMP,

    UNIQUE(project_path, role)        -- Can't have two agents for same project+role
);

-- Audit log (optional, for debugging)
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event TEXT,                       -- task_created | task_claimed | task_completed
    task_id TEXT,
    session_id TEXT,
    details TEXT,                     -- JSON for complex data

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE SET NULL
);

-- Indexes for query performance
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_agent ON tasks(agent_name, status);
CREATE INDEX idx_tasks_assigned ON tasks(assigned_to);
CREATE INDEX idx_sessions_agent ON sessions(agent_name);
CREATE INDEX idx_sessions_heartbeat ON sessions(last_heartbeat);
```

### WAL Mode Setup

```python
import sqlite3

def init_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety/speed
    conn.execute("PRAGMA busy_timeout=5000")   # Wait 5s if locked
    conn.execute("PRAGMA cache_size=-64000")   # 64MB cache

    # Create tables (schema above)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
```

---

## 3. Task Lifecycle & State Machine

```
┌─────────────────────────────────────────────────────────────┐
│                    Task State Diagram                        │
└─────────────────────────────────────────────────────────────┘

          [pending]
              ↓
    (Session polls, claims)
              ↓
          [running] ←─────────────────┐
              ↓                        │
       (Agent executes)               │
              ↓                        │
         ┌────┴─────┐                 │
         ↓          ↓                 │
    [completed]  [failed] ───────→ [retry] (if retry_count < max_retries)
                   ↓
         (Cron watches, reports)
         (Manual /cancel available)
              ↓
          [cancelled]
```

---

## 4. Polling Architecture

### Session Polling Loop

Each Claude Code session runs a **polling worker thread**:

```python
# In each Claude Code session spawned by Bridge

class TaskPoller:
    def __init__(self, agent_name: str, session_id: str, db_path: str):
        self.agent_name = agent_name
        self.session_id = session_id
        self.db_path = db_path
        self.poll_interval = 5  # seconds (configurable)
        self.running = True

    def start(self):
        """Start polling in background thread"""
        thread = Thread(target=self._poll_loop, daemon=True)
        thread.start()

    def _poll_loop(self):
        """Poll for tasks assigned to this agent"""
        while self.running:
            try:
                task = self._claim_pending_task()
                if task:
                    # Execute task synchronously
                    result = self._execute_task(task)
                    self._update_task_status(task.id, result)
                else:
                    # No tasks available, sleep
                    time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Poll error: {e}")
                time.sleep(self.poll_interval)

            # Update heartbeat
            self._update_heartbeat()

    def _claim_pending_task(self) -> Optional[Task]:
        """
        Atomically claim next pending task for this agent.

        SQL (single atomic transaction):
            BEGIN TRANSACTION;
            SELECT id FROM tasks
            WHERE status='pending' AND agent_name=?
            ORDER BY priority DESC, created_at ASC
            LIMIT 1;

            UPDATE tasks
            SET status='running', assigned_to=?, assigned_at=NOW()
            WHERE id=?;
            COMMIT;
        """
        conn = sqlite3.connect(self.db_path)
        conn.isolation_level = None  # Autocommit off, use transactions
        cursor = conn.cursor()

        try:
            cursor.execute("BEGIN IMMEDIATE")  # Exclusive lock

            # Get next task
            cursor.execute("""
                SELECT id, description, project_path, context
                FROM tasks
                WHERE status = 'pending' AND agent_name = ?
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            """, (self.agent_name,))

            row = cursor.fetchone()
            if not row:
                conn.commit()
                return None

            task_id = row[0]

            # Claim it atomically
            cursor.execute("""
                UPDATE tasks
                SET status = 'running',
                    assigned_to = ?,
                    assigned_at = CURRENT_TIMESTAMP,
                    started_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (self.session_id, task_id))

            conn.commit()

            # Fetch full task
            return self._load_task(task_id)

        except Exception as e:
            conn.rollback()
            logger.error(f"Claim error: {e}")
            return None
        finally:
            conn.close()

    def _execute_task(self, task: Task) -> TaskResult:
        """Run the actual task (via Claude Code)"""
        # This is where Claude Code agent does the work
        # Returns: (success: bool, output: str, files_changed: list, error: str)
        pass

    def _update_task_status(self, task_id: str, result: TaskResult):
        """Mark task as completed or failed"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE tasks
            SET status = ?,
                output = ?,
                files_changed = ?,
                error_message = ?,
                exit_code = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            'completed' if result.success else 'failed',
            result.output,
            json.dumps(result.files_changed),
            result.error or '',
            result.exit_code,
            task_id
        ))

        conn.commit()
        conn.close()

    def _update_heartbeat(self):
        """Tell DB this session is alive"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE sessions
            SET last_heartbeat = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (self.session_id,))
        conn.commit()
        conn.close()

    def stop(self):
        """Gracefully stop polling"""
        self.running = False
```

### Polling Interval Strategy

```
Poll Interval: 5 seconds (default, configurable)

Rationale:
- 1-2s: Too aggressive, wastes CPU on empty database
- 5s: Good balance — task appears in queue within 5s
- 30s: Acceptable, but less responsive
- >60s: Noticeable lag, not recommended

Configuration:
    # ~/.claude-bridge/config.yaml
    task_queue:
      poll_interval_seconds: 5
      busy_wait_multiplier: 1  # Poll faster if idle
      empty_queue_backoff: 30  # If no tasks for 30s, reduce polling
```

---

## 5. Ensuring Correct Session Picks Up Task

### Approach: Agent-Level Filtering

**Key constraint:** Each task specifies `agent_name` (e.g., "coder-my-app")

**Mechanism:**
1. **Telegram channel writes task** with `agent_name = "coder-my-app"`
2. **Only sessions running that agent** poll for it
3. **SQL WHERE clause** filters: `WHERE agent_name = ?`

```python
# Session A (running "coder-my-app")
# Query: SELECT ... WHERE agent_name = 'coder-my-app'
# ✅ Sees tasks for this agent

# Session B (running "researcher-my-app")
# Query: SELECT ... WHERE agent_name = 'researcher-my-app'
# ❌ Does NOT see tasks for coder-my-app
```

### Multiple Sessions for Same Agent (Parallel Execution)

If user spawns 2 sessions for the same agent:

```
Session A (coder-my-app, session_abc123)
Session B (coder-my-app, session_xyz789)

Both poll: WHERE agent_name='coder-my-app' AND status='pending'
```

**Race condition:** Both might try to claim the same task.

**Solution:** Use `IMMEDIATE` transaction mode:

```sql
BEGIN IMMEDIATE;  -- Exclusive lock acquired immediately
-- One session waits, the other claims the task
UPDATE tasks SET assigned_to=? WHERE id=? AND status='pending';
COMMIT;
```

**Result:**
- Session A claims task 1
- Session B claims task 2 (if available)
- If only 1 task, Session B waits or goes back to sleep

---

## 6. Preventing Duplicate Task Execution

### Atomic Claim-or-Nothing

The critical section:

```sql
BEGIN IMMEDIATE;

-- Check if still pending
SELECT status FROM tasks WHERE id = ?;

-- If pending, claim and lock
UPDATE tasks
SET status='running', assigned_to=?, assigned_at=NOW()
WHERE id = ? AND status='pending';

-- Verify update succeeded (check row count)
IF rows_affected == 0 THEN
    -- Another session already claimed it
    ROLLBACK;
    RETURN NULL;
ELSE
    COMMIT;
    RETURN task;
END IF;
```

**In Python with sqlite3:**

```python
cursor.execute("BEGIN IMMEDIATE")
cursor.execute("""
    UPDATE tasks
    SET status='running', assigned_to=?, assigned_at=CURRENT_TIMESTAMP
    WHERE id=? AND status='pending'
""", (session_id, task_id))

if cursor.rowcount == 0:
    # Task was already claimed by another session
    conn.rollback()
    return None

conn.commit()
```

### Why This Works

1. `BEGIN IMMEDIATE` acquires **exclusive lock** on entire database
2. Another session trying to claim **blocks** until lock released
3. Only one session's UPDATE succeeds (`rowcount > 0`)
4. Other sessions see `rowcount == 0` and know they lost the race

---

## 7. Can Claude Code CLI Monitor Task Queue?

### Short Answer: **Not directly via file watcher.**

Claude Code CLI doesn't have built-in task queue support. Two approaches:

#### Option A: **Wrapper Script (Recommended for MVP)**

```bash
#!/bin/bash
# claude-bridge-worker.sh

AGENT_NAME="$1"
DB_PATH="$HOME/.claude-bridge/tasks.db"

# Python task poller
python3 << 'EOF'
import sqlite3
import json
import time
import subprocess
import os

agent_name = os.environ['AGENT_NAME']
db_path = os.environ['DB_PATH']

def poll_and_execute():
    # (see TaskPoller class above)

poller = TaskPoller(agent_name, db_path)
poller.start()
EOF

# Keep running
wait
```

**Usage:**
```bash
$ claude --project ~/my-app &
$ ./claude-bridge-worker.sh coder-my-app &
```

#### Option B: **Separate Daemon Process**

Run a **single Bridge daemon** that:
1. Maintains database
2. Monitors Telegram channel
3. Spawns/manages Claude Code sessions as needed
4. Each session has built-in polling worker

This is the **recommended long-term architecture**.

---

## 8. Failure Scenarios & Recovery

### Scenario 1: Session Crashes Mid-Task

**State before crash:**
```
task.status = 'running'
task.assigned_to = 'session-abc'
task.started_at = 2026-03-26 10:15:00
```

**Recovery (via Cron watcher):**

```python
# Every 30 seconds, check for stale assignments
def recover_stale_tasks(db_path, stale_timeout_seconds=300):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Find tasks running too long (session crashed?)
    cursor.execute("""
        SELECT id, assigned_to, retry_count, max_retries
        FROM tasks
        WHERE status='running'
          AND datetime(started_at, '+' || ? || ' seconds') < datetime('now')
    """, (stale_timeout_seconds,))

    stale = cursor.fetchall()

    for task_id, session_id, retries, max_retries in stale:
        # Check if session still alive
        if not is_session_alive(db_path, session_id):
            if retries < max_retries:
                # Reset to pending, will be re-picked
                cursor.execute("""
                    UPDATE tasks
                    SET status='pending',
                        assigned_to=NULL,
                        retry_count=retry_count+1
                    WHERE id=?
                """, (task_id,))
            else:
                # Max retries exceeded
                cursor.execute("""
                    UPDATE tasks
                    SET status='failed',
                        error_message='Exceeded max retries after session crash'
                    WHERE id=?
                """, (task_id,))

    conn.commit()
    conn.close()
```

**Cron trigger:**
```
# ~/.claude-bridge/cron_config.yaml
watchers:
  - name: stale_task_recovery
    schedule: "*/1 * * * *"  # Every minute
    action: recover_stale_tasks
    timeout: 30
```

### Scenario 2: Database Locked (Contention)

**SQLite behavior:**
```
Session A: BEGIN IMMEDIATE (acquires lock)
Session B: BEGIN IMMEDIATE → BLOCKS
Session C: BEGIN IMMEDIATE → BLOCKS

[After Session A commits]
[One of B/C acquires lock, others wait]
```

**Timeout configuration prevents infinite hangs:**
```python
PRAGMA busy_timeout = 5000  # Wait 5 seconds
```

If timeout exceeded:
```python
try:
    cursor.execute("BEGIN IMMEDIATE")
except sqlite3.OperationalError as e:
    if "locked" in str(e):
        logger.warning("Database locked, backing off")
        time.sleep(random.uniform(1, 5))  # Exponential backoff
        return None  # Skip this poll cycle
```

### Scenario 3: Telegram Writes Invalid Task

**Validation in Telegram channel:**

```python
class TelegramChannel:
    async def create_task(self, description: str, agent_name: str):
        # Validate agent exists
        if not self._agent_exists(agent_name):
            await self.send_message("❌ Agent not found: " + agent_name)
            return

        # Validate project path
        profile = self._load_profile(agent_name)
        if not os.path.exists(profile.project_path):
            await self.send_message("❌ Project path invalid")
            return

        # Create task (DB will reject if agent FK constraint fails)
        try:
            self._create_task(agent_name, description)
            await self.send_message("✅ Task queued")
        except Exception as e:
            await self.send_message(f"❌ Error: {e}")
```

---

## 9. Pros/Cons: Polling vs Daemon Approach

### Polling (Proposed)

**Architecture:**
```
[Telegram] → [Write to SQLite]
[Session A] → [Poll SQLite] ← [Session B] ← [Session C]
[Cron] → [Monitor & report]
```

**Pros:**
- ✅ No IPC/sockets needed (very simple)
- ✅ Database provides all synchronization
- ✅ Stateless: sessions are interchangeable
- ✅ Easy to scale: spawn new sessions, they auto-poll
- ✅ Recovers gracefully from crashes
- ✅ SQLite handles all hard concurrency problems
- ✅ Built-in durability (WAL mode)
- ✅ Easy debugging (just query the database)

**Cons:**
- ❌ Not real-time (5-30s latency)
- ❌ Constant polling wakes up CPU
- ⚠️ Multiple sessions → redundant queries

**Latency Analysis:**
```
User sends task: T0
Telegram writes to DB: T0 + 0.1s
Next poll window: T0 + 0-5s
Task starts executing: T0 + 0.1 to 5.1s
Total: 5-5.1s latency (acceptable for MVP)
```

---

### Daemon Approach (Alternative)

**Architecture:**
```
[Telegram] → [Bridge Daemon] ← Direct IPC
              ↓       ↓       ↓
         [Session A][B][C]  (spawned by daemon)
```

**Pros:**
- ✅ Real-time notification (no polling)
- ✅ Single source of truth (daemon)
- ✅ Lower CPU (event-driven)
- ✅ Easier debugging (single log file)

**Cons:**
- ❌ Complex IPC (pipes, sockets, or pubsub)
- ❌ Daemon is single point of failure
- ❌ Sessions depend on daemon (can't poll independently)
- ❌ More state to manage (session lifecycle, socket handling)
- ❌ Requires event notification system (harder to implement)
- ❌ Debugging distributed state is harder

---

## 10. Failure Scenarios Matrix

| Scenario | SQLite Polling | Daemon IPC |
|----------|-----------|---------|
| **Session crashes** | ✅ Detected via heartbeat timeout | ⚠️ Daemon must detect disconnection |
| **DB locked/corrupted** | ✅ WAL recovery automatic | ⚠️ Daemon must detect & handle |
| **Telegram sends junk task** | ✅ DB constraint rejects | ✅ Daemon can validate |
| **Multiple sessions race** | ✅ SQL IMMEDIATE locks | ⚠️ Daemon must serialize |
| **Network outage** | ✅ Tasks queue, execute later | ❌ IPC broken, sessions hang |
| **Daemon crashes** | ❌ Orphaned session (but can poll) | ❌ All sessions blocked |
| **DB corruption** | ✅ WAL can recover | ❌ Daemon can't read state |
| **High load (100 tasks)** | ✅ DB scales, indexed queries | ⚠️ Daemon becomes bottleneck |

---

## 11. Recommended Configuration

```yaml
# ~/.claude-bridge/config.yaml

task_queue:
  db_path: "~/.claude-bridge/tasks.db"

  polling:
    interval_seconds: 5
    empty_queue_backoff_seconds: 30
    heartbeat_timeout_seconds: 300

  task_limits:
    max_retries: 3
    stale_timeout_seconds: 300
    max_concurrent_per_agent: 1  # Only 1 session per agent for MVP

  watchers:
    stale_task_recovery:
      enabled: true
      schedule: "*/1 * * * *"  # Every minute

    completion_reporter:
      enabled: true
      schedule: "*/5 * * * *"  # Every 5 minutes
      include: [summary, files_changed, duration]
```

---

## 12. Database Schema (SQL)

See **Section 2** above for full schema.

**Key constraints:**
```sql
-- Prevent duplicate agents
UNIQUE(project_path, role)

-- Prevent orphaned tasks
FOREIGN KEY (agent_name) REFERENCES agents(name) ON DELETE CASCADE
FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL

-- Prevent invalid status values
CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))
```

---

## 13. Pseudocode: Complete Flow

### Flow 1: User Creates Task via Telegram

```python
# In TelegramChannel.handle_message()
user_message = "Fix login bug in coder-my-app"

# Parse command
agent_name = extract_agent("coder-my-app")
description = extract_task("Fix login bug")

# Validate
if not self.agent_exists(agent_name):
    send_error("Agent not found")
    return

# Create task
task_id = generate_uuid()
conn = sqlite3.connect(DB_PATH)
conn.execute("""
    INSERT INTO tasks (id, agent_name, description, created_by, status)
    VALUES (?, ?, ?, ?, 'pending')
""", (task_id, agent_name, description, user_id))
conn.commit()

send_ack("✅ Task queued: " + task_id)
```

### Flow 2: Session Polls and Executes

```python
# TaskPoller._poll_loop() (runs every 5s in background thread)

while running:
    # Claim next task
    task = self._claim_pending_task()

    if task:
        logger.info(f"Claimed task {task.id}")

        # Execute via Claude Code
        result = subprocess.run([
            "claude",
            "--project", task.project_path,
            "-p", f"Execute: {task.description}"
        ], capture_output=True, timeout=600)  # 10 min timeout

        # Update status
        self._update_task_status(task.id, result)
        logger.info(f"Task {task.id} completed")

    else:
        # No tasks, sleep
        time.sleep(self.poll_interval)

    # Update heartbeat
    self._update_heartbeat()
```

### Flow 3: Cron Watches for Completion

```python
# Runs every 5 minutes
def report_completed_tasks(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, agent_name, output, completed_at
        FROM tasks
        WHERE status='completed' AND completed_at > datetime('now', '-5 minutes')
    """)

    for task_id, agent_name, output, completed_at in cursor.fetchall():
        # Send to Telegram
        telegram_channel.send_message(f"""
            ✅ Task {task_id} completed
            Agent: {agent_name}
            Output: {output[:500]}
        """)

        # Mark as reported
        cursor.execute("""
            UPDATE tasks SET reported_at=CURRENT_TIMESTAMP WHERE id=?
        """, (task_id,))

    conn.commit()
    conn.close()
```

---

## 14. Implementation Roadmap

### Phase 1: Foundation (Week 1)
- [ ] SQLite schema + init script
- [ ] TaskPoller class with atomic claiming
- [ ] Cron watcher for stale task recovery
- [ ] Basic Telegram integration to write tasks

### Phase 2: Integration (Week 2)
- [ ] Integrate TaskPoller into Claude Code session
- [ ] Cron reporter for task completion
- [ ] Heartbeat mechanism
- [ ] Manual `/cancel` command

### Phase 3: Robustness (Week 3)
- [ ] Exponential backoff for polling
- [ ] Retry logic with max_retries
- [ ] Error logging & audit trail
- [ ] Session health checks

### Phase 4: Advanced (Future)
- [ ] Priority queue (high/normal/low)
- [ ] Task dependencies (task A must complete before B)
- [ ] Scheduled tasks (at 3pm, every day)
- [ ] Task webhooks (notify external system when complete)

---

## 15. Success Criteria

- ✅ Multiple sessions can safely execute tasks concurrently
- ✅ No task is executed twice (atomic claiming)
- ✅ Crashed sessions don't orphan tasks (auto-recovery)
- ✅ Task appears in queue within 5s, starts within 10s
- ✅ Completion is reported back to user within 5 min
- ✅ Database doesn't corrupt under load (WAL + PRAGMA)
- ✅ Configuration is simple (one YAML file)
- ✅ Debugging is easy (just query the DB)

---

## 16. Comparison: SQLite Polling vs Redis Queue vs RabbitMQ

| Feature | SQLite Polling | Redis (BLPOP) | RabbitMQ |
|---------|-----------|-------|----------|
| **Setup complexity** | ⭐ Very simple | ⭐⭐ Medium | ⭐⭐⭐ Complex |
| **Dependencies** | None (stdlib) | Redis server | Erlang + RabbitMQ |
| **Real-time** | 5s latency | Instant | Instant |
| **Durability** | ✅ Excellent | ⚠️ Needs persistence config | ✅ Excellent |
| **Scaling to 1000s tasks** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Crash recovery** | ✅ Automatic (WAL) | ⚠️ Manual replay | ✅ Built-in |
| **Debugging** | ✅ SQL queries | ⚠️ CLI tools | ❌ Complex |
| **For MVP** | ✅ **Recommended** | ⚠️ Good alt | ❌ Overkill |

---

## 17. Final Recommendation

### Use SQLite + Polling for MVP

**Why:**
1. Single file, no external dependencies
2. ACID transactions solve concurrency automatically
3. 5-10s latency acceptable for task queue
4. Easier to debug than daemon IPC
5. Scales to 1000s of tasks efficiently
6. Graceful recovery from crashes

**When to upgrade:**
- Real-time dispatch required (→ Redis/daemon)
- 100+ concurrent sessions (→ professional queue)
- Complex task dependencies (→ specialized orchestrator)

### Code Structure

```python
# claude_bridge/task_queue/
├── database.py           # DB init, schema, connection pool
├── poller.py            # TaskPoller class (runs in each session)
├── telegram_adapter.py  # Write tasks from Telegram
├── watchers.py          # Cron jobs (recovery, reporting)
└── schema.sql           # Database schema
```

**Usage in Bridge:**

```python
# When spawning Claude Code session
session = spawn_claude_code(agent_name)

# Start polling worker
poller = TaskPoller(agent_name, session_id, db_path)
poller.start()  # Background thread
```

---

## References

- SQLite Transactions: https://www.sqlite.org/lang_transaction.html
- WAL Mode: https://www.sqlite.org/wal.html
- Concurrency: https://www.sqlite.org/appnote.html
- Busy Timeout: https://www.sqlite.org/pragma.html#pragma_busy_timeout
