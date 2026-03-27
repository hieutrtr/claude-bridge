# Tmux-Based Session Management for Claude Bridge

## Research Overview

This document provides a complete technical analysis of using **tmux** to manage persistent Claude Code agent sessions for the Claude Bridge project. It covers command reference, task routing logic, output capture methods, and trade-offs.

---

## 1. Tmux Fundamentals for Claude Bridge

### 1.1 Core Concept

Instead of spawning new Claude Code processes for each task, use tmux to:
1. **Create one tmux session per agent** (e.g., `claude-bridge-coder-my-app`)
2. **Run Claude Code once** inside that session with persistent stdin/stdout
3. **Send commands** to the session via `tmux send-keys`
4. **Capture output** from the pane buffer
5. **Attach/detach** without killing the session

### 1.2 Why Tmux?

**Advantages:**
- Sessions **persist across network interruptions** (SSH dropouts, Telegram reconnects)
- No startup overhead for subsequent tasks (Claude Code loads once)
- User can **manually attach** and debug if needed: `tmux attach -t claude-bridge-coder-my-app`
- Natural **window routing** via `select-window` for multiple agents
- Built-in **history buffer** for output capture
- Proven in production (used by DevOps, CI/CD, remote systems)

**Trade-offs:**
- Added complexity: need to parse pane buffer, handle escape sequences
- User visibility: unless user attaches, they only see what Bridge relays
- Message interleaving: must serialize output carefully (see section 4)
- Process lingering: must explicitly kill sessions or use timeout

---

## 2. Tmux Command Reference for Python Integration

### 2.1 Session Lifecycle Commands

```bash
# Create session (does NOT attach to terminal)
tmux new-session -d -s SESSION_NAME -c /working/dir

# Kill session gracefully
tmux kill-session -t SESSION_NAME

# List all sessions
tmux list-sessions

# Check if session exists
tmux has-session -t SESSION_NAME 2>/dev/null && echo "exists" || echo "not found"

# Get session state (list-sessions with format)
tmux list-sessions -F "#{session_name} #{session_windows} #{session_attached}"
```

### 2.2 Window Management Commands

```bash
# Create window in session
tmux new-window -t SESSION_NAME -n WINDOW_NAME

# Send keys to pane (executes command)
tmux send-keys -t SESSION_NAME:WINDOW_NAME.PANE_IDX "command arg1 arg2" Enter

# Select window (route to specific agent)
tmux select-window -t SESSION_NAME:WINDOW_IDX

# List windows in session
tmux list-windows -t SESSION_NAME -F "#{window_index} #{window_name}"

# Kill window
tmux kill-window -t SESSION_NAME:WINDOW_NAME
```

### 2.3 Pane Capture & Output Commands

```bash
# Capture visible pane content
tmux capture-pane -t SESSION_NAME:WINDOW_NAME.PANE_IDX -p

# Capture with history (N lines of scrollback)
tmux capture-pane -t SESSION_NAME:WINDOW_NAME.PANE_IDX -p -S -300

# Capture to file
tmux capture-pane -t SESSION_NAME:WINDOW_NAME.PANE_IDX -p > pane_output.txt

# Get pane dimensions (useful for output parsing)
tmux display-message -t SESSION_NAME:WINDOW_NAME.PANE_IDX -p \
  "#{pane_width}x#{pane_height}"
```

### 2.4 Monitoring & Status Commands

```bash
# Check pane is alive (exit code 0 if exists)
tmux list-panes -t SESSION_NAME:WINDOW_NAME -F "#{pane_pid}" | grep -q . && echo "alive"

# Get pane command (what process is running)
tmux display-message -t SESSION_NAME:WINDOW_NAME.PANE_IDX -p "#{pane_current_command}"

# Wait for pane to finish (poll until command completes)
# Method: check if pane_pid changes or capture-pane shows prompt

# Kill pane/window
tmux kill-pane -t SESSION_NAME:WINDOW_NAME.PANE_IDX
```

---

## 3. Python Integration: Sending Commands & Capturing Output

### 3.1 Sending Commands to a Pane

