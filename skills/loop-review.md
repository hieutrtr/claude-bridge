---
name: loop-review
description: Post-mortem audit for a goal loop instance. Pulls plan + iterations + tasks from bridge.db, traces what each iteration actually did, scores plan quality, identifies anti-patterns (plan fallback, mega-steps, cost spikes, premature failure), and emits a markdown report with concrete recommendations. Use when a loop ended with a surprising result, when iterations look bloated, or when validating that plan-first mode is producing per-step reports as intended.
---

# Goal-Loop Post-Mortem Review

You are auditing **one loop instance** that already ran (or is mid-flight). The goal is to produce an honest report: what the plan was, whether each iteration did what it was supposed to, why the loop ended where it did, and what should have been done differently.

This is **read-only**. Do not edit code, do not cancel/restart loops, do not write to the DB. Output is a markdown report only.

## Inputs

Accept exactly one of:

- `--loop-id <id>` — explicit 8-char loop_id
- `--last [N]` — most recent loop overall (or N-th most recent; default 1)
- `--agent <name> [--last N]` — most recent loop for a specific agent

Resolve to a single `loop_id` before proceeding. If ambiguous, list candidates and stop.

`CLAUDE_BRIDGE_HOME` defaults to `~/.claude-bridge`. Honor the env var if set.

## Phase 1 — Identify

Pull the loop row. Use the SQLite CLI directly against `$CLAUDE_BRIDGE_HOME/bridge.db`:

```bash
sqlite3 -json "$CLAUDE_BRIDGE_HOME/bridge.db" \
  "SELECT * FROM loops WHERE loop_id = '<id>';"
```

Capture: `agent`, `project`, `goal`, `done_when`, `loop_type`, `status`, `max_iterations`, `current_iteration`, `total_cost_usd`, `max_cost_usd`, `consecutive_failures`, `pending_approval`, `finish_reason`, `started_at`, `finished_at`, `plan_enabled`, `plan` (JSON), `channel_chat_id`.

Compute wall-clock duration if both timestamps present.

## Phase 2 — Plan quality

If `plan_enabled = 1`:

- Parse `loops.plan` as JSON. If null, the planning iter hasn't completed yet (loop still in iter 1) — note that and skip plan analysis.
- If parsed: count `steps`, list titles, check for `truncated`.
- Score the plan against these heuristics:
  - **Granularity**: 3–7 steps is the sweet spot. <3 → "too coarse, defeats plan-first". >7 → may overflow `max_iterations - 1`.
  - **Verification coverage**: how many steps have a non-empty `verification` field. Steps without it are harder to evaluate.
  - **Title shape**: imperative phrases ("Write X", "Refactor Y") are good; vague titles ("Step 2", "Continue") are red flags.
  - **Truncation**: `truncated=true` means agent wanted more steps than `max_iterations - 1` allowed → user under-budgeted iterations.

If `plan_enabled = 0`:

- Either user passed `--no-plan` *or* the plan parser fell back. Disambiguate by checking the notifications table for `'could not parse plan'`:
  ```bash
  sqlite3 "$CLAUDE_BRIDGE_HOME/bridge.db" \
    "SELECT message FROM notifications WHERE message LIKE '%Loop <id>%plan%';"
  ```
  If a fallback warning is present → plan parse failed. If not → user opt-out.

## Phase 3 — Iteration trace

Pull every iteration with its task row joined:

```bash
sqlite3 -json "$CLAUDE_BRIDGE_HOME/bridge.db" "
  SELECT
    li.iteration_num, li.task_id, li.prompt, li.result_summary,
    li.cost_usd, li.done_check_passed, li.status AS iter_status,
    li.started_at, li.finished_at,
    t.status AS task_status, t.exit_code, t.error_message,
    t.duration_ms, t.num_turns, t.result_file
  FROM loop_iterations li
  LEFT JOIN tasks t ON CAST(li.task_id AS INTEGER) = t.id
  WHERE li.loop_id = '<id>'
  ORDER BY li.iteration_num;"
```

For each iteration, classify it as one of:

- **Planning iter** — iter 1 when `plan_enabled = 1` and a parsed plan exists (or fallback occurred). Look for "PLANNING ONLY" in the prompt to confirm.
- **Plan-execution iter** — iter ≥ 2 when plan stored. The prompt contains "Current step (X/N)". Pull the step number and step title from the prompt.
- **Legacy iter** — `plan_enabled = 0` execution iter.
- **Manual-review iter** — followed by `pending_approval=1` (check next iter's start time vs this iter's finish; large gap = waiting for human).

For each non-planning iter, compare `result_summary` against the step's `verification`:

- Did the agent claim verification passed?
- Does the work described match the step's `description`?
- Did the agent describe work belonging to a *different* step? (Bleed/over-stuffing.)

If `result_file` exists on disk, read it for richer detail (full claude `--output-format json` payload). Otherwise rely on `result_summary`.

## Phase 4 — Failure mode (if terminal)

If `status` ∈ {`done`, `failed`, `cancelled`}, classify the exit:

