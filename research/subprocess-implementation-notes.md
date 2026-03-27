# Subprocess Implementation — Deep Dive Notes

**Reference guide** for developers implementing subprocess-based architecture.

---

## 1. Core Implementation Details

### 1.1 Spawn Process (Python)

**Headless Mode** (for task execution):
```python
import subprocess
import asyncio

async def spawn_headless(project_path: str, system_prompt: str):
    """Spawn Claude Code in headless mode."""

    proc = subprocess.Popen(
        [
            "claude",
            "--project", project_path,
            "--print",  # Output to stdout, not UI
            "-p", system_prompt
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # Line buffered
        universal_newlines=True
    )

    return proc

# Send task
proc.stdin.write("Fix the login bug\n")
proc.stdin.flush()

# Read output
while True:
    line = proc.stdout.readline()
    if not line:
        break  # EOF, process finished
    print(f"Agent: {line}", end='')

# Wait for completion
exit_code = proc.wait()
print(f"Process exited with code {exit_code}")
```

**Persistent Mode** (with tmux):
```bash
#!/bin/bash
# Start Claude Code in tmux for long-running sessions

tmux new-session -d -s agent-session-1 \
    bash -c '
        source ~/.bashrc 2>/dev/null || source ~/.zshrc 2>/dev/null || true

        export BRIDGE_WORKER_ID="worker-abc123"
        export BRIDGE_CALLBACK_SOCKET="/tmp/claude-bridge/daemon.sock"

        claude --project ~/my-app \
               --print \
               --channels telegram \
               -p "System prompt here"
    '

# Send task to session
tmux send-keys -t agent-session-1 "Fix the login bug" Enter

# Capture output
tmux capture-pane -t agent-session-1 -p

# Kill session when done
tmux kill-session -t agent-session-1
```

---

### 1.2 Async I/O Patterns

**Reading from stdout (non-blocking)**:
```python
import asyncio

async def read_output_async(proc):
    """Read process output asynchronously."""

    loop = asyncio.get_event_loop()

    while True:
        # Run blocking readline in thread pool
        line = await loop.run_in_executor(
            None,
            proc.stdout.readline
        )

        if not line:
            break  # EOF

        print(f"Output: {line.rstrip()}")

        # Yield to other tasks
        await asyncio.sleep(0)

# Usage
proc = subprocess.Popen([...], stdout=subprocess.PIPE, text=True)
task = asyncio.create_task(read_output_async(proc))
```

**Waiting for process with timeout**:
```python
async def execute_with_timeout(proc, timeout_seconds=300):
    """Execute process with timeout."""

    loop = asyncio.get_event_loop()

    try:
        # Wait for process to finish (in thread pool to avoid blocking)
        exit_code = await asyncio.wait_for(
            loop.run_in_executor(None, proc.wait),
            timeout=timeout_seconds
        )
        return exit_code

    except asyncio.TimeoutExpired:
        # Process hung, kill it
        proc.terminate()  # SIGTERM

        try:
            # Wait 5 seconds for graceful shutdown
            exit_code = await asyncio.wait_for(
                loop.run_in_executor(None, proc.wait),
                timeout=5
            )
        except asyncio.TimeoutExpired:
            # Still alive, force kill
            proc.kill()  # SIGKILL
            proc.wait()

        raise TimeoutError(f"Process exceeded {timeout_seconds}s")
```

---

### 1.3 IPC: Unix Sockets

