# Orchestration Layer

Technical reference for the iterative-execution subsystem: goal loops, the
done-condition evaluator, and the scheduler. This layer sits on top of the
execution layer (`src/execution/dispatcher.ts`) and never spawns Claude Code
directly — every iteration and every scheduled run is funneled through
`startTask` (`src/execution/dispatcher.ts:163`).

**Files in scope**

| File | Role |
| --- | --- |
| `src/orchestration/interfaces.ts` | Contracts: `ILoopOrchestrator`, `ILoopEvaluator`, `IScheduler`, `DoneCondition` |
| `src/orchestration/loop.ts` | `LoopOrchestrator` — state machine and iteration dispatch |
| `src/orchestration/evaluator.ts` | `LoopEvaluator` — parses and evaluates done conditions |
| `src/orchestration/scheduler.ts` | `Scheduler` — recurring-schedule poller |
| `src/orchestration/index.ts` | Re-exports |

Persistence lives in three SQLite tables declared in `src/data/db.ts`:
`loops` (`src/data/db.ts:153`), `loop_iterations` (`src/data/db.ts:177`), and
`schedules` (`src/data/db.ts:191`). All loop/schedule state is in
`~/.claude-bridge/bridge.db` — there is no in-memory state that needs to
survive daemon restarts (see Gotchas).

---

## 1. Loop Primitive

A loop is a task that re-dispatches itself until the evaluator decides it is
done. It is the only construct in Claude Bridge that creates more than one
task row from a single user intent.

### 1.1 Lifecycle

```
              startLoop()                     onTaskComplete()
   [nothing] ────────────▶ running ─────────────────────────────┐
                             │                                   │
                             │ evaluator.evaluate() = passed     │ condition type = "manual"
                             │                                   ▼
                             │                                  running + pending_approval=1
                             │                                   │
                             │                            ┌──────┴─────────┐
                             │                            │                │
                             │                     approveLoop()     rejectLoop()
                             │                            │                │
                             ▼                            ▼                ▼
                           done                         done       (dispatch iter N+1,
                                                                    pending_approval=0)
                             ▲
              cost limit / max iter / ▲
              too many failures       │
                             │         │
                             ▼         │
                          failed   cancelLoop() ──▶ cancelled
```

Column `loops.status` is the single source of truth. Its domain is
`running | paused | done | failed | timeout | cancelled` (`src/types.ts:84`)
but the orchestrator only writes `running`, `done`, `failed`, and
`cancelled`; `paused` and `timeout` are declared-but-unused. The separate
`pending_approval` integer (0/1) is a *sub-state* of `running` — a loop
with `status='running'` and `pending_approval=1` is waiting for a human,
not executing. `listLoops(..., "running")` returns pending-approval loops
as well, which is intentional but easy to miss.

### 1.2 State transitions and the functions that trigger them

| From | To | Trigger | Code |
| --- | --- | --- | --- |
| (none) | `running` | `startLoop` persists the loop and dispatches iter 1 | `src/orchestration/loop.ts:29` |
| `running` | `running` (next iter) | `onTaskComplete` → evaluator fails → under `max_iterations` → `dispatchIteration` | `src/orchestration/loop.ts:222` |
| `running` | `running` + `pending_approval=1` | `onTaskComplete` sees `manual:` condition | `src/orchestration/loop.ts:170` |
| `running` + `pending_approval=1` | `done` | `approveLoop` | `src/orchestration/loop.ts:274` |
| `running` + `pending_approval=1` | next iter (running) | `rejectLoop` → `dispatchIteration(current+1, feedback)` | `src/orchestration/loop.ts:285` |
| `running` + `pending_approval=1` | `failed` | `rejectLoop` when `current_iteration >= max_iterations` | `src/orchestration/loop.ts:294` |
| `running` | `done` | `onTaskComplete` → evaluator passes | `src/orchestration/loop.ts:194` |
| `running` | `failed` | `onTaskComplete` → cost limit | `src/orchestration/loop.ts:126` |
| `running` | `failed` | `onTaskComplete` → consecutive failures ≥ `max_consecutive_failures` | `src/orchestration/loop.ts:159` |
| `running` | `failed` | `onTaskComplete` → `current_iteration >= max_iterations` after evaluator failure | `src/orchestration/loop.ts:211` |
| `running` | `failed` | `onTaskComplete` → `isPlanExhausted` after step N ran but done condition still fails | `src/orchestration/loop.ts:200` |
| `running` | `failed` | Planning iter: plan parse failed + no iterations left for fallback execution | `src/orchestration/loop.ts:425` |
| `running` | `failed` | Planning iter: plan parsed, but no iterations left to execute it | `src/orchestration/loop.ts:451` |
| `running` | `failed` | `dispatchIteration` throws from `startTask` | `src/orchestration/loop.ts:640` |
| `running` (or `running`+pending) | `cancelled` | `cancelLoop` | `src/orchestration/loop.ts:263` |

