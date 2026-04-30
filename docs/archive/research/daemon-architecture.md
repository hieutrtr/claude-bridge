# Claude Bridge — Daemon-Based Architecture Proposal

**Status**: Design proposal for Phase 2+ (multi-agent coordination)
**Date**: 2026-03-26
**Scope**: Replace direct spawn model with persistent daemon orchestration

---

## Executive Summary

Current Bridge architecture (DESIGN.md) spawns Claude Code processes on-demand for each task. This works for single-task execution but becomes complex when:
- Multiple tasks arrive simultaneously (need queueing)
- Sessions need persistence across multiple tasks (tmux workaround)
- Process lifecycle management becomes ad-hoc
- Permission relay latency matters (Telegram roundtrip delays)

**Proposed solution**: A persistent **Bridge Daemon** process that:
1. Runs continuously as a background service (like `redis-server` or `postgres`)
2. Manages a pool of Claude Code sessions
3. Routes tasks via IPC (Unix sockets) + shared SQLite task queue
4. Provides its own Telegram MCP channel for I/O
5. Handles session failure/recovery automatically

**Key decision**: Daemon is **separate from Claude Code** — it orchestrates, Claude Code executes.

---

## 1. High-Level Architecture Diagram

### Current Model (Synchronous Spawn)
```
[Telegram]
    ↓
[Bridge CLI / Ad-hoc spawn]
    ↓ (spawn per task)
[Claude Code Session 1]
[Claude Code Session 2]
[Claude Code Session N]
    ↓
[Task output back to Telegram]
```

**Problems:**
- No central coordination
- Tmux sessions leak if daemon crashes
- Can't queue tasks elegantly
- Permission relay adds latency (blocking)

### Proposed Model (Daemon-Based)
```
┌──────────────────────────────────────────────────────────────┐
│ Telegram / Discord / Slack                                   │
└─────────────────┬──────────────────────────────────────────┘
                  │ (HTTP webhooks OR polling)
                  │ (via Telegram MCP Channel)
                  ▼
┌──────────────────────────────────────────────────────────────┐
│ BRIDGE DAEMON (persistent background process)               │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Components:                                                 │
│  ├─ TaskQueue (SQLite)                                      │
│  │  └─ [task_001] [task_002] [task_003] ...                │
│  │                                                          │
│  ├─ SessionPool                                             │
│  │  ├─ Worker 1: {session_pid, tmux_id, status}            │
│  │  ├─ Worker 2: {session_pid, tmux_id, status}            │
│  │  └─ Worker N: {session_pid, tmux_id, status}            │
│  │                                                          │
│  ├─ PermissionRouter                                        │
│  │  └─ Caches pending approvals + timeouts                 │
│  │                                                          │
│  ├─ ProfileManager                                          │
│  │  └─ Loads/caches profiles for agents                    │
│  │                                                          │
│  ├─ Signal Accumulator                                      │
│  │  └─ Collects signals for enhancement                    │
│  │                                                          │
│  └─ Telegram MCP Channel                                    │
│     └─ Plugin that Claude Code loads                        │
│                                                              │
└──────┬────────────┬──────────────┬──────────────────────────┘
       │            │              │
       ▼            ▼              ▼
    [Worker 1]  [Worker 2]   [Worker N]
    (Claude       (Claude      (Claude
     Code)        Code)        Code)
     PID:         PID:         PID:
     1234         5678         9012
```

### Component Interaction Diagram
```
┌────────────────────────────────────────────────────────────────┐
│ USER (Telegram)                                                │
└───────────┬────────────────────────────────────────────────────┘
            │ "Fix login bug"
            ▼
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: TaskRouter                                             │
│  1. Parse message                                              │
│  2. Create Task(agent_name, payload)                           │
│  3. INSERT INTO task_queue (status='pending')                  │
└────┬──────────────────────────────────────────────────────────┘
     │
     ▼ (pulls from queue)
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: SessionDispatcher                                      │
│  1. Pop task from queue (status='pending')                     │
│  2. UPDATE task_queue SET status='assigned'
│  3. Find available Worker (or spawn new one)                   │
│  4. Send task via IPC socket: Task(id, payload, context)       │
└────┬──────────────────────────────────────────────────────────┘
     │ (Unix socket or shared memory)
     ▼
┌────────────────────────────────────────────────────────────────┐
│ WORKER (Claude Code Session in tmux)                           │
│  1. Read from socket: Task                                     │
│  2. Load profile.yaml + CLAUDE.md                              │
│  3. Execute task                                               │
│  4. Send progress via callback socket back to Daemon            │
│  5. On permission needed: call Daemon.request_permission()     │
└────┬──────────────────────────────────────────────────────────┘
     │ (callback: progress updates + signals)
     ▼
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: Permission Relay                                       │
│  1. Receive from Worker: PermissionRequest                     │
│  2. INSERT INTO permissions (status='pending')                 │
│  3. Send to Telegram: [✅ Approve] [❌ Deny]                   │
│  4. Poll/wait for response (async)                             │
│  5. UPDATE permissions SET approved=True/False                 │
│  6. Send response back to Worker via callback socket           │
└────────────────────────────────────────────────────────────────┘
     │ (callback: approval status)
     ▼
[WORKER resumes/halts execution]
     │
     ▼
[Task complete, send final summary to Daemon]
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: Signal Collector + Reporter                            │
│  1. Receive TaskResult from Worker                             │
│  2. Log signals to enhancement-accumulator.yaml                │
│  3. UPDATE task_queue SET status='completed'                   │
│  4. Send summary to Telegram                                   │
│  5. Check if enhancement threshold hit                         │
│  6. If yes: show enhancement proposal                          │
└────────────────────────────────────────────────────────────────┘
     │
     ▼
┌────────────────────────────────────────────────────────────────┐
│ USER (Telegram): sees task output + enhancement proposal       │
└────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Questions & Answers

### Q1: How does the daemon maintain connections to multiple Claude Code processes?

#### A1: Multi-Channel IPC Model

**Connection Layer:**
```
Daemon (PID: 100)
    │
    ├─ Unix socket: /tmp/bridge/worker-1.sock (for Worker 1 communication)
    ├─ Unix socket: /tmp/bridge/worker-2.sock (for Worker 2 communication)
    ├─ Unix socket: /tmp/bridge/worker-n.sock (for Worker N communication)
    │
    ├─ Shared SQLite: ~/.claude-bridge/task_queue.db
    ├─ Shared file: ~/.claude-bridge/sessions.yaml (session registry)
    │
    └─ Event Loop (select/epoll/kqueue on macOS)
       └─ Async I/O on all sockets simultaneously
