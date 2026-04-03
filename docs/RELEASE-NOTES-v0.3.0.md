# Claude Bridge v0.3.0 — Goal Loop

**Released:** 2026-04-03

---

## What's New

### Goal Loop — autonomous task repetition until done

v0.3.0 introduces **Goal Loop**: tell Bridge what you want accomplished and *how you'll
know it's done*, then let it keep dispatching your agent until the goal is met.

Before v0.3.0 you had to manually re-dispatch a task every time it failed or fell short.
Goal Loop closes that cycle automatically — it re-dispatches with contextual feedback
from the previous iteration (test failures, stack traces), tracks cumulative cost, and
notifies you via Telegram when it's done or when it needs your approval.

```
bridge-cli loop backend "fix failing tests" --done-when "command:pytest"
```

That one command will keep asking your `backend` agent to fix tests, feeding it the
pytest failure output each round, until the full suite passes — or until it hits the
iteration/cost limits you set.

---

## Quick Start

### Run until a command succeeds

```bash
bridge-cli loop backend "fix failing tests" --done-when "command:pytest"
bridge-cli loop backend "fix failing tests" --done-when "command:pytest" --max 10
bridge-cli loop backend "fix failing tests" --done-when "command:pytest" --max-cost 2.00
```

### Run until a file appears

```bash
bridge-cli loop researcher "write executive summary" \
  --done-when "file_exists:output/brief.md"
```

### Run until a file contains a specific string

```bash
bridge-cli loop backend "deploy to staging" \
  --done-when "file_contains:deploy.log:SUCCESS"
```

### Run until an AI judge says the goal is met

```bash
bridge-cli loop backend "refactor auth module" \
  --done-when "llm_judge:Code has no TODOs, all functions have docstrings, test coverage > 80%"
```

### Run with manual human approval

```bash
bridge-cli loop researcher "draft Q2 report" \
  --done-when "manual:Review the draft before marking done"
# After each iteration, Bridge waits for your approval:
bridge-cli loop-approve <loop-id>          # mark done
bridge-cli loop-reject <loop-id> --feedback "Add competitive analysis section"
```

---

## Done Condition Reference

| Type | Syntax | Passes when |
|------|--------|-------------|
| `command` | `command:pytest` | Shell command exits 0 |
| `file_exists` | `file_exists:output/report.md` | File path exists |
| `file_contains` | `file_contains:log.txt:SUCCESS` | File contains substring |
| `llm_judge` | `llm_judge:<rubric>` | Claude evaluates rubric as met |
| `manual` | `manual:<message>` | You approve via CLI or Telegram |

---

## Loop Types

Bridge automatically picks the right loop strategy for your done condition:

| Condition type | Default strategy | Why |
|---------------|-----------------|-----|
| `command`, `file_exists`, `file_contains` + ≤ 5 iterations | **Agent loop** | Agent retries internally — faster, no round-trip overhead |
| `llm_judge`, `manual` | **Bridge loop** | Needs external evaluation between iterations |
| > 5 iterations | **Bridge loop** | Better observability for long-running goals |

Override with `--type bridge` or `--type agent` to force a specific strategy.

---

## Dashboard Commands

```bash
# See all loops (active + recent)
bridge-cli loop-list

# Filter to a specific agent
bridge-cli loop-list backend

# Show only running loops
bridge-cli loop-list --active

# Full iteration history for a loop
bridge-cli loop-history <loop-id>

# Current status
bridge-cli loop-status
bridge-cli loop-status --loop-id <loop-id>

# Cancel (current task finishes, no more iterations)
bridge-cli loop-cancel <loop-id>
```

---

## Telegram Integration

If you're using Bridge Bot, loop control works naturally from chat:

**Start a loop:**
```
loop backend fix tests until pytest passes
loop researcher write report until file output/report.md exists
```

