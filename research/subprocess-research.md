# Subprocess-Based Architecture Research
## Claude Bridge: Spawning Claude Code as Child Processes

**Date**: 2026-03-26
**Scope**: Research and reference document for implementing subprocess-based multi-agent orchestration
**Status**: Design proposal for Phase 1+ implementation

---

## Executive Summary

The proposed subprocess model treats Claude Bridge as a **parent process orchestrator** that spawns multiple **Claude Code CLI instances as child processes**, communicating via **Inter-Process Communication (IPC)** primitives (Unix sockets, pipes, HTTP localhost).

**Key insight**: Claude Code is already a standalone CLI tool. Rather than embedding it via SDK, spawn it as a sibling process and manage lifecycle/I/O programmatically.

**This avoids**:
- Complexity of Agent SDK integration
- Tight coupling to Claude's internal APIs
- Version fragility

**This enables**:
- Rapid iteration (spawn new agents without restarting daemon)
- Loose coupling (swap Claude Code versions easily)
- Better isolation (each agent in own process space)

---

## 1. Research Questions & Answers

### Q1: Can you spawn Claude Code CLI as subprocess and capture its I/O?

**Answer**: ✅ **Yes, absolutely.**

**Evidence from existing codebase**:

From `daemon-implementation-guide.md` (Section 4, Worker Spawner):
```python
# daemon/worker_spawner.py — WorkerSpawner class
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
```

**Technical approach**:

```python
import subprocess
import asyncio

# Headless mode: capture output directly
proc = subprocess.Popen(
    ["claude", "--project", "/path/to/project", "--print"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1  # Line buffered
)

# Send task via stdin
proc.stdin.write("Fix the login bug\n")
proc.stdin.flush()

# Read output asynchronously
async def read_output():
    while True:
        line = await asyncio.get_event_loop().run_in_executor(
            None, proc.stdout.readline
        )
        if not line:
            break
        print(f"Agent: {line}")

# Persistent mode: use tmux
subprocess.run([
    "tmux", "new-session", "-d", "-s", "agent-1",
    "claude", "--project", "/path/to/project"
])

# Send input via stdin
subprocess.run([
    "tmux", "send-keys", "-t", "agent-1",
    "Fix the login bug", "Enter"
])
```

**Key capabilities**:
- ✅ stdin/stdout/stderr capture
- ✅ Line buffering for streaming output
- ✅ Return code monitoring
- ✅ Signal handling (SIGTERM for graceful shutdown)
- ✅ Environment variable passing
- ✅ Working directory control

---

### Q2: What's the simplest IPC method: sockets, pipes, HTTP, files?

**Answer**: **Unix sockets** for simplicity + performance. HTTP localhost for fallback.

#### Comparison Matrix

| Method | Latency | Complexity | Reliability | Best For |
|--------|---------|------------|-------------|----------|
| **Unix sockets** | <1ms | Low | High | Primary choice |
| **Named pipes** | <1ms | Medium | Medium | Fallback on broken sockets |
| **HTTP localhost** | 2-5ms | Low | Medium | Debugging, language agnostic |
| **Shared files** | 10-50ms | Low | Low | Fallback, not real-time |
| **Message queues** | 5-20ms | High | High | If Redis/RabbitMQ available |

#### Recommended Stack

**Primary**: Unix sockets (`.sock` files in `/tmp/claude-bridge/`)
**Fallback**: HTTP on `localhost:9000+` (port pool)
**Persistence**: SQLite at `~/.claude-bridge/task_queue.db`

#### Protocol Specification (from codebase)

From `daemon-implementation-guide.md` (Section 1):

**Message Format**: JSON Lines (newline-delimited)

```
Client → Server (task delivery)
{"type": "task", "id": "task-001", "payload": {...}}

Server → Client (task response)
{"type": "task_response", "status": "ack"}
```

**Message Types**:

1. **Connection Handshake**
```json
{
  "type": "connect",
  "worker_id": "worker-abc123",
  "agent_name": "coder-my-app",
  "project_path": "/Users/hieutran/projects/my-app",
  "pid": 1234
}
```

2. **Task Delivery**
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

3. **Progress Updates**
```json
{
  "type": "progress",
  "task_id": "task-001",
  "output": "Analyzing auth module...\n",
  "timestamp": "2026-03-26T10:15:05Z"
}
```

4. **Permission Request**
```json
{
  "type": "permission_request",
  "id": "perm-xyz",
  "task_id": "task-001",
  "action": "bash",
  "pattern": "git push --force",
  "risk_level": "high"
}
```

