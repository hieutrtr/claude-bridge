# Claude Bridge — Technical Specifications

## Architecture Overview

```
Telegram ←MCP→ Bridge Bot (Claude Code session #0)
                    │
                    ├──→ claude -p --session-id agent-X --project-dir /path/X
                    ├──→ claude -p --session-id agent-Y --project-dir /path/Y
                    │
                    ├──→ SQLite (agents + tasks + status)
                    │
                    └──→ Task Watcher (cron/loop) → reports completions to Telegram
```

**Key design decisions:**
- **One Telegram channel** — Bridge Bot is the only session with MCP
- **Agents are persistent sessions** — `--session-id` preserves context across tasks
- **Fire-and-forget dispatch** — `claude -p` runs in background, watcher reports completion
- **SQLite tracks everything** — agents, tasks, PIDs, results
- **No IPC/sockets/tmux** — just CLI subprocess calls

See individual specs for details:
- `specs/04-agent-lifecycle.md` — Agent registration, task dispatch, watcher
- `specs/07-channels.md` — Telegram channel, command routing
- `specs/08-data-structures.md` — SQLite schema, data types

---

## 1. Profile System

### 1.1 Profile Schema (profile.yaml)

**Location:** `~/.claude-bridge/agents/{agent-name}/profile.yaml`

**Format:** YAML 1.2

**Required fields:**
```yaml
name: string                          # Unique agent name (alphanumeric + hyphen)
version: integer                      # Incremented on each enhancement
created: ISO8601 datetime             # When profile was created
last_enhanced: ISO8601 datetime       # When last enhanced (null if never)
base_template: string                 # Template used (coder-fullstack, etc.)

identity:
  role: string                        # coder | researcher | reviewer | devops | writer | analyst
  display_name: string                # For humans
  project: string                     # Absolute path to project
  description: string                 # One-line description (optional)

context:
  stack: list[string]                 # [nextjs, typescript, prisma]
  key_files:
    - path: string
      reason: string
      sensitive: boolean              # default: false

rules:
  hard: list[string]                  # User-defined, immutable
  soft: list[object]                  # Learned rules (can evolve)
    - text: string
      learned_from: string            # task_001 or pattern_detection
      confidence: string              # high | medium | low

plugins: list[object]
  - name: string
    source: string                    # marketplace | github/user/repo | ./local/path

skills: list[string]                  # [review, test, commit]

hooks:
  pre_tool_use:
    bash: list[object]
      - block_pattern: string OR
        relay_permission: string
        message: string (optional)
    write: list[object]
      - confirm_if_path_matches: string

  post_tool_use:
    write: list[object]
      - run: string
        async: boolean

  stop: list[object]
    - check_tests_written: boolean
      message: string (optional)

  pre_compact: list[object]
    - update_dev_docs: boolean

reporting:
  channel: string                     # telegram (default) | discord | slack
  style: string                       # brief | summary | detailed
  on_complete: list[string]
  on_error: list[string]
  on_permission_needed: list[string]
```

### 1.2 Profile Manager

**Class:** `ProfileManager`

**Methods:**

```python
class ProfileManager:

    def load(agent_name: str) -> Profile:
        """
        Load profile.yaml for agent.

        Args:
            agent_name: Name of agent (e.g., "coder-my-app")

        Returns:
            Profile object (dataclass or pydantic model)

        Raises:
            FileNotFoundError: If profile doesn't exist
            ValidationError: If YAML is invalid or required fields missing
        """
        pass

    def save(profile: Profile) -> None:
        """
        Save profile.yaml, incrementing version.

        Args:
            profile: Profile object to save

        Side effects:
            - Creates directory if needed
            - Increments version
            - Updates last_enhanced timestamp

        Raises:
            IOError: If write fails
        """
        pass

    def create(agent_name: str, project_path: str,
               template: str = "coder-fullstack",
               hard_rules: list[str] = None) -> Profile:
        """
        Create new profile from template.

        Args:
            agent_name: Unique name
            project_path: Absolute path to project
            template: Base template name
            hard_rules: User-provided hard rules (from Q3)

        Returns:
            Profile object

        Process:
            1. Load template
            2. Analyze project (ProjectScanner)
            3. Populate context (stack, key_files)
            4. Add hard_rules
            5. Return Profile
        """
        pass

    def validate(profile: Profile) -> ValidationResult:
        """
        Validate profile structure and values.

        Returns:
            ValidationResult with errors/warnings

        Checks:
            - All required fields present
            - Types correct
            - Paths exist
            - No duplicate rules
            - Valid role
        """
        pass
```

