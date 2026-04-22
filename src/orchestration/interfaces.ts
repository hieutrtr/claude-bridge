/**
 * Orchestration Layer Interfaces — loops, evaluation, scheduling.
 *
 * Matches Python loop_orchestrator.py, loop_evaluator.py, scheduler.py.
 */

import type { Loop, Task, Schedule } from "../types.js";
import type { IDatabase } from "../data/interfaces.js";

// --- Done Condition ---

export interface DoneCondition {
  type: "command" | "file_exists" | "file_contains" | "llm_judge" | "manual";
  args: string[];
}

// --- Loop Iteration Result ---

export interface LoopIterationResult {
  iteration: number;
  taskId: number;
  exitCode: number;
  summary: string | null;
  isDone: boolean;
  doneReason?: string;
}

// --- Agent Loop Result (parsed from task output) ---

export interface AgentLoopResult {
  attempts: number;
  status: string;
  final_state: string;
  remaining_issues: string[];
}

// --- Loop Orchestrator ---

export interface ILoopOrchestrator {
  /** Start a new goal loop — dispatches tasks iteratively until done condition met. */
  startLoop(
    agentName: string,
    goal: string,
    doneCondition: string,
    options?: {
      maxIterations?: number;
      maxConsecutiveFailures?: number;
      loopType?: string;
      maxCostUsd?: number | null;
      channel?: string;
      channelChatId?: string;
      userId?: string;
      /**
       * If true (default), iter 1 produces a structured plan (JSON sub-tasks)
       * and iters 2..N+1 execute one sub-task each. If parsing the plan fails,
       * the loop falls back to legacy single-shot execution. Set false to skip
       * planning entirely and have iter 1 attempt the full goal directly.
       */
      planFirst?: boolean;
    },
  ): Promise<string>;

  /** Called when a task in a loop completes. Evaluates and decides next action. */
  onTaskComplete(
    loopId: string,
    taskId: string,
    resultSummary: string,
    costUsd?: number,
  ): Promise<void>;

  /** Cancel a running loop. */
  cancelLoop(loopId: string): Promise<boolean>;

  /** Approve a pending_approval manual loop. */
  approveLoop(loopId: string): Promise<boolean>;

  /** Reject a pending_approval loop, dispatch next iteration with feedback. */
  rejectLoop(loopId: string, feedback?: string): Promise<boolean>;

  /** Get the status and history of a loop. */
  getLoopStatus(loopId: string): Promise<Loop | null>;

  /** Decide loop type based on goal, condition, and preferences. */
  decideLoopType(
    goal: string,
    doneWhen: string,
    userPreference?: string | null,
    maxIterations?: number,
  ): string;

  /** Format loop list for display. */
  formatLoopList(loops: Loop[]): string;

  /** Format loop history with iteration details. */
  formatLoopHistory(loop: Loop, iterations: import("../types.js").LoopIteration[]): string;
}

// --- Loop Evaluator ---

export interface ILoopEvaluator {
  /** Parse a done condition string into structured form. */
  parseDoneCondition(conditionStr: string): DoneCondition;

  /** Validate a done condition string. Returns [valid, errorMessage]. */
  validateDoneCondition(conditionStr: string): [boolean, string];

  /** Evaluate whether a done condition is satisfied. Returns [passed, reason]. */
  evaluate(
    condition: DoneCondition,
    projectDir: string,
    options?: {
      timeout?: number;
      resultSummary?: string;
    },
  ): Promise<[boolean, string]>;
}

// --- Scheduler ---

export interface IScheduler {
  /** Start the scheduler — polls for due schedules at interval. */
  start(intervalMs?: number): void;

  /** Stop the scheduler. */
  stop(): void;

  /** Compute the next run time for a schedule. */
  computeNextRun(schedule: Schedule, now?: Date, isError?: boolean): Date;

  /** Dispatch a task for a due schedule. */
  dispatchForSchedule(schedule: Schedule): Promise<number>;

  /** Run one check cycle (poll due schedules and dispatch). */
  runOnce(): Promise<void>;
}
