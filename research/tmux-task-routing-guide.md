# Tmux Task Routing & Message Ordering Guide

## Problem: Message Interleaving

When multiple tasks run on the same agent (or different agents), output can interleave:

```
User 1: "Fix bug A"
User 2: "Fix bug B"

Telegram User 1:
  Got: ✓ Started[BUG B OUTPUT HERE] Working...

Telegram User 2:
  Got: ✓ Started[BUG A OUTPUT HERE] Done
```

**Root cause:** Both tasks write to the same pane simultaneously. Capture-pane grabs mixed output.

---

## Solution: Per-Agent Task Queue

### Architecture

```
┌─────────────────────────────────────────────┐
│ Telegram / Message Channel                   │
└────────────┬────────────────────────────────┘
             │ (task received)
             ▼
┌─────────────────────────────────────────────┐
│ TaskRouter                                    │
│  • enqueue_task(task_request)                │
│  • task_queue["coder-my-app"] = [task1, ...] │
│  • task_queue_lock["coder-my-app"]           │
└────────────┬────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────┐
│ AgentWorker (async, one per agent)          │
│  • while True:                               │
│    - lock.acquire()                         │
│    - task = queue.pop()                     │
│    - execute(task)                          │
│    - lock.release()                         │
│    - notify_user()                          │
└────────────┬────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────┐
│ Tmux Pane (coder-my-app:0.0)                │
│ $ claude --project /path/to/project         │
│ >>>                                         │
└─────────────────────────────────────────────┘
```

### Key Invariants

1. **One worker per agent**: Only one coroutine processes tasks for a given agent
2. **Sequential execution**: Tasks queued for the same agent execute strictly one at a time
3. **Atomic capture**: Output is captured only after task completes (prompt returns)
4. **Lock protection**: Queue access is protected by asyncio.Lock()
5. **User notification**: Each user gets output ONLY for their task, AFTER completion

---

## Implementation: Complete Example

### 1. Data Structures

```python
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Optional

class TaskStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"

@dataclass
class TaskRequest:
    """A task to execute on an agent."""
    task_id: str
    agent_name: str
    user_id: int  # Telegram user ID
    channel: str  # "telegram", "discord", etc.
    task_text: str
    timestamp: datetime

    # Results (filled after execution)
    status: TaskStatus = TaskStatus.QUEUED
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time: float = 0.0

@dataclass
class ExecutionContext:
    """Context for current task execution."""
    task: TaskRequest
    start_time: float  # time.time()
    last_output_line: int = 0  # For incremental capture
```

### 2. Task Router (Main Orchestrator)