All terminal transitions go through `finalizeLoop`
(`src/orchestration/loop.ts:231`), which writes `status`, `finished_at`,
`finish_reason` and queues an end-of-loop notification via
`db.createNotification` if the loop has a channel bound to it. There is no
other code path that writes a terminal status — a clean funnel.

### 1.3 Interaction with the dispatcher

The loop never talks to `Bun.spawn`. Instead, `dispatchIteration`
(`src/orchestration/loop.ts:592`) builds a prompt via `buildPrompt`
(`src/orchestration/loop.ts:653`), which picks one of three templates
depending on loop state: planning prompt, plan-execution prompt (one step
at a time), or legacy single-shot prompt. For execution iterations the last
two iteration summaries are threaded in as "Previous iterations" context,
capped at `MAX_FEEDBACK_CHARS = 2000` (`src/orchestration/loop.ts:19`,
`:720`). `dispatchIteration` then inserts a `tasks` row with
`task_type='loop'` and the loop's channel info, inserts a `loop_iterations`
row, updates `loops.current_iteration` and `loops.current_task_id`, and
finally calls `startTask` from `src/execution/dispatcher.ts:163`.

**Do not add a parallel dispatch path.** The comment at
`src/orchestration/loop.ts:634` refers to an earlier bug where the iteration
task was created but never spawned, leaving loops hung on `pending` forever.
Invariant: every loop iteration goes through `startTask`, which takes care
of flipping the agent to `running`, setting `started_at`, and recording the
pid.

The completion seam is symmetric. When claude exits, the daemon's
`ProcessWatcher` (`src/infra/startup.ts:42`, primary path) or the stop-hook
fast-path in `cmdOnComplete` (`src/cli/index.ts:623`, rare — see
`docs/specs/02-execution-pipeline.md` §3) calls
`CompletionHandler.handleCompletion` (`src/execution/on-complete.ts:60`).
That handler matches the task to an active loop via
`db.getActiveLoopForAgent(agent.name)` and
`loop.current_task_id === String(taskId)`
(`src/execution/on-complete.ts:98`), invokes the `onLoopTaskComplete`
callback wired to `orchestrator.onTaskComplete`
(`src/infra/startup.ts:44`, `src/cli/index.ts:651`), and **suppresses the
queue-dequeue step** (`src/execution/on-complete.ts:115`). The loop owns
the agent for the duration; dequeuing underneath it would double-dispatch.

### 1.4 Approval/rejection flow

`manual:` done conditions never terminate on their own. Each iteration runs,
the evaluator returns `pending_approval=1` from `onTaskComplete`, and the
loop waits. The CLI exposes two resolutions:

- `bridge loop-approve <loop_id>` → `cmdLoopApprove` at
  `src/cli/index.ts:490` → `approveLoop` finalizes as `done`.
- `bridge loop-reject <loop_id> [--feedback <text>]` → `cmdLoopReject` at
  `src/cli/index.ts:503` → `rejectLoop` clears the flag and dispatches
  iteration N+1. The `--feedback` string is threaded into
  `dispatchIteration` and becomes the entire "Previous context" block for
  the next iteration, bypassing `generateFeedback`.

`cancelLoop` (`bridge loop-cancel`, `src/cli/index.ts:477`) works from
either `running` or `running`+pending state but **does not kill the
subprocess** if an iteration is still in flight. See Gotchas.

### 1.5 Loop types: `bridge` vs `agent`

`loop_type` is a prompt-shape hint, not a different execution path.
`decideLoopType` (`src/orchestration/loop.ts:316`): explicit
`--type agent|bridge` wins; `manual`/`llm_judge` → `bridge`;
`maxIterations > 5` → `agent`; otherwise `bridge`. When `loop_type ===
"agent"`, `buildLegacyIterationPrompt` (`src/orchestration/loop.ts:698`)
appends the done condition and a line asking the agent to try to satisfy
it. Every iteration still runs through the same dispatcher and the
evaluator still runs on every completion.

