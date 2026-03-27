# Agent Lifecycle Specification

## Overview

Agents are persistent Claude Code sessions, each tied to a specific project. The Bridge Bot (session #0) dispatches tasks to agents via `claude -p --session-id`. Agents accumulate context across tasks — they remember previous work.

**Key principle:** Each agent = one `--session-id` + one `--project-dir`. No stdin/stdout piping, no tmux, no IPC. Just `claude -p` calls tracked in SQLite.

---

## 1. Architecture

### 1.1 Dispatch Model

```
Telegram ←MCP→ Bridge Bot (Claude Code session #0)
                    │
                    │  Dispatches via CLI
                    ├──→ claude -p "task" --session-id agent-api --project-dir /projects/api
                    ├──→ claude -p "task" --session-id agent-web --project-dir /projects/web
                    └──→ claude -p "task" --session-id agent-ml  --project-dir /projects/ml

                    │  Tracks in SQLite
                    └──→ tasks.db (agents, tasks, status)

                    │  Monitors via cron/loop
                    └──→ Watcher checks PIDs + reads results → reports to Telegram
```

### 1.2 Key Insight

Each `claude -p` call is a **blocking subprocess**. It runs, completes, and exits. The `--session-id` ensures the next task for the same agent resumes the same conversation context.

---

## 2. Agent States

### 2.1 Simplified State Machine

```
┌──────────┐
│ CREATED  │  Agent registered in SQLite, no tasks yet
└────┬─────┘
     │ first task dispatched
     ▼
┌──────────┐
│  IDLE    │  Session exists, waiting for next task
└────┬─────┘
     │ task assigned
     ▼
┌──────────┐      ┌──────────┐
│ RUNNING  │─────→│  IDLE    │  task completed → ready for next
└────┬─────┘      └──────────┘
     │
     ├─────────────┐
     ▼             ▼
┌──────────┐  ┌──────────┐
│  FAILED  │  │ TIMEOUT  │
└──────────┘  └──────────┘
```

### 2.2 State Definitions

```python
class AgentState(Enum):
    CREATED = "created"       # Registered, never ran
    IDLE = "idle"             # Session exists, no active task
    RUNNING = "running"       # claude -p process active (PID tracked)
    FAILED = "failed"         # Last task failed
    TIMEOUT = "timeout"       # Last task timed out
```

---

## 3. Agent Registration

### 3.1 SQLite Schema

```sql
CREATE TABLE agents (
    name TEXT PRIMARY KEY,           -- e.g., "api-backend"
    project_dir TEXT NOT NULL,       -- /Users/hieutran/projects/my-api
    session_id TEXT NOT NULL UNIQUE, -- "agent-api-backend"
    state TEXT DEFAULT 'created',    -- created/idle/running/failed/timeout
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_task_at TIMESTAMP,
    total_tasks INTEGER DEFAULT 0,
    description TEXT                 -- optional: "Backend API agent"
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL REFERENCES agents(name),
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'pending',   -- pending/running/done/failed/timeout
    pid INTEGER,                     -- OS process ID when running
    result_file TEXT,                -- path to JSON result file
    result_summary TEXT,             -- brief summary for Telegram
    exit_code INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    reported INTEGER DEFAULT 0       -- 0=not reported, 1=sent to Telegram
);
```

### 3.2 Creating an Agent

From Telegram:
```
/create-agent api-backend /Users/hieutran/projects/my-api "Backend API development"
```

Bridge Bot executes:
```sql
INSERT INTO agents (name, project_dir, session_id, description)
VALUES ('api-backend', '/Users/hieutran/projects/my-api', 'agent-api-backend', 'Backend API development');
```

No process is spawned. The agent is just registered.

---

## 4. Task Dispatch

### 4.1 Dispatching a Task

From Telegram:
```
/task api-backend add pagination to the /users endpoint
```

Bridge Bot:
1. Looks up agent in SQLite
2. Inserts task row (`status=pending`)
3. Spawns `claude -p` as background subprocess
4. Updates task with PID (`status=running`)

### 4.2 The CLI Command

```bash
claude -p "add pagination to the /users endpoint" \
  --session-id agent-api-backend \
  --project-dir /Users/hieutran/projects/my-api \
  --output-format json \
  > /tmp/claude-bridge/task-42-result.json 2>&1
```

Flags:
- `-p "prompt"` — non-interactive, run and exit
- `--session-id` — resume same conversation (context persists)
- `--project-dir` — work in the project directory
- `--output-format json` — structured output for parsing

### 4.3 Spawn Logic

```python
class TaskDispatcher:
    """Dispatch tasks to agent sessions."""

    def dispatch(self, agent_name: str, prompt: str) -> int:
        """
        Dispatch task to agent.

        Returns:
            task_id

        Process:
            1. Look up agent in SQLite (validate exists)
            2. Check agent not already running a task
               - If running: queue task (status=pending) or reject
            3. Insert task row (status=pending)
            4. Build CLI command
            5. Spawn subprocess (background, non-blocking)
            6. Update task with PID (status=running)
            7. Update agent state (state=running)
            8. Return task_id
        """
        pass

    def _build_command(self, agent: Agent, task: Task) -> list[str]:
        """
        Build claude CLI command.

        Returns:
            Command as list for subprocess.Popen
        """
        result_file = f"/tmp/claude-bridge/task-{task.id}-result.json"
        return [
            "claude", "-p", task.prompt,
            "--session-id", agent.session_id,
            "--project-dir", agent.project_dir,
            "--output-format", "json",
        ]

    def _spawn(self, command: list[str], result_file: str) -> int:
        """
        Spawn claude process in background.

        Returns:
            PID of spawned process

        Implementation:
            - subprocess.Popen with stdout redirected to result_file
            - Non-blocking (don't wait for completion)
            - Store PID for monitoring
        """
        pass
```

### 4.4 Sequential Task Handling

If an agent is already running a task:
- **Option A (MVP):** Reject with message "Agent busy, try later"
- **Option B (Phase 2):** Queue the task (status=pending), process when current finishes

```python
def dispatch(self, agent_name: str, prompt: str) -> int:
    agent = self.db.get_agent(agent_name)

    # Check if busy
    running_task = self.db.get_running_task(agent_name)
    if running_task:
        raise AgentBusyError(f"{agent_name} is running task #{running_task.id}")

    # Dispatch
    task_id = self.db.insert_task(agent_name, prompt)
    pid = self._spawn(self._build_command(agent, task), result_file)
    self.db.update_task(task_id, status="running", pid=pid)
    self.db.update_agent_state(agent_name, "running")
    return task_id
```

---

## 5. Task Monitoring (Cron/Loop Watcher)

### 5.1 Watcher Purpose

A background process that:
1. Checks if running tasks have completed (PID no longer alive)
2. Reads result files
3. Updates SQLite
4. Reports completions back to Telegram

### 5.2 Watcher Logic

```python
class TaskWatcher:
    """Monitor running tasks and report completions."""

    def check_running_tasks(self) -> list[CompletedTask]:
        """
        Check all tasks with status='running'.

        For each:
            1. Check if PID is still alive (os.kill(pid, 0))
            2. If dead:
               a. Read result file
               b. Parse exit code and output
               c. Update task status (done/failed)
               d. Update agent state (idle/failed)
            3. If alive but exceeded timeout:
               a. Kill process (SIGTERM → SIGKILL)
               b. Mark as timeout

        Returns:
            List of newly completed tasks
        """
        pass

    def report_completions(self, completed: list[CompletedTask]) -> None:
        """
        Send completion reports to Telegram.

        For each completed task:
            1. Format summary message
            2. Send via Telegram MCP
            3. Mark task as reported=1

        Message format:
            ✓ Task #42 (api-backend) — done in 2m 15s
            Added pagination to /users endpoint.
            Files changed: src/routes/users.ts, src/utils/paginate.ts
        """
        pass

    def check_stale_tasks(self, max_age_hours: int = 2) -> None:
        """
        Find tasks running longer than max_age.
        Kill and mark as timeout.
        """
        pass
```

### 5.3 Running the Watcher

Two options:

**Option A: Cron job (every 1-5 minutes)**
```bash
# crontab
*/2 * * * * python3 ~/.claude-bridge/watcher.py
```

**Option B: Bridge Bot loop (via /loop skill)**
```
/loop 2m check-tasks
```

The watcher is a simple script that:
1. Opens SQLite
2. Queries running tasks
3. Checks PIDs
4. Updates status
5. Sends Telegram messages for completions
6. Exits

---

## 6. Agent Manager

### 6.1 AgentManager Class

```python
class AgentManager:
    """Manage agent lifecycle."""

    def create_agent(self, name: str, project_dir: str,
                     description: str = None) -> Agent:
        """
        Register a new agent.

        Process:
            1. Validate project_dir exists
            2. Generate session_id (f"agent-{name}")
            3. Insert into agents table
            4. Return Agent object

        No process spawned — agent is just registered.
        """
        pass

    def delete_agent(self, name: str) -> None:
        """
        Delete agent registration.

        Process:
            1. Kill any running task
            2. Delete from agents table
            3. Delete task history (optional, configurable)
        """
        pass

    def list_agents(self) -> list[Agent]:
        """List all registered agents with current state."""
        pass

    def get_agent_status(self, name: str) -> AgentStatus:
        """
        Get agent status.

        Returns:
            AgentStatus with:
            - state (idle/running/failed)
            - current task (if running)
            - total tasks completed
            - last task timestamp
        """
        pass

    def dispatch_task(self, agent_name: str, prompt: str) -> int:
        """Delegate to TaskDispatcher."""
        pass

    def kill_task(self, agent_name: str) -> None:
        """
        Kill the currently running task for an agent.

        Process:
            1. Get running task PID
            2. os.kill(pid, signal.SIGTERM)
            3. Wait 10 seconds
            4. If still alive: os.kill(pid, signal.SIGKILL)
            5. Update task status to 'killed'
            6. Update agent state to 'idle'
        """
        pass
```

---

## 7. Telegram Commands

### 7.1 Agent Commands

```
/create-agent <name> <project-path> [description]
  → Register new agent

/delete-agent <name>
  → Delete agent (kills running task if any)

/agents
  → List all agents with status
  Example output:
    api-backend   IDLE    /projects/my-api         (3 tasks done)
    web-frontend  RUNNING /projects/my-web  #47    (running 2m)
    ml-pipeline   IDLE    /projects/ml-pipeline    (1 task done)
```

### 7.2 Task Commands

```
/task <agent-name> <prompt>
  → Dispatch task to agent
  Example: /task api-backend add pagination to /users

/status [agent-name]
  → Check task status (all agents or specific)

/kill <agent-name>
  → Kill running task

/history <agent-name> [limit]
  → Show recent task history
```

---

## 8. Result File Format

### 8.1 Output from `claude -p --output-format json`

```json
{
  "type": "result",
  "subtype": "success",
  "cost_usd": 0.045,
  "duration_ms": 135000,
  "duration_api_ms": 98000,
  "is_error": false,
  "num_turns": 5,
  "result": "Added pagination to /users endpoint. Created paginate utility...",
  "session_id": "agent-api-backend",
  "total_cost_usd": 1.23
}
```

### 8.2 Parsing Results

```python
def parse_result(result_file: str) -> TaskResult:
    """
    Parse claude JSON output.

    Returns:
        TaskResult with:
        - success: bool (from is_error)
        - summary: str (from result, truncated)
        - cost: float (cost_usd)
        - duration: int (duration_ms)
        - turns: int (num_turns)
    """
    pass
```

---

## 9. Error Handling

| Error | Recovery |
|---|---|
| Agent not found | Return error message to Telegram |
| Agent busy (already running) | "Agent busy with task #X, try later" |
| Project dir doesn't exist | Reject agent creation |
| claude CLI not found | Error at dispatch time |
| Process crashes (non-zero exit) | Mark task failed, agent state=failed |
| Process hangs (timeout) | Watcher kills after max_age, marks timeout |
| SQLite locked | Retry with backoff (WAL mode helps) |
| Result file missing | Mark task as failed with "no output" |

---

## 10. Directory Structure

```
~/.claude-bridge/
├── config.yaml                    # Global config (Telegram token, etc.)
├── bridge.db                      # SQLite database (agents + tasks)
├── watcher.py                     # Task watcher script
└── logs/
    └── bridge.log                 # Bridge Bot logs

/tmp/claude-bridge/
├── task-42-result.json            # Result files (temporary)
├── task-43-result.json
└── ...
```

---

## 11. Success Criteria

Agent lifecycle complete when:

- [ ] Agent registration works (create/delete/list)
- [ ] Task dispatch spawns `claude -p` correctly
- [ ] `--session-id` preserves context across tasks
- [ ] Watcher detects task completion via PID
- [ ] Result files parsed correctly
- [ ] Telegram reports sent for completed tasks
- [ ] Busy agent rejection works
- [ ] Task killing works (SIGTERM → SIGKILL)
- [ ] Timeout detection works
- [ ] No zombie processes
