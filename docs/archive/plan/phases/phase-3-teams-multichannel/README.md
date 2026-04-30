# Phase 3: Agent Teams + Multi-Channel + Dashboard

**Goal:** Complex tasks split across coordinated agent teams (lead + teammates). Discord and Slack as additional dispatch channels. Cost dashboard with per-agent/project/day breakdowns. Operational maturity: workspace cleanup, session management.

**Status:** [ ] Not started

**Estimated effort:** ~39.5 hours (Week 5+)

**Dependencies:** Phase 2 complete (queue system required for team coordination); Discord/Slack MCP plugins available

---

## Demo Scenario

After this phase:

```
[Telegram] → "build user profile page with API and frontend"
Team task #15 dispatched to lead 'backend' with teammates: frontend.

[backend agent decomposes and dispatches sub-tasks]
  Sub-task #16 → frontend: "build profile UI component"
  Sub-task #17 → backend: "add GET /users/:id/profile endpoint"

[both sub-tasks complete]
✓ Team task #15 complete — 2 agents, 4m 32s, $0.12
  Backend: Added profile endpoint with avatar, bio, social links
  Frontend: React ProfileCard component with skeleton loading

[Discord] → "ask backend to fix the login bug"   ← works the same as Telegram
[Slack]   → "/dispatch frontend add dark mode"   ← works too

[Telegram] → "show cost dashboard"
Week total: $1.47 | 23 tasks | avg $0.06
Top agents: backend ($0.89), frontend ($0.58)
```

---

## Tasks

### Agent Teams

#### Task 3.1: Design Team Coordination Protocol
- **Effort:** 3 hours
- **Dependencies:** Phase 2 queue system
- **Acceptance Criteria:**
  - [ ] Documented: team definition format (lead + teammates)
  - [ ] Documented: how lead's CLAUDE.md instructs decomposition
  - [ ] Documented: sub-task dispatch mechanism (lead calls bridge-cli dispatch)
  - [ ] Documented: result aggregation (lead polls teammate status, collects results)
  - [ ] Documented: failure handling (teammate fails → lead decides retry or skip)
  - [ ] SQLite schema extension designed: `teams`, `team_members`, `task_parent_id`
- **Files:** `plan/architecture/team-coordination.md` (new)

#### Task 3.2: `create-team` Command
- **Effort:** 2 hours
- **Dependencies:** Task 3.1
- **Acceptance Criteria:**
  - [ ] `create-team fullstack --lead backend --members frontend,devops` succeeds
  - [ ] Validates all referenced agents exist
  - [ ] `teams` table: `name TEXT PRIMARY KEY, lead_agent TEXT, created_at TEXT`
  - [ ] `team_members` table: `team_name TEXT, agent_name TEXT`
  - [ ] `list-teams` shows all teams with members
  - [ ] `delete-team <name>` removes team (agents preserved)
- **Files:** `src/claude_bridge/db.py`, `src/claude_bridge/cli.py`

#### Task 3.3: `team-dispatch` Command
- **Effort:** 3 hours
- **Dependencies:** Tasks 3.2, Phase 2 queue
- **Acceptance Criteria:**
  - [ ] `team-dispatch fullstack "build user profile page"` dispatches to lead
  - [ ] Lead's prompt augmented: original + team context + decomposition instructions
  - [ ] Lead dispatches sub-tasks via `bridge-cli dispatch` (using Bash tool)
  - [ ] Parent task row: `type='team'`; sub-tasks linked via `parent_task_id`
- **Files:** `src/claude_bridge/cli.py`, `src/claude_bridge/dispatcher.py`

#### Task 3.4: `team-status` Command
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.3
- **Acceptance Criteria:**
  - [ ] Shows parent task status (lead agent)
  - [ ] Shows all sub-tasks: agent name, status, prompt summary, duration
  - [ ] Shows overall progress: "3/5 sub-tasks complete"
- **Files:** `src/claude_bridge/cli.py`

#### Task 3.5: Team Result Aggregation
- **Effort:** 2.5 hours
- **Dependencies:** Tasks 3.3–3.4
- **Acceptance Criteria:**
  - [ ] `on_complete.py` detects when a sub-task completes
  - [ ] Checks if all sub-tasks for parent are done
  - [ ] If all done and lead idle: notifies lead to aggregate results
  - [ ] Parent task marked done with aggregated summary
  - [ ] Total cost = sum of lead + all sub-task costs
- **Files:** `src/claude_bridge/on_complete.py`

#### Task 3.6: Test Agent Teams
- **Effort:** 2 hours
- **Acceptance Criteria:**
  - [ ] Create 2+ agents for different concerns
  - [ ] Dispatch team task; lead decomposes and assigns sub-tasks
  - [ ] Sub-tasks complete; lead aggregates; team status shows all outcomes
  - [ ] Total cost tracked across all agents

---

### Multi-Channel Support

#### Task 3.7: Design Channel Abstraction Layer
- **Effort:** 2 hours
- **Dependencies:** Phase 1 Telegram integration
- **Acceptance Criteria:**
  - [ ] Documented: abstraction interface (receive_message, send_message, send_buttons)
  - [ ] Documented: how each platform maps to the abstraction
  - [ ] Decision: one Bridge Bot per channel vs multi-channel MCP
  - [ ] Decision: how to handle channel-specific features (threads, reactions)
- **Files:** `plan/architecture/channel-abstraction.md` (new), `src/claude_bridge/channel.py`