| `finish_reason` pattern | Diagnosis |
| --- | --- |
| `Approved by user` | Manual loop, user accepted result |
| `passed` / `condition met` | Done condition evaluator returned true |
| `Exceeded cost limit` | Hit `max_cost_usd` |
| `Too many consecutive failures` | Reached `max_consecutive_failures` — usually means agent is stuck |
| `Exceeded max iterations` | Ran out of budget; condition was reachable in principle |
| `Plan exhausted but done condition still not satisfied` | Plan was incomplete relative to the done condition |
| `Plan parse failed and no iterations left for fallback execution` | Iter 1 didn't produce a plan and `max_iterations=1` |
| `No iterations left after planning` | Planning succeeded but `max_iterations` left no slots for execution |
| `Cancelled by user` | Manual cancel (subprocess may still have completed in flight) |
| `Dispatch failed: ...` | `startTask` threw — usually missing `claude` binary or worktree issue |
| `Process N died without writing a result` | Watcher fallback — claude crashed or was killed |

## Phase 5 — Anti-pattern checklist

Run through this list and note every match. Each becomes a finding in the report.

- [ ] **Plan fallback** — `plan_enabled=0` due to parse failure, not user opt-out
- [ ] **Plan too coarse** — <3 steps for a non-trivial goal, or single mega-step
- [ ] **Plan truncated** — agent wanted more steps than budget allowed
- [ ] **No verification fields** — every step lacks `verification` (bad agent prompt adherence or genuinely unverifiable goal)
- [ ] **Iter cost spike** — any iter cost > 2× the median of execution iters
- [ ] **Step bleed** — iter X's `result_summary` describes work from step Y where Y > X (agent worked ahead despite "Do NOT work ahead")
- [ ] **Consecutive failures recovered** — failures in middle, then succeeded — instability signal
- [ ] **Plan exhausted, condition unmet** — plan was insufficient, suggest revising goal or adding eval steps
- [ ] **Manual loop stale** — `pending_approval=1` and `started_at` > 1 day ago
- [ ] **Done check trivially false** — `done_when` is `file_exists:` for a path that never plausibly gets created (typo?)
- [ ] **Channel routing missing** — `channel_chat_id IS NULL` but loop should report somewhere
- [ ] **No reports emitted** — pending iterations exist but `notifications` table has nothing for this loop's task IDs
- [ ] **Pass-threshold misconfigured for stochastic condition** — `done_when` starts with `llm_judge:` but `pass_threshold = 1`. Single PASS from a noisy judge can false-finalize. Recommend `--pass-threshold 2` (or 3 if cost permits).
- [ ] **Pass-threshold wasted on deterministic condition** — `done_when` is `file_exists:` / `file_contains:` but `pass_threshold > 1`. Re-checking deterministic state burns iterations for no signal. Only meaningful when state can change between checks (flaky tests, etc.).
- [ ] **Threshold never reached but PASSes accumulated** — `consecutive_passes > 0` then reset multiple times. Likely judge variance — bump `pass_threshold`, or switch to a deterministic condition if available.

## Output template

Emit exactly this structure (Vietnamese OR English depending on user's question language; default English):

```markdown
# Loop Review — `<loop_id>`

**Agent / Project:** <agent> on `<project>`
**Goal:** <goal>
**Done when:** `<done_when>`
**Status:** <emoji> <status> — <finish_reason>
**Duration:** <hh:mm:ss> · <current_iter>/<max_iter> iterations · $<total_cost_usd>

## Plan

<one of:>
- N/A — `--no-plan`, single-shot execution
- Fallback — plan parse failed at iter 1; loop ran legacy from iter 2
- N steps (truncated/full): <bullet list of titles>

**Plan quality:** <good/coarse/over-detailed/missing-verification>

## Iteration trace

| # | Type | Step | Cost | Outcome | Notes |
|---|---|---|---|---|---|
| 1 | planning | — | $0.02 | plan stored | 4 steps |
| 2 | exec | 1/4 Write model | $0.08 | ✅ verified | — |
| 3 | exec | 2/4 Write API | $0.21 | ⚠ also did step 3 work | bleed |
| ... |

## Failure mode

<paragraph explaining why the loop ended where it did, mapped to the table in Phase 4>

## Findings

- 🔴 **<critical anti-pattern>** — <evidence + line ref>
- 🟡 **<warning>** — <evidence>
- 🟢 **<positive observation>** — <evidence>

## Recommendations

1. <concrete actionable suggestion, e.g., "Increase max_iterations to 8 — agent's plan wanted 6 steps">
2. <next>
3. ...
```

## Guardrails

- **Honest gaps.** If a section can't be filled (e.g., result_file missing, plan unparseable), say so explicitly. Do not invent data.
- **No grading rubric.** Findings are observations, not scores. Recommend, don't mandate.
- **Cite evidence.** Every finding must point at a specific iter number, cost number, prompt excerpt, or notification message.
- **No editing.** This skill never writes to the DB, never modifies code, never restarts loops. If the user wants action, surface the fix as a recommendation and let them run it.
- **Cost transparency.** Mention if you used result files (cheap) vs spawned a sub-claude for judgment (this skill should never need that).