5. **Permission Response**
```json
{
  "type": "permission_response",
  "id": "perm-xyz",
  "approved": false
}
```

6. **Task Completion**
```json
{
  "type": "task_complete",
  "task_id": "task-001",
  "status": "success",
  "output": "Fixed login bug...",
  "files_changed": ["src/auth/session.ts"],
  "signals": [{...}],
  "duration_seconds": 45.3
}
```

7. **Heartbeat**
```json
{
  "type": "heartbeat",
  "daemon_version": "0.1.0"
}
```

---

### Q3: How do you know when a child Claude Code process finishes?

**Answer**: Multiple signal methods work together:

#### 1. Exit Code Polling
```python
import subprocess

proc = subprocess.Popen([...])

# Poll exit code
exit_code = proc.poll()  # Returns None if still running, int if done

# Or wait with timeout
try:
    exit_code = proc.wait(timeout=300)
except subprocess.TimeoutExpired:
    proc.terminate()  # or proc.kill()
```

#### 2. Output Stream Closure
```python
# When process exits, stdout reaches EOF
while True:
    line = proc.stdout.readline()
    if not line:  # EOF reached
        print("Process finished")
        break
```

#### 3. Explicit Task Completion Message
```json
{
  "type": "task_complete",
  "task_id": "task-001",
  "status": "success"
}
```

#### 4. Heartbeat Timeout
```python
# Daemon sends heartbeat every 10 seconds
# If no heartbeat_ack in 30 seconds, assume dead

async def monitor_worker(worker_id: str):
    last_heartbeat = time.time()

    while True:
        await asyncio.sleep(10)
        await send_heartbeat(worker_id)

        # Check for response
        response_time = time.time()
        if response_time - last_heartbeat > 30:
            # Worker is dead
            await cleanup_worker(worker_id)
```

#### 5. Process Monitoring (macOS/Linux)
```python
import os
import signal

pid = proc.pid

# Check if process still exists
try:
    os.kill(pid, 0)  # Doesn't kill, just checks
except ProcessLookupError:
    # Process is dead
```

**Recommended approach**: Combine **exit code polling** + **heartbeat timeout** + **IPC message**.

---

### Q4: Can you manage multiple children from one parent process?

**Answer**: ✅ **Yes, with proper async/await or select/epoll.**

#### Architecture from Codebase

From `daemon-architecture.md`:

```
┌──────────────────────────────────────────────────────┐
│ BRIDGE DAEMON (persistent background process)       │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Components:                                        │
│  ├─ TaskQueue (SQLite)                             │
│  │  └─ [task_001] [task_002] [task_003] ...       │
│  │                                                 │
│  ├─ SessionPool                                    │
│  │  ├─ Worker 1: {pid, tmux_id, status}          │
│  │  ├─ Worker 2: {pid, tmux_id, status}          │
│  │  └─ Worker N: {pid, tmux_id, status}          │
│  │                                                 │
│  ├─ PermissionRouter                              │
│  │  └─ Caches pending approvals + timeouts       │
│  │                                                 │
│  ├─ ProfileManager                                │
│  │  └─ Loads/caches profiles for agents          │
│  │                                                 │
│  ├─ Signal Accumulator                            │
│  │  └─ Collects signals for enhancement          │
│  │                                                 │
│  └─ Telegram MCP Channel                          │
│     └─ Plugin that Claude Code loads              │
│                                                    │
└──────┬────────────┬──────────────┬──────────────┘
       │            │              │
       ▼            ▼              ▼
    [Worker 1]  [Worker 2]   [Worker N]
    (Claude       (Claude      (Claude
     Code)        Code)        Code)
     PID:         PID:         PID:
     1234         5678         9012
```

#### Implementation: Async Event Loop

From `daemon-implementation-guide.md` (Section 2):

```python
# daemon/ipc_server.py
import socket
import asyncio
from pathlib import Path
from typing import Dict, Callable

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

**Key capabilities**:
- ✅ Async/await handles multiple concurrent connections
- ✅ Each worker gets own `asyncio.StreamReaderProtocol` handle
- ✅ Non-blocking I/O via `readline()`, `write()`, `drain()`
- ✅ Register message handlers per message type
- ✅ Send to specific worker by worker_id

---

### Q5: Does Claude Code support being spawned programmatically?

**Answer**: ✅ **Yes, via CLI flags. Full support.**

#### Claude Code CLI Interface

**Standard spawn command** (from existing codebase):
```bash
claude --project ~/my-app \
       --print \
       --channels telegram \
       -p "System prompt here"