```

**Implementation approach:**

```python
# daemon/ipc_server.py
import socket
import threading
from pathlib import Path

class IPCServer:
    """Manages all worker connections."""

    def __init__(self, socket_dir: str = "/tmp/bridge"):
        self.socket_dir = Path(socket_dir)
        self.socket_dir.mkdir(exist_ok=True)
        self.workers = {}  # {worker_id: socket_connection}
        self.event_loop = None

    def start(self):
        """Start listening for worker connections."""
        # macOS uses kqueue, Linux uses epoll
        self.event_loop = select.kqueue() if platform.system() == "Darwin" else select.epoll()

        # Main accept loop (in separate thread)
        threading.Thread(target=self._accept_connections, daemon=True).start()

        # I/O loop (in separate thread)
        threading.Thread(target=self._handle_io, daemon=True).start()

    def _accept_connections(self):
        """Accept new worker connections."""
        server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_path = self.socket_dir / "daemon.sock"
        server_path.unlink(missing_ok=True)

        server_socket.bind(str(server_path))
        server_socket.listen(10)

        while True:
            worker_socket, _ = server_socket.accept()
            worker_id = f"worker-{uuid.uuid4()}"

            # Register worker
            self.workers[worker_id] = {
                "socket": worker_socket,
                "state": "ready",
                "last_heartbeat": time.time(),
            }

            # Add to event loop
            self.event_loop.register(worker_socket, select.EPOLLIN)

            logger.info(f"Worker {worker_id} connected")

    def _handle_io(self):
        """Handle I/O from all workers."""
        while True:
            # Wait for events on all sockets
            events = self.event_loop.poll(timeout=1.0)

            for fileno, event in events:
                if event & select.EPOLLIN:
                    # Data available to read
                    worker_socket = self._get_socket_by_fileno(fileno)
                    data = worker_socket.recv(4096)

                    if data:
                        msg = json.loads(data.decode())
                        self._handle_message(msg, worker_socket)
                    else:
                        # Socket closed
                        self._unregister_worker(worker_socket)

    def send_task_to_worker(self, worker_id: str, task: Task) -> bool:
        """Send task to worker via socket."""
        try:
            socket = self.workers[worker_id]["socket"]
            msg = json.dumps({
                "type": "task",
                "payload": task.to_dict(),
            })
            socket.send(msg.encode() + b"\n")
            return True
        except (KeyError, BrokenPipeError):
            return False

    def request_permission_from_daemon(self, permission_req: PermissionRequest):
        """Worker calls this to ask daemon for permission approval."""
        # Daemon will handle Telegram relay
        # Worker blocks until response
        return self._wait_for_permission(permission_req)
```

**Session Registry** (shared YAML):
```yaml
# ~/.claude-bridge/sessions.yaml
workers:
  worker-abc123:
    agent_name: coder-my-app
    project_path: ~/my-app
    pid: 1234
    tmux_session: bridge-abc123
    state: running
    last_heartbeat: 2026-03-26T10:15:00Z
    connected_at: 2026-03-26T10:00:00Z

  worker-def456:
    agent_name: researcher
    project_path: ~/my-app
    pid: 5678
    tmux_session: bridge-def456
    state: waiting_permission
    last_heartbeat: 2026-03-26T10:14:58Z
    connected_at: 2026-03-26T10:10:00Z

  worker-ghi789:
    agent_name: reviewer
    project_path: ~/my-app
    pid: 9012
    tmux_session: bridge-ghi789
    state: idle
    last_heartbeat: 2026-03-26T10:14:59Z
    connected_at: 2026-03-26T10:05:00Z