### 1.3 Project Scanner

**Class:** `ProjectScanner`

**Purpose:** Analyze project structure to populate profile context

```python
class ProjectScanner:

    def scan(project_path: str) -> ProjectContext:
        """
        Scan project and return detected context.

        Returns:
            ProjectContext with:
            - stack: detected tech stack
            - key_dirs: important directories
            - critical_files: suggested important files
            - conventions: detected linting/formatting rules
        """
        pass

    def _detect_stack(project_path: str) -> list[str]:
        """
        Detect tech stack from:
        - package.json → [nextjs, react, typescript, etc.]
        - requirements.txt/pyproject.toml → [python, django, etc.]
        - go.mod → [go, gin, etc.]
        - Dockerfile → [docker]
        - docker-compose.yml → [postgres, redis, etc.]

        Returns: list of technology names
        """
        pass

    def _detect_key_dirs(project_path: str) -> list[DirInfo]:
        """
        Identify important directories based on structure.

        Heuristics:
        - src/auth → auth logic
        - src/payments → payment logic
        - src/api → API endpoints
        - tests/ → test suite
        - migrations/ → database migrations

        Returns: list of DirInfo(path, reason)
        """
        pass

    def _detect_critical_files(project_path: str) -> list[FileInfo]:
        """
        Identify critical files.

        Heuristics:
        - prisma/schema.prisma → DB schema
        - .env.example → environment variables
        - docker-compose.yml → service setup
        - package.json / requirements.txt → dependencies

        Returns: list of FileInfo(path, reason)
        """
        pass

    def _detect_conventions(project_path: str) -> Conventions:
        """
        Detect coding conventions from config files.

        Checks:
        - .eslintrc → linting rules
        - .prettierrc → formatting style
        - pyproject.toml [tool.ruff] → Python linting
        - .github/workflows → CI commands
        - Makefile → build commands

        Returns: Conventions object
        """
        pass
```

---

## 2. CLAUDE.md Generator

### 2.1 Multi-Layer Generation

**Files to generate:**
```
{project}/CLAUDE.md                    ← Project-wide rules, stack, general
{project}/src/auth/CLAUDE.md           ← Auth-specific rules + constraints
{project}/src/payments/CLAUDE.md       ← Payment-specific rules
... (one per sensitive_dir or custom layer)
```

**Algorithm:**
```
For each layer:
  1. Determine context (project level or specific dir)
  2. Load applicable profile rules
  3. If dir is sensitive → add extra constraints
  4. Render template with variables
  5. Write to CLAUDE.md in that layer
```

### 2.2 Template System

**Location:** `claude_bridge/templates/claude_md_template.jinja2`

**Variables available:**
```jinja2
{{ agent_name }}           # coder-my-app
{{ role }}                 # Senior Full-stack Developer
{{ project_path }}         # ~/projects/my-app
{{ stack }}                # Next.js, TypeScript, Prisma
{{ key_files }}            # List of critical files
{{ hard_rules }}           # Hard rules as numbered list
{{ soft_rules }}           # Soft rules with confidence
{{ description }}          # Project description
{{ sensitive_dirs }}       # Dirs marked sensitive
{{ layer_specific }}       # If generating for subdir, specific constraints
```

**Base template structure:**
```markdown
# Agent: {{ agent_name }}
<!-- generated by claude-bridge v{{ version }} -->
<!-- last updated: {{ timestamp }} -->

## 🎭 Role
{{ description }}
Stack: {{ stack }}

## 📁 Project Structure
{{ key_dirs_description }}

## 📎 Key Files
{{ key_files_list }}

## 🔒 Hard Rules — NEVER BREAK
{{ hard_rules_numbered }}

## 📐 Conventions
{{ soft_rules_list }}

## 📣 Reporting
{{ reporting_style }}

## 🧠 Context
{{ learned_patterns }}

## 📋 If Session Compacts
{{ dev_docs_reference }}
```

### 2.3 CLAUDE.md Generator Class

