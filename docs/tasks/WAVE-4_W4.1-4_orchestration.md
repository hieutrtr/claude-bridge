# Wave 4: Orchestration Layer (W4.1-W4.4)

## W4.1: Expand Orchestration Interfaces
- Expand ILoopOrchestrator from 5→9 methods (add onTaskComplete, approveLoop, rejectLoop, decideLoopType, formatLoopList, formatLoopHistory)
- Expand ILoopEvaluator from 1→3 methods (add parseDoneCondition, validateDoneCondition)
- Expand IScheduler from 3→5 methods (add computeNextRun, dispatchForSchedule, runOnce)
- Add DoneCondition and AgentLoopResult types

## W4.2: LoopOrchestrator
- Port loop_orchestrator.py (21 fns, 1059 LOC)
- State machine: running → dispatch → evaluate → decide → completed/failed/cancelled
- Bridge vs agent loop types with branching heuristic
- Iteration tracking, feedback generation, cost ceiling
- Approval workflow for manual conditions
- Notification on progress and terminal events

## W4.3: LoopEvaluator
- Port loop_evaluator.py (8 fns, 313 LOC)
- Parse done conditions: command, file_exists, file_contains, llm_judge, manual
- Evaluate each type against project directory
- Subprocess spawn for command and llm_judge types

## W4.4: Scheduler
- Port scheduler.py (3 fns, 125 LOC)
- Anchor-based next_run computation
- Error backoff: 2^errors * interval, capped at 8x
- Poll due schedules, dispatch tasks, skip high-error schedules

## Post-wave enhancements

Added after the original wave completed — see ARCHITECTURE.md §4b/§4c for the
current behavior, and CHANGELOG / git log for the exact commits.

- **Dispatch actually runs** (iteration tasks previously sat in `pending`
  forever). `dispatchIteration` now calls the shared `startTask` helper.
- **Channel routing for loops.** Persist `channel`, `channel_chat_id`, and
  `user_id` on the loop; inherit onto each iteration task; emit per-iteration
  and end-of-loop notifications through a single `finalizeLoop` exit.
- **Plan-first mode (default).** Iter 1 is a planning iteration that asks the
  agent for a JSON plan; iters 2..N+1 execute one sub-task each with a focused
  prompt. Plan is capped at `max_iterations - 1` steps. Parse failure falls
  back to legacy single-shot execution. New columns on `loops`: `plan`,
  `plan_enabled`. Opt out via `--no-plan` (CLI) / `plan_first: false` (MCP).
  Plan-first forces `loop_type = bridge`.
- **Watcher is the primary completion path**, not the stop hook — see
  ARCHITECTURE §4b for why. `LoopOrchestrator.onTaskComplete` is now called
  via `CompletionHandler` from the watcher tick rather than the stop hook.