```

**Flags supported**:
- `--project` — Working directory
- `--print` — Output to stdout (not interactive UI)
- `--channels` — Which channel(s) to use (Telegram, Discord, etc.)
- `-p` / `--prompt` — System prompt (can be very long)

**Environment variables** (passed to spawned process):
```bash
BRIDGE_WORKER_ID=worker-abc123
BRIDGE_CALLBACK_SOCKET=/tmp/claude-bridge/daemon.sock
BRIDGE_DAEMON_PID=100
```

**Input methods**:
1. **stdin** — Pipe task payload
2. **Telegram MCP channel** — If agent needs user interaction
3. **Hooks/callbacks** — Call back to daemon for permissions

**Output methods**:
1. **stdout** — Streamed output
2. **IPC callback** — Send progress/completion messages
3. **Telegram** — Via MCP channel plugin

---

### Q6: Pros/cons: complexity vs latency vs reliability?

**Answer**: Detailed trade-off matrix below.

#### Approach: MVP Spawn (Direct)

**How it works**:
- Parent CLI spawns new `claude` process for each task
- Pipes stdin/stdout
- Waits for completion
- No persistent daemon

**Complexity**: ⭐ (very simple)
**Latency**: ⭐⭐⭐⭐ (spawn overhead ~2-3 sec)
**Reliability**: ⭐⭐ (no recovery, tmux leaks possible)
**Scalability**: ⭐ (1 task at a time)

**Pros**:
- ✅ Minimal code (~200 lines Python)
- ✅ Easy to debug
- ✅ Fast validation of concept
- ✅ No daemon process to maintain

**Cons**:
- ❌ Spawn latency kills UX (each task = 2-3 sec overhead)
- ❌ Can't queue tasks
- ❌ No session persistence
- ❌ tmux sessions leak if crash
- ❌ Can't handle burst requests

**Timeline**: 1-2 weeks full-time

---

#### Approach: Daemon Tier 1 (Basic Queue)

**How it works**:
- Persistent daemon process
- SQLite task queue
- Spawn one worker per task (like MVP)
- Basic IPC via Unix sockets
- One task at a time (but queued)

**Complexity**: ⭐⭐ (simple)
**Latency**: ⭐⭐⭐ (queue hides spawn latency)
**Reliability**: ⭐⭐⭐ (basic recovery possible)
**Scalability**: ⭐⭐ (queue enables batching)

**Pros**:
- ✅ Queue prevents task loss
- ✅ Removes spawn latency from user perception
- ✅ Daemon can restart cleanly
- ✅ Basic monitoring/recovery
- ✅ ~400 lines Python

**Cons**:
- ⚠️ Still single-task execution
- ⚠️ IPC sockets can leak if not cleaned
- ⚠️ SQLite contention (one writer at a time)
- ⚠️ Some OS-specific quirks (socket cleanup on macOS)

**Timeline**: 1 week (after MVP validated)

---

#### Approach: Daemon Tier 2 (Worker Pool)

**How it works**:
- Daemon maintains pool of idle `claude` processes (e.g., 3-5)
- Tasks assigned to available worker
- Non-blocking async dispatch
- Health monitoring + auto-respawn

**Complexity**: ⭐⭐⭐ (moderate async code)
**Latency**: ⭐⭐ (<100ms task handoff)
**Reliability**: ⭐⭐⭐⭐ (workers auto-recover)
**Scalability**: ⭐⭐⭐⭐ (2-5 concurrent tasks)

**Pros**:
- ✅ Multiple concurrent tasks
- ✅ Low task assignment latency
- ✅ Auto-respawn on crash
- ✅ Predictable resource usage
- ✅ ~600 lines Python

**Cons**:
- ⚠️ Async complexity (Python async/await required)
- ⚠️ Pool sizing not obvious
- ⚠️ Memory overhead (idle processes)
- ⚠️ Edge cases in worker health checks

**Timeline**: 1 week (after Tier 1 stable)

---

#### Approach: Daemon Tier 3 (Async I/O + Production)

**How it works**:
- Full async event loop (kqueue on macOS, epoll on Linux)
- Unlimited concurrent tasks (resource-limited)
- Async permission relay (no blocking on user approval)
- Session recovery + graceful shutdown

**Complexity**: ⭐⭐⭐⭐⭐ (high async complexity)
**Latency**: ⭐ (<10ms overhead)
**Reliability**: ⭐⭐⭐⭐⭐ (production-ready)
**Scalability**: ⭐⭐⭐⭐⭐ (10-100s concurrent tasks)

**Pros**:
- ✅ Unlimited concurrent task support
- ✅ Non-blocking permission relay
- ✅ Survive daemon crash
- ✅ Production-grade failure handling
- ✅ ~1000 lines Python

**Cons**:
- ❌ OS-specific code (kqueue vs epoll)
- ❌ Edge cases in signal handling
- ❌ Hard to debug distributed failures
- ❌ Requires extensive testing

**Timeline**: 2 weeks (Week 5+, only if needed)

---

#### Recommendation

From `daemon-decision-guide.md`:

| Scenario | MVP | Tier 1 | Tier 2 | Tier 3 |
|----------|-----|--------|--------|--------|
| **Single user, validate concept** | ✅ | ❌ | ❌ | ❌ |
| **Multiple tasks in sequence** | ✅ | ✅ | ✅ | ✅ |
| **2-3 concurrent tasks** | ❌ | ✅ | ✅ | ✅ |
| **5+ concurrent tasks** | ❌ | ⚠️ | ✅ | ✅ |
| **Permission relay < 5 sec** | ❌ | ❌ | ✅ | ✅ |
| **Survive daemon crash** | ❌ | ⚠️ | ⚠️ | ✅ |
| **Simple codebase** | ✅ | ✅ | ⚠️ | ❌ |
| **Production-ready** | ❌ | ❌ | ⚠️ | ✅ |

**Current decision** (from memory):
- **MVP phase**: Use MVP Spawn (direct CLI spawn)
- **Phase 1**: Upgrade to Daemon Tier 1 (add queue)
- **Phase 1.5**: Upgrade to Daemon Tier 2 (worker pool)
- **Phase 2**: Upgrade to Daemon Tier 3 (full async) — only if needed

---

## 2. Architecture Diagrams

### Process Tree: Multi-Agent Session

```
┌──────────────────────────────────────────────────────────────┐
│ Bridge Daemon (main parent process)                          │
│ PID: 100                                                     │
│                                                              │
│ [TaskQueue] [SessionPool] [PermissionRouter] [SignalCollector]
│                                                              │
│ Unix Socket: /tmp/claude-bridge/daemon.sock                │
│ SQLite DB:   ~/.claude-bridge/task_queue.db                │
└──────┬───────────────────────────────────────────────────┬──┘
       │                                                     │
       ├─────────────────┬─────────────────┬────────────────┤
       │                 │                 │                │
       ▼                 ▼                 ▼                ▼