```python
class ClaudeMdGenerator:

    def generate_all(agent_name: str, profile: Profile) -> None:
        """
        Generate CLAUDE.md at all layers.

        Process:
            1. Generate project-level CLAUDE.md
            2. For each sensitive_dir in profile:
               - Generate subdir-level CLAUDE.md
        """
        pass

    def generate_project_level(profile: Profile) -> str:
        """
        Generate project root CLAUDE.md.

        Returns:
            Markdown content
        """
        pass

    def generate_layer_specific(profile: Profile,
                               dir_path: str,
                               is_sensitive: bool = False) -> str:
        """
        Generate CLAUDE.md for specific directory.

        Args:
            dir_path: Directory (e.g., "src/auth")
            is_sensitive: Add extra constraints?

        Returns:
            Markdown content with layer-specific rules
        """
        pass

    def _render_template(variables: dict) -> str:
        """
        Render Jinja2 template with variables.
        """
        pass
```

---

## 3. Enhancement Accumulator

### 3.1 Signal Types

```python
class SignalType(Enum):
    USER_CORRECTED = "user_corrected"      # User fixed agent's work
    AGENT_ASKED = "agent_asked"            # Agent asked clarifying Q
    HOOK_BLOCKED = "hook_blocked"          # Hook blocked action
    PATTERN_DETECTED = "pattern_detected"  # Agent's repeated behavior
    FILES_TOUCHED = "files_touched"        # Files frequently edited
    TASK_PATTERN = "task_pattern"          # Similar tasks repeat

class Signal:
    type: SignalType
    content: str                           # Description
    task_id: str                           # Which task generated this
    timestamp: datetime
    proposed_change: str                   # What to suggest to user (optional)
    confidence: str                        # high | medium | low (optional)
```

### 3.2 Accumulator Schema

**Location:** `~/.claude-bridge/agents/{agent-name}/enhancement-accumulator.yaml`

```yaml
signals:
  user_corrected:
    - task_001: "description"
    - task_003: "description"
    # When count reaches 5 → suggest enhancement

  agent_asked:
    - task_002: "description"
    # When count reaches 5 → suggest enhancement

  # ... other types

last_enhancement: 2026-03-26T10:00:00
pending_proposals: []                 # Proposals waiting for user approval
applied_signals: []                   # Which signals were applied to profile
```

### 3.3 Accumulator Class

```python
class EnhancementAccumulator:

    def log_signal(agent_name: str, signal: Signal) -> None:
        """
        Log a signal.

        Side effects:
            - Append to accumulator.yaml
            - Check if any type hit 5+ threshold
            - If yes, trigger enhancement proposal (async)
        """
        pass

    def load_accumulator(agent_name: str) -> Accumulator:
        """Load accumulator.yaml."""
        pass

    def save_accumulator(agent_name: str, acc: Accumulator) -> None:
        """Save accumulator.yaml."""
        pass

    def get_signals_by_type(agent_name: str,
                           signal_type: SignalType) -> list[Signal]:
        """Get all signals of a specific type."""
        pass

    def check_thresholds(agent_name: str) -> list[SignalType]:
        """
        Check if any signal type hit 5+ threshold.

        Returns:
            List of signal types that should trigger enhancement
        """
        pass

    def clear_applied_signals(agent_name: str,
                             signal_types: list[SignalType]) -> None:
        """Remove signals that were applied to profile."""
        pass
```

### 3.4 Enhancement Engine

```python
class EnhancementEngine:

    def generate_proposals(agent_name: str,
                          signal_types: list[SignalType]) -> list[Proposal]:
        """
        Analyze signals and generate proposals.

        Process for each signal type:
        1. Group signals by theme
        2. Extract common pattern
        3. Create proposal (with text to add to profile)

        Returns:
            list[Proposal] with:
            - type: SignalType
            - signals_count: int
            - proposed_text: str
            - confidence: str
        """
        pass

    def apply_proposals(agent_name: str,
                       proposals: list[Proposal],
                       approved_indices: list[int]) -> None:
        """
        Apply user-approved proposals to profile.

        Process:
        1. Load profile
        2. For each approved proposal:
           - Add to soft_rules (if type=user_corrected)
           - Add to key_files (if type=agent_asked)
           - Update rules (if type=pattern_detected)
        3. Increment version
        4. Save profile
        5. Regenerate CLAUDE.md
        6. Clear applied signals from accumulator
        """
        pass
```

---

## 4. Agent Manager

### 4.1 Agent Lifecycle States

```
CREATED → IDLE ←→ RUNNING → IDLE
                      ↓
                 FAILED / TIMEOUT
```