**Plan-first forces `bridge`.** `startLoop` (`src/orchestration/loop.ts:75`)
overrides `loop_type` to `bridge` whenever `planFirst=true` (the default),
because `agent` loops deliberately do all work inside one claude invocation
— incompatible with per-step progress reports. See §1.6.

### 1.6 Plan-first mode

Goal loops have historically tended to dump the entire implementation into
iteration 1, defeating the point of iterative dispatch (early reports,
mid-loop redirection). Plan-first mode fixes this by making iter 1 a
dedicated **planning iteration** — the agent must output a structured JSON
plan of sub-tasks instead of writing code. Iterations 2..N+1 then execute
one plan step each.

`planFirst` is **on by default**; `--no-plan` (CLI) / `plan_first: false`
(MCP) opts out.

**Persistence** (see `src/data/db.ts:170` migration):

- `loops.plan_enabled` (INTEGER 0/1) — locked at `startLoop` time, flipped
  to 0 on plan parse failure fallback.
- `loops.plan` (TEXT JSON) — set once after the planning iter completes
  successfully. Structure mirrors the TypeScript `LoopPlan` type
  (`src/types.ts`): `{ steps: [{ id, title, description, verification? }],
  truncated? }`.

**Prompt flow** (`buildPrompt`, `src/orchestration/loop.ts:653`):

| Condition | Prompt | Template at |
| --- | --- | --- |
| `plan_enabled=1`, iter 1, no plan yet | Planning prompt — "PLANNING ONLY", asks for fenced ```json``` block | `src/orchestration/loop.ts:681` |
| `plan` stored, iter > 1 | Plan-execution prompt — "Current step X/N", full plan overview with arrow marker, verification line, "Do NOT work ahead" guardrail | `src/orchestration/loop.ts:710` |
| `plan_enabled=0` or no plan | Legacy single-shot prompt | `src/orchestration/loop.ts:749` |

**Planning-iter completion** — `handlePlanningCompletion`
(`src/orchestration/loop.ts:411`) is called from `onTaskComplete` via
`isPlanningIteration` (`src/orchestration/loop.ts:397`), *before* cost,
failure-counting, and done-check logic run. That's deliberate: the planning
iter produces no code, so it can't satisfy a goal or "fail" in the same
sense. It does count toward `total_cost_usd` (so cost limits still apply)
and toward `current_iteration` (so `max_iterations` still bounds the loop).

1. `parsePlan` (`src/orchestration/loop.ts:469`) extracts candidate JSON.
   Order of preference: fenced ```json``` blocks (all of them), then a
   balanced-brace fallback that finds `"steps"` and walks back to the
   enclosing `{`. Each candidate is tried in turn; first valid one wins.
2. `validatePlan` (`src/orchestration/loop.ts:520`) requires `steps` to be
   a non-empty array of objects with non-empty `title` + `description`;
   `verification` optional. It renumbers `id` contiguously and truncates
   to `max_iterations - 1` steps (leaving room for the planning iter),
   setting `truncated: true` when it does.
3. On success: persist `loop.plan` as JSON; emit a plan notification
   showing the step list to the channel; dispatch iter 2.
4. On parse failure: set `plan_enabled=0`, emit a fallback notification
   (`"could not parse plan"`), and dispatch iter 2 with the legacy prompt.
   If `current_iteration >= max_iterations` the loop instead finalizes as
   failed.

**Plan exhaustion.** `isPlanExhausted`
(`src/orchestration/loop.ts:582`) fires in `onTaskComplete` *after*
done-check fails and *before* the max-iter check: if `current_iteration
>= plan.steps.length + 1` (1 for the planning iter, N for executions),
the loop finalizes as `failed` with reason "Plan exhausted but done
condition still not satisfied". This is separate from the
max-iterations failure so the user can see that the plan was the
limiting factor, not the iteration budget.

**What the planning iter does NOT do:**

- It does NOT evaluate the done condition (returning early before
  `evaluator.evaluate` is called, `src/orchestration/loop.ts:139`).
- It does NOT increment `consecutive_failures` even if the task row is
  `failed` — because the "failure" would be about not producing code, not
  about failed work.
- It does NOT set `done_check_passed` on the iteration row.

