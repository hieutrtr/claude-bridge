---
name: loop-code-review
description: Code review for the goal-loop implementation in src/orchestration/. Audits the state machine, plan-first parser, prompt templates, dispatcher seam, completion seam, and test coverage against an explicit checklist. Surfaces missing edge-case handling, prompt drift, race conditions on shared state, and coverage gaps. Use when modifying loop.ts, adding a new done-condition type, changing the plan-first contract, or before merging a loop-touching PR.
---

# Goal-Loop Code Review

You are reviewing the **implementation** of the goal-loop subsystem, not a particular run. Goal: surface logic gaps, correctness risks, and coverage holes against an explicit checklist. Output is a markdown findings report grouped by severity.

This is **read-only**. Do not modify code, run migrations, or trigger loops. If the user wants a fix, surface it as a recommendation; let them run a follow-up.

## Scope

| File | Owns |
| --- | --- |
| `src/orchestration/loop.ts` | LoopOrchestrator state machine, plan parser, prompt builders |
| `src/orchestration/evaluator.ts` | Done-condition parsing + evaluation |
| `src/orchestration/interfaces.ts` | `ILoopOrchestrator` / `ILoopEvaluator` contracts |
| `src/types.ts` | `Loop`, `LoopIteration`, `LoopPlan`, `LoopPlanStep` |
| `src/data/db.ts` | `loops` schema, `LOOP_UPDATABLE` whitelist, migrations, `createLoop` |
| `src/data/interfaces.ts` | `IDatabase.createLoop` signature |
| `src/execution/on-complete.ts` | `LoopCompletionCallback`, loop-handoff branch in `handleCompletion` |
| `src/execution/dispatcher.ts` | `startTask` shared spawn helper |
| `src/infra/startup.ts` | Wiring of orchestrator into `ProcessWatcher` callback |
| `src/cli/index.ts` | `cmdLoop`, `cmdLoopApprove`, `cmdLoopReject`, `cmdLoopCancel`, `cmdOnComplete` (loop callback wiring) |
| `src/mcp/tool-handlers.ts` | `bridge_loop`, `bridge_loop_*` arms — must mirror CLI behavior |
| `src/mcp/tools.ts` | Loop tool schemas (must match handler args) |
| `tests/wave4/loop.test.ts` | LoopOrchestrator coverage (state machine + plan-first) |
| `tests/wave4/evaluator.test.ts` (if exists) | Done-condition coverage |
| `tests/wave2/cross-compat.test.ts` | Loop schema column list — must include all loop columns |

For canonical behavior see `docs/specs/03-orchestration.md`. If the doc and the code disagree, that *is* a finding.

## Inputs

Optional `--scope <area>` to narrow review:

- `state-machine` — only loop.ts state transitions + finalizeLoop
- `plan-first` — only the planning iter / parser / execution prompt path
- `evaluator` — only evaluator.ts
- `seams` — only the dispatcher + on-complete + startup wiring
- `tests` — only test coverage + tests/wave4/loop.test.ts
- (default) all of the above

## Workflow

### Phase A — Read the contract first

1. Read `interfaces.ts` (`ILoopOrchestrator.startLoop` options, `onTaskComplete` signature). The contract is the source of truth — implementations may have grown extra options that the interface doesn't declare; flag those.
2. Read `types.ts` for `Loop`, `LoopPlan`, `LoopPlanStep`. Confirm every column on the SQLite `loops` schema is also on the TS `Loop` interface (and vice versa). Drift here causes silent dropped fields.
3. Read `docs/specs/03-orchestration.md` §1.1–§1.6 to ground yourself in intended behavior. Spot-check that line refs in the doc still resolve correctly.

### Phase B — State machine review (loop.ts)

Walk through `onTaskComplete` (`src/orchestration/loop.ts:98`) top to bottom and verify:

- **Single funnel.** Every terminal transition (done/failed/cancelled) goes through `finalizeLoop`. Search for `db.updateLoop(.*status:` and confirm every match is inside `finalizeLoop` or is setting a non-terminal status (`pending_approval`, `consecutive_failures`, etc.).
- **Order of branches.** Cost-limit check fires *before* failure-count check fires *before* done-condition check. If the order changes, a runaway loop could escape one limiter and trip another with confusing finish_reason.
- **Planning iter early-return.** `isPlanningIteration` fires before consecutive-failure increment and before done-check. If reordered, planning iter would be evaluated against the goal (always failing) → false consecutive failure increment.
- **`loop.status !== "running"` early return.** Confirms cancelled/done loops can't accidentally re-dispatch via stale callbacks.
- **`current_task_id` matching.** `on-complete.ts:98` checks `loop.current_task_id === String(taskId)` before invoking the loop callback. If a stale task completes after the loop moved on, the callback should be skipped.