### 4.2 Agent (Session-based)

```python
class Agent:
    name: str                         # Primary key, e.g., "api-backend"
    project_dir: str                  # Absolute path to project
    session_id: str                   # Claude Code --session-id
    state: str                        # created | idle | running | failed | timeout
    created_at: datetime
    last_task_at: datetime
    total_tasks: int
    description: str                  # Optional
```

### 4.3 Agent Manager Class

```python
class AgentManager:

    def create_agent(name: str, project_dir: str,
                     description: str = None) -> Agent:
        """
        Register a new agent in SQLite.
        No process spawned — just a registration.
        Session ID auto-generated: f"agent-{name}"
        """
        pass

    def delete_agent(name: str) -> None:
        """Delete agent. Kill running task if any."""
        pass

    def dispatch_task(agent_name: str, prompt: str) -> int:
        """
        Dispatch task to agent via:
          claude -p "prompt" --session-id <session> --project-dir <path> --output-format json

        Returns: task_id
        Raises: AgentBusyError if already running a task
        """
        pass

    def kill_task(agent_name: str) -> None:
        """Kill running task (SIGTERM → SIGKILL)."""
        pass

    def list_agents() -> list[Agent]:
        """List all agents with status."""
        pass

    def get_status(agent_name: str) -> AgentStatus:
        """Get agent status + current task info."""
        pass
```

### 4.4 Task

```python
class Task:
    id: int                           # Auto-increment
    agent_name: str                   # FK to agents
    prompt: str
    status: str                       # pending | running | done | failed | timeout | killed
    pid: int                          # OS process ID
    result_file: str                  # Path to JSON result
    result_summary: str               # Brief summary for Telegram
    exit_code: int
    created_at: datetime
    started_at: datetime
    completed_at: datetime
    reported: bool                    # Sent to Telegram?
```

### 4.5 Task Watcher

```python
class TaskWatcher:
    """Cron/loop that monitors running tasks and reports completions."""

    def check_running_tasks() -> list[CompletedTask]:
        """Check PIDs, read results, update SQLite."""
        pass

    def report_completions(completed: list[CompletedTask]) -> None:
        """Send completion reports to Telegram."""
        pass
```

See `specs/04-agent-lifecycle.md` for full details.

---

## 5. Permission Relay System

### 5.1 Permission Request

```python
class PermissionRequest:
    id: str                           # UUID for this request
    agent_name: str
    action: str                       # "bash: git push", "write: /payments/..."
    pattern_matched: str              # e.g., "prisma migrate"
    risk_level: str                   # low | medium | high
    file_preview: str                 # If available (optional)
    timestamp: datetime
    timeout_seconds: int              # default: 300
    created_at: datetime
```

### 5.2 Hook Integration

**Hook fires when:**
- Agent tries to run blocked bash pattern
- Agent tries to write to sensitive file
- Agent tries to run dangerous command

**Hook behavior:**
```
Hook intercepts action
  ↓
Hook calls PermissionHandler.request(PermissionRequest)
  ↓
PermissionHandler sends Telegram message to user
  ↓
User taps [✅ Approve] or [❌ Deny]
  ↓
Handler returns: ALLOW (exit 0) or DENY (exit 2)
  ↓
Hook receives exit code and allows/blocks action
```

### 5.3 Permission Handler Class

```python
class PermissionHandler:

    def request(req: PermissionRequest) -> PermissionResponse:
        """
        Send permission request to Telegram, wait for response.

        Args:
            req: PermissionRequest

        Returns:
            PermissionResponse with approved=True/False

        Process:
        1. Send Telegram message with inline keyboard
        2. Poll for user response (up to timeout_seconds)
        3. Return response
        4. Save to audit log

        If timeout: default to DENY
        """
        pass

    def send_telegram_message(req: PermissionRequest) -> None:
        """Send formatted message to Telegram."""
        pass

    def wait_for_response(req_id: str,
                         timeout: int) -> PermissionResponse:
        """Poll for Telegram button tap."""
        pass
```

---

## 6. Telegram Channel (MCP)

### 6.1 Single Channel Architecture

**One Telegram channel → Bridge Bot only.** Agents have no channels.

```
Telegram ←MCP→ Bridge Bot → dispatches tasks → Agent sessions (headless)
```

The Bridge Bot is the only Claude Code session with a Telegram MCP channel.
It parses commands (`/task`, `/agents`, `/create-agent`) and dispatches accordingly.

