/**
 * Orchestration Layer Interfaces — loops, evaluation, scheduling.
 */

import type { Loop, Task } from "../types.js";

// --- Loop Orchestrator ---

export interface LoopIterationResult {
  iteration: number;
  taskId: number;
  exitCode: number;
  summary: string | null;
  isDone: boolean;
  doneReason?: string;
}

export interface ILoopOrchestrator {
  /**
   * Start a new goal loop — dispatches tasks iteratively until done condition met.
   */
  startLoop(
    agentName: string,
    goal: string,
    doneCondition: string,
    maxIterations?: number,
  ): Promise<Loop>;

  /**
   * Resume a paused loop.
   */
  resumeLoop(loopId: number): Promise<void>;

  /**
   * Pause a running loop (finishes current iteration, then stops).
   */
  pauseLoop(loopId: number): Promise<void>;

  /**
   * Cancel a loop immediately.
   */
  cancelLoop(loopId: number): Promise<void>;

  /**
   * Get the status and history of a loop.
   */
  getLoopStatus(loopId: number): Promise<Loop | null>;
}

// --- Loop Evaluator ---

export interface ILoopEvaluator {
  /**
   * Evaluate whether a loop iteration satisfies the done condition.
   * May invoke Claude to assess the result.
   */
  evaluate(
    loop: Loop,
    latestTask: Task,
    taskSummary: string,
  ): Promise<{ isDone: boolean; reason: string }>;
}

// --- Scheduler ---

export interface IScheduler {
  /**
   * Start the scheduler — checks cron expressions and dispatches tasks.
   */
  start(): void;

  /**
   * Stop the scheduler.
   */
  stop(): void;

  /**
   * Get the next run time for a cron expression.
   */
  getNextRun(cronExpression: string): Date;
}