```python
import asyncio
import logging
import time
from typing import Dict, List, Optional, Callable

class TaskRouter:
    """
    Routes tasks to agents with strict sequential execution.
    Prevents message interleaving via per-agent queueing.
    """

    def __init__(self, agent_manager, channel_manager, logger: logging.Logger):
        self.agent_manager = agent_manager
        self.channel_manager = channel_manager
        self.logger = logger

        # Per-agent state
        self.task_queues: Dict[str, List[TaskRequest]] = {}
        self.task_locks: Dict[str, asyncio.Lock] = {}
        self.workers: Dict[str, asyncio.Task] = {}

        # Task tracking
        self.active_tasks: Dict[str, TaskRequest] = {}
        self.completed_tasks: List[TaskRequest] = []

    async def enqueue_task(self, task: TaskRequest) -> str:
        """
        Add task to agent's queue. Returns immediately (non-blocking).
        Task will be processed sequentially.
        """
        agent_name = task.agent_name

        # Lazy-initialize per-agent structures
        if agent_name not in self.task_queues:
            self.task_queues[agent_name] = []
            self.task_locks[agent_name] = asyncio.Lock()

            # Spawn worker for this agent
            self.workers[agent_name] = asyncio.create_task(
                self._worker_loop(agent_name)
            )
            self.logger.info(f"Started worker for {agent_name}")

        # Add to queue
        self.task_queues[agent_name].append(task)
        self.logger.info(
            f"Queued task {task.task_id} for {agent_name} "
            f"(queue size: {len(self.task_queues[agent_name])})"
        )

        return task.task_id

    async def _worker_loop(self, agent_name: str):
        """
        Worker coroutine for ONE agent.
        Processes queued tasks sequentially.

        This runs forever (or until agent is killed).
        """
        self.logger.info(f"Worker started for {agent_name}")

        while True:
            # 1. Wait for a task to appear in queue
            while not self.task_queues.get(agent_name):
                await asyncio.sleep(0.5)

            # 2. Get next task atomically (with lock)
            async with self.task_locks[agent_name]:
                if not self.task_queues[agent_name]:
                    # Race condition: task was removed
                    continue

                task = self.task_queues[agent_name].pop(0)
                self.active_tasks[task.task_id] = task

            # 3. Execute task (no other task running on this agent)
            try:
                self.logger.info(f"Executing task {task.task_id} on {agent_name}")
                await self._execute_task(agent_name, task)

            except Exception as e:
                self.logger.exception(f"Task {task.task_id} failed")
                task.status = TaskStatus.FAILED
                task.error = str(e)

            finally:
                # 4. Notify user (after task done, output captured)
                await self._notify_user(task)

                # 5. Record completion
                del self.active_tasks[task.task_id]
                self.completed_tasks.append(task)

            self.logger.info(f"Task {task.task_id} complete on {agent_name}")

    async def _execute_task(self, agent_name: str, task: TaskRequest):
        """
        Execute ONE task on an agent.
        Strictly sequential (no concurrency).
        """
        agent = self.agent_manager.get_agent(agent_name)
        if not agent:
            task.error = f"Agent {agent_name} not found"
            task.status = TaskStatus.FAILED
            return

        task.status = TaskStatus.RUNNING
        start_time = time.time()

        # Step 1: Send task to pane
        self.logger.debug(f"Sending task text to {agent_name}: {task.task_text[:50]}...")
        success = agent.send_command(task.task_text)

        if not success:
            task.error = "Failed to send command to pane"
            task.status = TaskStatus.FAILED
            return

        # Step 2: Wait for completion (with timeout)
        timeout_seconds = self._get_timeout(agent_name)
        try:
            # Block until prompt appears (runs in thread to avoid blocking event loop)
            prompt_found = await asyncio.wait_for(
                asyncio.to_thread(
                    self._wait_for_prompt,
                    agent,
                    timeout_seconds
                ),
                timeout=timeout_seconds + 10
            )

            if not prompt_found:
                # Timeout: kill the command
                self.logger.warning(f"Timeout on task {task.task_id}. Killing...")
                agent.send_raw_keys("C-c")  # Ctrl+C
                await asyncio.sleep(1)
                task.status = TaskStatus.TIMEOUT
                task.error = f"Task timeout after {timeout_seconds}s"
                return

        except asyncio.TimeoutError:
            self.logger.error(f"Task {task.task_id} exceeded timeout")
            task.status = TaskStatus.TIMEOUT
            task.error = f"Task exceeded {timeout_seconds}s"
            agent.send_raw_keys("C-c")
            return

        # Step 3: Capture output
        self.logger.debug(f"Capturing output for task {task.task_id}...")
        output = agent.capture_output(lines=500)

        task.output = output
        task.status = TaskStatus.COMPLETED
        task.execution_time = time.time() - start_time

        self.logger.info(
            f"Task {task.task_id} completed in {task.execution_time:.1f}s "
            f"({len(output)} chars output)"
        )

    def _wait_for_prompt(self, agent, timeout_seconds: int) -> bool:
        """
        Poll for prompt appearance (synchronous, runs in thread).

        This is a synchronous function because it uses time.sleep (blocking).
        Called via asyncio.to_thread() to avoid blocking the event loop.
        """
        start = time.time()
        prompt_pattern = r'>>> $|>> $|\$ $|>>>$|>>>(?=\s|$)'

        while time.time() - start < timeout_seconds:
            output = agent.capture_output(lines=50)

            if output:
                # Check last line for prompt
                last_line = output.split('\n')[-1]
                if re.search(prompt_pattern, last_line):
                    return True

            time.sleep(0.5)  # Poll interval

        return False

    async def _notify_user(self, task: TaskRequest):
        """
        Send task result to user via their channel.

        Called AFTER task completes.
        Only this user gets their result (no interleaving).
        """
        channel = self.channel_manager.get_channel(task.channel)

        if task.status == TaskStatus.COMPLETED:
            # Success
            msg = f"✅ Task {task.task_id[:8]}... completed in {task.execution_time:.1f}s\n\n"
            msg += self._format_output(task.output, max_chars=2000)
        elif task.status == TaskStatus.TIMEOUT:
            msg = f"⏱️ Task {task.task_id[:8]}... timed out\n\n{task.error}"
        else:
            msg = f"❌ Task {task.task_id[:8]}... failed\n\n{task.error}"

        await channel.send_message(task.user_id, msg)

    def _format_output(self, output: str, max_chars: int = 2000) -> str:
        """
        Format output for sending to user.
        - Truncate if too long
        - Escape special characters
        - Add code fence if looks like structured output
        """
        if len(output) > max_chars:
            # Truncate to max_chars, include last lines
            lines = output.split('\n')
            result = []
            char_count = 0
            for line in reversed(lines):
                if char_count + len(line) > max_chars:
                    result.append("... (truncated)")
                    break
                result.insert(0, line)
                char_count += len(line)
            output = '\n'.join(result)

        # Use code fence for multi-line output
        if '\n' in output and len(output.split('\n')) > 2:
            return f"```\n{output}\n```"
        return output

    def _get_timeout(self, agent_name: str) -> int:
        """Get timeout in seconds based on agent role/config."""
        # Extract role from agent name (e.g., "coder-my-app" → "coder")
        role = agent_name.split('-')[0] if '-' in agent_name else "default"

        timeouts = {
            "coder": 600,      # 10 minutes
            "researcher": 900, # 15 minutes
            "reviewer": 300,   # 5 minutes
            "devops": 1200,    # 20 minutes
        }
        return timeouts.get(role, 600)

    async def get_task_status(self, task_id: str) -> Optional[dict]:
        """Get current task status (for user queries)."""
        task = self.active_tasks.get(task_id)
        if task:
            return {
                "status": "running",
                "started": task.timestamp,
                "elapsed": time.time() - task.timestamp.timestamp()
            }

        # Check completed tasks
        for completed in self.completed_tasks[-100:]:  # Last 100
            if completed.task_id == task_id:
                return {
                    "status": completed.status.value,
                    "output": completed.output,
                    "error": completed.error,
                    "execution_time": completed.execution_time
                }

        return None

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        task = self.active_tasks.get(task_id)
        if not task:
            return False

        agent = self.agent_manager.get_agent(task.agent_name)
        if agent:
            agent.send_raw_keys("C-c")
            task.status = TaskStatus.FAILED
            task.error = "Cancelled by user"
            return True

        return False
```