**Approve / reject (for manual loops):**
```
approve
approve loop 42
reject: needs more detail on section 3
/approve-loop 42
/deny-loop 42
```

**Check status:**
```
loop status
loop status 42
list loops
```

Bridge Bot sends you automatic notifications when:
- A loop starts
- Each iteration completes (with running cost)
- A manual condition needs your approval
- The loop finishes (with total cost + duration)

---

## Feedback Between Iterations

Between iterations, Bridge automatically extracts and forwards to the next prompt:
- **pytest failures** — `FAILED test_foo.py::test_bar` lines
- **Python stack traces** — last traceback, truncated to 2 000 chars
- **Result summary** — last 2 iteration summaries, up to 500 chars each

The agent receives this context in its next task prompt, so it can focus on what
specifically failed rather than starting from scratch.

---

## Cost Tracking

Every iteration's cost is recorded. Loop reports show:
- Cost per iteration
- Cumulative total
- Warning at 80% of cost limit
- Hard stop when limit is reached

```bash
# Set a $2.00 ceiling
bridge-cli loop backend "refactor auth" --done-when "command:pytest" --max-cost 2.00
```

---

## Migrating from v0.2

No breaking changes. Existing agents, tasks, and sessions are unaffected.

The database migration is **automatic**: on first run, Bridge adds `loops` and
`loop_iterations` tables to your existing `~/.claude-bridge/bridge.db`. No manual
steps required.

**New CLI commands** (all additive, no existing commands changed):

| Command | What it does |
|---------|-------------|
| `bridge-cli loop` | Start a goal loop |
| `bridge-cli loop-list` | List all loops |
| `bridge-cli loop-history <id>` | Full iteration history |
| `bridge-cli loop-status` | Current loop status |
| `bridge-cli loop-cancel <id>` | Cancel a running loop |
| `bridge-cli loop-approve <id>` | Approve a manual loop |
| `bridge-cli loop-reject <id>` | Reject and continue |

**New MCP tools** (for Bridge Bot):
`bridge_loop`, `bridge_loop_status`, `bridge_loop_cancel`, `bridge_loop_approve`,
`bridge_loop_reject`, `bridge_loop_list`, `bridge_loop_history`, `bridge_loop_notify`,
`bridge_parse_loop_command`

---

## Known Limitations

1. **LLM judge requires `claude --print`** — the `llm_judge` condition invokes the
   `claude` CLI with `--print`. If your Claude CLI version does not support this flag,
   the judge will fall back gracefully (condition evaluates to "not done") and log a
   warning to stderr. Upgrade to the latest Claude CLI if you rely on this condition.

2. **Bridge Bot loop notifications require a CLAUDE.md update** — the notification
   formatters and `bridge_loop_notify` MCP tool are implemented, but the Bridge Bot's
   `CLAUDE.md` needs to be updated to automatically call `bridge_loop_notify` after
   task completion events. Until then, you can trigger notifications manually via the
   MCP tool.

3. **Natural language done conditions are limited** — the Telegram NLP parser handles
   common patterns (`pytest passes`, `file X exists`, `file X contains Y`). Time-based
   or open-ended conditions (`until it works`, `until 3pm`) are not parsed — pass an
   explicit `done-when` string for those.

4. **One loop per agent at a time** — Bridge rejects a new loop if the agent already
   has a running loop. Cancel the existing loop first with `loop-cancel` if you want
   to start a different one.

5. **Agent loop result parsing uses regex** — the `AGENT_LOOP_RESULT` JSON marker is
   extracted with a regex that may not handle deeply nested JSON correctly in edge
   cases. In practice, the agent result JSON is shallow and this is not a real concern.

---

## Stats

| Metric | Value |
|--------|-------|
| New files | 5 |
| Modified files | 8 |
| New tests | 240 |
| Total tests | 684 |
| Test pass rate | 100% |
| Regressions | 0 |

---

*Questions? Open an issue or message the bridge bot — it's always listening.*