┌─────────────┐   ┌─────────────┐   ┌──────────────┐   ┌───────────┐
│ Worker 1    │   │ Worker 2    │   │ Worker 3     │   │ (idle)    │
│ (Claude)    │   │ (Claude)    │   │ (Claude)     │   │ (spare)   │
│ PID: 1001   │   │ PID: 1002   │   │ PID: 1003    │   │ PID: 1004 │
│             │   │             │   │              │   │           │
│ Status:     │   │ Status:     │   │ Status:      │   │ Status:   │
│ EXECUTING   │   │ READY       │   │ EXECUTING    │   │ READY     │
│             │   │             │   │              │   │           │
│ Task:       │   │ Task:       │   │ Task:        │   │           │
│ task-001    │   │ (waiting)   │   │ task-002     │   │           │
│             │   │             │   │              │   │           │
│ Socket:     │   │ Socket:     │   │ Socket:      │   │ Socket:   │
│ /tmp/.../1  │   │ /tmp/.../2  │   │ /tmp/.../3   │   │ /tmp/.../4│
└─────────────┘   └─────────────┘   └──────────────┘   └───────────┘

Communication flow:
Daemon ←→ Worker 1 (task-001 in progress)
Daemon ←→ Worker 2 (idle, waiting for task)
Daemon ←→ Worker 3 (task-002 in progress)
Daemon ←→ Worker 4 (idle, spare capacity)

Task Queue (SQLite):
[task-001] ASSIGNED → Worker 1
[task-002] ASSIGNED → Worker 3
[task-003] PENDING → (waiting for available worker)
[task-004] PENDING → (waiting for available worker)
```

### IPC Message Flow: Task Execution

```
┌────────────────────────────────────────────────────────────────┐
│ USER (Telegram)                                                │
└─────────────┬──────────────────────────────────────────────────┘
              │ "Fix login bug"
              │
              ▼
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: TaskRouter                                             │
│  1. Parse message                                              │
│  2. Create Task(agent_name, payload)                           │
│  3. INSERT INTO task_queue (status='pending')                  │
└─────┬──────────────────────────────────────────────────────────┘
      │
      ▼ (pulls from queue)
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: SessionDispatcher                                      │
│  1. Pop task from queue (status='pending')                     │
│  2. UPDATE task_queue SET status='assigned'                    │
│  3. Find available Worker (or spawn new one)                   │
│  4. Send task via IPC socket: Task(id, payload, context)       │
└─────┬──────────────────────────────────────────────────────────┘
      │ Unix socket: /tmp/claude-bridge/worker-1.sock
      │ JSON: {"type": "task", "id": "task-001", ...}
      │
      ▼