```python
import subprocess
import time

def send_command_to_pane(session: str, window: int, pane: int, command: str) -> bool:
    """
    Send a command to a tmux pane.

    Args:
        session: Session name (e.g., "claude-bridge-coder-my-app")
        window: Window index (0, 1, 2, ...)
        pane: Pane index (0 for single pane)
        command: Command to execute (without Enter)

    Returns:
        True if successful, False otherwise
    """
    target = f"{session}:{window}.{pane}"
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", target, command, "Enter"],
            check=True,
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to send command: {e.stderr.decode()}")
        return False


def send_command_raw(session: str, window: int, pane: int, keys: str) -> bool:
    """
    Send raw keys to tmux pane (without Enter).
    Useful for: Ctrl-C, Ctrl-D, arrow keys, etc.
    """
    target = f"{session}:{window}.{pane}"
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", target, keys],
            check=True,
            capture_output=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

# Usage Examples
send_command_to_pane("claude-bridge-coder-my-app", 0, 0, "Fix the login bug")
send_command_raw("claude-bridge-coder-my-app", 0, 0, "C-c")  # Send Ctrl+C
```

### 3.2 Capturing Output from a Pane

```python
import subprocess
import re
from typing import Optional

def capture_pane_output(
    session: str,
    window: int,
    pane: int,
    lines: int = 300,
    strip_ansi: bool = True
) -> Optional[str]:
    """
    Capture output from a tmux pane.

    Args:
        session: Session name
        window: Window index
        pane: Pane index
        lines: Number of history lines to capture (scrollback)
        strip_ansi: Remove ANSI escape codes (colors, formatting)

    Returns:
        Output text or None if capture fails
    """
    target = f"{session}:{window}.{pane}"
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}"],
            capture_output=True,
            text=True,
            check=True
        )

        output = result.stdout

        # Strip ANSI escape sequences (color codes, cursor moves, etc.)
        if strip_ansi:
            ansi_pattern = re.compile(r'\x1b\[[0-9;]*[mGKHF]')
            output = ansi_pattern.sub('', output)

        return output.strip()
    except subprocess.CalledProcessError as e:
        print(f"Failed to capture pane: {e.stderr.decode()}")
        return None


def capture_new_output(
    session: str,
    window: int,
    pane: int,
    last_line_count: int = 0,
    strip_ansi: bool = True
) -> tuple[str, int]:
    """
    Capture only NEW output since last capture.

    Args:
        session, window, pane: Target pane
        last_line_count: Number of lines captured in previous call
        strip_ansi: Remove ANSI codes

    Returns:
        Tuple of (new_output, current_line_count)
    """
    full_output = capture_pane_output(session, window, pane, lines=500, strip_ansi=strip_ansi)

    if not full_output:
        return "", 0

    lines = full_output.split('\n')
    new_output = '\n'.join(lines[last_line_count:])

    return new_output, len(lines)


# Usage Examples
output = capture_pane_output("claude-bridge-coder-my-app", 0, 0, lines=100)
print("Full output:", output)

new_output, line_count = capture_new_output("claude-bridge-coder-my-app", 0, 0, last_line_count=50)
print("New output since line 50:", new_output)
```

### 3.3 Detecting Task Completion

