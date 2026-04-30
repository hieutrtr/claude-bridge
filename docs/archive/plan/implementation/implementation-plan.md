# Claude Bridge -- Implementation Plan

> Multi-session Claude Code dispatch from Telegram.
> Built on top of Claude Code native features, not around them.

---

## Prerequisites

Before starting implementation, ensure the following are in place:

| Requirement | Details |
|-------------|---------|
| **macOS** | Primary development and runtime platform |
| **Claude Code CLI** | Installed and authenticated (`claude --version` works) |
| **Max subscription** | Required for Claude Code usage (Sonnet default, Opus access) |
| **Telegram account** | For BotFather bot creation |
| **Telegram Bot Token** | Create via @BotFather before Day 8 |
| **Python 3.11+** | For bridge-cli, on-complete.py, watcher.py |
| **SQLite3** | Bundled with Python, no separate install needed |
| **Git** | For worktree isolation (native Claude Code feature) |
| **Telegram MCP plugin** | Official Anthropic plugin, install before Day 8 |

---

## Development Approach

1. **Build each component independently** -- bridge-cli.py commands work standalone from terminal before integrating with Telegram
2. **Test from terminal first** -- every CLI command must work via `python3 bridge-cli.py <command>` before Bridge Bot touches it
3. **Leverage Claude Code native features** -- never reimplement what Claude Code already provides (sessions, worktrees, memory, hooks)
4. **Minimal code** -- target ~425 lines total Python across all files
5. **SQLite as single source of truth** -- all state flows through bridge.db
6. **Incremental integration** -- each milestone produces a testable artifact

---

## Phase 1: MVP Core Dispatch (Week 1-2)

### Goals

- Individual developer can create agents, dispatch tasks, and receive results
- Full lifecycle: create agent -> dispatch task -> task runs -> completion detected -> report delivered
- Telegram integration for remote dispatch from phone
- Single task execution per agent (no queue)

### Components to Build

| Component | Lines | Purpose |
|-----------|-------|---------|
| `bridge-cli.py` | ~250 | Agent CRUD, task dispatch, status, kill, history, memory |
| `on-complete.py` | ~30 | Stop hook handler: parse result, update SQLite, print report |
| `watcher.py` | ~50 | Fallback cron job: detect crashed/timed-out tasks |
| `bridge.db` schema | ~25 | SQLite tables: agents + tasks |
| Bridge Bot `CLAUDE.md` | ~60 | Command routing rules for Bridge Bot session |
| Agent `.md` template | -- | Generated per agent in `~/.claude/agents/` |

### Dependencies

- Claude Code CLI must be installed and authenticated
- Python 3.10+ available at `/usr/bin/python3` or equivalent
- Git installed for worktree support

### Risks

| Risk | Mitigation |
|------|------------|
| Stop hook doesn't fire on crash | watcher.py fallback with 5-min cron |
| Telegram MCP plugin not available | Test CLI-only first, add Telegram last (Day 8-9) |
| CLAUDE.md init prompt produces poor output | Iterate on prompt, test with 2-3 real projects |
| subprocess.Popen PID tracking race conditions | Write PID to SQLite immediately after Popen |
| Claude Code CLI flags change | Pin to known working version, test on each update |

### Success Criteria

- [ ] `bridge-cli.py create-agent` creates agent with valid .md file and workspace
- [ ] `bridge-cli.py dispatch` spawns Claude Code with correct flags, PID tracked
- [ ] Task completion detected via Stop hook, SQLite updated, report printed
- [ ] `bridge-cli.py status` shows accurate running/idle state
- [ ] `bridge-cli.py kill` terminates running task cleanly
- [ ] End-to-end: Telegram message -> Bridge Bot -> bridge-cli.py -> Claude Code -> result -> Telegram
- [ ] Watcher catches crashed tasks within 5 minutes

---

## Phase 2: Queue + Permissions + Model Routing (Week 3-4)

### Goals

- Tasks queue when agent is busy, processed in FIFO order
- Permission requests (dangerous commands) relay to Telegram for human approval
- Model routing: Sonnet for routine tasks, Opus for complex, configurable per agent
- Improved cost tracking and visibility

### Components to Build

| Component | Purpose |
|-----------|---------|
| Task queue logic in `bridge-cli.py` | Queue tasks when agent busy, dequeue on completion |
| Queue processor in `on-complete.py` | After task completes, check queue, dispatch next |
| Permission hook script | Intercept permission requests, send Telegram inline buttons |
| Permission approval handler | Process button callbacks, resume/deny task |
| Model routing in agent `.md` | Configure model per agent, override per task |
| Cost tracking improvements | Parse cost from Claude output, aggregate in SQLite |

### Dependencies

- Phase 1 complete and stable
- Telegram inline keyboard buttons working (via MCP plugin)
- Understanding of Claude Code hook system for permission interception

### Risks