┌────────────────────────────────────────────────────────────────┐
│ WORKER 1 (Claude Code Session)                                │
│  1. Read from socket: Task                                     │
│  2. Load profile.yaml + CLAUDE.md                              │
│  3. Execute task (read stdin, write stdout)                    │
│  4. Send progress via callback socket to Daemon                │
└─────┬──────────────────────────────────────────────────────────┘
      │ Unix socket callback
      │ JSON: {"type": "progress", "output": "..."}
      │
      ▼
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: PermissionRouter (waits for blocking call)             │
│  IF permission needed:                                         │
│  1. Receive from Worker: PermissionRequest                     │
│  2. INSERT INTO permissions (status='pending')                 │
│  3. Send to Telegram: [✅ Approve] [❌ Deny]                   │
│  4. Poll/wait for response (async)                             │
└─────┬──────────────────────────────────────────────────────────┘
      │ Telegram callback when user taps button
      │
      ▼
┌────────────────────────────────────────────────────────────────┐
│ DAEMON: Permission Response Handler                            │
│  1. UPDATE permissions SET approved=True/False                 │
│  2. Send response back to Worker via callback socket           │
└─────┬──────────────────────────────────────────────────────────┘
      │ Unix socket: {"type": "permission_response", ...}
      │
      ▼
[WORKER resumes/halts execution]
      │
      ▼
[Task complete, send final summary to Daemon]
      │
      ├─ {"type": "task_complete", "status": "success", ...}
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
└─────┬──────────────────────────────────────────────────────────┘
      │
      ▼
┌────────────────────────────────────────────────────────────────┐
│ USER (Telegram): sees task output + enhancement proposal       │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. IPC Protocol Specification

### Message Types

See Q2 above for detailed examples.

### Socket File Locations

```
/tmp/claude-bridge/
├── daemon.sock              # Main server socket (daemon listens)
├── worker-1.sock           # Worker 1 connected socket
├── worker-2.sock           # Worker 2 connected socket
└── worker-N.sock           # Worker N connected socket

~/.claude-bridge/
├── task_queue.db           # SQLite task queue + permissions
├── agents/
│   ├── coder-my-app/
│   │   ├── profile.yaml
│   │   ├── enhancement-accumulator.yaml
│   │   └── session.log
│   └── researcher-data/
│       └── ...
├── sessions.yaml           # Registry of active workers
└── daemon.log              # Daemon process log
```

### Error Handling

```python
# TimeoutError: If permission request exceeds 5 minutes
# ProcessError: If worker crashes
# SocketError: If IPC socket breaks (worker dead)
# DatabaseError: If task_queue.db corrupted

# Graceful degradation:
# - Lost permission approval → deny action (safe fail)
# - Worker crash → log signals collected so far → mark task as 'error'
# - Daemon restart → tasks in 'pending' re-queue, 'assigned' marked 'error'
```

---

## 4. Spawning & Cleanup Code Outline

### Spawning a Worker (Pseudocode)

```python
async def spawn_worker(agent_name: str, project_path: str) -> Worker:
    """Spawn a new Claude Code process."""

    worker_id = f"worker-{uuid.uuid4()}"

    # Load profile
    profile = ProfileManager().load(agent_name)
    claude_md = ClaudeMdGenerator().generate(profile)

    # Build environment
    env = os.environ.copy()
    env.update({
        "BRIDGE_WORKER_ID": worker_id,
        "BRIDGE_CALLBACK_SOCKET": "/tmp/claude-bridge/daemon.sock",
        "BRIDGE_DAEMON_PID": str(os.getpid()),
    })

    # Build system prompt
    system_prompt = f"""
You are an agent with this role: {profile.role}
Project: {project_path}

{claude_md}

Rules:
{profile.rules}
"""

    # Spawn in tmux (persistent mode)
    tmux_session = f"bridge-{worker_id}"
    cmd = [
        "tmux", "new-session", "-d", "-s", tmux_session,
        "bash", "-c", f"""
            source ~/.bashrc 2>/dev/null || source ~/.zshrc 2>/dev/null || true
            export BRIDGE_WORKER_ID='{worker_id}'
            export BRIDGE_CALLBACK_SOCKET='/tmp/claude-bridge/daemon.sock'
            export BRIDGE_DAEMON_PID='{os.getpid()}'

            claude --project '{project_path}' \\
                   --print \\
                   --channels telegram \\
                   -p '{system_prompt}'
        """
    ]

    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SpawnError(f"Failed to spawn worker: {proc.stderr}")

    # Get PID from tmux
    pid = int(subprocess.check_output(
        ["tmux", "list-panes", "-t", tmux_session, "-F", "#{pane_pid}"],
        text=True
    ).strip())

    # Register worker
    worker = Worker(
        id=worker_id,
        agent_name=agent_name,
        pid=pid,
        tmux_session=tmux_session,
        state="ready",
        started_at=datetime.now()
    )

    # Register in DB
    await task_queue_db.insert_worker(worker)

    # Wait for connection (worker calls "connect" message)
    await asyncio.wait_for(wait_for_connect(worker_id), timeout=10)

    return worker
```