```python
import re
import time
from typing import Optional

def wait_for_prompt(
    session: str,
    window: int,
    pane: int,
    timeout_seconds: int = 300,
    poll_interval: float = 0.5,
    prompt_pattern: str = r">>> $|>> $|\$ $"  # Common prompts
) -> bool:
    """
    Wait for a command to complete (prompt appears again).

    Args:
        session, window, pane: Target pane
        timeout_seconds: Max time to wait
        poll_interval: Check output every N seconds
        prompt_pattern: Regex to detect prompt

    Returns:
        True if prompt detected, False if timeout
    """
    start_time = time.time()
    last_output = ""

    while time.time() - start_time < timeout_seconds:
        output = capture_pane_output(session, window, pane, lines=50)

        if output and re.search(prompt_pattern, output.split('\n')[-1]):
            return True

        last_output = output
        time.sleep(poll_interval)

    print(f"Timeout waiting for prompt. Last output:\n{last_output}")
    return False


def detect_task_completion(session: str, window: int, pane: int) -> Optional[dict]:
    """
    Detect if Claude Code task completed (not foolproof, needs refinement).

    Returns dict with:
        - completed: bool
        - exit_code: int or None
        - output: str (last N lines)
    """
    output = capture_pane_output(session, window, pane, lines=50)

    if not output:
        return {"completed": False, "exit_code": None, "output": ""}

    lines = output.split('\n')
    last_line = lines[-1] if lines else ""

    # Heuristics for completion:
    # 1. Prompt visible at end
    # 2. "Task completed" message
    # 3. Exit code visible

    completion_markers = [
        r">>> $",
        r"Task completed",
        r"✓ Done",
        r"agent exited with code"
    ]

    is_complete = any(re.search(marker, last_line) for marker in completion_markers)

    return {
        "completed": is_complete,
        "output": '\n'.join(lines[-10:]),  # Last 10 lines
        "exit_code": None  # TODO: parse from output
    }

# Usage
if wait_for_prompt("claude-bridge-coder-my-app", 0, 0, timeout_seconds=60):
    result = detect_task_completion("claude-bridge-coder-my-app", 0, 0)
    print(f"Completed: {result['completed']}")
    print(f"Output: {result['output']}")
else:
    print("Task timed out")
```

---

## 4. Task Routing & Message Interleaving Prevention

### 4.1 The Interleaving Problem

**Scenario:**
- User sends task via Telegram
- Bridge sends it to Agent 1 window
- Agent 1 is still processing a previous task
- Output from Agent 1 + output from Agent 2 get mixed up in Telegram relay

**Solution: Strict Serialization**

### 4.2 Task Queue & Locking Pattern

```python
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

@dataclass
class TaskRequest:
    """A task to be executed on an agent."""
    task_id: str
    agent_name: str
    user_id: int  # Telegram user
    task_text: str
    timestamp: datetime

    # Results (populated after execution)
    output: Optional[str] = None
    exit_code: Optional[int] = None
    completed: bool = False
    error: Optional[str] = None


class TaskRouter:
    """
    Routes tasks to agents while preventing message interleaving.

    Design:
    1. Each agent has ONE window in tmux
    2. Tasks for that agent are queued
    3. Only ONE task executes at a time per agent
    4. Output is captured atomically, sent to user before next task
    """

    def __init__(self, bridge_daemon):
        self.daemon = bridge_daemon

        # Per-agent locks (mutex): task_queue_lock[agent_name] = asyncio.Lock()
        self.task_queue_lock = {}

        # Per-agent task queues: task_queue[agent_name] = [TaskRequest, ...]
        self.task_queue = {}

        # Per-agent worker tasks: worker[agent_name] = asyncio.Task
        self.workers = {}

        self.logger = logging.getLogger(__name__)

    async def enqueue_task(self, request: TaskRequest) -> str:
        """
        Add task to agent's queue. Returns task_id for tracking.
        """
        agent_name = request.agent_name

        # Lazy-initialize agent's queue & lock
        if agent_name not in self.task_queue:
            self.task_queue[agent_name] = []
            self.task_queue_lock[agent_name] = asyncio.Lock()
            # Start worker for this agent
            self.workers[agent_name] = asyncio.create_task(
                self._worker_loop(agent_name)
            )

        self.task_queue[agent_name].append(request)
        self.logger.info(f"Task {request.task_id} queued for {agent_name}")

        return request.task_id

    async def _worker_loop(self, agent_name: str):
        """
        Worker coroutine: processes tasks for one agent sequentially.
        Ensures no interleaving.
        """
        while True:
            # Wait for task or idle
            while not self.task_queue.get(agent_name):
                await asyncio.sleep(0.5)

            # Get next task atomically
            async with self.task_queue_lock[agent_name]:
                if not self.task_queue[agent_name]:
                    continue

                task = self.task_queue[agent_name].pop(0)

            try:
                await self._execute_task(agent_name, task)
            except Exception as e:
                self.logger.error(f"Task {task.task_id} failed: {e}")
                task.error = str(e)
            finally:
                # Notify user (via Telegram)
                await self._relay_result(task)

    async def _execute_task(self, agent_name: str, task: TaskRequest):
        """
        Execute ONE task on an agent:
        1. Send command to tmux pane
        2. Wait for completion (prompt reappears)
        3. Capture output
        4. Populate task.output, task.exit_code, task.completed
        """
        agent = self.daemon.agents.get(agent_name)
        if not agent:
            task.error = f"Agent {agent_name} not found"
            return

        # Send task to agent (to tmux pane)
        window_idx = agent.tmux_window
        pane_idx = 0

        self.logger.info(f"Executing task {task.task_id} on {agent_name}")

        # Send the task text
        success = send_command_to_pane(
            agent.tmux_session,
            window_idx,
            pane_idx,
            task.task_text
        )

        if not success:
            task.error = "Failed to send command to pane"
            return

        # Wait for completion (prompt)
        completed = await asyncio.to_thread(
            wait_for_prompt,
            agent.tmux_session,
            window_idx,
            pane_idx,
            timeout_seconds=300
        )

        if not completed:
            task.error = "Task timeout (prompt not detected)"
            return

        # Capture output
        task.output = capture_pane_output(
            agent.tmux_session,
            window_idx,
            pane_idx,
            lines=500
        )
        task.completed = True

    async def _relay_result(self, task: TaskRequest):
        """
        Send task result back to user via Telegram (or other channel).
        This is done AFTER task completes, so no interleaving.
        """
        channel = self.daemon.get_channel(task.user_id)

        if task.completed:
            await channel.send_message(
                task.user_id,
                f"✅ Task {task.task_id} completed:\n\n{task.output}"
            )
        else:
            await channel.send_message(
                task.user_id,
                f"❌ Task {task.task_id} failed:\n\n{task.error}"
            )

# Usage
router = TaskRouter(bridge_daemon)

# User sends task via Telegram
request = TaskRequest(
    task_id="task_001",
    agent_name="coder-my-app",
    user_id=12345,
    task_text="Fix the login bug",
    timestamp=datetime.now()
)

task_id = await router.enqueue_task(request)
# → Task queued, worker will execute it when ready
```