**Invariant:** once `loop.plan` is non-null, the loop is committed to
plan-first execution for the rest of its life. The only exit is plan
exhaustion, max iterations, cost limit, consecutive failures during
execution, done-condition pass, or manual cancel/approve.

---

## 2. Evaluator

`LoopEvaluator` (`src/orchestration/evaluator.ts:24`) is the policy module
that decides, given a single iteration's output, whether the loop is done.

### 2.1 Contract

```ts
interface ILoopEvaluator {
  parseDoneCondition(str): DoneCondition;
  validateDoneCondition(str): [boolean, string];
  evaluate(cond, projectDir, { timeout?, resultSummary? }): Promise<[boolean, string]>;
}
```

`DoneCondition` is `{ type, args[] }` where `type ∈ { command, file_exists,
file_contains, llm_judge, manual }`. Format is `"type:args"` (and
`"file_contains:path:pattern"` as a special case parsed on the second
colon at `src/orchestration/evaluator.ts:38`).

`evaluate` returns `[passed, reason]`. The caller
(`LoopOrchestrator.onTaskComplete`) never throws from a failed evaluation —
`passed=false` means "keep iterating" and the reason is stored as the
iteration's `done_check_passed=0` result.

### 2.2 "continue vs. stop vs. ask-for-approval"

The decision is split: `LoopOrchestrator.onTaskComplete` short-circuits
`manual:` *before* calling `evaluate` and sets `pending_approval=1`
(`src/orchestration/loop.ts:170`). For all other types the orchestrator
calls `evaluate`; `true` → `finalizeLoop("done", reason)`, `false` → check
max iterations, then dispatch next. "Ask for approval" is *only* the manual
path — other conditions either pass or re-dispatch. The evaluator's own
`manual` handler returns `[false, "Requires manual approval"]` as a safety
default but is unreachable in the normal flow.

### 2.3 What `evaluate` actually does

| Type | Implementation | Calls claude? |
| --- | --- | --- |
| `command` | `Bun.spawn(["sh", "-c", cmd])` in `projectDir`, 30s timeout, exit 0 = pass | No |
| `file_exists` | `existsSync(resolved)`; `projectDir` is the base for relative paths | No |
| `file_contains` | Full-file `readFileSync` + `String.includes(pattern)`. Not regex, not line-based. | No |
| `llm_judge` | `Bun.spawn(["claude", "--print", "-p", prompt])` with the `LLM_JUDGE_PROMPT` template; first line must contain `PASS` or `FAIL` | **Yes, a second claude invocation** |

The `llm_judge` path (`src/orchestration/evaluator.ts:159`) is the one place
outside the dispatcher that spawns `claude`. It is *not* routed through the
dispatcher, does not produce a task row, and does not count against the
loop's `total_cost_usd`. Ambiguous output (neither `PASS` nor `FAIL` on
first line) is treated as fail. Absence of the `claude` binary on `PATH`
also fails gracefully with `"LLM judge unavailable"`.

All command- and judge-based evaluations use a 30-second default timeout
(configurable via `options.timeout` but no caller currently overrides it).

---

## 3. Scheduler

### 3.1 What it is, and what it isn't

The `Scheduler` (`src/orchestration/scheduler.ts:15`) is a **fixed-interval
recurring dispatcher**, not a cron engine. Despite the `cron_expr` column
on the `schedules` table (`src/data/db.ts:197`), the code ignores it —
next-run is always computed as `last_run + interval_minutes` or
`now + interval_minutes` (`src/orchestration/scheduler.ts:43`). The
`run_once` column is honored by `addSchedule` but not by `dispatchForSchedule`;
a `run_once` schedule will re-fire unless someone pauses or removes it.
These are known incomplete pieces, not intentional design.

### 3.2 How scheduled tasks fire

`Scheduler.start(intervalMs)` (`src/orchestration/scheduler.ts:23`) installs
a `setInterval` timer (default 60s) that calls `runOnce`
(`src/orchestration/scheduler.ts:81`). `runOnce` queries
`db.getDueSchedules(now)` — `SELECT ... WHERE enabled=1 AND next_run_at <=
now` (`src/data/db.ts:655`), skips any schedule with `consecutive_errors >=
5` (belt-and-suspenders; `db.updateScheduleError` already sets `enabled=0`
at that threshold, `src/data/db.ts:680`), and calls `dispatchForSchedule`
which inserts a `tasks` row with `session_id = ${agent}--scheduled` then
`db.updateScheduleSuccess` (which sets `next_run_at = now + interval`).
DB-polling only; no per-schedule timer.