### Dispatching a Task (Pseudocode)

```python
async def dispatch_task(task_id: str, payload: str, agent_name: str):
    """Assign a task to an available worker."""

    # Get next pending task
    task = await task_queue_db.pop_pending_task()
    if not task:
        return

    # Find or spawn worker
    worker = await get_available_worker(agent_name)
    if not worker:
        worker = await spawn_worker(agent_name, task['project_path'])

    # Load profile + CLAUDE.md
    profile = ProfileManager().load(agent_name)
    claude_md = ClaudeMdGenerator().generate(profile)

    # Send task via IPC
    task_msg = {
        "type": "task",
        "id": task_id,
        "agent_name": agent_name,
        "payload": payload,
        "profile": profile.to_dict(),
        "claude_md": claude_md,
        "timeout_seconds": 300
    }

    success = await ipc_server.send_to_worker(worker.id, task_msg)
    if success:
        await task_queue_db.update_task(task_id, status="assigned", assigned_worker_id=worker.id)
        worker.state = "executing"
        worker.current_task_id = task_id
    else:
        # Worker unreachable, mark as error
        await task_queue_db.update_task(task_id, status="error", error="Worker unreachable")
        await cleanup_worker(worker.id)
```

### Cleanup on Exit (Pseudocode)

```python
async def cleanup_worker(worker_id: str):
    """Kill a worker and clean up resources."""

    worker = await task_queue_db.get_worker(worker_id)
    if not worker:
        return

    # Kill tmux session
    try:
        subprocess.run(["tmux", "kill-session", "-t", worker.tmux_session])
    except:
        pass

    # Kill process if still alive
    try:
        os.kill(worker.pid, signal.SIGTERM)
        time.sleep(1)
        os.kill(worker.pid, signal.SIGKILL)  # Force kill
    except ProcessLookupError:
        pass  # Already dead

    # Clean up IPC socket
    socket_path = Path(f"/tmp/claude-bridge/{worker_id}.sock")
    socket_path.unlink(missing_ok=True)

    # Update DB
    await task_queue_db.update_worker(worker_id, state="stopped")

    # Mark any assigned tasks as error
    tasks = await task_queue_db.get_tasks(
        status="assigned",
        filter_worker_id=worker_id
    )
    for task in tasks:
        await task_queue_db.update_task(
            task['id'],
            status="error",
            error=f"Worker {worker_id} crashed"
        )

async def daemon_shutdown():
    """Graceful daemon shutdown."""

    logger.info("Shutting down daemon...")

    # Get all workers
    workers = await task_queue_db.get_all_workers()

    # Send graceful shutdown signal to each
    for worker in workers:
        await ipc_server.send_to_worker(worker.id, {
            "type": "shutdown",
            "reason": "daemon_stopping"
        })

    # Wait a bit for graceful shutdown
    await asyncio.sleep(5)

    # Force kill any remaining
    for worker in workers:
        try:
            os.kill(worker.pid, signal.SIGKILL)
        except:
            pass

    # Close IPC server
    ipc_server.stop()

    # Close DB
    task_queue_db.close()

    logger.info("Daemon shutdown complete")
```

---

## 5. Limitations & Gotchas

### 1. Socket File Cleanup

**Problem**: Unix sockets persist even if process crashes. Next daemon startup may fail with "Address already in use".

**Solution**:
```python
socket_path = Path("/tmp/claude-bridge/daemon.sock")
socket_path.unlink(missing_ok=True)  # Remove stale socket

server = await asyncio.start_unix_server(
    self._handle_connection,
    path=str(socket_path),
)
```

### 2. macOS vs Linux: Signal Handling

