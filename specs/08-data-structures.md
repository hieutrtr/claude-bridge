# Data Structures Specification

## Overview

All data structures for the session-based dispatch architecture. SQLite is the single source of truth for agents and tasks.

---

## 1. Core Entities

### 1.1 Agent

```python
@dataclass
class Agent:
    """A registered agent — a persistent Claude Code session for a project."""
    name: str                        # Primary key, e.g., "api-backend"
    project_dir: str                 # Absolute path to project
    session_id: str                  # Claude Code session ID
    state: AgentState                # current state
    description: str | None          # optional description
    created_at: datetime
    last_task_at: datetime | None
    total_tasks: int

class AgentState(Enum):
    CREATED = "created"              # Registered, never ran
    IDLE = "idle"                    # Ready for tasks
    RUNNING = "running"              # Task in progress
    FAILED = "failed"                # Last task failed
    TIMEOUT = "timeout"              # Last task timed out
```

### 1.2 Task

```python
@dataclass
class Task:
    """A dispatched task — a single claude -p invocation."""
    id: int                          # Auto-increment
    agent_name: str                  # FK to agents.name
    prompt: str                      # The task prompt
    status: TaskStatus               # current status
    pid: int | None                  # OS process ID when running
    result_file: str | None          # Path to JSON result
    result_summary: str | None       # Brief summary for Telegram
    exit_code: int | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    reported: bool                   # Sent to Telegram?

class TaskStatus(Enum):
    PENDING = "pending"              # Queued (Phase 2)
    RUNNING = "running"              # claude -p process active
    DONE = "done"                    # Completed successfully
    FAILED = "failed"                # Non-zero exit or error
    TIMEOUT = "timeout"              # Killed due to timeout
    KILLED = "killed"                # Manually killed by user
```

### 1.3 Task Result (parsed from claude JSON output)

```python
@dataclass
class TaskResult:
    """Parsed result from claude -p --output-format json."""
    success: bool                    # from is_error
    result_text: str                 # from result field
    cost_usd: float                  # from cost_usd
    duration_ms: int                 # from duration_ms
    num_turns: int                   # from num_turns
    session_id: str                  # from session_id
```

---

## 2. Command Parsing

### 2.1 Parsed Command

```python
@dataclass
class Command:
    """Parsed Telegram command."""
    action: str                      # create-agent, task, status, kill, etc.
    agent_name: str | None           # Target agent (if applicable)
    args: str | None                 # Remaining arguments
    raw_text: str                    # Original message

    # For /create-agent
    project_dir: str | None
    description: str | None
```

---

## 3. Status Reports

### 3.1 Agent Status

```python
@dataclass
class AgentStatus:
    """Status of a single agent."""
    name: str
    state: AgentState
    project_dir: str
    current_task: Task | None        # If running
    total_tasks: int
    last_task_at: datetime | None
```

### 3.2 Completed Task Report

```python
@dataclass
class CompletedTask:
    """A task that just completed (for reporting)."""
    task: Task
    result: TaskResult | None        # Parsed result (None if result file missing)
    agent: Agent
    duration_seconds: float
```

---

## 4. Configuration

### 4.1 Bridge Config

```python
@dataclass
class BridgeConfig:
    """Global configuration from ~/.claude-bridge/config.yaml."""
    telegram_bot_token: str
    admin_users: list[int]           # Telegram user IDs
    allowed_users: list[int]
    db_path: str                     # Default: ~/.claude-bridge/bridge.db
    result_dir: str                  # Default: /tmp/claude-bridge/
    task_timeout_minutes: int        # Default: 30
    watcher_interval_minutes: int    # Default: 2
    log_level: str                   # Default: INFO
```

---

## 5. SQLite Schema

### 5.1 Full Schema

```sql
-- Enable WAL mode for concurrent reads
PRAGMA journal_mode=WAL;

CREATE TABLE agents (
    name TEXT PRIMARY KEY,
    project_dir TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
    state TEXT DEFAULT 'created',
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_task_at TIMESTAMP,
    total_tasks INTEGER DEFAULT 0
);

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL REFERENCES agents(name) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    pid INTEGER,
    result_file TEXT,
    result_summary TEXT,
    exit_code INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    reported INTEGER DEFAULT 0
);

-- Index for watcher queries
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_agent ON tasks(agent_name);
CREATE INDEX idx_tasks_unreported ON tasks(reported) WHERE reported = 0;
```

---

## 6. Profile (Simplified for MVP)

For MVP, the profile is minimal — just enough for CLAUDE.md generation:

```python
@dataclass
class AgentProfile:
    """Simplified profile for MVP."""
    name: str
    project_dir: str
    role: str                        # coder | researcher | devops
    stack: list[str]                 # Detected or user-provided
    hard_rules: list[str]            # User-defined rules
    description: str | None
```

Full profile system (spec 01) remains valid for Phase 2 enhancement accumulation.

---

## 7. Type Aliases

```python
from datetime import datetime
from enum import Enum
from dataclasses import dataclass

AgentName = str                     # e.g., "api-backend"
SessionId = str                     # e.g., "agent-api-backend"
TaskId = int                        # Auto-increment integer
ProjectPath = str                   # Absolute path
TelegramUserId = int                # Telegram user ID
```

---

## 8. JSON Serialization

```python
class BridgeJSONEncoder(json.JSONEncoder):
    """Encode Bridge dataclasses to JSON."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, '__dataclass_fields__'):
            return {
                k: v for k, v in obj.__dict__.items()
                if v is not None
            }
        return super().default(obj)
```

---

## 9. Success Criteria

- [ ] SQLite schema works (create, query, update)
- [ ] Agent CRUD operations work
- [ ] Task lifecycle tracked correctly
- [ ] Result parsing handles all claude output formats
- [ ] Config loads from YAML
- [ ] No circular dependencies between types