### 3.3 **This class is not wired into the daemon**

Grep for `new Scheduler(` across `src/`: zero call sites outside tests.
`StartupOrchestrator` (`src/infra/startup.ts:22`) does not construct or
start it. The CLI imports `Scheduler` at `src/cli/index.ts:19` but never
uses the symbol — `schedule-add`/`schedule-list`/etc. all call
`db.addSchedule`/`db.listSchedules` directly.

The practical consequence: **adding a schedule with `bridge schedule-add`
persists the row but nothing fires it.** The class itself is correct and
tested (`tests/wave4/scheduler.test.ts`,
`tests/coverage/evaluator-scheduler-extra.test.ts`); the integration seam
is missing. The fix is a one-liner in `StartupOrchestrator.start`:
construct a `Scheduler` and call `.start()` alongside the watcher.

### 3.4 `dispatchForSchedule` is also under-wired

Even once the poller is started, `dispatchForSchedule`
(`src/orchestration/scheduler.ts:66`) only **creates a `tasks` row**; it
does not call `startTask`. The task row sits `pending` until something else
picks it up. In the intended flow, the `ProcessWatcher`'s dequeue path or
the MCP `bridge_dispatch` tool would claim it, but neither today polls for
`task_type='schedule'` pending rows. This is a second gap on the same
feature — noted here so a maintainer doesn't add scheduling support piecemeal.

### 3.5 Error backoff

`Scheduler.computeNextRun(..., isError=true)` applies exponential backoff
of `2^consecutive_errors * interval_minutes`, capped at 8× (constants
`MAX_CONSECUTIVE_ERRORS=5`, `MAX_BACKOFF_MULTIPLIER=8`). This matches the
backoff that `db.updateScheduleError` already writes to `next_run_at`
directly (`src/data/db.ts:686`), so the two paths duplicate the same
formula. The DB path is the one actually used — `runOnce` doesn't call
`computeNextRun` at all.

### 3.6 pause / resume / remove semantics

All three operate directly on the DB, not on the Scheduler instance
(accepting either numeric id or string name):

| Command | Handler | Effect |
| --- | --- | --- |
| `bridge schedule-pause <id>` | `src/cli/index.ts:603` | `enabled = 0` |
| `bridge schedule-resume <id>` | `src/cli/index.ts:611` | `enabled = 1`, `consecutive_errors = 0` |
| `bridge schedule-remove <id>` | `src/cli/index.ts:576` | `DELETE FROM schedules` |

Resume clears the error counter so a schedule that auto-disabled itself
after 5 errors will start fresh. Remove is irreversible; there is no soft
delete.

---

## 4. CLI surface (cross-reference)

All handlers live in `src/cli/index.ts` and share the same `CommandContext`
(db + config + args). Each handler constructs a fresh `LoopOrchestrator` —
the orchestrator is stateless beyond its constructor injections.

| Command | Handler | Line |
| --- | --- | --- |
| `loop` | `cmdLoop` | `src/cli/index.ts:411` |
| `loop-status` | `cmdLoopStatus` | `src/cli/index.ts:448` |
| `loop-cancel` | `cmdLoopCancel` | `src/cli/index.ts:477` |
| `loop-approve` | `cmdLoopApprove` | `src/cli/index.ts:490` |
| `loop-reject` | `cmdLoopReject` | `src/cli/index.ts:503` |
| `loop-list` | `cmdLoopList` | `src/cli/index.ts:518` |
| `loop-history` | `cmdLoopHistory` | `src/cli/index.ts:534` |
| `schedule-add` | `cmdScheduleAdd` | `src/cli/index.ts:554` |
| `schedule-remove` | `cmdScheduleRemove` | `src/cli/index.ts:578` |
| `schedule-list` | `cmdScheduleList` | `src/cli/index.ts:589` |
| `schedule-pause` | `cmdSchedulePause` | `src/cli/index.ts:605` |
| `schedule-resume` | `cmdScheduleResume` | `src/cli/index.ts:613` |

The same loop operations are also exposed via MCP at `bridge_loop`,
`bridge_loop_status`, `bridge_loop_cancel`, `bridge_loop_approve`,
`bridge_loop_reject`, `bridge_loop_list`, `bridge_loop_history`
(`src/mcp/tool-handlers.ts:223` onward). Schedules are not currently
exposed via MCP.

