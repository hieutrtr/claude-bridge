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
