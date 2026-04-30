# Claude Bridge Daemon — Implementation Guide

**Companion to**: `daemon-architecture.md`
**Scope**: Detailed code samples, IPC patterns, and testing strategies

---

## 1. IPC Protocol Specification

### Message Format: JSON Lines

**Why JSON Lines?**
- Line-based: `\n` delimiters → easy to parse in any language
- No fixed-size frames → flexible payload sizes
- Human-readable: can tail/debug logs easily

```
# Client → Server (socket send)
{"type": "task", "id": "task-001", "payload": {...}}

# Server → Client (socket send back)
{"type": "task_response", "status": "ack"}
```

### Message Types

#### 1. Connection Handshake

**Worker connects to daemon:**
```json
{
  "type": "connect",
  "worker_id": "worker-abc123",
  "agent_name": "coder-my-app",
  "project_path": "/Users/hieutran/projects/my-app",
  "pid": 1234
}
```

**Daemon responds:**
```json
{
  "type": "connected",
  "daemon_version": "0.1.0",
  "session_id": "session-def456"
}
```

#### 2. Task Delivery

**Daemon → Worker:**
```json
{
  "type": "task",
  "id": "task-001",
  "agent_name": "coder-my-app",
  "payload": "Fix the login bug",
  "profile": {...profile_yaml...},
  "claude_md": "# Agent: ...",
  "timeout_seconds": 300
}
```

**Worker acknowledges:**
```json
{
  "type": "task_ack",
  "task_id": "task-001",
  "status": "started"
}
```

#### 3. Progress Updates

**Worker → Daemon (periodic):**
```json
{
  "type": "progress",
  "task_id": "task-001",
  "output": "Analyzing auth module...\n",
  "timestamp": "2026-03-26T10:15:05Z"
}
```

**Daemon stores in logs, relays to Telegram (async).**

#### 4. Permission Request

**Worker → Daemon (blocking):**
```json
{
  "type": "permission_request",
  "id": "perm-xyz",
  "task_id": "task-001",
  "action": "bash",
  "pattern": "git push --force",
  "file_preview": null,
  "risk_level": "high"
}
```

**Daemon → Telegram (async):**
- Sends formatted message with [✅ Approve] [❌ Deny] buttons

**Telegram user taps button → Daemon sends response:**
```json
{
  "type": "permission_response",
  "id": "perm-xyz",
  "approved": false,
  "reason": "user_denied"
}
```

**Daemon → Worker (response on same socket, unblocks):**
```json
{
  "type": "permission_response",
  "id": "perm-xyz",
  "approved": false
}
```

#### 5. Task Completion

**Worker → Daemon:**
```json
{
  "type": "task_complete",
  "task_id": "task-001",
  "status": "success",
  "output": "Fixed login bug. Files changed:\n- src/auth/session.ts",
  "files_changed": ["src/auth/session.ts"],
  "signals": [
    {
      "type": "user_corrected",
      "content": "Agent tried Joi first, user suggested Zod",
      "confidence": "high"
    }
  ],
  "duration_seconds": 45.3
}
```

**Daemon processes:**
- Log signals → enhancement-accumulator.yaml
- Send summary to Telegram
- Check enhancement threshold
- Update task queue

#### 6. Heartbeat

**Daemon → Worker (every 10 seconds):**
```json
{
  "type": "heartbeat",
  "daemon_version": "0.1.0"
}
```

**Worker responds:**
```json
{
  "type": "heartbeat_ack",
  "worker_id": "worker-abc123",
  "status": "alive"
}
```

---

## 2. Socket Communication Implementation

### Daemon IPC Server