### 4.3 Window-per-Agent Pattern

Instead of a single window, use **one window per agent**:

```python
class AgentSession:
    """Persistent tmux session for an agent."""

    def __init__(self, agent_name: str, project_path: str):
        self.agent_name = agent_name
        self.tmux_session = f"claude-bridge-{agent_name}"
        self.tmux_window = 0  # Always window 0 for this agent
        self.tmux_pane = 0

    def spawn(self):
        """Create tmux session and start Claude Code."""
        subprocess.run(
            [
                "tmux", "new-session",
                "-d",  # detached
                "-s", self.tmux_session,
                "-c", self.project_path,
                # Start Claude Code in interactive mode
                f"claude --project {self.project_path} --print"
            ],
            check=True
        )

    def kill(self):
        """Destroy session."""
        subprocess.run(
            ["tmux", "kill-session", "-t", self.tmux_session],
            check=False  # Session might not exist
        )

    def is_alive(self) -> bool:
        """Check if session exists."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.tmux_session],
            capture_output=True
        )
        return result.returncode == 0

# Multi-agent setup
agents = {
    "coder-my-app": AgentSession("coder-my-app", "/home/user/projects/my-app"),
    "researcher-docs": AgentSession("researcher-docs", "/home/user/projects/docs"),
}

# Launch all agents
for agent in agents.values():
    agent.spawn()

# Route tasks by agent_name:
# Task for coder → send to agents["coder-my-app"].tmux_session:0.0
# Task for researcher → send to agents["researcher-docs"].tmux_session:0.0
```

---

## 5. Output Capture & ANSI Stripping

### 5.1 ANSI Escape Code Challenge

Claude Code outputs **colored text** via ANSI sequences:
```
\x1b[92m✓ Task started\x1b[0m
\x1b[31mERROR: Something failed\x1b[0m
```

When captured from tmux and relayed to Telegram (plain text), these codes clutter the output.

### 5.2 ANSI Stripping Solution

