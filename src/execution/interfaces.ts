/**
 * Execution Layer Interfaces — task dispatching, completion handling, process watching, notification.
 *
 * Expanded in Wave 3.1 to match full Python execution layer feature set.
 */

import type { Task, Notification } from "../types.js";

// --- Dispatcher ---

export interface DispatchOptions {
  useWorktree?: boolean;
  env?: Record<string, string>;
  model?: string;
}

export interface IDispatcher {
  /** Spawn a Claude Code process for a task. Returns PID. */
  dispatch(task: Task, agentFileName: string, projectDir: string, options?: DispatchOptions): Promise<number>;

  /** Cancel a running task (SIGTERM → wait → SIGKILL). Returns true if killed. */
  cancel(pid: number, graceful?: boolean, timeout?: number): Promise<boolean>;

  /** Check if a process is still running. */
  isRunning(pid: number): boolean;

  /** Convert session_id + task_id to a deterministic UUID. */
  sessionIdToUuid(sessionId: string, taskId?: number): string;

  /** Get the result file path for a task. */
  getResultFile(sessionId: string, taskId: number): string;

  /** Get the stderr file path for a task. */
  getStderrFile(sessionId: string, taskId: number): string;
}

// --- Completion Handler ---

export interface CompletionResult {
  exitCode: number;
  summary: string | null;
  costUsd: number | null;
  durationMs: number | null;
  numTurns: number | null;
}

export interface ICompletionHandler {
  /** Parse a JSON result file from claude CLI. Returns parsed result or null. */
  parseResultFile(resultFile: string): Promise<CompletionResult | null>;

  /** Handle task completion — update DB, trigger notification, dequeue next. */
  handleCompletion(sessionId: string, taskId: number, result: CompletionResult): Promise<void>;

  /** CLI entry point — called from stop hook with argv. */
  main(argv?: string[]): Promise<void>;
}

// --- Process Watcher ---

export interface IProcessWatcher {
  /** Start watching running tasks for process death. */
  start(intervalMs?: number): void;

  /** Stop the watcher loop. */
  stop(): void;

  /** Run a single watch cycle (check all running tasks). */
  checkOnce(): Promise<void>;
}

// --- Notifier ---

export interface INotifier {
  /** Format a task completion message. */
  formatMessage(task: Task, agentName: string): string;

  /** Send a notification about task completion. */
  notify(notification: Pick<Notification, "chat_id" | "message">): Promise<boolean>;

  /** Retry failed notifications. */
  retryFailed(): Promise<void>;
}
