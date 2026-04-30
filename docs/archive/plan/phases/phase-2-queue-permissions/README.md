# Phase 2: Queue + Permissions + Model Routing

**Goal:** Tasks queue when agent is busy (FIFO, auto-dequeued on completion). Permission requests for dangerous commands relay to Telegram for human approval. Model routing: Sonnet for routine tasks, Opus for complex — configurable per agent and per task.

**Status:** [ ] Not started

**Estimated effort:** ~25.5 hours (Week 3–4)

**Dependencies:** Phase 1 complete and stable

---

## Demo Scenario

After this phase:

```
[Telegram] → "ask backend to refactor auth module"   ← agent is busy
Agent 'backend' is busy. Task #8 queued at position 1.

[later, task #7 completes]
Auto-dispatching queued Task #8 to agent 'backend'.

[during task #8, agent tries git push]
[Telegram] ← "⚠️ backend wants to run: git push origin main
              [Approve] [Deny]"

[tap Approve] → task continues and completes

[Telegram] → "ask backend to rewrite the whole API --model opus"
Task #9 dispatched (using claude-opus-4-5) to agent 'backend'.
```

---

## Tasks

### Task Queue

#### Task 2.1: Add Queue Status to SQLite Schema
- **Effort:** 1 hour
- **Dependencies:** Phase 1 schema
- **Acceptance Criteria:**
  - [ ] `tasks.position INTEGER` column (nullable, only for queued tasks)
  - [ ] Status enum expanded: `pending`, `queued`, `running`, `done`, `failed`, `timeout`, `killed`
  - [ ] Index on `(session_id, status)` for fast queue lookups
  - [ ] Migration is backward-compatible (existing data preserved)
- **Files:** `src/claude_bridge/db.py`

#### Task 2.2: Queue-on-Busy Logic in `dispatch`
- **Effort:** 2 hours
- **Dependencies:** Task 2.1
- **Acceptance Criteria:**
  - [ ] Dispatch to idle agent: immediate execution (unchanged)
  - [ ] Dispatch to busy agent: task inserted with `status='queued'`, `position=next_in_line`
  - [ ] Prints: `Agent 'backend' is busy. Task #<id> queued at position <n>`
  - [ ] SQLite transaction ensures no duplicate positions
- **Files:** `src/claude_bridge/cli.py`, `src/claude_bridge/dispatcher.py`

#### Task 2.3: `queue` Command
- **Effort:** 1 hour
- **Dependencies:** Task 2.2
- **Acceptance Criteria:**
  - [ ] `queue` shows all queued tasks; `queue backend` shows for specific agent
  - [ ] Shows: position, task ID, prompt (truncated), queued_at
  - [ ] Shows "No tasks in queue" if empty
- **Files:** `src/claude_bridge/cli.py`

#### Task 2.4: Auto-Dequeue on Completion
- **Effort:** 2.5 hours
- **Dependencies:** Tasks 2.2, Phase 1 on_complete.py
- **Acceptance Criteria:**
  - [ ] After marking task done/failed: queries for queued tasks with same session_id
  - [ ] If queued tasks exist: dequeues lowest position, spawns subprocess, stores PID
  - [ ] Agent state stays `busy` (no idle gap between tasks)
  - [ ] Remaining queued tasks have positions decremented
  - [ ] If no queued tasks: agent state → `idle`
  - [ ] SQLite transaction prevents race conditions
- **Files:** `src/claude_bridge/on_complete.py`

#### Task 2.5: `cancel` Command
- **Effort:** 1 hour
- **Dependencies:** Task 2.2
- **Acceptance Criteria:**
  - [ ] `cancel <task_id>` removes task from queue
  - [ ] Errors if task doesn't exist or not in `queued` status
  - [ ] Remaining tasks have positions adjusted (no gaps)
- **Files:** `src/claude_bridge/cli.py`

#### Task 2.6: Test Task Queue End-to-End
- **Effort:** 1.5 hours
- **Acceptance Criteria:**
  - [ ] Dispatch to idle → runs immediately
  - [ ] Two more dispatches while running → queued at positions 1 and 2
  - [ ] First completes → second auto-dispatches
  - [ ] Cancel third while second running → removed from queue
  - [ ] Second completes → agent idle

---

### Permission Relay

#### Task 2.7: Design Permission Hook Architecture
- **Effort:** 2 hours
- **Acceptance Criteria:**
  - [ ] Documented: which hook type (PreToolUse) intercepts permission requests
  - [ ] Documented: data available in hook (tool, command, context)
  - [ ] Documented: how to approve/deny (polling response file)
  - [ ] Decision on blocking vs polling approach for Telegram approval
- **Files:** Architecture note in this doc or `plan/architecture/`