```python
# daemon/ipc_server.py
import socket
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, Callable

logger = logging.getLogger(__name__)

class IPCServer:
    """Unix socket server for daemon ↔ worker communication."""

    def __init__(self, socket_dir: str = "/tmp/claude-bridge"):
        self.socket_dir = Path(socket_dir)
        self.socket_dir.mkdir(parents=True, exist_ok=True)
        self.server_socket_path = self.socket_dir / "daemon.sock"
        self.workers: Dict[str, asyncio.StreamReaderProtocol] = {}
        self.handlers = {}  # {msg_type: handler_func}

    def register_handler(self, msg_type: str, handler: Callable):
        """Register a message handler."""
        self.handlers[msg_type] = handler

    async def start(self):
        """Start listening for worker connections."""
        # Remove stale socket
        self.server_socket_path.unlink(missing_ok=True)

        # Create server
        server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(self.server_socket_path),
        )

        logger.info(f"IPC server listening on {self.server_socket_path}")

        async with server:
            await server.serve_forever()

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter):
        """Handle new worker connection."""
        client_addr = writer.get_extra_info('peername')
        logger.debug(f"New connection from {client_addr}")

        try:
            while True:
                # Read line (JSON message)
                line = await reader.readline()
                if not line:
                    # Connection closed
                    break

                # Parse JSON
                try:
                    msg = json.loads(line.decode().strip())
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from {client_addr}: {e}")
                    continue

                # Route to handler
                msg_type = msg.get("type")
                if msg_type in self.handlers:
                    response = await self.handlers[msg_type](msg, writer)
                    if response:
                        self._send_message(writer, response)
                else:
                    logger.warning(f"Unknown message type: {msg_type}")

        except asyncio.CancelledError:
            logger.debug(f"Connection closed: {client_addr}")
        finally:
            writer.close()
            await writer.wait_closed()

    def _send_message(self, writer: asyncio.StreamWriter, msg: dict):
        """Send JSON message to worker."""
        json_str = json.dumps(msg)
        writer.write((json_str + "\n").encode())

    async def send_to_worker(self, worker_id: str, msg: dict) -> bool:
        """Send message to specific worker."""
        if worker_id not in self.workers:
            return False

        try:
            writer = self.workers[worker_id]["writer"]
            self._send_message(writer, msg)
            await writer.drain()
            return True
        except Exception as e:
            logger.error(f"Failed to send to {worker_id}: {e}")
            return False
```

### Worker IPC Client (runs inside Claude Code)

```python
# bridge/hooks/ipc_client.py
# This runs as a hook inside Claude Code

import socket
import json
import asyncio
import os
from typing import Dict, Any

class WorkerIPCClient:
    """Client-side socket connection to daemon."""

    def __init__(self):
        self.worker_id = os.getenv("BRIDGE_WORKER_ID")
        self.callback_socket_path = os.getenv("BRIDGE_CALLBACK_SOCKET")
        self.socket = None

    async def connect(self):
        """Connect to daemon."""
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.connect(self.callback_socket_path)
        self.socket.setblocking(False)

        # Send connect message
        await self.send({
            "type": "connect",
            "worker_id": self.worker_id,
            "pid": os.getpid(),
        })

    async def send(self, msg: Dict[str, Any]):
        """Send message to daemon."""
        json_str = json.dumps(msg)
        self.socket.sendall((json_str + "\n").encode())

    async def send_and_wait(self, msg: Dict[str, Any], timeout: int = 30) -> Dict:
        """Send message and wait for response (for permission requests)."""
        await self.send(msg)

        # Wait for response (blocking)
        start = time.time()
        while time.time() - start < timeout:
            try:
                data = self.socket.recv(1024)
                if data:
                    return json.loads(data.decode().strip())
            except (BlockingIOError, socket.error):
                await asyncio.sleep(0.1)

        raise TimeoutError(f"No response from daemon after {timeout}s")

    async def send_permission_request(self,
                                     action: str,
                                     pattern: str,
                                     file_path: str = None) -> bool:
        """Ask daemon for permission (blocking)."""
        msg = {
            "type": "permission_request",
            "id": f"perm-{uuid.uuid4()}",
            "action": action,
            "pattern": pattern,
            "file_path": file_path,
        }

        try:
            response = await self.send_and_wait(msg, timeout=300)
            return response.get("approved", False)
        except TimeoutError:
            logger.error("Permission request timed out, denying")
            return False

    async def send_progress(self, output: str):
        """Send progress update (non-blocking)."""
        await self.send({
            "type": "progress",
            "output": output,
            "timestamp": datetime.now().isoformat(),
        })

    async def send_task_complete(self, status: str, output: str,
                                 files_changed: list, signals: list):
        """Send task completion."""
        await self.send({
            "type": "task_complete",
            "status": status,
            "output": output,
            "files_changed": files_changed,
            "signals": signals,
        })
```

---

## 3. Task Queue Implementation

### SQLite Schema