```

**Key design decisions:**
- ✅ **Unix sockets** (not TCP): Faster, local-only, no firewall issues
- ✅ **Event loop** (kqueue/epoll): Handle many workers efficiently
- ✅ **Shared registry**: YAML file is small, can check worker status without socket
- ✅ **Heartbeat**: Workers send periodic status → daemon detects dead workers
- ✅ **Async I/O**: Daemon doesn't block waiting for one worker

---

### Q2: Can each Claude Code session connect back to daemon as a tool/client?

#### A2: Yes — Two-way callback architecture

Claude Code cannot directly call daemon functions (no RPC), but it can use **hooks + environment variables** to trigger daemon callbacks:

**Architecture:**
```
Claude Code (Worker)
    │
    ├─ Reads env var: BRIDGE_CALLBACK_SOCKET=/tmp/bridge/daemon-abc123.sock
    │
    ├─ Hook: PreToolUse[Bash]
    │  └─ Detects blocked pattern
    │     └─ Sends JSON to BRIDGE_CALLBACK_SOCKET: {type: "permission_request", ...}
    │     └─ BLOCKS execution, waits for response
    │
    └─ Env var: BRIDGE_TASK_SOCKET=/tmp/bridge/task-abc123.sock
       └─ Reads next task
       └─ Sends progress updates
       └─ Sends completion signal
```

**Implementation:**

```python
# daemon/worker_spawner.py
def spawn_worker(agent_name: str, project_path: str) -> AgentProcess:
    """Spawn Claude Code session with bridge env vars + hooks."""

    worker_id = f"worker-{uuid.uuid4()}"
    tmux_session = f"bridge-{worker_id}"

    # Create callback socket (daemon side, worker connects to it)
    callback_socket_path = f"/tmp/bridge/callback-{worker_id}.sock"
    task_socket_path = f"/tmp/bridge/task-{worker_id}.sock"

    # Generate hooks config (passed to Claude Code)
    hooks_config = generate_hooks(
        callback_socket=callback_socket_path,
        permission_handler="bridge_permission_relay",  # Custom hook
    )

    # Environment variables
    env = os.environ.copy()
    env.update({
        "BRIDGE_WORKER_ID": worker_id,
        "BRIDGE_CALLBACK_SOCKET": callback_socket_path,
        "BRIDGE_TASK_SOCKET": task_socket_path,
        "BRIDGE_DAEMON_PID": os.getpid(),
    })

    # Start Claude Code in tmux
    tmux_cmd = f"""
    tmux new-session -d -s {tmux_session} -x 200 -y 50 \\
        bash -c '
            source ~/.bashrc

            # Claude Code with hooks + channels
            claude --project {project_path} \\
                   --print \\
                   --channels telegram \\
                   -p "System prompt from profile..." \\
                   --hooks-config {hooks_config_path}
        '
    """

    subprocess.run(tmux_cmd, shell=True, env=env, check=True)

    # Get PID
    pid = get_tmux_pane_pid(tmux_session)

    # Register in daemon
    daemon.register_worker(
        worker_id=worker_id,
        agent_name=agent_name,
        pid=pid,
        tmux_session=tmux_session,
        callback_socket=callback_socket_path,
        task_socket=task_socket_path,
    )

    return AgentProcess(
        worker_id=worker_id,
        pid=pid,
        agent_name=agent_name,
        state="ready",
    )
```

**Hook Integration** (Claude Code reads this):

```json
{
  "hooks": {
    "pre_tool_use": {
      "bash": [
        {
          "block_pattern": "rm -rf",
          "action": "relay_permission",
          "relay_handler": "bridge_relay",
          "timeout_seconds": 300
        },
        {
          "block_pattern": "git push --force",
          "action": "relay_permission"
        }
      ]
    },
    "post_tool_use": {
      "write": [
        {
          "callback": "bridge_post_write",
          "async": true
        }
      ]
    },
    "session_start": {
      "callback": "bridge_session_start"
    }
  }
}
```

**Callback Handler** (runs inside Claude Code process):

```python
# bridge/hooks/bridge_permission_relay.py
# This gets injected into Claude Code's hook system

import socket
import json
import os

def handle_permission_request(action: str, pattern: str, file_path: str = None) -> bool:
    """
    Called when hook detects blocked action.
    Sends request to daemon, waits for approval.
    """
    callback_socket = os.getenv("BRIDGE_CALLBACK_SOCKET")
    worker_id = os.getenv("BRIDGE_WORKER_ID")

    # Create request
    permission_req = {
        "type": "permission_request",
        "worker_id": worker_id,
        "action": action,
        "pattern": pattern,
        "file_path": file_path,
        "timestamp": datetime.now().isoformat(),
    }

    # Send to daemon
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(callback_socket)
    sock.send(json.dumps(permission_req).encode() + b"\n")

    # Wait for response (blocking)
    response = sock.recv(1024).decode()
    response_obj = json.loads(response)

    sock.close()

    return response_obj.get("approved", False)
