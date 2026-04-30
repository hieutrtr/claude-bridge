# Subprocess Architecture — Quick Reference

**TL;DR**: Spawn Claude Code CLI as subprocesses. Manage via async daemon. Communicate with Unix sockets + JSON.

---

## 1. Quick Answers

| Question | Answer | Evidence |
|----------|--------|----------|
| **Spawn as subprocess?** | ✅ Yes | `subprocess.Popen()` works perfectly |
| **Best IPC?** | Unix sockets | <1ms latency, simple |
| **Know when done?** | ✅ Yes | Exit code + IPC message + heartbeat |
| **Manage multiple children?** | ✅ Yes | Async event loop handles N workers |
| **Spawn programmatically?** | ✅ Yes | `claude --project --print -p "prompt"` |
| **Simple approach?** | MVP spawn | ~200 lines Python, validates concept |
| **Scalable approach?** | Daemon Tier 2 | ~600 lines, handles 2-5 concurrent tasks |
| **Production approach?** | Daemon Tier 3 | ~1000 lines, handles 10-100s concurrent |

---

## 2. Code Skeleton: MVP Spawn

```python
#!/usr/bin/env python3
"""MVP: Direct Claude Code spawn (no daemon)."""

import subprocess
import sys
from pathlib import Path

def spawn_and_execute(agent_name: str, project_path: str, task: str) -> dict:
    """Spawn Claude Code, send task, collect result."""

    # Build command
    cmd = [
        "claude",
        "--project", project_path,
        "--print",
        "--channels", "telegram",
        "-p", "You are a helpful assistant..."
    ]

    # Spawn process
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line buffered
    )

    # Send task
    try:
        stdout, stderr = proc.communicate(input=task, timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        return {"status": "timeout", "output": "Task exceeded 5 minutes"}

    # Check result
    return {
        "status": "success" if proc.returncode == 0 else "error",
        "output": stdout,
        "exit_code": proc.returncode,
        "stderr": stderr
    }

# Usage
result = spawn_and_execute(
    "coder-my-app",
    "/Users/hieutran/projects/my-app",
    "Fix the login bug"
)
print(result)
```

---

## 3. Code Skeleton: Daemon Tier 1 (Queue + IPC)

```python
#!/usr/bin/env python3
"""Daemon Tier 1: Queue + basic IPC."""

import asyncio
import json
import sqlite3
from pathlib import Path

# ============================================================================
# IPC: Unix Socket Server
# ============================================================================

class IPCServer:
    def __init__(self, socket_path: str = "/tmp/claude-bridge/daemon.sock"):
        self.socket_path = Path(socket_path)
        self.workers = {}

    async def start(self):
        """Start listening for worker connections."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)

        server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self.socket_path)
        )
        print(f"IPC server listening on {self.socket_path}")

        async with server:
            await server.serve_forever()

    async def _handle_connection(self, reader, writer):
        """Handle worker connection."""
        while True:
            line = await reader.readline()
            if not line:
                break

            msg = json.loads(line.decode().strip())
            print(f"Received: {msg['type']}")

            # Route to handler
            if msg["type"] == "task_complete":
                # Process completion
                pass

            writer.close()

# ============================================================================
# Task Queue: SQLite
# ============================================================================

class TaskQueue:
    def __init__(self, db_path: str = "~/.claude-bridge/task_queue.db"):
        self.db = sqlite3.connect(Path(db_path).expanduser(), check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        """Create tables if not exists."""
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS workers (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                pid INTEGER NOT NULL,
                state TEXT DEFAULT 'ready'
            );
        """)
        self.db.commit()

    def insert_task(self, task_id: str, agent_name: str, payload: str):
        """Add task to queue."""
        self.db.execute(
            "INSERT INTO tasks (id, agent_name, payload) VALUES (?, ?, ?)",
            (task_id, agent_name, payload)
        )
        self.db.commit()

    def get_pending_task(self):
        """Get next pending task."""
        cursor = self.db.execute(
            "SELECT * FROM tasks WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
        )
        return cursor.fetchone()

    def update_task(self, task_id: str, status: str):
        """Update task status."""
        self.db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
        self.db.commit()

# ============================================================================
# Worker Spawner
# ============================================================================

async def spawn_worker(agent_name: str, project_path: str) -> str:
    """Spawn a Claude Code process."""
    import uuid
    import subprocess

    worker_id = f"worker-{uuid.uuid4()}"

    env = {
        "BRIDGE_WORKER_ID": worker_id,
        "BRIDGE_CALLBACK_SOCKET": "/tmp/claude-bridge/daemon.sock"
    }

    cmd = [
        "claude",
        "--project", project_path,
        "--print",
        "-p", "You are a helpful assistant..."
    ]

    proc = subprocess.Popen(cmd, env=env)
    print(f"Spawned worker {worker_id} (PID {proc.pid})")

    return worker_id

# ============================================================================
# Main Daemon Loop
# ============================================================================

async def main():
    """Run daemon."""
    ipc = IPCServer()
    queue = TaskQueue()

    # Task dispatcher loop
    async def dispatch_tasks():
        while True:
            await asyncio.sleep(1)
            task = queue.get_pending_task()
            if task:
                task_id, agent_name, payload, _, _ = task
                worker_id = await spawn_worker(agent_name, "/tmp/test-project")
                queue.update_task(task_id, "assigned")

    # Start both
    await asyncio.gather(
        ipc.start(),
        dispatch_tasks()
    )

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. Code Skeleton: Daemon Tier 2 (Worker Pool)

```python
#!/usr/bin/env python3
"""Daemon Tier 2: Worker pool + health monitoring."""