#### Task 2.8: `permission_relay.py` (PreToolUse Hook)
- **Effort:** 3 hours
- **Dependencies:** Task 2.7
- **Acceptance Criteria:**
  - [ ] Called by PreToolUse hook with request details
  - [ ] Writes permission request to `bridge.db` (permissions table)
  - [ ] Contains: task_id, session_id, tool_name, command, timestamp
  - [ ] Polls DB for approval response with 10-min timeout
  - [ ] If approved: exits with success (Claude Code proceeds)
  - [ ] If denied/timeout: exits with failure (Claude Code skips)
- **Files:** `src/claude_bridge/permission_relay.py`

#### Task 2.9: Telegram Permission Notification
- **Effort:** 3 hours
- **Dependencies:** Task 2.8, channel server Approve/Deny buttons
- **Acceptance Criteria:**
  - [ ] Bridge Bot detects pending permissions and sends Telegram message
  - [ ] Message: `"Agent 'backend' wants to run: git push — [Approve] [Deny]"`
  - [ ] Approve button: writes approved=true to DB
  - [ ] Deny button: writes approved=false to DB
  - [ ] Timeout notification sent: "Permission request timed out (auto-denied)"
- **Files:** Bridge Bot CLAUDE.md update; `src/claude_bridge/cli.py` (approve/deny commands)

#### Task 2.10: Test Permission Relay
- **Effort:** 1.5 hours
- **Acceptance Criteria:**
  - [ ] Task triggers dangerous command → permission appears in Telegram
  - [ ] Tap Approve → task continues and completes
  - [ ] Tap Deny → task stops that action, continues with alternatives
  - [ ] Let permission timeout → auto-denied, notification received

---

### Model Routing

#### Task 2.11: Model Configuration in Agent Schema
- **Effort:** 1 hour
- **Dependencies:** Phase 1 schema
- **Acceptance Criteria:**
  - [ ] `agents.model TEXT DEFAULT 'sonnet'`
  - [ ] `create-agent` accepts `--model opus`
  - [ ] Valid models: `sonnet`, `opus`
  - [ ] Agent `.md` frontmatter `model:` field set from config
  - [ ] `list-agents` shows model column
- **Files:** `src/claude_bridge/db.py`, `src/claude_bridge/agent_md.py`

#### Task 2.12: Per-Task Model Override
- **Effort:** 1.5 hours
- **Dependencies:** Task 2.11
- **Acceptance Criteria:**
  - [ ] `dispatch backend "complex task" --model opus` overrides agent default
  - [ ] Model passed to Claude Code via `--model` flag
  - [ ] Task row records which model was actually used
  - [ ] `history` shows model used per task
- **Files:** `src/claude_bridge/cli.py`, `src/claude_bridge/dispatcher.py`

#### Task 2.13: `set-model` Command
- **Effort:** 0.5 hours
- **Acceptance Criteria:**
  - [ ] `set-model backend opus` updates SQLite and regenerates agent `.md` file
- **Files:** `src/claude_bridge/cli.py`

#### Task 2.14: Test Model Routing
- **Effort:** 1 hour
- **Acceptance Criteria:**
  - [ ] Agent default sonnet → dispatched tasks use sonnet
  - [ ] Override `--model opus` → task uses opus
  - [ ] Change agent default → subsequent tasks use new default
  - [ ] History shows correct model per task

---

### Cost Tracking Improvements

#### Task 2.15: Enhanced Cost Parsing
- **Effort:** 1.5 hours
- **Dependencies:** Phase 1 on_complete.py
- **Acceptance Criteria:**
  - [ ] Parse `cost_usd`, `input_tokens`, `output_tokens` from Claude JSON output
  - [ ] Store in tasks table
  - [ ] Handle missing cost data gracefully (NULL, don't fail)
  - [ ] `history` shows cost column formatted as `$0.04`
- **Files:** `src/claude_bridge/on_complete.py`, `src/claude_bridge/db.py`

#### Task 2.16: `cost` Command
- **Effort:** 1.5 hours
- **Dependencies:** Task 2.15
- **Acceptance Criteria:**
  - [ ] `cost` shows total across all agents
  - [ ] `cost backend` shows for specific agent
  - [ ] `cost --period today|week|month|all`
  - [ ] Shows: total cost, task count, average cost per task
- **Files:** `src/claude_bridge/cli.py`

---

## Summary

| Area | Tasks | Effort |
|------|-------|--------|
| Task Queue | 6 tasks | ~9 h |
| Permission Relay | 4 tasks | ~9.5 h |
| Model Routing | 4 tasks | ~4 h |
| Cost Tracking | 2 tasks | ~3 h |
| **Total** | **16 tasks** | **~25.5 h** |
