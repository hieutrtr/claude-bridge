# Phase 2: Queue + Permissions + Model Routing -- Detailed Tasks

> Week 3-4 | Depends on Phase 1 complete and stable
> Goal: Queue tasks when busy, relay permission requests to Telegram, route models per agent/task

---

## Task Queue

### Task 2.1: Add Queue Status to SQLite Schema

- **Description:** Extend the tasks table to support queued tasks. Add a `position` column for queue ordering and a 'queued' status value. Add index on (session_id, status) for efficient queue queries.
- **Effort:** 1 hour
- **Dependencies:** Phase 1 SQLite schema
- **Acceptance Criteria:**
  - [ ] `tasks` table has new column: `position INTEGER` (nullable, only set for queued tasks)
  - [ ] Status enum expanded: pending, queued, running, done, failed, timeout, killed
  - [ ] Index created on `(session_id, status)` for fast queue lookups
  - [ ] Migration is backward-compatible (existing data preserved)
  - [ ] `bridge-cli.py` schema init handles upgrade from Phase 1

### Task 2.2: Implement Queue-on-Busy Logic in dispatch

- **Description:** Modify the `dispatch` command so that when an agent is busy, the task is queued instead of rejected. Assign a position based on existing queue length. Print queue position to user.
- **Effort:** 2 hours
- **Dependencies:** Task 2.1
- **Acceptance Criteria:**
  - [ ] Dispatch to idle agent: behaves as before (immediate execution)
  - [ ] Dispatch to busy agent: task inserted with status='queued', position=next_in_line
  - [ ] Prints: "Agent 'backend' is busy. Task #<id> queued at position <n>"
  - [ ] Queue position is 1-indexed for user display
  - [ ] Multiple queued tasks get sequential positions
  - [ ] SQLite transaction ensures no duplicate positions

### Task 2.3: Implement Queue Viewer Command

- **Description:** Add `bridge-cli.py queue [agent_name]` command to view pending queued tasks for an agent or all agents.
- **Effort:** 1 hour
- **Dependencies:** Task 2.2
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py queue` shows all queued tasks across all agents
  - [ ] `bridge-cli.py queue backend` shows queued tasks for specific agent
  - [ ] Shows: position, task ID, prompt (truncated), queued_at timestamp
  - [ ] Shows "No tasks in queue" if empty
  - [ ] Output suitable for Telegram relay

### Task 2.4: Implement Auto-Dequeue on Completion

- **Description:** Modify `on-complete.py` to check the queue after a task completes. If there are queued tasks for this agent, automatically dispatch the next one (lowest position).
- **Effort:** 2.5 hours
- **Dependencies:** Tasks 2.2, Phase 1 on-complete.py
- **Acceptance Criteria:**
  - [ ] After marking task as done/failed, queries for queued tasks with same session_id
  - [ ] If queued tasks exist: dequeues the one with lowest position
  - [ ] Dequeue process: update status to 'running', spawn Claude Code subprocess, store PID
  - [ ] Agent state remains 'busy' (no idle gap between tasks)
  - [ ] Remaining queued tasks have positions decremented
  - [ ] If no queued tasks: agent state set to 'idle' (existing behavior)
  - [ ] Prints: "Auto-dispatching queued Task #<id> to agent 'backend'"
  - [ ] SQLite transaction prevents race conditions

### Task 2.5: Implement Queue Cancel Command

- **Description:** Add `bridge-cli.py cancel <task_id>` to remove a queued task from the queue.
- **Effort:** 1 hour
- **Dependencies:** Task 2.2
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py cancel 5` removes task #5 from queue
  - [ ] Errors if task doesn't exist or is not in 'queued' status
  - [ ] Remaining tasks in same queue have positions adjusted (no gaps)
  - [ ] Prints: "Task #5 cancelled and removed from queue"

### Task 2.6: Test Task Queue End-to-End

- **Description:** Full test of queue behavior with real tasks.
- **Effort:** 1.5 hours
- **Dependencies:** Tasks 2.2, 2.3, 2.4, 2.5
- **Acceptance Criteria:**
  - [ ] Dispatch task to idle agent: runs immediately
  - [ ] Dispatch second task while first is running: queued at position 1
  - [ ] Dispatch third task: queued at position 2
  - [ ] First task completes: second task auto-dispatches
  - [ ] Cancel third task while second is running: removed from queue
  - [ ] Second task completes: agent becomes idle (no more queued)
  - [ ] Queue command shows correct state at each step

---

## Permission Relay

### Task 2.7: Design Permission Hook Architecture

- **Description:** Design how permission requests from Claude Code are intercepted and relayed to Telegram for human approval. Research Claude Code's permission hook system and determine the hook type, event format, and response mechanism.
- **Effort:** 2 hours
- **Dependencies:** Understanding of Claude Code hook system
- **Acceptance Criteria:**
  - [ ] Documented: which hook type intercepts permission requests
  - [ ] Documented: what data is available in the hook (command, tool, context)
  - [ ] Documented: how to approve/deny from the hook (exit code, response file, etc.)
  - [ ] Documented: how to make the hook block until Telegram response received
  - [ ] Decision on blocking vs polling approach for Telegram approval

### Task 2.8: Implement Permission Hook Script

- **Description:** Create `permission-hook.py` that is called by Claude Code when a permission request occurs. Sends the request details to a local file/socket and waits for approval.
- **Effort:** 3 hours
- **Dependencies:** Task 2.7
- **Acceptance Criteria:**
  - [ ] Script is called by Claude Code permission hook with request details
  - [ ] Writes permission request to `~/.claude-bridge/workspaces/<session_id>/pending-permission.json`
  - [ ] Contains: task_id, session_id, tool_name, command, timestamp
  - [ ] Polls for approval file (`permission-response.json`) with configurable timeout (default 10 min)
  - [ ] If approved: exits with success code (Claude Code proceeds)
  - [ ] If denied: exits with failure code (Claude Code skips the action)
  - [ ] If timeout: exits with failure code, writes timeout note
  - [ ] Agent `.md` template updated to include permission hook

