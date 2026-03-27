# Phase 3: Agent Teams + Multi-Channel + Dashboard -- Detailed Tasks

> Week 5+ | Depends on Phase 2 complete (queue system required for teams)
> Goal: Coordinated agent teams, Discord/Slack channels, cost visibility, operational maturity

---

## Agent Teams Integration

### Task 3.1: Design Team Coordination Protocol

- **Description:** Design how a lead agent decomposes a complex task into sub-tasks and dispatches them to teammate agents. Define the data model (team definitions, sub-task tracking), communication flow (lead dispatches via bridge-cli.py), and result aggregation strategy.
- **Effort:** 3 hours
- **Dependencies:** Phase 2 queue system (sub-tasks queue like any other task)
- **Acceptance Criteria:**
  - [ ] Documented: team definition format (lead agent + list of teammate agents)
  - [ ] Documented: how lead agent's CLAUDE.md instructs it to decompose tasks
  - [ ] Documented: sub-task dispatch mechanism (lead calls bridge-cli.py dispatch for teammates)
  - [ ] Documented: result aggregation (lead polls teammate status, collects results)
  - [ ] Documented: failure handling (teammate fails -> lead decides to retry or skip)
  - [ ] SQLite schema extension designed: `teams` table, `task_parent_id` column

### Task 3.2: Implement Team Definition Command

- **Description:** Add `bridge-cli.py create-team <team_name> --lead <agent> --members <agent1,agent2,...>`. Stores team definition in SQLite.
- **Effort:** 2 hours
- **Dependencies:** Task 3.1, Phase 1 agent CRUD
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py create-team fullstack --lead backend --members frontend,devops` succeeds
  - [ ] Validates all referenced agents exist
  - [ ] Lead agent must be different from members
  - [ ] `teams` table created: `name TEXT PRIMARY KEY, lead_agent TEXT, created_at TEXT`
  - [ ] `team_members` table created: `team_name TEXT, agent_name TEXT`
  - [ ] `bridge-cli.py list-teams` shows all teams with members
  - [ ] `bridge-cli.py delete-team <name>` removes team (agents preserved)

### Task 3.3: Implement Team Dispatch Command

- **Description:** Add `bridge-cli.py team-dispatch <team_name> "<prompt>"`. Dispatches the task to the lead agent with special instructions to decompose and coordinate.
- **Effort:** 3 hours
- **Dependencies:** Task 3.2, Phase 2 queue
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py team-dispatch fullstack "build user profile page with API"` dispatches to lead
  - [ ] Lead agent's prompt is augmented: original prompt + team context + instructions to decompose
  - [ ] Augmented prompt includes: list of available teammates, their purposes, how to dispatch sub-tasks
  - [ ] Lead agent dispatches sub-tasks via bridge-cli.py (using Bash tool)
  - [ ] Parent task row created with type='team', sub-tasks linked via `parent_task_id`
  - [ ] Prints: "Team task #<id> dispatched to lead 'backend' with teammates: frontend, devops"

### Task 3.4: Implement Team Status Command

- **Description:** Add `bridge-cli.py team-status <team_name|task_id>` showing lead and all sub-task statuses.
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.3
- **Acceptance Criteria:**
  - [ ] Shows parent task status (lead agent)
  - [ ] Shows all sub-tasks with: agent name, status, prompt summary, duration
  - [ ] Shows overall progress: "3/5 sub-tasks complete"
  - [ ] If lead is still running: shows it's coordinating
  - [ ] Output suitable for Telegram relay

### Task 3.5: Implement Team Result Aggregation

- **Description:** When all sub-tasks complete, the lead agent collects results and produces a final summary. Modify on-complete.py to detect team task completion.
- **Effort:** 2.5 hours
- **Dependencies:** Tasks 3.3, 3.4
- **Acceptance Criteria:**
  - [ ] on-complete.py detects when a sub-task completes
  - [ ] Checks if all sub-tasks for the parent are done
  - [ ] If all done and lead is idle: notifies lead to aggregate results
  - [ ] Lead reads sub-task result files and produces final summary
  - [ ] Parent task marked as done with aggregated summary
  - [ ] Total cost is sum of lead + all sub-task costs
  - [ ] Final report sent to Telegram with full breakdown

### Task 3.6: Test Agent Teams

- **Description:** End-to-end test with a real multi-agent task.
- **Effort:** 2 hours
- **Dependencies:** Tasks 3.3, 3.4, 3.5
- **Acceptance Criteria:**
  - [ ] Create 2+ agents for different concerns (backend + frontend)
  - [ ] Create team with backend as lead
  - [ ] Dispatch team task: "build user profile page with API endpoint and frontend"
  - [ ] Lead decomposes into sub-tasks and dispatches to teammates
  - [ ] Sub-tasks run (possibly queued) and complete
  - [ ] Lead aggregates results into final summary
  - [ ] Team status shows all sub-task outcomes
  - [ ] Total cost tracked across all agents

---

## Multi-Channel Support