**Problem**: `signal.SIGTERM` behavior differs between OSes.

**Solution**:
```python
# Always try SIGTERM first, then SIGKILL
os.kill(pid, signal.SIGTERM)
await asyncio.sleep(1)
try:
    os.kill(pid, 0)  # Check if still alive
    os.kill(pid, signal.SIGKILL)  # Force kill
except ProcessLookupError:
    pass  # Already dead
```

### 3. tmux Session Persistence

**Problem**: If daemon crashes, tmux sessions remain. Manual cleanup required.

**Solution**:
```bash
# Manual cleanup when starting daemon
tmux kill-server  # Nuclear option

# Or more granular
tmux list-sessions | grep "^bridge-" | cut -d: -f1 | xargs -I {} tmux kill-session -t {}
```

### 4. Permission Relay Latency

**Problem**: User approval can take 30+ seconds. Worker blocks waiting.

**Solution**:
- Timeout permission requests to 5 minutes (safety)
- If timeout, deny action (fail safe)
- Log permission timeout as signal

### 5. Process Resource Limits

**Problem**: Spawning many workers → memory leak if not cleaned up.

**Solution**:
```python
# Implement worker pool sizing
MAX_WORKERS = 5  # Configurable

# Monitor memory
if memory_usage > 80%:
    # Kill idle workers
    for worker in idle_workers:
        await cleanup_worker(worker.id)
```

### 6. JSON Serialization of Large Payloads

**Problem**: CLAUDE.md can be 10-50KB. JSON over socket may split across packets.

**Solution**:
```python
# Use JSON Lines (newline-delimited)
# Each message is ONE line, guaranteeing atomic read/write

msg_json = json.dumps(msg)  # Compact
writer.write((msg_json + "\n").encode())  # Add newline delimiter
await writer.drain()

# On reader side
line = await reader.readline()  # Reads until \n
msg = json.loads(line.decode().strip())
```

### 7. Stale Worker Detection

**Problem**: Worker process dies unexpectedly. Daemon doesn't know immediately.

**Solution**:
```python
# Heartbeat every 10 seconds
async def heartbeat_monitor():
    while True:
        await asyncio.sleep(10)

        for worker in self.workers:
            await send_heartbeat(worker)

            # Check for response
            if not await wait_for_heartbeat_ack(worker, timeout=20):
                # Worker is dead
                await cleanup_worker(worker.id)
```

---

## 6. Comparison with Alternatives

### Alternative 1: Claude Code Agent SDK

**Pros**:
- Direct API access (no subprocess overhead)
- Tighter integration

**Cons**:
- ❌ Embeds Claude Code version (upgrades break compatibility)
- ❌ Complex dependency tree
- ❌ Poor isolation (single process space)
- ❌ Harder to test (requires SDK)
- ❌ Blocks on full SDK release

**Decision**: **Not recommended for MVP**. Subprocess approach simpler + looser coupling.

---

### Alternative 2: Message Queue (Redis/RabbitMQ)

**Pros**:
- Distributed queue (survives process crashes)
- Multiple daemon support (future scaling)

**Cons**:
- ❌ Extra dependency (Redis/RabbitMQ installation)
- ❌ Overkill for single-user MVP
- ⚠️ More complex deployment

**Decision**: **Defer to Phase 2**. SQLite sufficient for MVP.

---

### Alternative 3: HTTP REST API (instead of Unix sockets)

**Pros**:
- Language agnostic
- Works across networks (future)
- Easier to debug (can curl)

**Cons**:
- ❌ Higher latency (2-5ms vs <1ms)
- ❌ More overhead (HTTP headers, connection pooling)
- ⚠️ Need to bind port (potential conflicts)

**Decision**: **Use as fallback**. Prefer Unix sockets for MVP, add HTTP option in Phase 1.5.

---

## 7. Testing Strategy

### Unit Tests

```python
# Test IPC message parsing
def test_task_message_parsing():
    msg = '{"type": "task", "id": "task-001", ...}\n'
    parsed = json.loads(msg.strip())
    assert parsed["type"] == "task"

# Test permission handling
async def test_permission_relay():
    # Send permission request
    # Mock Telegram response
    # Verify response sent to worker
    ...

# Test worker spawning
async def test_spawn_worker():
    worker = await spawn_worker("coder-my-app", "/tmp/test-project")
    assert worker.state == "ready"
    assert worker.pid > 0
```

### Integration Tests