```python
# daemon/database.py
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional

class TaskQueueDB:
    """SQLite-backed task queue."""

    def __init__(self, db_path: str = "~/.claude-bridge/task_queue.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row  # Fetch as dicts
        self._init_schema()

    def _init_schema(self):
        """Create tables if not exists."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                project_path TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                assigned_worker_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                result TEXT,
                error TEXT,
                retry_count INTEGER DEFAULT 0,
                user_id TEXT,

                FOREIGN KEY (assigned_worker_id) REFERENCES workers(id)
            );

            CREATE TABLE IF NOT EXISTS permissions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                requested_at TIMESTAMP,
                responded_at TIMESTAMP,
                response TEXT,
                timeout_seconds INTEGER DEFAULT 300,

                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                task_id TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence TEXT,
                logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE TABLE IF NOT EXISTS workers (
                id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                project_path TEXT NOT NULL,
                pid INTEGER NOT NULL,
                tmux_session TEXT NOT NULL,
                state TEXT DEFAULT 'ready',
                spawned_at TIMESTAMP,
                last_heartbeat TIMESTAMP,
                current_task_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_permissions_status ON permissions(status);
            CREATE INDEX IF NOT EXISTS idx_workers_state ON workers(state);
        """)
        self.conn.commit()

    async def insert_task(self, task_id: str, agent_name: str,
                         project_path: str, payload: str,
                         user_id: str = None) -> bool:
        """Insert new task."""
        try:
            self.conn.execute("""
                INSERT INTO tasks (id, agent_name, project_path, payload, user_id)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, agent_name, project_path, payload, user_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to insert task: {e}")
            return False

    async def pop_pending_task(self) -> Optional[Dict]:
        """Get next pending task (FIFO)."""
        cursor = self.conn.execute("""
            SELECT * FROM tasks
            WHERE status='pending'
            ORDER BY created_at ASC
            LIMIT 1
        """)
        row = cursor.fetchone()
        return dict(row) if row else None

    async def update_task(self, task_id: str, **updates):
        """Update task fields."""
        set_clause = ", ".join(f"{k}=?" for k in updates.keys())
        values = list(updates.values()) + [task_id]

        self.conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id=?",
            values
        )
        self.conn.commit()

    async def get_tasks(self, agent_name: str = None,
                       status: str = None, limit: int = 10) -> List[Dict]:
        """Query tasks with filters."""
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []

        if agent_name:
            query += " AND agent_name=?"
            params.append(agent_name)

        if status:
            query += " AND status=?"
            params.append(status)

        query += f" ORDER BY created_at DESC LIMIT {limit}"

        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    async def insert_permission(self, perm_id: str, task_id: str,
                               worker_id: str, action: str) -> bool:
        """Insert permission request."""
        try:
            self.conn.execute("""
                INSERT INTO permissions (id, task_id, worker_id, action)
                VALUES (?, ?, ?, ?)
            """, (perm_id, task_id, worker_id, action))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to insert permission: {e}")
            return False

    async def update_permission(self, perm_id: str, status: str,
                               response: Dict = None):
        """Update permission with response."""
        response_json = json.dumps(response) if response else None
        self.conn.execute("""
            UPDATE permissions
            SET status=?, response=?, responded_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (status, response_json, perm_id))
        self.conn.commit()

    async def get_permission(self, perm_id: str) -> Optional[Dict]:
        """Get permission by ID."""
        cursor = self.conn.execute(
            "SELECT * FROM permissions WHERE id=?", (perm_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None
```

---

## 4. Worker Spawner