#### Task 3.8: Discord MCP Integration
- **Effort:** 3 hours
- **Dependencies:** Task 3.7, Discord MCP plugin availability
- **Acceptance Criteria:**
  - [ ] Discord bot created and MCP plugin configured
  - [ ] All bridge-cli commands accessible from Discord
  - [ ] Task completion reports delivered to the Discord channel that requested them

#### Task 3.9: Slack MCP Integration
- **Effort:** 3 hours
- **Dependencies:** Task 3.7, Slack MCP plugin availability
- **Acceptance Criteria:**
  - [ ] Slack app created and MCP plugin configured
  - [ ] `/dispatch` slash command registered in Slack workspace
  - [ ] Task completion reports delivered to the Slack thread that requested them

#### Task 3.10: Update Bridge Bot for Multi-Channel
- **Effort:** 2 hours
- **Dependencies:** Tasks 3.8–3.9
- **Acceptance Criteria:**
  - [ ] Bridge Bot routes commands from any channel through same bridge-cli
  - [ ] Responses formatted appropriately per channel (Slack markdown vs Telegram HTML)
  - [ ] `tasks.channel TEXT` column (telegram, discord, slack, cli)
- **Files:** Bridge Bot CLAUDE.md update, `src/claude_bridge/db.py`

#### Task 3.11: Test Multi-Channel
- **Effort:** 2 hours
- **Acceptance Criteria:**
  - [ ] Dispatch from Telegram, Discord, Slack — all work, results returned to origin
  - [ ] Dispatch from Telegram, check status from Discord: correct state
  - [ ] History shows which channel each task came from

---

### Cost Dashboard

#### Task 3.12: Cost Aggregation Queries
- **Effort:** 2 hours
- **Dependencies:** Phase 2 cost tracking
- **Acceptance Criteria:**
  - [ ] Queries: total cost per agent, per project, per day/week/month
  - [ ] Queries: cost per model (sonnet vs opus)
  - [ ] All queries handle NULL costs gracefully
- **Files:** `src/claude_bridge/db.py`

#### Task 3.13: `dashboard` Command
- **Effort:** 2.5 hours
- **Dependencies:** Task 3.12
- **Acceptance Criteria:**
  - [ ] `dashboard --period week|month|all`
  - [ ] Shows: total spend, breakdown by agent, by project, by model
  - [ ] Shows: daily trend, top 5 most expensive tasks
  - [ ] Compact version suitable for Telegram relay
- **Files:** `src/claude_bridge/cli.py`

#### Task 3.14: Cost Alerts
- **Effort:** 1.5 hours
- **Dependencies:** Task 3.13
- **Acceptance Criteria:**
  - [ ] `set-alert daily <amount>` / `set-alert per-task <amount>`
  - [ ] `on_complete.py` checks alerts after each task
  - [ ] Sends Telegram warning when thresholds exceeded
- **Files:** `src/claude_bridge/on_complete.py`, `src/claude_bridge/cli.py`

---

### Workspace Cleanup

#### Task 3.15: `cleanup` Command
- **Effort:** 2 hours
- **Dependencies:** Phase 1 workspace structure
- **Acceptance Criteria:**
  - [ ] `cleanup` removes task result files older than retention period (default 7 days)
  - [ ] `cleanup --retention 30` uses 30-day retention
  - [ ] `cleanup --dry-run` shows what would be deleted
  - [ ] Removes: result JSON, stderr logs, orphaned worktrees (`git worktree prune`)
  - [ ] Does NOT remove: SQLite data, active task files, agent definitions
  - [ ] Reports: "Cleaned up 15 files, freed 42 MB"
- **Files:** `src/claude_bridge/cli.py`

#### Task 3.16: Auto-Cleanup via Cron
- **Effort:** 1 hour
- **Dependencies:** Task 3.15
- **Acceptance Criteria:**
  - [ ] `watcher.py` runs cleanup once daily (marker file detection)
  - [ ] Retention period configurable (default 7 days)
  - [ ] Cleanup logged to `~/.claude-bridge/cleanup.log`
- **Files:** `src/claude_bridge/watcher.py`

---

### Session Management

#### Task 3.17: `reset-session` Command
- **Effort:** 1.5 hours
- **Acceptance Criteria:**
  - [ ] `reset-session backend` generates new session_id; errors if task running
  - [ ] Updates SQLite and agent `.md` Stop hook
  - [ ] Auto Memory preserved (lives in Claude Code project memory)
  - [ ] Old workspace preserved; new workspace created
- **Files:** `src/claude_bridge/cli.py`, `src/claude_bridge/agent_md.py`

#### Task 3.18: `fork-session` Command
- **Effort:** 2 hours
- **Acceptance Criteria:**
  - [ ] `fork-session backend backend-v2` creates new agent
  - [ ] Copies: purpose, model, project_dir
  - [ ] Fresh: session_id, workspace, agent .md file
  - [ ] Does NOT copy: task history, session context
  - [ ] DOES share: project Auto Memory (same project_dir)
- **Files:** `src/claude_bridge/cli.py`

#### Task 3.19: `session-info` Command
- **Effort:** 1 hour
- **Acceptance Criteria:**
  - [ ] Shows: session_id, created_at, task count (total/done/failed)
  - [ ] Shows: workspace size, Auto Memory file count/size, model config
- **Files:** `src/claude_bridge/cli.py`

---

## Summary

| Area | Tasks | Effort |
|------|-------|--------|
| Agent Teams | 6 tasks | ~14 h |
| Multi-Channel | 5 tasks | ~12 h |
| Cost Dashboard | 3 tasks | ~6 h |
| Workspace Cleanup | 2 tasks | ~3 h |
| Session Management | 3 tasks | ~4.5 h |
| **Total** | **19 tasks** | **~39.5 h** |