```python
import re

ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[mGKHF]')

def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences."""
    return ANSI_ESCAPE.sub('', text)

# Comprehensive ANSI removal (handles more complex sequences)
def strip_ansi_comprehensive(text: str) -> str:
    """Remove all ANSI sequences."""
    # Matches:
    # - \x1b[...m (color/style)
    # - \x1b[...H (cursor movement)
    # - \x1b[...K (erase line)
    # - CSI sequences (more general)
    ansi_escape = re.compile(r'''
        \x1B  # ESC
        (?:   # 7-bit C1 Fe (except CSI)
            [@-Z\\-_]
        |     # or [ for CSI, followed by parameter bytes + intermediate bytes + final byte
            \[0-?]*[ -/]*[@-~]
        )
    ''', re.VERBOSE)
    return ansi_escape.sub('', text)

# Test
colored_text = "\x1b[92m✓ Done\x1b[0m Failed here: \x1b[31mERROR\x1b[0m"
print(strip_ansi(colored_text))
# Output: "✓ Done Failed here: ERROR"
```

### 5.3 Incremental Output Capture

For **long-running tasks**, capture output incrementally:

```python
async def stream_task_output(
    agent_name: str,
    session: str,
    window: int,
    pane: int,
    task_id: str,
    callback: callable
):
    """
    Stream output to user as task executes (instead of waiting for completion).

    Args:
        callback: async function(chunk: str) to send output chunks to user
    """
    last_lines = 0
    chunk_delay = 2.0  # Send chunks every 2 seconds

    while True:
        new_output, line_count = capture_new_output(
            session, window, pane,
            last_line_count=last_lines,
            strip_ansi=True
        )

        if new_output.strip():
            await callback(new_output)

        # Check if task completed
        result = detect_task_completion(session, window, pane)
        if result["completed"]:
            # Send final chunk
            final_output = capture_pane_output(session, window, pane, lines=100)
            await callback(f"\n✓ Task completed")
            break

        last_lines = line_count
        await asyncio.sleep(chunk_delay)
```

---

## 6. Handling Long-Running Tasks & Timeouts

### 6.1 Timeout Strategy

```python
import signal

class TaskTimeout:
    """Handle task timeouts gracefully."""

    # Default timeout per agent role
    TIMEOUTS = {
        "coder": 600,      # 10 minutes
        "researcher": 900, # 15 minutes
        "reviewer": 300,   # 5 minutes
        "devops": 1200,    # 20 minutes
    }

    @staticmethod
    def get_timeout(agent_name: str) -> int:
        """Get timeout in seconds based on agent role."""
        role = agent_name.split('-')[0]  # Extract role from "coder-my-app"
        return TaskTimeout.TIMEOUTS.get(role, 600)

    @staticmethod
    async def timeout_task(
        agent_name: str,
        session: str,
        window: int,
        pane: int,
        task_id: str,
        callback: callable
    ):
        """
        Execute task with timeout. If timeout, kill it gracefully.
        """
        timeout_seconds = TaskTimeout.get_timeout(agent_name)

        try:
            # Wait for prompt (with timeout)
            completed = await asyncio.wait_for(
                asyncio.to_thread(
                    wait_for_prompt,
                    session, window, pane,
                    timeout_seconds=timeout_seconds
                ),
                timeout=timeout_seconds + 10  # asyncio timeout slightly higher
            )

            if completed:
                output = capture_pane_output(session, window, pane)
                await callback({
                    "status": "completed",
                    "output": output,
                    "task_id": task_id
                })
            else:
                await callback({
                    "status": "timeout",
                    "message": f"Task timed out after {timeout_seconds}s",
                    "task_id": task_id
                })
                # Kill the hung command
                send_command_raw(session, window, pane, "C-c")

        except asyncio.TimeoutError:
            await callback({
                "status": "timeout",
                "message": f"Task exceeded {timeout_seconds}s timeout",
                "task_id": task_id
            })
            # Force kill
            send_command_raw(session, window, pane, "C-c")
            await asyncio.sleep(2)
            send_command_raw(session, window, pane, "C-d")  # Exit shell if Ctrl+C didn't work
```