### 6.2 Commands

```
/create-agent <name> <path> [description]   → Register agent
/delete-agent <name>                         → Remove agent
/agents                                      → List agents + status
/task <agent> <prompt>                       → Dispatch task
/status [agent]                              → Check running tasks
/kill <agent>                                → Kill running task
/history <agent> [n]                         → Last n task results
```

See `specs/07-channels.md` for full details.

---

## 7. Data Storage

### 7.1 Directory Structure

```
~/.claude-bridge/
├── config.yaml                       # Global settings (Telegram token, etc.)
├── agents/
│   ├── coder-my-app/
│   │   ├── profile.yaml
│   │   ├── enhancement-accumulator.yaml
│   │   ├── session.log               # Current session output
│   │   └── audit.log                 # Permission requests, signals
│   ├── researcher/
│   │   ├── profile.yaml
│   │   ├── enhancement-accumulator.yaml
│   │   └── ...
│   └── ...
├── templates/
│   ├── claude_md_template.jinja2
│   └── ...
└── logs/
    └── daemon.log
```

### 7.2 Session Log

**Location:** `~/.claude-bridge/agents/{agent-name}/session.log`

**Purpose:** Track signals and events during task execution

```
[2026-03-26T10:15:00] TASK_START task_001 "Fix login bug"
[2026-03-26T10:15:05] FILE_CHANGED src/auth/session.ts
[2026-03-26T10:15:10] BASH_RUN npm test
[2026-03-26T10:15:20] USER_CORRECTED "Use Zod not Joi"
[2026-03-26T10:15:25] TASK_COMPLETE task_001 success
[2026-03-26T10:15:25] SIGNAL_LOG user_corrected task_001
```

---

## 8. Error Handling

### 8.1 Error Categories

| Error | Cause | Recovery |
|---|---|---|
| `ProfileNotFound` | Agent doesn't exist | Create new agent |
| `ProjectNotFound` | Project path invalid | Validate path |
| `SpawnError` | Claude Code failed to start | Check Claude Code installation, env vars |
| `PermissionTimeout` | User didn't respond in time | Default to DENY |
| `ValidationError` | Profile invalid | List errors, suggest fixes |
| `EnhancementError` | Enhancement failed | Rollback profile, log error |

### 8.2 Recovery Strategies

- Profile validation errors → show suggestions, don't save
- Spawn failures → log to stderr, inform user
- Permission timeout → default to DENY (safe)
- Signal logging failure → continue (don't block task)

---

## 9. Testing Strategy

### 9.1 Unit Tests

- ProfileManager: load, save, validate
- ProjectScanner: detect stack, dirs, files
- ClaudeMdGenerator: template rendering, multi-layer
- EnhancementEngine: proposal generation
- SignalAccumulator: signal logging, threshold checking

### 9.2 Integration Tests

- Profile → CLAUDE.md generation end-to-end
- Signal accumulation → enhancement proposal
- Agent spawn → task execution → signal collection
- Permission request → Telegram relay → approval

### 9.3 Test Fixtures

- Mock project directory with real structure
- Pre-made profiles
- Mock Telegram API responses

---

## 10. Configuration

### 10.1 Global Config

**Location:** `~/.claude-bridge/config.yaml`

```yaml
telegram:
  bot_token: "..."
  admin_user_ids: [123456789]    # Can manage all agents
  allowed_user_ids: [123456789, 987654321]

log_level: INFO                  # DEBUG | INFO | WARN | ERROR

features:
  auto_enhancement: true         # Auto-trigger at threshold
  permission_relay: true
  dev_docs_persistence: true
```

### 10.2 Per-Agent Config

**In profile.yaml:**
```yaml
reporting:
  channel: telegram
  style: summary
```

---

## 11. Success Criteria

Each component complete when:

- **ProfileManager**: Load/save/validate works, no data loss
- **ProjectScanner**: Detects common stacks (Node, Python, Go, Docker)
- **ClaudeMdGenerator**: Multi-layer CLAUDE.md generates with correct content
- **EnhancementAccumulator**: Signals log correctly, threshold triggers reliably
- **EnhancementEngine**: Proposals make sense, user can approve/reject
- **AgentManager**: Spawn/kill/monitor work, signals collected correctly
- **TelegramChannel**: Messages send/receive, buttons work
- **PermissionRelay**: Requests shown to user, approvals route correctly back

