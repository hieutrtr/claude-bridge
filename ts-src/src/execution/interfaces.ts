/**
 * Execution Layer Interfaces — task dispatching, completion handling, process watching.
 */

import type { Task, Notification } from "../types.js";

// --- Dispatcher ---

export interface DispatchOptions {
  /** Use git worktree isolation */
  useWorktree?: boolean;
  /** Custom environment variables */
  env?: Record<string, string>;
}

export interface IDispatcher {
  /**
   * Spawn a Claude Code process for a task.
   * Returns the PID of the spawned process.
   */
  dispatch(task: Task, options?: DispatchOptions): Promise<number>;

  /**
   * Cancel a running task by sending SIGTERM to its process group.
   */
  cancel(task: Task): Promise<void>;

  /**
   * Check if a process is still running.
   */
  isRunning(pid: number): boolean;
}

// --- Completion Handler ---

export interface CompletionResult {
  exitCode: number;
  summary: string | null;
  costUsd: number | null;
  durationSeconds: number | null;
}

export interface ICompletionHandler {
  /**
   * Handle task completion — called by the stop hook.
   * Reads result files, updates DB, triggers notification.
   */
  handleCompletion(
    sessionId: string,
    taskId: number,
    result: CompletionResult,
  ): Promise<void>;
}

// --- Process Watcher ---

export interface IProcessWatcher {
  /**
   * Start watching running tasks for process death.
   * Fallback mechanism in case stop hooks fail.
   */
  start(intervalMs?: number): void;

  /** Stop the watcher loop */
  stop(): void;
}

// --- Notifier ---

export interface INotifier {
  /**
   * Send a notification about task completion to the configured channel.
   */
  notify(notification: Notification): Promise<void>;
}