```

**Daemon receives permission request:**

```python
# daemon/permission_router.py
def handle_permission_callback(worker_id: str, req: PermissionRequest):
    """Worker sent permission request via callback socket."""

    # 1. Store request
    self.pending_permissions[req.id] = {
        "request": req,
        "worker_id": worker_id,
        "timestamp": time.time(),
        "response": None,
    }

    # 2. Send to Telegram (async)
    asyncio.create_task(
        self.telegram_channel.send_permission_request(req)
    )

    # 3. Wait for user response (with timeout)
    # Worker is blocked waiting on socket
    # When user taps button, daemon sends response via socket
```

**Key design decisions:**
- ✅ **No RPC**: Simpler than gRPC/JSON-RPC (fewer dependencies)
- ✅ **Blocking I/O for permission**: Worker waits (acceptable, permission is rare)
- ✅ **Async signal collection**: Progress updates don't block
- ✅ **Env vars**: Claude Code doesn't need to know about daemon internals

---

### Q3: What's the minimal viable implementation for process spawning?

#### A3: Three-tier implementation strategy

**Tier 1 — MVP (Week 1-2): Single-Worker Blocking Spawn**

```python
# Minimal daemon that spawns ONE Claude Code per task
# (Current architecture, but centralized)

class BridgeDaemon:
    def __init__(self):
        self.db = sqlite3.connect("~/.claude-bridge/task_queue.db")
        self.current_worker = None

    def start(self):
        """Main event loop."""
        while True:
            # Pull next task from queue
            task = self.db.execute(
                "SELECT * FROM tasks WHERE status='pending' LIMIT 1"
            ).fetchone()

            if not task:
                time.sleep(1)
                continue

            # Spawn worker for this task
            self.spawn_worker(task)

            # Block until task complete
            self.wait_for_completion()

    def spawn_worker(self, task: Task):
        """Spawn single Claude Code process."""
        # Simple: just run claude in tmux
        cmd = f"""
        tmux new-session -d -s task-{task.id} \\
            claude --project {task.project} \\
                   --channels telegram \\
                   -p "{task.system_prompt}"
        """
        subprocess.run(cmd, shell=True)

    def wait_for_completion(self):
        """Block until tmux session exits."""
        while True:
            ret = subprocess.run(
                ["tmux", "list-sessions", "-t", f"task-{self.current_task.id}"],
                capture_output=True,
            )
            if ret.returncode != 0:
                # Session dead
                break
            time.sleep(1)
```

**Cons of Tier 1:**
- Only one task at a time (no parallelism)
- Can't handle rapid task bursts
- Permission relay is slow (synchronous)

**Tier 2 — Phase 1.5 (Week 3-4): Pool-based async spawning**

```python
class BridgeDaemon:
    def __init__(self, pool_size: int = 3):
        self.db = sqlite3.connect("~/.claude-bridge/task_queue.db")
        self.pool_size = pool_size
        self.workers = {}  # {worker_id: process}
        self.event_loop = asyncio.new_event_loop()

    def start(self):
        """Start daemon with worker pool."""
        # Spawn N idle workers
        for i in range(self.pool_size):
            self.spawn_idle_worker()

        # Main loop: dispatcher
        asyncio.run(self.dispatcher_loop())

    async def dispatcher_loop(self):
        """Continuously assign tasks to free workers."""
        while True:
            # Find free worker
            for worker_id, worker in self.workers.items():
                if worker["state"] == "idle":
                    # Pull next task
                    task = await self.db.get_pending_task()
                    if task:
                        await self.send_task_to_worker(worker_id, task)

            await asyncio.sleep(0.5)

    def spawn_idle_worker(self):
        """Spawn Claude Code waiting for tasks."""
        worker_id = f"worker-{uuid.uuid4()}"

        # Claude Code in "listen" mode (reads from stdin)
        cmd = f"""
        tmux new-session -d -s {worker_id} \\
            bash -c '
                export BRIDGE_WORKER_ID={worker_id}
                claude --listen-for-tasks \\
                       --profile-dir ~/.claude-bridge/agents
            '
        """

        subprocess.run(cmd, shell=True)
        self.workers[worker_id] = {"state": "idle"}
```

**Cons of Tier 2:**
- Still not fully async (socket I/O still blocks)
- Permission relay still synchronous
- Session persistence rough

**Tier 3 — Full Implementation (Week 5+): Event-driven async IPC**

```python
class BridgeDaemon:
    def __init__(self, pool_size: int = 5):
        self.db = sqlite3.connect("~/.claude-bridge/task_queue.db")
        self.pool_size = pool_size
        self.workers = {}
        self.permissions = {}
        self.event_loop = asyncio.new_event_loop()
        self.ipc_server = IPCServer(self.handle_worker_message)
        self.telegram = TelegramChannel()

    async def start(self):
        """Start daemon (fully async)."""
        # Spawn initial workers
        for i in range(self.pool_size):
            self.spawn_worker()

        # Concurrent tasks
        await asyncio.gather(
            self.ipc_server.start(),
            self.dispatcher_loop(),
            self.permission_monitor(),
            self.signal_accumulator_loop(),
            self.telegram.poll_messages(),
        )

    async def dispatcher_loop(self):
        """Non-blocking task assignment."""
        while True:
            free_workers = [
                w for w in self.workers.values()
                if w["state"] == "idle"
            ]

            pending_tasks = await self.db.get_pending_tasks(
                limit=len(free_workers)
            )

            for task, worker in zip(pending_tasks, free_workers):
                await self.send_task_to_worker(worker["id"], task)

            await asyncio.sleep(0.5)

    async def handle_worker_message(self, worker_id: str, msg: dict):
        """Worker sent message via IPC."""
        msg_type = msg.get("type")

        if msg_type == "permission_request":
            await self.handle_permission_request(worker_id, msg)
        elif msg_type == "progress":
            await self.handle_progress(worker_id, msg)
        elif msg_type == "task_complete":
            await self.handle_completion(worker_id, msg)
        elif msg_type == "signal":
            await self.handle_signal(worker_id, msg)