**Server (Daemon)**:
```python
import socket
import asyncio
import json
from pathlib import Path

class IPCServer:
    def __init__(self, socket_path="/tmp/claude-bridge/daemon.sock"):
        self.socket_path = Path(socket_path)
        self.connections = {}  # {worker_id: (reader, writer)}

    async def start(self):
        """Start Unix socket server."""

        # Clean up old socket
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)

        # Create async server
        server = await asyncio.start_unix_server(
            self.client_connected,
            path=str(self.socket_path)
        )

        async with server:
            await server.serve_forever()

    async def client_connected(self, reader, writer):
        """Handle worker connection."""

        worker_id = None

        try:
            while True:
                # Read JSON line
                line = await asyncio.wait_for(
                    reader.readline(),
                    timeout=600  # 10 min idle timeout
                )

                if not line:
                    break  # EOF

                msg = json.loads(line.decode().strip())

                # First message should be "connect"
                if msg["type"] == "connect":
                    worker_id = msg["worker_id"]
                    self.connections[worker_id] = (reader, writer)
                    print(f"Worker {worker_id} connected")

                # Process message
                await self.handle_message(msg, writer)

        except asyncio.TimeoutError:
            print(f"Worker {worker_id} idle timeout")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            if worker_id and worker_id in self.connections:
                del self.connections[worker_id]
            writer.close()
            await writer.wait_closed()

    async def handle_message(self, msg, writer):
        """Route message to handler."""

        msg_type = msg.get("type")

        if msg_type == "task_complete":
            await self.on_task_complete(msg)
        elif msg_type == "permission_request":
            await self.on_permission_request(msg)
        elif msg_type == "progress":
            await self.on_progress(msg)

    async def send_to_worker(self, worker_id, msg):
        """Send message to worker."""

        if worker_id not in self.connections:
            return False

        reader, writer = self.connections[worker_id]

        try:
            json_str = json.dumps(msg)
            writer.write((json_str + "\n").encode())
            await writer.drain()
            return True
        except Exception as e:
            print(f"Failed to send: {e}")
            return False
```

**Client (Worker)**:
```python
import socket
import asyncio
import json
import os

class IPCClient:
    def __init__(self, socket_path="/tmp/claude-bridge/daemon.sock"):
        self.socket_path = socket_path
        self.reader = None
        self.writer = None

    async def connect(self):
        """Connect to daemon."""

        reader, writer = await asyncio.open_unix_connection(
            self.socket_path
        )

        self.reader = reader
        self.writer = writer

        # Send connect message
        await self.send({
            "type": "connect",
            "worker_id": os.getenv("BRIDGE_WORKER_ID"),
            "pid": os.getpid(),
        })

    async def send(self, msg):
        """Send message to daemon."""

        json_str = json.dumps(msg)
        self.writer.write((json_str + "\n").encode())
        await self.writer.drain()

    async def recv(self):
        """Receive message from daemon."""

        line = await self.reader.readline()
        if not line:
            return None

        return json.loads(line.decode().strip())

    async def send_and_wait(self, msg, timeout=30):
        """Send and wait for response."""

        await self.send(msg)

        try:
            response = await asyncio.wait_for(
                self.recv(),
                timeout=timeout
            )
            return response
        except asyncio.TimeoutError:
            return None

    async def request_permission(self, action, pattern):
        """Block until user approves/denies."""

        msg = {
            "type": "permission_request",
            "action": action,
            "pattern": pattern,
        }

        response = await self.send_and_wait(msg, timeout=300)

        if response and response.get("approved"):
            return True
        else:
            return False

    async def send_progress(self, output):
        """Send progress (non-blocking)."""

        await self.send({
            "type": "progress",
            "output": output,
        })

    async def send_task_complete(self, status, output, files_changed):
        """Send task completion."""

        await self.send({
            "type": "task_complete",
            "status": status,
            "output": output,
            "files_changed": files_changed,
        })
```

---

## 2. Signal Collection & Reporting

### 2.1 Signal Types

From codebase (Profile system):
```python
# Signal types to track
SIGNAL_TYPES = [
    "user_corrected",      # User had to fix agent's work
    "agent_asked",         # Agent repeatedly asked about something
    "hook_blocked",        # Hook blocked dangerous action
    "pattern_detected",    # Agent's repeated behavior
    "files_touched",       # Files agent frequently edits
    "task_pattern",        # Similar tasks keep coming up
]

# Threshold for enhancement
ENHANCEMENT_THRESHOLD = 5  # 5+ signals of same type triggers proposal
```

### 2.2 Signal Collection During Task Execution