### 6.2 Session Recovery After Crash

```python
async def ensure_agent_alive(agent: AgentSession):
    """Check if agent session is alive. Respawn if dead."""
    if not agent.is_alive():
        logger.warning(f"Agent {agent.agent_name} session crashed. Respawning...")
        agent.spawn()
        await asyncio.sleep(3)  # Give Claude Code time to start
```

---

## 7. Permission Relay (Telegram Integration)

### 7.1 Permission Dialog Pattern

When Claude Code tries to execute a **blocked action** (e.g., `git push`), the tmux approach integrates with the permission relay:

```python
async def handle_permission_request(
    agent_name: str,
    session: str,
    window: int,
    pane: int,
    action: str,
    context: str,
    user_id: int
) -> bool:
    """
    Pause agent, ask user for permission via Telegram.
    Resume or cancel based on user's response.
    """
    # Send Ctrl+C to pause current command
    send_command_raw(session, window, pane, "C-c")

    # Ask user via Telegram
    keyboard = [
        [{"text": "✅ Allow", "callback_data": f"allow_{action}"}],
        [{"text": "❌ Deny", "callback_data": f"deny_{action}"}]
    ]

    approved = await get_user_approval(
        user_id,
        f"Agent {agent_name} wants to: {action}\n\nContext: {context}",
        keyboard
    )

    if approved:
        # Resume command
        send_command_to_pane(session, window, pane, "# [USER APPROVED]")
        return True
    else:
        # Cancel
        send_command_raw(session, window, pane, "C-d")  # EOF
        return False
```

---

## 8. Trade-offs & Decision Matrix

### 8.1 Tmux vs. Process Subprocess Approaches

| Aspect | Tmux Sessions | Fresh Process per Task | Process Pool |
|--------|---------------|----------------------|--------------|
| **Startup overhead** | None (reuse) | High (cold start) | Medium |
| **Session persistence** | ✅ Yes | ❌ No | ❌ No |
| **User visibility** | ✅ Can attach | ❌ Hidden | ❌ Hidden |
| **Message interleaving** | Solvable (queue) | Built-in separation | Requires locking |
| **Complexity** | Higher | Lower | Medium |
| **Recovery (network) | ✅ Survives SSH drop | ❌ Dies | ❌ Dies |
| **Memory footprint** | 1x Claude per agent | Nx Claude for N tasks | M x Claude for pool size M |
| **Debugging ease** | ✅ Attach & inspect | ❌ Process gone | Medium |
| **Task timeout/kill** | Send Ctrl+C | SIGTERM/SIGKILL | SIGTERM/SIGKILL |

**Verdict for Claude Bridge:**
- **MVP:** Tmux sessions ✅ (matches design in DESIGN.md section 4.3)
- **Phase 2:** Consider process pool if memory is bottleneck

### 8.2 Visibility Trade-offs

**Tmux advantage:**
```
User can manually attach: tmux attach -t claude-bridge-coder-my-app
See live output, even if Bridge relay is slow/broken
Debug directly in the session
```

**Tmux complexity:**
```
Must parse pane buffer carefully
ANSI codes need stripping
Capture-pane can be slow for large buffers
Escape sequences from cursor movement, colors, etc.
```

**Mitigation:**
- Use `strip_ansi` consistently
- Limit capture to last 500 lines (not entire history)
- Cache last_line_count to avoid recapturing everything

---

## 9. Implementation Roadmap

### Phase 1: Core Infrastructure

```python
# 1. AgentSession class (spawn/kill/is_alive)
# 2. send_command_to_pane() function
# 3. capture_pane_output() function
# 4. strip_ansi() function
# 5. TaskRouter with per-agent queueing
# 6. wait_for_prompt() polling loop
```

### Phase 2: Reliability

```python
# 7. Session recovery (crash detection + respawn)
# 8. Timeout handling (Ctrl+C, Ctrl+D)
# 9. Incremental output streaming
# 10. Permission relay integration
```

### Phase 3: Polish

```python
# 11. User can /attach session
# 12. Session statistics (duration, output size, etc.)
# 13. Historical logs per session
# 14. Error reporting with context
```