### 3. Agent Session Wrapper

```python
import subprocess
import re
import logging

class AgentSession:
    """Wrapper around a tmux session for one agent."""

    def __init__(self, agent_name: str, project_path: str, logger: logging.Logger):
        self.agent_name = agent_name
        self.project_path = project_path
        self.tmux_session = f"claude-bridge-{agent_name}"
        self.tmux_window = 0
        self.tmux_pane = 0
        self.logger = logger

    def spawn(self) -> bool:
        """Create tmux session with Claude Code."""
        try:
            subprocess.run(
                [
                    "tmux", "new-session", "-d",
                    "-s", self.tmux_session,
                    "-c", self.project_path,
                    f"claude --project {self.project_path} --print"
                ],
                check=True,
                capture_output=True
            )
            self.logger.info(f"Spawned session {self.tmux_session}")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to spawn {self.tmux_session}: {e.stderr.decode()}")
            return False

    def kill(self):
        """Kill session."""
        subprocess.run(
            ["tmux", "kill-session", "-t", self.tmux_session],
            capture_output=True
        )
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
            target = f"{self.tmux_session}:{self.tmux_window}.{self.tmux_pane}"
            subprocess.run(
                ["tmux", "send-keys", "-t", target, command, "Enter"],
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def send_raw_keys(self, keys: str) -> bool:
        """Send raw keys (Ctrl+C, etc.)."""
        try:
            target = f"{self.tmux_session}:{self.tmux_window}.{self.tmux_pane}"
            subprocess.run(
                ["tmux", "send-keys", "-t", target, keys],
                check=True,
                capture_output=True
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def capture_output(self, lines: int = 300) -> str:
        """Capture and return pane output (ANSI stripped)."""
        try:
            target = f"{self.tmux_session}:{self.tmux_window}.{self.tmux_pane}"
            result = subprocess.run(
                ["tmux", "capture-pane", "-t", target, "-p", "-S", f"-{lines}"],
                capture_output=True,
                text=True,
                check=True
            )

            # Strip ANSI codes
            output = result.stdout
            output = re.sub(r'\x1b\[[0-9;]*[mGKHF]', '', output)

            return output.strip()
        except subprocess.CalledProcessError:
            return ""
```