```python
# Test full task execution flow
async def test_task_execution_end_to_end():
    # 1. Spawn daemon
    # 2. Spawn worker
    # 3. Dispatch task
    # 4. Monitor completion
    # 5. Verify output
    # 6. Check signals collected
    # 7. Cleanup
    ...

# Test worker crash recovery
async def test_worker_crash_recovery():
    # 1. Spawn worker
    # 2. Kill worker unexpectedly
    # 3. Verify daemon detects crash
    # 4. Verify task marked as error
    # 5. Verify worker respawned for next task
    ...
```

### Load Tests

```python
# Test with multiple concurrent tasks
async def test_concurrent_tasks():
    # Dispatch 10 tasks simultaneously
    # Verify all complete successfully
    # Measure throughput
    ...
```

---

## 8. Implementation Roadmap

### Phase 0: MVP (Weeks 1-2)

**Scope**: Direct spawn, no daemon
- [ ] Spawn single Claude Code process
- [ ] Pipe stdin/stdout
- [ ] Monitor completion
- [ ] Collect signals
- [ ] Telegram integration

**Validation**: Does core agent lifecycle work?

---

### Phase 1: Daemon Tier 1 (Week 3)

**Scope**: Add queue, basic IPC
- [ ] Implement daemon skeleton
- [ ] SQLite task queue schema
- [ ] Unix socket IPC server
- [ ] Task dispatcher (FIFO)
- [ ] Worker spawner
- [ ] Basic heartbeat

**Validation**: Can daemon queue & execute tasks?

---

### Phase 1.5: Daemon Tier 2 (Week 4)

**Scope**: Worker pool + async
- [ ] Worker pool (idle workers)
- [ ] Async task dispatcher
- [ ] Health monitoring + respawn
- [ ] Permission relay (async)
- [ ] Signal accumulation (in-flight)

**Validation**: Multiple concurrent tasks? Auto-recovery?

---

### Phase 2: Daemon Tier 3 (Weeks 5-6)

**Scope**: Production hardening
- [ ] Full async I/O (kqueue/epoll)
- [ ] Session recovery (daemon restart)
- [ ] Comprehensive logging
- [ ] Monitoring dashboard (optional)
- [ ] Graceful shutdown
- [ ] Extensive testing

**Validation**: Production-ready?

---

## 9. Key Metrics to Track

### Performance
- **Task spawn latency**: 2-3 sec (MVP) → <1 sec (Tier 2)
- **Permission relay latency**: 30-60 sec (MVP) → <5 sec (Tier 2)
- **Worker startup time**: Should be consistent (~2 sec)
- **IPC message latency**: <1ms (sockets)

### Reliability
- **Task success rate**: Should be >99%
- **Worker crash frequency**: Monitor & alert
- **Socket cleanup**: No stale sockets
- **Memory usage**: Grow linearly with worker count

### User Experience
- **Time from task send to completion**: Perceived quickly
- **Permission approval feedback**: Immediate
- **Error messages**: Clear and actionable

---

## 10. References

### Existing Codebase Documents

1. **DESIGN.md** — High-level vision, profile system, enhancement flow
2. **daemon-architecture.md** — Daemon design, component interaction
3. **daemon-decision-guide.md** — When/how to implement daemon, risk assessment
4. **daemon-implementation-guide.md** — Code samples, IPC protocol, task queue schema
5. **specs/04-agent-lifecycle.md** — Agent state machine, spawning/cleanup
6. **specs/07-channels.md** — Telegram MCP channel interface

### External References

- **subprocess module**: https://docs.python.org/3/library/subprocess.html
- **asyncio**: https://docs.python.org/3/library/asyncio.html
- **Unix domain sockets**: https://en.wikipedia.org/wiki/Unix_domain_socket
- **tmux**: https://github.com/tmux/tmux/wiki
- **SQLite**: https://www.sqlite.org/

---

## Summary

**Can spawn Claude Code as subprocess?** ✅ Yes
**Best IPC method?** Unix sockets + JSON Lines
**Know when child finishes?** Yes (exit code + heartbeat + explicit message)
**Manage multiple children?** Yes (async event loop)
**Spawn programmatically?** Yes (via CLI flags)

**Recommended approach**: Start with MVP (direct spawn), upgrade to Daemon Tier 1-2 as needed.

**Complexity-Latency-Reliability spectrum**:
- MVP: Simple + slow + fragile
- Tier 1: Balanced + acceptable + improving
- Tier 2: Moderate complexity + fast + reliable
- Tier 3: Complex + minimal latency + production-ready

**Next steps**:
1. Validate MVP concept (Weeks 1-2)
2. Add daemon + queue (Week 3)
3. Add worker pool (Week 4)
4. Production hardening (Weeks 5-6, if needed)