---

## 10. Example: Full Workflow

```python
# Setup
agents = {
    "coder-my-app": AgentSession("coder-my-app", "/home/user/projects/my-app")
}

for agent in agents.values():
    agent.spawn()  # Create tmux session

router = TaskRouter(bridge_daemon)

# User sends task
task = TaskRequest(
    task_id="task_001",
    agent_name="coder-my-app",
    user_id=12345,
    task_text="Fix the login bug",
    timestamp=datetime.now()
)

await router.enqueue_task(task)

# Router's worker loop:
# 1. Acquires lock for "coder-my-app"
# 2. Sends "Fix the login bug" to tmux pane
# 3. Waits for prompt
# 4. Captures output
# 5. Strips ANSI codes
# 6. Sends to Telegram
# 7. Moves to next task in queue

# User can also inspect live:
# $ tmux attach -t claude-bridge-coder-my-app
# → See Claude Code running live
```

---

## 11. Comparison: Tmux vs. Current Design

Current DESIGN.md (section 4.3) mentions:
```
Each agent:
- Runs in tmux for persistence
- Reads its own profile.yaml
- Reads generated CLAUDE.md
- Reports back to Bridge
```

This research **validates & expands** that design:
- ✅ Confirmed tmux is viable for persistence
- ✅ Provided concrete command reference
- ✅ Showed how to send commands & capture output
- ✅ Solved message interleaving via TaskRouter
- ✅ Outlined ANSI stripping & timeout handling
- ✅ Defined window-per-agent routing pattern

---

## 12. Conclusion & Recommendations

**For Claude Bridge MVP:**

1. **Use tmux sessions** (confirms existing design)
2. **One session per agent**, one window per agent
3. **TaskRouter with per-agent queue** prevents interleaving
4. **ANSI stripping + incremental output** for clean relay
5. **Timeout + recovery** for reliability

**Key commands to implement:**
- `tmux send-keys` (send commands)
- `tmux capture-pane` (get output)
- `tmux has-session` (check alive)
- `tmux kill-session` (cleanup)

**Next steps:**
- Implement `AgentSession` class (wrapper around tmux)
- Implement `TaskRouter` with asyncio locking
- Integration test with real Claude Code process
- Performance test (output capture speed, memory usage)

---

## Appendix A: Complete Code Skeleton

```python
# agent_session.py
import subprocess
import logging

class AgentSession:
    def __init__(self, agent_name: str, project_path: str):
        self.agent_name = agent_name
        self.tmux_session = f"claude-bridge-{agent_name}"
        self.project_path = project_path
        self.logger = logging.getLogger(f"agent.{agent_name}")

    def spawn(self):
        """Spawn Claude Code in tmux."""
        try:
            subprocess.run(
                ["tmux", "new-session", "-d", "-s", self.tmux_session,
                 "-c", self.project_path,
                 f"cd {self.project_path} && claude --project {self.project_path}"],
                check=True
            )
            self.logger.info(f"Spawned session {self.tmux_session}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to spawn: {e}")
            raise

    def kill(self):
        """Kill session."""
        subprocess.run(["tmux", "kill-session", "-t", self.tmux_session],
                      capture_output=True)
        self.logger.info(f"Killed session {self.tmux_session}")

    def is_alive(self) -> bool:
        """Check if session exists."""
        return subprocess.run(
            ["tmux", "has-session", "-t", self.tmux_session],
            capture_output=True
        ).returncode == 0

    def send_command(self, command: str) -> bool:
        """Send command to pane."""
        try:
            subprocess.run(
                ["tmux", "send-keys", "-t", f"{self.tmux_session}:0.0", command, "Enter"],
                check=True, capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def capture_output(self, lines: int = 300, strip_ansi: bool = True) -> str:
        """Capture pane output."""
        try:
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", f"{self.tmux_session}:0.0",
                 "-p", "-S", f"-{lines}"],
                capture_output=True, text=True, check=True
            )
            output = result.stdout
            if strip_ansi:
                output = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', output)
            return output.strip()
        except subprocess.CalledProcessError:
            return ""
```

---

**End of Research Document**