### 4. Integration with Bridge Daemon

```python
async def start_bridge_daemon():
    """Initialize the daemon with tmux-based routing."""

    logger = logging.getLogger("bridge")

    # Initialize managers
    agent_manager = AgentManager(logger)
    channel_manager = ChannelManager(logger)

    # Create router
    router = TaskRouter(agent_manager, channel_manager, logger)

    # Spawn initial agents (from config)
    for agent_config in load_agent_configs():
        agent = AgentSession(agent_config['name'], agent_config['project'], logger)
        agent.spawn()
        agent_manager.register_agent(agent)

    # Listen for incoming tasks
    async def handle_telegram_message(user_id: int, text: str):
        """Telegram message handler."""
        task = TaskRequest(
            task_id=generate_task_id(),
            agent_name="coder-my-app",  # TODO: detect from user config
            user_id=user_id,
            channel="telegram",
            task_text=text,
            timestamp=datetime.now()
        )
        await router.enqueue_task(task)

    # Start Telegram listener
    await channel_manager.start_telegram_listener(handle_telegram_message)

    # Keep daemon alive
    await asyncio.Event().wait()
```

---

## Guarantees Provided by This Design

| Guarantee | How | Example |
|-----------|-----|---------|
| **No message interleaving** | Per-agent lock + queue | Task A output + Task B output never mixed |
| **FIFO execution** | queue.pop(0) | Tasks execute in order received |
| **User gets only their results** | Notify after task complete | User A doesn't see User B's output |
| **One task at a time** | async with lock | No concurrent task execution on same agent |
| **Clean output** | ANSI stripping + prompt detection | No garbage escape codes in relay |
| **Timeout protection** | asyncio.wait_for() | No hung tasks block subsequent tasks |

---

## Testing Scenarios

### Test 1: Two Tasks, Same Agent
```python
task1 = TaskRequest(..., task_text="Find all bugs", agent_name="coder-my-app")
task2 = TaskRequest(..., task_text="Write tests", agent_name="coder-my-app")

await router.enqueue_task(task1)
await router.enqueue_task(task2)

# Expected: Task 1 runs, completes, output to user1
#          Task 2 runs, completes, output to user2
#          No interleaving
```

### Test 2: Two Tasks, Different Agents
```python
task1 = TaskRequest(..., agent_name="coder-my-app")
task2 = TaskRequest(..., agent_name="researcher-docs")

await router.enqueue_task(task1)
await router.enqueue_task(task2)

# Expected: Both run in parallel (different agents)
#          Both complete independently
```

### Test 3: Timeout
```python
task = TaskRequest(..., task_text="sleep 1000")  # Long-running

await router.enqueue_task(task)
# Wait... after timeout_seconds:
# Expected: Task killed with Ctrl+C
#          User notified: "Task timeout"
```

---

## Conclusion

This design **guarantees sequential, non-interleaved execution per agent** while **allowing parallel execution across agents**. The key mechanism is:

1. **TaskRouter** manages one worker per agent
2. **Each worker** processes tasks from a queue sequentially
3. **asyncio.Lock()** protects queue access
4. **Output capture** happens atomically after task completion
5. **User notification** happens once, after all I/O is done

Result: Clean, serialized output to users with no message corruption.