### Phase C — Plan-first review (the new surface)

This is the most fragile area; review carefully.

**Parser robustness** — `parsePlan` (`src/orchestration/loop.ts:469`):

- Fenced ```json``` extraction: regex must be non-greedy and multi-line. Confirm `[\s\S]*?` (not `.*`).
- Fallback to balanced-brace search for raw JSON: must handle escaped quotes, strings containing `{` or `}`, and unicode. `findMatchingBrace` (`:506`) is the implementation — verify it tracks `inString` + `escape` flags.
- All candidates tried in order; first valid wins. Single bad candidate must not mask a later good one.
- `JSON.parse` exceptions caught silently — confirm yes (not `console.error`-ing in a way that pollutes stderr during normal fallback).

**Validator** — `validatePlan` (`src/orchestration/loop.ts:520`):

- `steps` must be a non-empty array of objects with non-empty `title` *and* `description`. Empty strings should not pass.
- Renumbering: `id` field is rewritten to 1..N regardless of agent input. Confirm.
- Truncation: cap at `Math.max(1, maxIterations - 1)`. If `maxIterations === 1`, plan still gets at least 1 step (fallback execution will fail at no-iters-left, which is the correct behavior — but verify the off-by-one).
- `truncated` flag set when truncation actually happened, not always.

**Prompt templates** — `buildPlanningPrompt` (`:681`), `buildPlanExecutionPrompt` (`:710`):

- Planning prompt must say "PLANNING ONLY" and "do NOT" perform work. Without that the agent often dives in.
- Planning prompt mentions "Available iterations for execution: N" — confirms `max_iterations - 1` math.
- Execution prompt highlights current step with `→` marker for visibility.
- Execution prompt has "Do NOT work ahead" guardrail.
- Both templates close cleanly at end of string (no dangling joins).

**`handlePlanningCompletion`** (`:411`):