```

**Recommended approach for MVP:**
- **Start with Tier 1** (simpler, tests core logic)
- **Transition to Tier 2** (enable task queueing)
- **Implement Tier 3** (async I/O for prod-readiness)

---

### Q4: How do you handle session failure/recovery?

#### A4: Automatic restart + task replay

**Failure detection:**

```python
# daemon/worker_monitor.py
class WorkerMonitor:
    """Periodically check worker health."""

    async def monitor_loop(self):
        """Heartbeat-based monitoring."""
        while True:
            for worker_id, worker in self.workers.items():
                await self.check_worker_health(worker_id)

            await asyncio.sleep(5)  # Check every 5 seconds

    async def check_worker_health(self, worker_id: str):
        """Check if worker is alive."""
        worker = self.workers[worker_id]

        # Check 1: Process still running?
        if not self.is_process_alive(worker["pid"]):
            await self.handle_worker_crash(worker_id)
            return

        # Check 2: Heartbeat timeout?
        if time.time() - worker["last_heartbeat"] > 30:
            # Worker hung, kill and restart
            await self.kill_worker(worker_id)
            await self.restart_worker(worker_id)
            return

        # Check 3: Socket still responsive?
        try:
            await self.send_heartbeat(worker_id, timeout=5)
        except asyncio.TimeoutError:
            # Worker not responding, restart
            await self.restart_worker(worker_id)

    async def handle_worker_crash(self, worker_id: str):
        """Worker died unexpectedly."""
        worker = self.workers[worker_id]
        agent_name = worker["agent_name"]

        logger.error(f"Worker {worker_id} crashed (PID {worker['pid']})")

        # 1. Check what task it was running
        task = await self.db.get_task_by_worker(worker_id)

        if task and task["status"] == "running":
            # 2. Save partial output for logging
            session_log = self.get_tmux_scrollback(worker["tmux_session"])
            await self.db.update_task(
                task["id"],
                status="failed",
                error=f"Worker crashed. Last output:\n{session_log}",
            )

            # 3. Log signal for enhancement (worker crash)
            await self.signal_accumulator.log_signal(
                agent_name,
                Signal(
                    type=SignalType.HOOK_BLOCKED,
                    content="Worker process crashed",
                    task_id=task["id"],
                    proposed_change="Review process stability, increase timeout",
                ),
            )

            # 4. Notify user
            await self.telegram.send_message(
                f"⚠️ Task {task['id']} failed: Worker crashed\n"
                f"Restarting worker...",
            )

        # 5. Clean up dead worker
        del self.workers[worker_id]

        # 6. Respawn replacement worker
        new_worker = self.spawn_worker(agent_name=agent_name)
        logger.info(f"Respawned worker as {new_worker['id']}")
```

**Task replay:**

```python
# daemon/task_recovery.py
class TaskRecovery:
    """Handle task re-execution after failure."""

    async def handle_task_failure(self, task_id: str, reason: str):
        """Decide if task should be replayed."""
        task = await self.db.get_task(task_id)

        # Rules:
        # - If worker crashed: ALWAYS replay (fatal error, not task error)
        # - If task errored: NEVER replay (agent decision)
        # - If timeout: replay ONCE (might be transient)
        # - If permission timeout: replay after user re-approves

        if reason == "worker_crash":
            # Replay immediately
            await self.replay_task(task_id)

        elif reason == "timeout":
            # Replay with longer timeout
            await self.replay_task(task_id, retry_count=task["retry_count"] + 1)

        elif reason == "permission_timeout":
            # Wait for user to provide permission
            await self.db.update_task(
                task_id,
                status="pending_permission",
            )

    async def replay_task(self, task_id: str, retry_count: int = 1):
        """Replay a failed task."""
        task = await self.db.get_task(task_id)

        if retry_count > 3:
            # Too many retries
            await self.db.update_task(
                task_id,
                status="failed",
                error="Max retries exceeded",
            )
            await self.telegram.send_message(
                f"❌ Task {task_id} failed after {retry_count} retries",
            )
            return

        # Reset task to pending
        await self.db.update_task(
            task_id,
            status="pending",
            retry_count=retry_count,
        )

        logger.info(f"Replaying task {task_id} (attempt {retry_count})")

        # Dispatcher will pick it up next cycle