```python
# daemon/worker_spawner.py
import subprocess
import json
from pathlib import Path
from datetime import datetime

class WorkerSpawner:
    """Spawn Claude Code processes in tmux."""

    def __init__(self, tmux_base: str = "bridge"):
        self.tmux_base = tmux_base

    async def spawn_worker(self, agent_name: str, project_path: str) -> Dict:
        """Spawn new Claude Code session."""
        worker_id = f"worker-{uuid.uuid4()}"
        tmux_session = f"{self.tmux_base}-{worker_id}"

        # Load profile and generate CLAUDE.md
        profile_mgr = ProfileManager()
        profile = profile_mgr.load(agent_name)
        claude_md = ClaudeMdGenerator().generate(profile)

        # Generate hooks config
        hooks_config = self._generate_hooks_config(worker_id)

        # Environment variables
        env = os.environ.copy()
        env.update({
            "BRIDGE_WORKER_ID": worker_id,
            "BRIDGE_CALLBACK_SOCKET": f"/tmp/claude-bridge/daemon.sock",
            "BRIDGE_DAEMON_PID": str(os.getpid()),
        })

        # Build Claude Code command
        system_prompt = self._build_system_prompt(profile, claude_md)

        cmd = f"""
        tmux new-session -d -s {tmux_session} -x 200 -y 50 bash -c '
            # Source user shell
            source ~/.bashrc 2>/dev/null || source ~/.zshrc 2>/dev/null || true

            # Run Claude Code
            export {' '.join(f'{k}={v}' for k, v in env.items() if k.startswith('BRIDGE_'))}

            claude --project {project_path} \\
                   --print \\
                   --channels telegram \\
                   -p "{system_prompt}"
        '
        """

        try:
            subprocess.run(cmd, shell=True, check=True, capture_output=True)

            # Get PID
            pid = self._get_tmux_pane_pid(tmux_session)

            logger.info(f"Spawned worker {worker_id} (PID {pid}, session {tmux_session})")

            return {
                "worker_id": worker_id,
                "agent_name": agent_name,
                "project_path": project_path,
                "pid": pid,
                "tmux_session": tmux_session,
                "state": "spawned",
                "spawned_at": datetime.now().isoformat(),
            }

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to spawn worker: {e}")
            raise

    def _build_system_prompt(self, profile, claude_md: str) -> str:
        """Build system prompt from profile + CLAUDE.md."""
        return f"""You are {profile['identity']['display_name']}.

Project: {profile['identity']['project']}

{claude_md}

When you need to take an action that might be risky (git push, write to sensitive files, etc.),
send a permission request to the daemon via the IPC socket.
The user will approve via Telegram.

When you complete the task, send a task_complete message with the results.
"""

    def _get_tmux_pane_pid(self, session_name: str) -> int:
        """Get PID of tmux pane."""
        result = subprocess.run(
            ["tmux", "list-panes", "-t", session_name, "-p"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to get tmux pane PID")

        pane = result.stdout.strip()
        result = subprocess.run(
            ["tmux", "send-keys", "-t", pane, "echo $BASHPID", "Enter"],
            capture_output=True,
            text=True,
        )
        # This is a simplified version; in production, capture from stderr
        return int(result.stdout.split('\n')[-2])

    def _generate_hooks_config(self, worker_id: str) -> Dict:
        """Generate hooks config for this worker."""
        return {
            "hooks": {
                "pre_tool_use": {
                    "bash": [
                        {
                            "block_pattern": "rm -rf /",
                            "action": "block",
                        },
                        {
                            "block_pattern": "git push --force",
                            "action": "relay_permission",
                            "timeout_seconds": 300,
                        },
                    ]
                },
                "post_tool_use": {
                    "write": [
                        {
                            "callback": "bridge_signal_file_changed",
                        }
                    ]
                },
            }
        }
```

---

## 5. Permission Router

```python
# daemon/permission_router.py
import asyncio
import uuid
from datetime import datetime

class PermissionRouter:
    """Route permission requests to Telegram."""

    def __init__(self, db: TaskQueueDB, telegram_channel):
        self.db = db
        self.telegram = telegram_channel
        self.pending_permissions = {}  # {perm_id: future}

    async def handle_permission_request(self, worker_id: str,
                                       req: Dict) -> Dict:
        """Worker requested permission."""
        perm_id = req["id"]
        task_id = req["task_id"]

        # Store in DB
        await self.db.insert_permission(
            perm_id=perm_id,
            task_id=task_id,
            worker_id=worker_id,
            action=req["action"],
        )

        # Send to Telegram
        await self.telegram.send_permission_request(
            perm_id=perm_id,
            action=req["action"],
            pattern=req["pattern"],
            file_path=req.get("file_preview"),
            timeout_seconds=req.get("timeout_seconds", 300),
        )

        # Create future (will be resolved when user responds)
        future = asyncio.Future()
        self.pending_permissions[perm_id] = future

        # Wait with timeout
        try:
            response = await asyncio.wait_for(
                future,
                timeout=req.get("timeout_seconds", 300),
            )
            return response
        except asyncio.TimeoutError:
            await self.db.update_permission(
                perm_id,
                status="timeout",
                response={"reason": "user_timeout"},
            )
            return {"approved": False, "reason": "timeout"}

    async def handle_permission_response(self, perm_id: str,
                                        approved: bool):
        """User responded to permission request via Telegram."""
        # Update DB
        await self.db.update_permission(
            perm_id,
            status="approved" if approved else "denied",
            response={"approved": approved},
        )

        # Resolve future (worker is waiting)
        if perm_id in self.pending_permissions:
            future = self.pending_permissions[perm_id]
            future.set_result({"approved": approved})
            del self.pending_permissions[perm_id]
```

---

## 6. Testing Strategy

### Unit Tests