| Risk | Mitigation |
|------|------------|
| Queue race conditions (two tasks dequeue simultaneously) | SQLite transactions with EXCLUSIVE lock |
| Permission hook blocks task indefinitely | Timeout after 10 min, auto-deny with notification |
| Model routing syntax changes in Claude Code | Abstract behind config, easy to update |
| Cost parsing from Claude output is fragile | Regex with fallback, log unparseable output for debugging |

### Success Criteria

- [ ] Dispatch to busy agent queues task, auto-dispatches when agent becomes idle
- [ ] Queue order is FIFO, visible via `bridge-cli.py queue <agent>`
- [ ] Permission request appears in Telegram with Approve/Deny buttons
- [ ] Approve resumes task, Deny stops task -- both update SQLite
- [ ] Permission timeout after 10 min auto-denies with notification
- [ ] Agent can be configured for Sonnet or Opus model
- [ ] Task dispatch can override agent default model with `--model opus`
- [ ] Cost per task is tracked in SQLite, viewable via `bridge-cli.py history`

---

## Phase 3: Agent Teams + Multi-Channel + Dashboard (Week 5+)

### Goals

- Complex tasks can be split across coordinated agent teams (lead + teammates)
- Support Discord and Slack as additional dispatch channels
- Cost dashboard with per-agent, per-project, per-day breakdowns
- Operational improvements: workspace cleanup, session management

### Components to Build

| Component | Purpose |
|-----------|---------|
| Agent Teams orchestration | Lead agent decomposes task, assigns to teammates |
| Team coordination protocol | Status tracking, result aggregation across team members |
| Discord MCP integration | Add Discord as dispatch channel |
| Slack MCP integration | Add Slack as dispatch channel |
| Channel abstraction layer | Unified interface for Telegram/Discord/Slack |
| Cost dashboard (`bridge-cli.py dashboard`) | Aggregate cost views |
| Workspace cleanup automation | Prune old worktrees and task results |
| Session management commands | Reset session, fork session |

### Dependencies

- Phase 2 complete (queue system needed for team coordination)
- Discord MCP plugin available (Anthropic official or community)
- Slack MCP plugin available
- Sufficient task history data for meaningful dashboard

### Risks

| Risk | Mitigation |
|------|------------|
| Agent Teams feature not yet in Claude Code | Design as composable dispatch (lead dispatches sub-tasks via bridge-cli) |
| Discord/Slack MCP plugins don't exist or differ in API | Build channel abstraction early, adapt per platform |
| Cost data incomplete from earlier phases | Backfill from Claude Code logs if available |
| Workspace cleanup deletes needed data | Configurable retention period, dry-run mode |
| Team coordination adds significant complexity | Start with simple 1-lead + 1-teammate, expand |

### Success Criteria

- [ ] Lead agent can decompose a task and dispatch sub-tasks to teammate agents
- [ ] Team results are aggregated and reported back as a single response
- [ ] Tasks can be dispatched from Discord with same UX as Telegram
- [ ] Tasks can be dispatched from Slack with same UX as Telegram
- [ ] `bridge-cli.py dashboard` shows cost breakdown by agent, project, and day
- [ ] Old workspaces auto-cleaned after configurable retention period
- [ ] `bridge-cli.py reset-session <agent>` clears session context
- [ ] `bridge-cli.py fork-session <agent> <new-agent>` creates agent with copied context

---

## Timeline Overview

```
Week 1-2 (Phase 1: MVP)
├── Day 1-2:  Foundation (project structure, SQLite, agent CRUD)
├── Day 3:    CLAUDE.md init (purpose-driven project scan)
├── Day 4-5:  Task dispatch (subprocess, PID tracking, status, kill)
├── Day 6-7:  Completion system (Stop hook, watcher, cron)
├── Day 8-9:  Telegram integration (Bridge Bot, MCP plugin)
└── Day 10:   Polish (history, memory, NLP, edge cases, E2E test)

Week 3-4 (Phase 2: Queue + Permissions + Models)
├── Day 11-12: Task queue (FIFO, dequeue on completion)
├── Day 13-14: Permission relay (hook interception, Telegram buttons)
├── Day 15-16: Model routing (per-agent config, per-task override)
└── Day 17-18: Cost tracking + integration testing

Week 5+ (Phase 3: Teams + Channels + Dashboard)
├── Agent Teams integration
├── Discord + Slack channels
├── Cost dashboard
├── Workspace cleanup
└── Session management
```

---

## File System at Each Phase

```
Phase 1 delivers:
  ~/.claude-bridge/
  ├── bridge-cli.py
  ├── on-complete.py
  ├── watcher.py
  ├── bridge.db
  ├── CLAUDE.md              (Bridge Bot instructions)
  └── workspaces/

Phase 2 adds:
  ~/.claude-bridge/
  ├── permission-hook.py     (permission interception)
  └── config.yaml            (model routing, timeouts)

Phase 3 adds:
  ~/.claude-bridge/
  ├── dashboard.py           (cost aggregation)
  └── cleanup.py             (workspace retention)
```