```

**Session persistence across crashes:**

```python
# daemon/session_registry.py
class SessionRegistry:
    """Maintain worker state across crashes."""

    async def save_session(self, worker_id: str):
        """Snapshot worker state to disk."""
        worker = self.workers[worker_id]

        session_data = {
            "worker_id": worker_id,
            "agent_name": worker["agent_name"],
            "project_path": worker["project_path"],
            "tmux_session": worker["tmux_session"],
            "current_task_id": worker.get("current_task_id"),
            "spawned_at": worker["spawned_at"],
            "saved_at": time.time(),
        }

        # Save to YAML for recovery
        with open(f"~/.claude-bridge/sessions/{worker_id}.yaml", "w") as f:
            yaml.dump(session_data, f)

    async def recover_session(self, session_file: str) -> dict:
        """Restore worker state from disk."""
        with open(session_file) as f:
            session_data = yaml.safe_load(f)

        # Check if tmux session still exists
        tmux_session = session_data["tmux_session"]
        if self.tmux_session_exists(tmux_session):
            # Session survived crash! Reattach
            logger.info(f"Reattaching to tmux session {tmux_session}")

            # Resume the worker
            return self.attach_to_existing_session(tmux_session)
        else:
            # Tmux session gone, respawn
            logger.info(f"Respawning worker {session_data['worker_id']}")
            return self.spawn_worker(
                agent_name=session_data["agent_name"],
                project_path=session_data["project_path"],
            )
```

**Recovery on daemon startup:**

```python
# daemon/startup.py
async def daemon_startup(self):
    """Recover state after daemon crash."""

    # 1. Scan for dead tasks
    running_tasks = await self.db.get_tasks(status="running")
    for task in running_tasks:
        logger.warning(
            f"Found orphaned task {task['id']}, "
            f"marking as failed (daemon restart)"
        )
        await self.db.update_task(
            task["id"],
            status="failed",
            error="Daemon crashed, task interrupted",
        )

    # 2. Recover existing tmux sessions
    sessions_dir = Path("~/.claude-bridge/sessions")
    for session_file in sessions_dir.glob("*.yaml"):
        await self.recover_session(str(session_file))

    # 3. Respawn missing workers
    for agent_name in self.configured_agents:
        if agent_name not in self.workers:
            self.spawn_worker(agent_name)

    # 4. Replay pending tasks
    pending = await self.db.get_tasks(status="pending")
    logger.info(f"Replaying {len(pending)} pending tasks")
```

**Key design decisions:**
- ✅ **Heartbeat monitoring**: Detect hangs quickly
- ✅ **Automatic respawn**: Self-healing (max retries = 3)
- ✅ **Tmux persistence**: Sessions survive daemon crash if tmux lives
- ✅ **Task replay logic**: Different strategies for different failure modes
- ✅ **Save-to-disk**: Session state recoverable even if daemon crashes

---

## 5. Implementation Outline

### Phase 1: Core Daemon (2 weeks)

```python
# daemon/daemon.py
class BridgeDaemon:
    """Main daemon orchestrator."""

    def __init__(self):
        self.db = TaskQueueDB("~/.claude-bridge/task_queue.db")
        self.ipc = IPCServer()
        self.telegram = TelegramChannel()
        self.profile_mgr = ProfileManager()
        self.signal_acc = SignalAccumulator()
        self.permission_router = PermissionRouter()
        self.worker_monitor = WorkerMonitor()
        self.workers = {}

    async def start(self):
        """Start all services concurrently."""
        await asyncio.gather(
            self.ipc.start(),
            self.telegram.start(),
            self.dispatcher_loop(),
            self.worker_monitor.monitor_loop(),
            self.permission_monitor_loop(),
            self.signal_accumulator_loop(),
        )

    async def dispatcher_loop(self):
        """Main task dispatching."""
        while True:
            # Get free worker
            free_worker = self._get_free_worker()
            if not free_worker:
                await asyncio.sleep(0.5)
                continue

            # Pop task
            task = await self.db.pop_pending_task()
            if not task:
                await asyncio.sleep(1)
                continue

            # Send to worker
            await self.send_task_to_worker(free_worker, task)

    # ... (other methods)
```

### Phase 2: IPC + Process Management (1 week)

```python
# daemon/ipc_server.py
class IPCServer:
    """Unix socket server for worker communication."""

    async def start(self):
        """Listen for worker connections."""
        # Implementation details above
        pass

# daemon/worker_spawner.py
class WorkerSpawner:
    """Spawn and manage Claude Code processes."""

    async def spawn_worker(self, agent_name: str, project_path: str):
        """Spawn single worker in tmux."""
        # Implementation details above
        pass
```

### Phase 3: Permission Relay (1 week)

```python
# daemon/permission_router.py
class PermissionRouter:
    """Route permission requests to Telegram."""

    async def handle_permission_request(self, req: PermissionRequest):
        """Send to Telegram, wait for response."""
        # Implementation details above
        pass
```

### Phase 4: Recovery + Monitoring (1 week)

```python
# daemon/worker_monitor.py
class WorkerMonitor:
    """Monitor worker health, restart on crash."""

    async def monitor_loop(self):
        """Periodic health checks."""
        # Implementation details above
        pass