### Task 3.7: Design Channel Abstraction Layer

- **Description:** Design an abstraction that lets Bridge Bot work with Telegram, Discord, and Slack through a unified interface. The abstraction should handle message receiving, sending, and interactive elements (buttons) across platforms.
- **Effort:** 2 hours
- **Dependencies:** Phase 1 Telegram integration working
- **Acceptance Criteria:**
  - [ ] Documented: channel abstraction interface (receive_message, send_message, send_buttons)
  - [ ] Documented: how each platform maps to the abstraction
  - [ ] Documented: Bridge Bot CLAUDE.md changes to support multiple channels
  - [ ] Decision: one Bridge Bot per channel vs one Bridge Bot with multi-channel MCP
  - [ ] Decision: how to handle channel-specific features (threads, reactions, file upload)

### Task 3.8: Integrate Discord MCP Plugin

- **Description:** Install and configure the Discord MCP plugin for Claude Code. Create a Discord bot and connect it to Bridge Bot.
- **Effort:** 3 hours
- **Dependencies:** Task 3.7, Discord MCP plugin availability
- **Acceptance Criteria:**
  - [ ] Discord bot created via Discord Developer Portal
  - [ ] Discord MCP plugin installed and configured
  - [ ] Bridge Bot can receive messages from Discord
  - [ ] Bridge Bot can send responses to Discord
  - [ ] All bridge-cli.py commands accessible from Discord
  - [ ] Task completion reports delivered to the Discord channel that requested them
  - [ ] Permission relay works with Discord buttons (if supported)

### Task 3.9: Integrate Slack MCP Plugin

- **Description:** Install and configure the Slack MCP plugin for Claude Code. Create a Slack app and connect it to Bridge Bot.
- **Effort:** 3 hours
- **Dependencies:** Task 3.7, Slack MCP plugin availability
- **Acceptance Criteria:**
  - [ ] Slack app created via Slack API
  - [ ] Slack MCP plugin installed and configured
  - [ ] Bridge Bot can receive messages from Slack (mentions or DMs)
  - [ ] Bridge Bot can send responses to Slack threads
  - [ ] `/dispatch` slash command registered in Slack workspace
  - [ ] Task completion reports delivered to the Slack thread that requested them
  - [ ] Permission relay works with Slack interactive messages (if supported)

### Task 3.10: Update Bridge Bot for Multi-Channel

- **Description:** Update Bridge Bot CLAUDE.md and configuration to handle messages from all connected channels. Ensure channel-specific formatting (Slack markdown vs Telegram HTML, etc.).
- **Effort:** 2 hours
- **Dependencies:** Tasks 3.8, 3.9
- **Acceptance Criteria:**
  - [ ] Bridge Bot routes commands from any channel through same bridge-cli.py
  - [ ] Responses formatted appropriately per channel
  - [ ] Task results sent back to the channel that dispatched them
  - [ ] Channel source tracked in task row (for history/reporting)
  - [ ] `tasks` table has new column: `channel TEXT` (telegram, discord, slack, cli)

### Task 3.11: Test Multi-Channel

- **Description:** Test the same workflow across all three channels.
- **Effort:** 2 hours
- **Dependencies:** Tasks 3.8, 3.9, 3.10
- **Acceptance Criteria:**
  - [ ] Dispatch task from Telegram: works, result returned to Telegram
  - [ ] Dispatch task from Discord: works, result returned to Discord
  - [ ] Dispatch task from Slack: works, result returned to Slack
  - [ ] Dispatch from Telegram, check status from Discord: shows correct state
  - [ ] History shows which channel each task came from

---

## Cost Dashboard

### Task 3.12: Implement Cost Aggregation Queries

- **Description:** Build SQLite queries for aggregating cost data by agent, project, day, week, and month. Create utility functions used by the dashboard command.
- **Effort:** 2 hours
- **Dependencies:** Phase 2 cost tracking
- **Acceptance Criteria:**
  - [ ] Query: total cost per agent (all time, this week, today)
  - [ ] Query: total cost per project directory (all time, this week, today)
  - [ ] Query: daily cost breakdown for last 30 days
  - [ ] Query: cost per model (sonnet vs opus)
  - [ ] Query: average cost per task by agent
  - [ ] All queries handle NULL costs gracefully

### Task 3.13: Implement Dashboard Command

- **Description:** Add `bridge-cli.py dashboard [--period week|month|all]` showing a comprehensive cost overview.
- **Effort:** 2.5 hours
- **Dependencies:** Task 3.12
- **Acceptance Criteria:**
  - [ ] Shows total spend for the period
  - [ ] Shows breakdown by agent: name, task count, total cost, avg cost
  - [ ] Shows breakdown by project: path, task count, total cost
  - [ ] Shows breakdown by model: model name, task count, total cost
  - [ ] Shows daily trend for the period (last 7 or 30 days)
  - [ ] Shows top 5 most expensive tasks
  - [ ] Output formatted for terminal (with alignment)
  - [ ] Compact version suitable for Telegram relay