### Task 2.9: Implement Telegram Permission Notification

- **Description:** Bridge Bot detects pending permission files and sends Telegram messages with inline Approve/Deny buttons. Process button callbacks to write approval files.
- **Effort:** 3 hours
- **Dependencies:** Task 2.8, Telegram MCP plugin with inline buttons
- **Acceptance Criteria:**
  - [ ] Bridge Bot periodically checks for `pending-permission.json` files
  - [ ] Sends Telegram message: "Agent 'backend' wants to run: `rm -rf dist/` -- [Approve] [Deny]"
  - [ ] Message includes: agent name, tool/command, task context
  - [ ] Approve button: writes `permission-response.json` with `{"approved": true}`
  - [ ] Deny button: writes `permission-response.json` with `{"approved": false}`
  - [ ] Permission hook detects response file and proceeds/stops accordingly
  - [ ] Timeout notification sent to Telegram: "Permission request timed out (auto-denied)"

### Task 2.10: Test Permission Relay

- **Description:** End-to-end test of permission relay with a task that triggers a permission request.
- **Effort:** 1.5 hours
- **Dependencies:** Tasks 2.8, 2.9
- **Acceptance Criteria:**
  - [ ] Dispatch task that requires a dangerous command (e.g., `git push`)
  - [ ] Permission request appears in Telegram with Approve/Deny buttons
  - [ ] Tap Approve: task continues and completes
  - [ ] Dispatch another task requiring permission
  - [ ] Tap Deny: task stops that action, continues with alternatives
  - [ ] Let permission timeout: auto-denied, notification received
  - [ ] Multiple permission requests in same task handled sequentially

---

## Model Routing

### Task 2.11: Add Model Configuration to Agent Schema

- **Description:** Add a `model` column to the agents table and support model configuration in `create-agent` command. Default to 'sonnet'.
- **Effort:** 1 hour
- **Dependencies:** Phase 1 SQLite schema
- **Acceptance Criteria:**
  - [ ] `agents` table has new column: `model TEXT DEFAULT 'sonnet'`
  - [ ] `create-agent` accepts optional `--model` flag: `create-agent backend /path "purpose" --model opus`
  - [ ] Valid models: sonnet, opus (validated on input)
  - [ ] Agent `.md` frontmatter `model:` field set from this config
  - [ ] `list-agents` shows model column

### Task 2.12: Implement Per-Task Model Override

- **Description:** Allow dispatching a task with a model override that takes precedence over the agent's default model.
- **Effort:** 1.5 hours
- **Dependencies:** Task 2.11
- **Acceptance Criteria:**
  - [ ] `dispatch backend "complex task" --model opus` overrides agent default
  - [ ] Model override passed to Claude Code via `--model` flag (or equivalent)
  - [ ] Task row records which model was actually used
  - [ ] If no override specified: uses agent's default model
  - [ ] History command shows model used per task

### Task 2.13: Implement Model Change Command

- **Description:** Add `bridge-cli.py set-model <agent_name> <model>` to change an agent's default model.
- **Effort:** 0.5 hours
- **Dependencies:** Task 2.11
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py set-model backend opus` updates agent's default model
  - [ ] Updates both SQLite and regenerates agent `.md` file
  - [ ] Validates model name
  - [ ] Prints: "Agent 'backend' model changed to opus"

### Task 2.14: Test Model Routing

- **Description:** Verify model routing works correctly for both agent defaults and per-task overrides.
- **Effort:** 1 hour
- **Dependencies:** Tasks 2.11, 2.12, 2.13
- **Acceptance Criteria:**
  - [ ] Create agent with default sonnet: dispatched tasks use sonnet
  - [ ] Override with --model opus: task uses opus
  - [ ] Change agent default to opus: subsequent tasks use opus
  - [ ] History shows correct model per task
  - [ ] Cost difference visible between sonnet and opus tasks

---

## Cost Tracking Improvements

### Task 2.15: Enhanced Cost Parsing

- **Description:** Improve cost extraction from Claude Code output JSON. Parse detailed cost breakdown and store in SQLite.
- **Effort:** 1.5 hours
- **Dependencies:** Phase 1 on-complete.py
- **Acceptance Criteria:**
  - [ ] Parse `cost_usd` from Claude Code JSON output
  - [ ] Parse `input_tokens` and `output_tokens` if available
  - [ ] Store in tasks table: `cost REAL, input_tokens INTEGER, output_tokens INTEGER`
  - [ ] Handle cases where cost data is missing (set to NULL, don't fail)
  - [ ] History command shows cost column with formatting ($0.04)

### Task 2.16: Cost Summary Command

- **Description:** Add `bridge-cli.py cost [agent_name] [--period today|week|month|all]` to show aggregated cost information.
- **Effort:** 1.5 hours
- **Dependencies:** Task 2.15
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py cost` shows total cost across all agents
  - [ ] `bridge-cli.py cost backend` shows cost for specific agent
  - [ ] `bridge-cli.py cost --period today` shows today's cost
  - [ ] Shows: total cost, task count, average cost per task
  - [ ] Output suitable for Telegram relay

---

## Summary

| Area | Tasks | Total Effort |
|------|-------|-------------|
| Task Queue | 6 tasks | ~9 hours |
| Permission Relay | 4 tasks | ~9.5 hours |
| Model Routing | 4 tasks | ~4 hours |
| Cost Tracking | 2 tasks | ~3 hours |
| **Total** | **16 tasks** | **~25.5 hours** |