```python
class SignalCollector:
    """Collect signals during task execution."""

    def __init__(self, task_id, agent_name):
        self.task_id = task_id
        self.agent_name = agent_name
        self.signals = []

    def on_file_write(self, file_path):
        """Agent modified a file."""
        self.signals.append({
            "type": "pattern_detected",
            "content": f"Agent frequently edits {file_path}",
            "confidence": "medium"
        })

    def on_user_correction(self, correction):
        """User corrected agent."""
        self.signals.append({
            "type": "user_corrected",
            "content": correction,
            "confidence": "high"
        })

    def on_permission_blocked(self, pattern):
        """Hook blocked dangerous action."""
        self.signals.append({
            "type": "hook_blocked",
            "content": f"Blocked pattern: {pattern}",
            "confidence": "high"
        })

    async def report(self, ipc_client):
        """Report signals to daemon."""

        await ipc_client.send({
            "type": "task_complete",
            "status": "success",
            "signals": self.signals,
        })
```

### 2.3 Enhancement Proposal Logic

```python
class EnhancementProposer:
    """Analyze signals and propose profile enhancements."""

    def __init__(self, accumulator_path):
        self.accumulator = yaml.safe_load(open(accumulator_path))

    def check_threshold(self):
        """Check if any signal type hit threshold."""

        proposals = []
        threshold = 5

        for signal_type, signals in self.accumulator["signals"].items():
            if len(signals) >= threshold:
                proposals.append({
                    "signal_type": signal_type,
                    "count": len(signals),
                    "examples": signals[:3],  # Top 3
                })

        return proposals

    async def send_to_telegram(self, telegram_channel, proposals):
        """Propose enhancements to user."""

        text = "🔧 Found enhancements:\n\n"

        for proposal in proposals:
            text += f"🔴 {proposal['signal_type']} ({proposal['count']} signals):\n"
            for sig in proposal['examples']:
                text += f"  • {sig['content']}\n"

        text += "\n[✅ Apply All] [👁️ Review Each] [❌ Skip]"

        await telegram_channel.send_message(text)
```

---

## 3. Worker Health Monitoring

### 3.1 Heartbeat Protocol

```python
class HeartbeatMonitor:
    """Monitor worker health via heartbeat."""

    def __init__(self, timeout_seconds=30):
        self.timeout_seconds = timeout_seconds
        self.last_heartbeat = {}  # {worker_id: timestamp}

    async def start(self, ipc_server, cleanup_callback):
        """Start heartbeat monitoring loop."""

        while True:
            await asyncio.sleep(10)  # Check every 10 sec

            # Send heartbeat to all connected workers
            for worker_id in ipc_server.connections.keys():
                await ipc_server.send_to_worker(worker_id, {
                    "type": "heartbeat"
                })

            # Check for timeouts
            now = time.time()
            dead_workers = []

            for worker_id, last_beat in self.last_heartbeat.items():
                if now - last_beat > self.timeout_seconds:
                    dead_workers.append(worker_id)

            # Clean up dead workers
            for worker_id in dead_workers:
                await cleanup_callback(worker_id)
                del self.last_heartbeat[worker_id]

    async def on_heartbeat_ack(self, worker_id):
        """Worker is alive."""
        self.last_heartbeat[worker_id] = time.time()
```

---

## 4. Error Handling & Recovery

### 4.1 Worker Crash Recovery

```python
async def monitor_and_respawn(worker_id, spawn_callback):
    """Monitor worker, respawn if it dies."""

    backoff = [1, 2, 5, 10, 30]  # Exponential backoff seconds
    retry_count = 0

    while True:
        # Check if worker still alive
        try:
            os.kill(worker_pid, 0)  # Check without killing
        except ProcessLookupError:
            # Process is dead
            retry_count += 1

            if retry_count > len(backoff):
                # Too many retries, give up
                await cleanup_worker(worker_id)
                return

            # Wait before respawning
            wait_time = backoff[retry_count - 1]
            print(f"Worker {worker_id} dead, respawning in {wait_time}s")
            await asyncio.sleep(wait_time)

            # Respawn
            new_worker = await spawn_callback(worker_id)
            worker_pid = new_worker.pid

        # Sleep before next check
        await asyncio.sleep(30)
```

### 4.2 Task Failure Recovery