- Parse failure path sets `plan_enabled=0` AND emits a notification AND dispatches iter 2 with legacy prompt — not all three skipped.
- Success path persists `loop.plan` *before* dispatching iter 2 (so iter 2's prompt-builder sees the plan).
- `current_iteration >= max_iterations` check exists in both branches — otherwise plan-first with `max_iterations=1` would silently advance to iter 2.

**Plan exhaustion** — `isPlanExhausted` (`:582`):

- Only fires when `plan_enabled=1` and `loop.plan` parsed cleanly — never on legacy loops.
- Triggers when `current_iteration >= plan.steps.length + 1` (the +1 accounts for the planning iter).
- Fires *after* done-check (early exit on success) but *before* max-iter check (so the user gets the more specific reason).

### Phase D — Evaluator review

Read `evaluator.ts`. Per-type check:

- **`command`** — `Bun.spawn(["sh", "-c", cmd])`, 30s timeout. Verify timeout enforcement and that exit 0 = pass. SQL injection / shell injection on `cmd` is an accepted risk (user controls done_when), but document if there's any place we sanitize.
- **`file_exists`** — relative paths resolved against `projectDir`. Symlinks?
- **`file_contains`** — `String.includes`, not regex. Document this clearly in the spec; users sometimes assume regex.
- **`llm_judge`** — spawns claude out-of-band. Cost is *not* tracked (known gap; see `docs/specs/03-orchestration.md` §6 cost blind spot). Confirm error path: missing claude binary → graceful fail.
- **`manual`** — handled in `LoopOrchestrator.onTaskComplete`, not here. Evaluator's `manual` arm returns `[false, ...]` as defensive default (unreachable in normal flow). Confirm dead-code comment.

`parseDoneCondition`: `file_contains:path:pattern` splits on the second colon. What about `file_contains:path:with:colons:in:pattern`? The pattern keeps everything after the second colon — verify with a test.

### Phase E — Seams (dispatcher + on-complete + startup)

`startTask` (`src/execution/dispatcher.ts:163`) is the single dispatch funnel. Confirm:

- `loop.ts:dispatchIteration` calls it.
- `cli/index.ts:cmdDispatch` calls it.
- `mcp/tool-handlers.ts:bridge_dispatch` calls it.
- `execution/on-complete.ts:handleCompletion` (the dequeue branch) calls it.

If you find any place doing `dispatcher.dispatch()` directly without going through `startTask`, that's a bug — `startTask` does agent state flip + task started_at + pid recording + failure rollback. Bypassing it loses bookkeeping.

`handleCompletion` loop-callback branch (`src/execution/on-complete.ts:98`):

- Skips dequeue when loop callback handled the agent (`loopHandled=true`). Without this, a loop dispatching iter N+1 would race with the dequeue and double-spawn.
- Callback exception caught and logged — does not abort the rest of `handleCompletion` (which still needs to update task status and notification).

`StartupOrchestrator` (`src/infra/startup.ts:34`):

- `ProcessWatcher` constructed with both `dispatcher` and the `onLoopTaskComplete` callback. If either is missing, completion stops working.
- Watcher interval is 5s (`WATCHER_INTERVAL_MS`). Anything longer makes per-iteration latency painful.

### Phase F — Test coverage

Read `tests/wave4/loop.test.ts`. The plan-first describe block must cover:

- Default planFirst=true (smoke test for the bare default)
- `loopType=agent + planFirst → forces bridge`
- Parses plan from fenced JSON and dispatches execution iter 2
- Done-condition NOT evaluated on planning iter
- Truncation at `max_iterations - 1`
- Fallback when plan parse fails (and it dispatches iter 2 with legacy)
- Fails when plan parse fails AND no iterations left
- Fails when plan exhausted but condition unmet
- Emits plan notification when persisted

If any of those is missing, that's a 🔴 finding. Bonus coverage to look for:

- Plan with empty steps array → validator rejects → fallback fires
- Plan with `id` numbers out of order → renumbered to 1..N
- `verification` field optional → step still valid without it
- `result_file` exists with malformed JSON → parser returns null gracefully

`tests/wave2/cross-compat.test.ts` must list `plan` and `plan_enabled` in the loops column expectation. If schema migrates again, this test catches drift.

### Phase G — Tool schema parity

`mcp/tools.ts` `bridge_loop` schema must declare every option `mcp/tool-handlers.ts` reads from `args`. Cross-check:

- `agent`, `goal`, `done_when` — required
- `max_iterations`, `loop_type`, `max_cost_usd`, `chat_id`, `user_id`, `plan_first` — optional

If the handler reads `args["foo"]` but the schema doesn't declare `foo`, MCP clients won't know to pass it.

CLI parity: `cmdLoop` (`src/cli/index.ts:411`) must accept the same set as MCP, exposed through `--<flag>` form. Currently: `--max`, `--max-failures`, `--type`, `--max-cost`, `--channel`, `--chat-id`, `--user-id`, `--no-plan`. If MCP adds an option, CLI should too (or accept the asymmetry consciously).

## Findings template

Group by severity. Be specific — every finding cites a file:line.

```markdown
# Loop Code Review

**Scope:** <state-machine | plan-first | evaluator | seams | tests | all>
**Last commit reviewed:** <git rev-parse HEAD>

## 🔴 Critical (correctness risk or coverage gap that can lose work)

- **<title>** — <one-line>. <File:line>. Why it matters: <…>. Suggested fix: <…>.

## 🟡 Warning (smell, drift, or fragility)

- ...

## 🟢 Positive (intentional pattern worth preserving)

- ...

## Doc/code consistency

Compare findings against `docs/specs/03-orchestration.md`. List any place the doc lies about current behavior.

## Test coverage gaps

Bullet list of behaviors with no test, ranked by risk.

## Recommendations

Ordered list of concrete next actions. Group as "should fix before merge" vs "follow-up".
```

## Guardrails

- **Read-only.** Never edit code as part of this skill. Even small fixes go in a separate task.
- **No `git commit`, `bun test`, or `tsc --noEmit`.** This skill is reasoning over code, not exercising it. If you want test results, run them in a separate step *before* invoking this skill.
- **Cite evidence.** Every finding must point at `path/to/file.ts:NNN`. Vague observations without line references are not findings — drop them.
- **Honor scope.** If `--scope state-machine` was passed, do not pad the report with seam findings.
- **Don't argue with the spec.** If the spec describes intended behavior and the code matches, that is not a finding even if you would have designed it differently. Behavior changes are a separate conversation.
- **No invented coverage claims.** If you didn't open `tests/wave4/loop.test.ts`, you cannot claim test coverage exists. Open the file or omit the assertion.