import asyncio
import os
import signal
from enum import Enum

class WorkerState(Enum):
    IDLE = "idle"
    EXECUTING = "executing"
    DEAD = "dead"

class Worker:
    def __init__(self, worker_id: str, pid: int):
        self.id = worker_id
        self.pid = pid
        self.state = WorkerState.IDLE
        self.current_task = None

    async def send_task(self, task_id: str, payload: str):
        """Send task to worker."""
        self.state = WorkerState.EXECUTING
        self.current_task = task_id
        # IPC: send via Unix socket
        print(f"Sending {task_id} to {self.id}")

    async def is_alive(self) -> bool:
        """Check if worker process alive."""
        try:
            os.kill(self.pid, 0)  # Doesn't kill, just checks
            return True
        except ProcessLookupError:
            return False

class WorkerPool:
    def __init__(self, pool_size: int = 3):
        self.pool_size = pool_size
        self.workers: list[Worker] = []

    async def initialize(self):
        """Spawn idle workers at startup."""
        for i in range(self.pool_size):
            worker = await self._spawn_one()
            self.workers.append(worker)

    async def _spawn_one(self) -> Worker:
        """Spawn one worker."""
        import uuid
        import subprocess

        worker_id = f"worker-{uuid.uuid4()}"
        proc = subprocess.Popen(["claude", "--project", "/tmp/test-project"])
        return Worker(worker_id, proc.pid)

    async def get_available_worker(self) -> Worker | None:
        """Get idle worker, or None."""
        for worker in self.workers:
            if worker.state == WorkerState.IDLE:
                return worker
        return None

    async def dispatch_task(self, task_id: str, payload: str):
        """Dispatch task to available worker."""
        worker = await self.get_available_worker()
        if not worker:
            print("No workers available, queueing...")
            return False

        await worker.send_task(task_id, payload)
        return True

    async def health_check(self):
        """Periodically check worker health."""
        while True:
            await asyncio.sleep(10)

            dead_workers = []
            for worker in self.workers:
                if not await worker.is_alive():
                    dead_workers.append(worker)
                    worker.state = WorkerState.DEAD

            # Respawn dead workers
            for worker in dead_workers:
                self.workers.remove(worker)
                new_worker = await self._spawn_one()
                self.workers.append(new_worker)
                print(f"Respawned {worker.id}")

async def main():
    pool = WorkerPool(pool_size=3)
    await pool.initialize()

    # Start health check
    asyncio.create_task(pool.health_check())

    # Dispatch tasks as they arrive
    for task_id in ["task-001", "task-002", "task-003", "task-004"]:
        success = await pool.dispatch_task(task_id, f"Do {task_id}")
        if not success:
            print(f"Failed to dispatch {task_id}")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 5. IPC Message Cheat Sheet

### Spawn Worker
```json
← No message needed. Daemon spawns internally.
```