```python
# tests/test_ipc_server.py
import pytest
import asyncio
import json
import socket

@pytest.mark.asyncio
async def test_ipc_connect_and_message():
    """Test worker connecting and sending message."""
    server = IPCServer()

    # Track received messages
    received = []

    async def msg_handler(msg, writer):
        received.append(msg)
        return {"type": "ack", "status": "ok"}

    server.register_handler("test", msg_handler)

    # Start server in background
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.1)  # Let server start

    # Connect as client
    reader, writer = await asyncio.open_unix_connection(
        str(server.server_socket_path)
    )

    # Send message
    msg = {"type": "test", "data": "hello"}
    writer.write((json.dumps(msg) + "\n").encode())
    await writer.drain()

    # Read response
    response = await reader.readline()
    assert response

    # Verify handler was called
    assert len(received) == 1
    assert received[0]["type"] == "test"

@pytest.mark.asyncio
async def test_task_queue_fifo():
    """Test task queue respects FIFO order."""
    db = TaskQueueDB(":memory:")

    # Insert 3 tasks
    for i in range(3):
        await db.insert_task(
            f"task-{i}",
            "agent",
            "/path",
            f"payload-{i}",
        )

    # Pop them in order
    task1 = await db.pop_pending_task()
    assert task1["id"] == "task-0"

    task2 = await db.pop_pending_task()
    assert task2["id"] == "task-1"

@pytest.mark.asyncio
async def test_permission_timeout():
    """Test permission request times out."""
    router = PermissionRouter(db, telegram)

    # Request permission with 1 second timeout
    response = await router.handle_permission_request("worker-1", {
        "id": "perm-1",
        "task_id": "task-1",
        "action": "bash",
        "timeout_seconds": 1,
    })

    # Should timeout and return False
    assert response["approved"] == False
    assert response["reason"] == "timeout"
```

### Integration Tests

```python
# tests/test_daemon_e2e.py
import pytest
import asyncio
import subprocess

@pytest.mark.asyncio
async def test_full_task_execution():
    """End-to-end: spawn daemon, send task, get result."""

    # Start daemon
    daemon_proc = subprocess.Popen(
        ["python", "-m", "claude_bridge.daemon"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    await asyncio.sleep(1)  # Let daemon start

    try:
        # Create task
        db = TaskQueueDB()
        await db.insert_task(
            "task-e2e-1",
            "test-agent",
            "/tmp/test-project",
            "echo Hello World",
        )

        # Wait for completion (with timeout)
        for _ in range(30):  # 30 second timeout
            task = await db.get_task("task-e2e-1")
            if task["status"] == "completed":
                break
            await asyncio.sleep(1)

        # Verify completion
        assert task["status"] == "completed"
        assert "Hello World" in task["result"]

    finally:
        daemon_proc.terminate()
        daemon_proc.wait(timeout=5)
```

---

## 7. Debugging & Monitoring

### Daemon Logs

```bash
# Start daemon with debug logging
LOGLEVEL=DEBUG python -m claude_bridge.daemon

# Tail logs
tail -f ~/.claude-bridge/daemon.log

# Watch task queue
sqlite3 ~/.claude-bridge/task_queue.db "SELECT id, status, created_at FROM tasks ORDER BY created_at DESC LIMIT 10;"

# Watch workers
sqlite3 ~/.claude-bridge/task_queue.db "SELECT id, agent_name, state, last_heartbeat FROM workers;"
```

### Socket Inspection (macOS)

```bash
# List Unix sockets
lsof -U | grep claude

# Monitor socket I/O (requires dtrace)
dtrace -n 'syscall:::entry /execname == "Python"/ { @[execname] = count(); }'
```

### Tmux Inspection

```bash
# List all bridge sessions
tmux list-sessions | grep bridge

# Attach to worker
tmux attach-session -t bridge-worker-abc123

# View scrollback
tmux capture-pane -t bridge-worker-abc123 -p -S -100
```

---

## 8. Deployment Checklist

- [ ] All tests pass (unit + integration)
- [ ] Daemon handles SIGTERM gracefully (cleanup)
- [ ] Daemon auto-restarts on crash (systemd/launchd)
- [ ] Task queue persists across restarts
- [ ] Worker crashes don't crash daemon
- [ ] IPC sockets cleaned up on shutdown
- [ ] Logs rotate (don't fill disk)
- [ ] Performance tested (100+ tasks queued)
- [ ] Security verified (Unix socket perms, no exposure)

---

## Conclusion

This implementation guide provides **production-ready patterns** for:
- IPC message passing (JSON lines)
- SQLite task queue
- Async worker spawning
- Permission relay with timeouts
- Testing strategies
- Debugging approaches

Start with the **MVP (Tier 1)** and incrementally move to **Tier 2-3** as needed.