---

## 5. Integration seam with the execution layer

The orchestration layer has exactly **one outgoing call** into the
execution layer and **one incoming callback** from it. Preserving these is
the correctness contract.

**Outgoing** — `LoopOrchestrator.dispatchIteration` calls `startTask`
(`src/orchestration/loop.ts:635`, resolved to
`src/execution/dispatcher.ts:163`). Do not add alternate dispatch paths
that bypass `startTask`; you will miss `agents.state = running`, `pid`
recording, and the dispatch-failure bookkeeping.

**Incoming** — `CompletionHandler.handleCompletion` invokes the
`onLoopTaskComplete` callback **only when** (a) the task's agent has an
active loop and (b) `loop.current_task_id === String(taskId)`
(`src/execution/on-complete.ts:98`). If either check is falsy, the
handler treats the task as a plain task and dequeues the next queued task
instead. Both conditions matter: the first filters out non-loop tasks; the
second prevents stale callbacks when the loop moved on between the task
spawning and its completion.

The agent state machine is the silent third party. During a loop,
`agents.state` flips `running` → `idle` (on completion) → `running` (on
next iteration dispatch) repeatedly. Outside observers that watch
`agents.state` will see it bounce; they should key on `loops.status`
instead.

---

## 6. Gotchas

**Cancelling a running iteration does not kill the subprocess.**
`cancelLoop` (`src/orchestration/loop.ts:263`) only writes
`status='cancelled'` and queues a notification. A mid-flight claude keeps
running; on exit `CompletionHandler` still writes the task's completion,
but `onTaskComplete` early-returns when `loop.status !== "running"`
(`src/orchestration/loop.ts:105`), so no next iteration is dispatched. Net
effect: the final iteration completes and is charged to the loop's cost,
but the loop does not advance. For immediate termination, run `bridge kill
<session>` after `bridge loop-cancel`.

**Daemon restart mid-loop.** Loop state is in SQLite, so the loop itself
survives. The in-flight subprocess is orphaned: after restart the new
`ProcessWatcher` polls every 5s (`src/infra/startup.ts:19`) and checks
liveness on the recorded pids. If the original claude process is still
alive it will be reaped normally when it exits. If it died during the
restart, the task is marked `failed` with "Process N died without writing
a result" (`src/execution/watcher.ts:97`), and the loop's next
`onTaskComplete` callback treats this as a failed iteration (counter++).
A loop will not spontaneously resume a lost iteration.

**Cost tracking has one blind spot.** `onTaskComplete` adds each
iteration's `costUsd` to `loops.total_cost_usd`
(`src/orchestration/loop.ts:121`) and enforces `max_cost_usd` *after* the
iteration that crossed the threshold completes — no pre-dispatch check.
The planning iteration (plan-first mode) also counts toward
`total_cost_usd` even though it produces no code. The blind spot:
`llm_judge` evaluations invoke `claude` out-of-band and their cost is not
tracked anywhere.

**No rate limiting.** Neither the orchestrator nor the dispatcher imposes
any inter-iteration delay. A loop whose done condition is trivially false
and whose iterations return fast will re-dispatch as quickly as claude can
spawn. Protection is entirely via `max_iterations` (default 10) and
`max_cost_usd` (default null → unlimited). If you need a cooldown, add it
to `dispatchIteration` — there is no other chokepoint.

**One active loop per agent.** Enforced at `startLoop` by
`db.getActiveLoopForAgent` (`src/orchestration/loop.ts:51`). If a loop is
stuck in `running` + pending-approval and someone forgets about it,
attempts to start a new loop on that agent will fail until the stale loop
is cancelled or approved.

**`pending_approval=1` is still `status='running'`.** Queries that filter
`status='running'` (e.g., `listLoops(..., "running")` used by
`bridge loop-status` without `--loop-id` at `src/cli/index.ts:466`) include
loops waiting for human approval. This is intentional — the UI should show
them — but be aware when writing new queries.

**Scheduler is not running.** See §3.3. `bridge schedule-add` writes rows
that never fire. A complete fix requires (a) starting a `Scheduler` in
`StartupOrchestrator.start`, and (b) either making `dispatchForSchedule`
call `startTask` or having the watcher claim pending `task_type='schedule'`
rows. Until that lands, schedules are a config-only feature.