### Task 3.14: Implement Cost Alerts

- **Description:** Add configurable cost alerts that notify via Telegram when spending exceeds thresholds.
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.13
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py set-alert daily <amount>` sets daily spend alert (e.g., $5.00)
  - [ ] `bridge-cli.py set-alert per-task <amount>` sets per-task alert (e.g., $1.00)
  - [ ] Alerts stored in `config.yaml`
  - [ ] on-complete.py checks alerts after each task
  - [ ] If daily threshold exceeded: sends Telegram warning
  - [ ] If single task exceeded threshold: includes warning in completion report
  - [ ] `bridge-cli.py alerts` shows current alert configuration

---

## Workspace Cleanup Automation

### Task 3.15: Implement Workspace Cleanup Command

- **Description:** Add `bridge-cli.py cleanup [--retention N]` to remove old task results, worktrees, and log files. Default retention: 7 days.
- **Effort:** 2 hours
- **Dependencies:** Phase 1 workspace structure
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py cleanup` removes task result files older than retention period
  - [ ] `bridge-cli.py cleanup --retention 30` uses 30-day retention
  - [ ] `bridge-cli.py cleanup --dry-run` shows what would be deleted without deleting
  - [ ] Removes: result JSON files, stderr logs, orphaned worktrees
  - [ ] Does NOT remove: SQLite data (history preserved), active task files, agent definitions
  - [ ] Reports: "Cleaned up 15 files, freed 42 MB"
  - [ ] Claude Code worktrees cleaned via `git worktree prune`

### Task 3.16: Implement Auto-Cleanup via Cron

- **Description:** Add auto-cleanup to the existing watcher cron job. Run cleanup once daily (detect day change).
- **Effort:** 1 hour
- **Dependencies:** Task 3.15, Phase 1 watcher cron
- **Acceptance Criteria:**
  - [ ] watcher.py checks if cleanup has run today (marker file)
  - [ ] If not run today: runs cleanup with configured retention
  - [ ] Retention period configurable in config.yaml (default 7 days)
  - [ ] Cleanup results logged to `~/.claude-bridge/cleanup.log`
  - [ ] Does not interfere with watcher's primary PID-checking function

---

## Session Management Improvements

### Task 3.17: Implement Reset Session Command

- **Description:** Add `bridge-cli.py reset-session <agent_name>` to clear an agent's Claude Code session context. The agent starts fresh but retains its configuration and Auto Memory.
- **Effort:** 1.5 hours
- **Dependencies:** Phase 1 agent management
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py reset-session backend` clears session context
  - [ ] Errors if agent has a running task
  - [ ] Generates a new session_id (e.g., `backend--my-api-v2`) to avoid old context
  - [ ] Updates SQLite agent row with new session_id
  - [ ] Updates agent `.md` file with new session_id in Stop hook
  - [ ] Auto Memory preserved (lives in Claude Code's project memory, not session)
  - [ ] Old session workspace preserved (for history)
  - [ ] New workspace created for new session
  - [ ] Prints: "Session reset for agent 'backend'. New session: backend--my-api-v2"

### Task 3.18: Implement Fork Session Command

- **Description:** Add `bridge-cli.py fork-session <source_agent> <new_agent_name>` to create a new agent that inherits the source agent's configuration but gets an independent session.
- **Effort:** 2 hours
- **Dependencies:** Task 3.17, Phase 1 agent CRUD
- **Acceptance Criteria:**
  - [ ] `bridge-cli.py fork-session backend backend-v2` creates new agent
  - [ ] New agent copies: purpose, model, project_dir from source
  - [ ] New agent gets: fresh session_id, fresh workspace, own agent `.md` file
  - [ ] New agent does NOT copy: task history, session context
  - [ ] New agent DOES share: project Auto Memory (same project_dir)
  - [ ] Source agent is unchanged
  - [ ] Prints: "Forked agent 'backend' -> 'backend-v2'"

### Task 3.19: Implement Session Info Command

- **Description:** Add `bridge-cli.py session-info <agent_name>` showing detailed session information including memory size, task count, session age, and workspace size.
- **Effort:** 1 hour
- **Dependencies:** Phase 1 agent management
- **Acceptance Criteria:**
  - [ ] Shows: session_id, created_at, task count (total/done/failed)
  - [ ] Shows: workspace size on disk
  - [ ] Shows: Auto Memory file count and total size
  - [ ] Shows: model configuration
  - [ ] Shows: agent state (idle/busy) and current task if busy
  - [ ] Output suitable for Telegram relay

---

## Summary

| Area | Tasks | Total Effort |
|------|-------|-------------|
| Agent Teams | 6 tasks | ~14 hours |
| Multi-Channel | 5 tasks | ~12 hours |
| Cost Dashboard | 3 tasks | ~6 hours |
| Workspace Cleanup | 2 tasks | ~3 hours |
| Session Management | 3 tasks | ~4.5 hours |
| **Total** | **19 tasks** | **~39.5 hours** |