```python
async def execute_with_recovery(task_id, agent_name, payload, max_retries=3):
    """Execute task with retry logic."""

    for attempt in range(1, max_retries + 1):
        try:
            # Try to get or spawn worker
            worker = await get_worker(agent_name)
            if not worker:
                worker = await spawn_worker(agent_name, "/tmp/test-project")

            # Send task
            result = await worker.execute(task_id, payload)

            if result["status"] == "success":
                return result

            # Transient error, retry
            if attempt < max_retries:
                print(f"Task {task_id} failed, retrying (attempt {attempt})")
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

        except Exception as e:
            if attempt < max_retries:
                print(f"Error: {e}, retrying...")
                await asyncio.sleep(2 ** attempt)
            else:
                raise

    # All retries exhausted
    return {"status": "error", "error": "Max retries exceeded"}
```

---

## 5. macOS-Specific Considerations

### 5.1 tmux Issues

**Problem**: tmux may not be installed or in PATH
```python
import shutil

def check_tmux():
    """Check if tmux is available."""

    if not shutil.which("tmux"):
        raise RuntimeError("tmux not found in PATH. Install with: brew install tmux")

    # Check version
    result = subprocess.run(["tmux", "-V"], capture_output=True, text=True)
    print(f"tmux {result.stdout.strip()}")
```

**Problem**: Socket cleanup can fail on macOS
```python
import os
import stat

def force_cleanup_socket(socket_path):
    """Forcefully clean up socket file on macOS."""

    try:
        # Check if it's actually a socket
        mode = os.stat(socket_path).st_mode
        if stat.S_ISSOCK(mode):
            os.unlink(socket_path)
        else:
            print(f"{socket_path} is not a socket, skipping")
    except FileNotFoundError:
        pass  # Already deleted
    except PermissionError:
        # Might be owned by different user
        os.system(f"sudo rm -f {socket_path}")
```

### 5.2 Process Management

**Problem**: On macOS, SIGTERM may not work as expected
```python
async def kill_gracefully(pid, timeout=5):
    """Kill process gracefully, then forcefully."""

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return  # Already dead

    # Wait for graceful shutdown
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)  # Check if alive
        except ProcessLookupError:
            return  # Shutdown successful

        await asyncio.sleep(0.1)

    # Timeout, force kill
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
```

---

## 6. Performance Optimization

### 6.1 Line Buffering for stdout

**Problem**: unbuffered output causes many small reads
```python
# GOOD: Line buffered
proc = subprocess.Popen(
    [...],
    stdout=subprocess.PIPE,
    bufsize=1,  # Line buffered
    text=True
)

# BAD: Fully buffered (default), or unbuffered
proc = subprocess.Popen(
    [...],
    stdout=subprocess.PIPE,
    bufsize=-1,  # System default (bad for streaming)
)

# BAD: Unbuffered
proc = subprocess.Popen(
    [...],
    stdout=subprocess.PIPE,
    bufsize=0
)
```

### 6.2 Batch Message Processing

```python
class BatchMessageProcessor:
    """Batch progress messages for efficiency."""

    def __init__(self, batch_size=10, batch_timeout=1.0):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.batch = []
        self.last_send = time.time()

    async def add(self, progress_msg):
        """Add message to batch."""

        self.batch.append(progress_msg)

        # Send if batch full or timeout
        if len(self.batch) >= self.batch_size:
            await self.flush()
        elif time.time() - self.last_send >= self.batch_timeout:
            await self.flush()

    async def flush(self):
        """Send batch to daemon."""

        if not self.batch:
            return

        # Combine messages
        combined = "\n".join(msg["output"] for msg in self.batch)

        await ipc_client.send({
            "type": "progress",
            "output": combined,
        })

        self.batch = []
        self.last_send = time.time()
```

---

## 7. Testing Strategies

### 7.1 Unit Tests

```python
# test_ipc.py
import pytest
import asyncio
import json

@pytest.mark.asyncio
async def test_ipc_message_parsing():
    """Test IPC message parsing."""

    msg_json = '{"type": "task_complete", "status": "success"}\n'
    msg = json.loads(msg_json.strip())

    assert msg["type"] == "task_complete"
    assert msg["status"] == "success"

@pytest.mark.asyncio
async def test_worker_spawn():
    """Test worker spawning."""

    worker = await spawn_worker("test-agent", "/tmp/test")

    assert worker.pid > 0
    assert worker.state == "ready"

    # Cleanup
    await cleanup_worker(worker.id)

@pytest.mark.asyncio
async def test_heartbeat_timeout():
    """Test heartbeat timeout detection."""

    monitor = HeartbeatMonitor(timeout_seconds=2)

    # Simulate worker without heartbeat
    worker_id = "worker-test"
    monitor.last_heartbeat[worker_id] = time.time() - 5  # 5 sec ago

    dead_workers = [
        wid for wid, last_beat in monitor.last_heartbeat.items()
        if time.time() - last_beat > monitor.timeout_seconds
    ]

    assert worker_id in dead_workers
```