```

### File structure:

```
claude_bridge/
├── daemon/
│   ├── __init__.py
│   ├── daemon.py                 # Main entry point
│   ├── ipc_server.py            # Unix socket I/O
│   ├── worker_spawner.py        # Process spawn + tmux
│   ├── worker_monitor.py        # Health checks + restart
│   ├── permission_router.py     # Permission relay
│   ├── task_queue.py            # SQLite wrapper
│   ├── session_registry.py      # Session recovery
│   └── recovery.py              # Crash recovery logic
│
├── channels/
│   ├── telegram_channel.py      # Telegram MCP plugin
│   └── base_channel.py
│
├── models/
│   ├── task.py                  # Task dataclass
│   ├── worker.py                # Worker state
│   └── permission.py            # Permission request
│
└── utils/
    ├── ipc.py                   # IPC helpers
    ├── tmux.py                  # Tmux wrapper
    └── logging.py
```

---

## 6. Data Models

### Task Queue (SQLite)

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    project_path TEXT NOT NULL,
    payload TEXT NOT NULL,  -- JSON
    status TEXT DEFAULT 'pending',  -- pending|assigned|running|completed|failed
    assigned_worker_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    result TEXT,  -- JSON output
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    user_id TEXT,  -- Telegram user ID

    FOREIGN KEY (assigned_worker_id) REFERENCES workers(id)
);

CREATE TABLE permissions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    action TEXT NOT NULL,  -- "bash: git push", "write: /payments/..."
    status TEXT DEFAULT 'pending',  -- pending|approved|denied|timeout
    requested_at TIMESTAMP,
    responded_at TIMESTAMP,
    response TEXT,  -- JSON (approved/denied reason)
    timeout_seconds INTEGER DEFAULT 300,

    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE signals (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    task_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,  -- user_corrected, agent_asked, etc.
    content TEXT NOT NULL,
    logged_at TIMESTAMP,

    FOREIGN KEY (agent_name) REFERENCES agents(name),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE workers (
    id TEXT PRIMARY KEY,
    agent_name TEXT NOT NULL,
    project_path TEXT NOT NULL,
    pid INTEGER NOT NULL,
    tmux_session TEXT NOT NULL,
    state TEXT DEFAULT 'ready',  -- ready|running|waiting_permission|paused|dead
    spawned_at TIMESTAMP,
    last_heartbeat TIMESTAMP,
    current_task_id TEXT,

    FOREIGN KEY (agent_name) REFERENCES agents(name),
    FOREIGN KEY (current_task_id) REFERENCES tasks(id)
);
```

---

## 7. Trade-offs vs. Other Approaches

### Option 1: Proposed Daemon Architecture
**Pros:**
- ✅ Central coordination point (easier to debug)
- ✅ True async/concurrent task execution (multiple workers)
- ✅ Persistent sessions survive daemon crash (tmux)
- ✅ Clean separation: daemon (orchestration) vs Claude Code (execution)
- ✅ Easy to add more channels later (Discord, Slack)
- ✅ Natural place for signal accumulation + enhancement

**Cons:**
- ❌ More complex (new IPC layer, event loops)
- ❌ More dependencies (asyncio, socket management)
- ❌ Harder to debug (distributed architecture)
- ❌ Requires understanding of kqueue/epoll (OS-specific)

**When to use:** Multi-agent scenarios, production use, complex task workflows

### Option 2: Agent SDK Direct Spawn (Current MVP)
**Pros:**
- ✅ Simpler (direct function calls)
- ✅ Fewer dependencies
- ✅ Easier for single-user MVP
- ✅ Direct integration with Claude Code SDK

**Cons:**
- ❌ Single task at a time (no concurrency)
- ❌ Permission relay is synchronous (slow)
- ❌ No session pooling
- ❌ Tmux sessions leak on crash

**When to use:** MVP validation, single-user scenarios

### Option 3: Job Queue Service (Redis/Celery)
**Pros:**
- ✅ Industry standard (lots of tooling)
- ✅ Distributed (can run on separate machines)
- ✅ Persistent (survives restarts)
- ✅ Scalable

**Cons:**
- ❌ Heavy dependencies (Redis, Celery)
- ❌ Overkill for single-machine MVP
- ❌ Adds network layer (localhost socket simpler for macOS)
- ❌ Requires extra infrastructure

**When to use:** Multi-machine deployment, production scale

### Option 4: Multi-process Pool (Python multiprocessing)
**Pros:**
- ✅ Built-in to Python stdlib
- ✅ Simpler than async I/O
- ✅ Good for CPU-bound work

**Cons:**
- ❌ Designed for Python parallelism (Claude Code is external process)
- ❌ Can't easily manage external process lifecycle
- ❌ Less suited for I/O-bound (waiting on permission relay)

**When to use:** Python-only task parallelism

### Recommendation Matrix

| Criteria | Daemon (Proposed) | Direct Spawn | Redis/Celery | Multiprocessing |
|----------|-------------------|--------------|--------------|-----------------|
| MVP Simplicity | 3/5 | 5/5 | 2/5 | 4/5 |
| Production-Ready | 5/5 | 2/5 | 5/5 | 3/5 |
| Concurrency | 5/5 | 1/5 | 5/5 | 4/5 |
| Debuggability | 3/5 | 5/5 | 2/5 | 4/5 |
| Dependencies | 3/5 | 5/5 | 2/5 | 5/5 |
| Multi-machine | 2/5 | 1/5 | 5/5 | 1/5 |