### Task Execution
```json
→ (Daemon → Worker)
{
  "type": "task",
  "id": "task-001",
  "payload": "Fix the login bug",
  "timeout_seconds": 300
}

← (Worker → Daemon)
{
  "type": "task_ack",
  "task_id": "task-001",
  "status": "started"
}

← (Worker → Daemon, periodic)
{
  "type": "progress",
  "task_id": "task-001",
  "output": "Analyzing code...\n"
}

← (Worker → Daemon, final)
{
  "type": "task_complete",
  "task_id": "task-001",
  "status": "success",
  "output": "Fixed!",
  "files_changed": ["src/auth.ts"]
}
```

### Permission Relay
```json
← (Worker → Daemon)
{
  "type": "permission_request",
  "id": "perm-xyz",
  "action": "bash",
  "pattern": "git push --force"
}

→ (Daemon → Worker, after user approves on Telegram)
{
  "type": "permission_response",
  "id": "perm-xyz",
  "approved": true
}
```

### Heartbeat
```json
→ (Daemon → Worker, every 10 seconds)
{
  "type": "heartbeat"
}

← (Worker → Daemon)
{
  "type": "heartbeat_ack"
}
```

---

## 6. File Locations Reference

```
/tmp/claude-bridge/
├── daemon.sock                    # Main daemon socket
├── worker-abc123.sock            # Worker 1 socket (if using HTTP instead)
└── ...

~/.claude-bridge/
├── task_queue.db                 # SQLite queue
├── daemon.log                    # Daemon logs
├── agents/
│   ├── coder-my-app/
│   │   ├── profile.yaml
│   │   ├── enhancement-accumulator.yaml
│   │   └── session.log
│   └── ...
└── sessions.yaml                 # Worker registry
```

---

## 7. Common Pitfalls & Fixes

| Problem | Fix |
|---------|-----|
| **Socket "Address already in use"** | `socket_path.unlink(missing_ok=True)` before creating |
| **Worker crashes silently** | Implement heartbeat timeout (detect death in <30 sec) |
| **Lost messages** | Use JSON Lines (newline-delimited), guarantee atomicity |
| **Worker hangs on permission** | Timeout to 5 minutes, fail safe (deny) |
| **tmux sessions leak** | Daemon startup: `tmux kill-server` or track session IDs |
| **High memory** | Limit worker pool size, kill old workers |
| **Worker respawn loop** | Add backoff (exponential), cap retry count |

---

## 8. MVP vs Production Comparison

| Aspect | MVP | Tier 2 | Tier 3 |
|--------|-----|--------|--------|
| **Lines of code** | ~200 | ~600 | ~1000 |
| **Task latency** | 2-3 sec | <1 sec | <100 ms |
| **Concurrent tasks** | 1 | 2-5 | 10-100 |
| **Worker management** | Manual | Auto respawn | Full monitoring |
| **Permission relay** | Blocking | Async | Non-blocking |
| **Complexity** | Simple | Moderate | High |
| **Ready for production?** | No | Maybe | Yes |

---

## 9. Deployment Checklist

### MVP Phase
- [ ] Can spawn `claude` via subprocess.Popen
- [ ] Can pipe stdin/stdout
- [ ] Can monitor exit code
- [ ] Can pass environment variables
- [ ] Integration with Telegram channel works

### Phase 1 (Add Queue)
- [ ] Daemon process starts cleanly
- [ ] SQLite queue creates tables
- [ ] Tasks enqueue and dequeue correctly
- [ ] Unix socket creates and listens
- [ ] Worker receives task via IPC

### Phase 1.5 (Add Pool)
- [ ] N workers spawn on startup
- [ ] Tasks dispatch to idle workers
- [ ] Dead workers auto-respawn
- [ ] Multiple concurrent tasks work
- [ ] No socket file leaks

### Phase 2 (Production)
- [ ] Comprehensive logging
- [ ] Graceful shutdown (all tasks saved)
- [ ] Memory monitoring + alerts
- [ ] High availability (daemon restart recovery)
- [ ] Full test coverage

---

## 10. Next Steps

1. **Validate MVP** (Weeks 1-2)
   - Spawn single Claude Code process
   - Execute task, collect output
   - Telegram integration

2. **Add daemon + queue** (Week 3)
   - Basic daemon skeleton
   - SQLite task queue
   - Worker spawner

3. **Add worker pool** (Week 4)
   - Idle workers at startup
   - Task dispatch to available worker
   - Health monitoring

4. **Production hardening** (Weeks 5-6)
   - Async I/O optimization
   - Graceful shutdown
   - Comprehensive testing