### 7.2 Integration Tests

```python
# test_daemon_e2e.py
@pytest.mark.asyncio
async def test_task_execution_end_to_end():
    """Test complete task execution flow."""

    # 1. Start daemon
    daemon = await start_daemon()
    await asyncio.sleep(0.5)

    # 2. Queue task
    await daemon.task_queue.insert_task(
        "task-001", "test-agent", "Test task"
    )

    # 3. Dispatch
    await daemon.dispatch_tasks()

    # 4. Wait for completion
    await asyncio.sleep(30)

    # 5. Verify result
    task = await daemon.task_queue.get_task("task-001")
    assert task["status"] == "completed"

    # 6. Cleanup
    await daemon.shutdown()
```

---

## 8. Debugging Tips

### 8.1 Enable Detailed Logging

```python
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("~/.claude-bridge/daemon.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

logger.debug(f"Starting worker {worker_id}")
logger.info(f"Task {task_id} completed")
logger.error(f"Worker {worker_id} crashed: {error}")
```

### 8.2 Monitor Socket Activity

```bash
# Watch for new sockets
watch -n 1 'ls -la /tmp/claude-bridge/'

# Monitor process tree
pstree -p | grep claude

# Check tmux sessions
tmux list-sessions

# Tail daemon log
tail -f ~/.claude-bridge/daemon.log
```

### 8.3 Inspect SQLite Queue

```bash
# Open database
sqlite3 ~/.claude-bridge/task_queue.db

# View tasks
SELECT id, status, created_at FROM tasks ORDER BY created_at DESC;

# View workers
SELECT id, state, last_heartbeat FROM workers;

# View permissions
SELECT id, status, action FROM permissions;
```

---

## 9. Scaling Considerations

### 9.1 Multiple Daemons (Future)

```
If you want to run multiple Bridge instances (for high availability):

1. Use different socket paths:
   /tmp/claude-bridge-1/daemon.sock
   /tmp/claude-bridge-2/daemon.sock

2. Use different DB files:
   ~/.claude-bridge-1/task_queue.db
   ~/.claude-bridge-2/task_queue.db

3. Use load balancer (like nginx) to distribute tasks

4. Shared SQLite → migrate to PostgreSQL (Phase 3+)
```

### 9.2 Worker Pool Sizing

```python
# Heuristic for optimal pool size
import psutil

def recommended_pool_size():
    """Recommend worker pool size based on system."""

    cpu_count = psutil.cpu_count()
    memory_mb = psutil.virtual_memory().total / (1024 * 1024)

    # Each worker: ~100 MB memory, ~0.5 CPU during execution
    memory_per_worker = 100
    max_workers_memory = int(memory_mb * 0.5 / memory_per_worker)

    # Assume 1 task per 0.5 CPU
    max_workers_cpu = int(cpu_count * 0.5)

    # Conservative estimate
    return min(max_workers_memory, max_workers_cpu, 10)
```

---

## 10. Troubleshooting Checklist

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| **Socket "Address already in use"** | Old socket persisting | `rm /tmp/claude-bridge/daemon.sock` |
| **Worker won't spawn** | Claude not in PATH | `which claude` / reinstall |
| **Permission requests timeout** | Telegram not working | Check bot token, network |
| **Memory grows unbounded** | Workers not cleaning up | Implement worker pool limits |
| **Tasks stuck in "assigned"** | Worker crashed silently | Increase heartbeat frequency |
| **macOS tmux issues** | tmux not installed | `brew install tmux` |
| **IPC messages corrupted** | Socket write race | Ensure JSON Lines format |
| **High latency (>5 sec)** | Spawn overhead | Move to Tier 2 (worker pool) |