**Recommendation:**
- **MVP (Weeks 1-2)**: Use Option 2 (direct spawn, no daemon)
- **Phase 1.5 (Week 3-4)**: Introduce daemon with Tier 1 implementation
- **Phase 2 (Weeks 5-6)**: Add IPC + worker pool (Tier 2-3)
- **Future**: Consider Redis/Celery if multi-machine deployment needed

---

## 8. Integration with Existing Systems

### How Daemon Replaces Current Architecture

**Current (DESIGN.md):**
```
Telegram → Bridge CLI → spawn claude --project ... → done
```

**With Daemon:**
```
Telegram → Bridge Daemon (persistent) → [worker pool] → done
                     ↓
            SQLite task queue
            Session registry
            Permission router
```

### Backwards Compatibility

**Option A: Gradual Migration**
```
Phase 1: Daemon runs alongside current CLI
- /spawn still works (routes through daemon)
- Old tmux sessions continue working
- New tasks use daemon pooling

Phase 2: Deprecate direct spawn
- All tasks go through daemon
- Old sessions cleaned up
```

**Option B: Wrapper Layer**
```
claude-bridge CLI (unchanged interface)
    ↓
DaemonClient (new abstraction)
    ↓
Daemon process (new backend)
```

### Messaging Layer Integration

**Telegram MCP Channel in Worker:**
```
Claude Code (Worker)
    ├─ Loads Telegram MCP plugin (from Channels spec)
    ├─ Sends output to Telegram automatically
    └─ Receives tasks from Telegram polling
```

**Daemon's role:**
```
Daemon
    ├─ Spawns workers with --channels telegram flag
    ├─ Intercepts permission requests (hook system)
    ├─ Monitors task progress (indirect, via logs)
    └─ Collects signals on completion
```

**No direct Telegram communication from daemon** (workers handle that).

---

## 9. Minimal Example: Daemon in Action

### Setup
```bash
# Terminal 1: Start daemon
python -m claude_bridge.daemon

# Terminal 2: Send task
claude-bridge task spawn coder-my-app --project ~/my-app

# Terminal 3: Telegram sends "Fix login bug"
```

### Flow
```
User (Telegram):
  "Fix login bug"

Bridge Daemon:
  1. Receive from TelegramChannel
  2. INSERT INTO tasks (status='pending', agent='coder-my-app', payload='Fix login bug')
  3. Dispatcher: pop task, find free worker
  4. If no free worker: spawn new one
     - Spawn: claude --project ~/my-app --channels telegram
     - In tmux: bridge-worker-abc123
  5. Send task via /tmp/bridge/callback-abc123.sock
     - {"type": "task", "payload": "Fix login bug"}

Worker (Claude Code):
  1. Read from socket
  2. Load profile.yaml + CLAUDE.md
  3. Execute: "Fix login bug"
  4. Send progress: {"type": "progress", "output": "..."}
  5. On permission needed: {"type": "permission_request", ...}

Daemon (PermissionRouter):
  1. Receive permission request
  2. INSERT INTO permissions (status='pending')
  3. Send to Telegram: "Fix login bug requires approval: git push"
     [✅ Approve] [❌ Deny]
  4. User taps ✅
  5. UPDATE permissions SET status='approved'
  6. Send back to worker: {"type": "permission_response", "approved": true}

Worker:
  1. Resume execution
  2. git push
  3. Complete task
  4. Send: {"type": "task_complete", "status": "success", "output": "..."}

Daemon (Signal Collector):
  1. Receive task complete
  2. Log signals to enhancement-accumulator.yaml
  3. UPDATE tasks SET status='completed'
  4. Send summary to Telegram
  5. Check enhancement threshold
```

---

## 10. Success Criteria (for Daemon Implementation)

- [ ] Daemon starts/stops cleanly
- [ ] Task queue SQLite working (insert/pop/update)
- [ ] At least 1 worker spawns and stays alive
- [ ] Task routed to worker via socket
- [ ] Worker output collected and sent to Telegram
- [ ] Permission request sent to Telegram + response routes back
- [ ] Signals logged on task completion
- [ ] Worker crash detected + respawned
- [ ] Daemon crash → tasks recovered on restart
- [ ] Multiple tasks queued + executed in parallel
- [ ] Session pool sizing working (respawn on high load)

---

## Conclusion

The daemon architecture represents a **strategic shift from ad-hoc spawning to coordinated orchestration**.

**Key insight**: The daemon is **not a new component that "replaces" Claude Code**. Rather, it's an **intermediary** that:
- Coordinates multiple Claude Code sessions (pooling)
- Manages task delivery (queue + routing)
- Handles permission relay (Telegram integration)
- Collects signals for enhancement (learning)
- Recovers from failures automatically

This separation of concerns makes Bridge **composable**, **debuggable**, and **extensible** for future phases (multi-machine, multiple channels, advanced orchestration).

**Implementation recommendation**: Start with Phase 1 MVP (direct spawn), validate the core model, then introduce daemon layer iteratively (Tier 1 → Tier 2 → Tier 3) as complexity demands.
