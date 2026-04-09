/**
 * Dispatcher — spawns Claude Code processes for tasks.
 *
 * Uses Bun.spawn() with detached process groups for isolation.
 * Matches Python dispatcher.py behavior.
 */

import { join } from "path";
import { createHash } from "crypto";
import { mkdirSync, openSync } from "fs";
import type { Task } from "../types.js";
import type { IDispatcher, DispatchOptions } from "./interfaces.js";

export class Dispatcher implements IDispatcher {
  constructor(private homeDir: string) {}

  /**
   * Convert session_id + optional task_id to a deterministic UUID.
   * Used as --session-id for Claude Code to maintain session continuity.
   */
  sessionIdToUuid(sessionId: string, taskId?: number): string {
    const input = taskId !== undefined ? `${sessionId}:${taskId}` : sessionId;
    const hash = createHash("md5").update(input).digest("hex");
    // Format as UUID v4-like
    return [
      hash.slice(0, 8),
      hash.slice(8, 12),
      hash.slice(12, 16),
      hash.slice(16, 20),
      hash.slice(20, 32),
    ].join("-");
  }

  /** Get the result file path for a task. */
  getResultFile(sessionId: string, taskId: number): string {
    return join(this.homeDir, "workspaces", sessionId, "tasks", `${taskId}.result.json`);
  }

  /** Get the stderr file path for a task. */
  getStderrFile(sessionId: string, taskId: number): string {
    return join(this.homeDir, "workspaces", sessionId, "tasks", `${taskId}.stderr`);
  }

  /** Check if a process is still running. */
  isRunning(pid: number): boolean {
    try {
      process.kill(pid, 0);
      return true;
    } catch {
      return false;
    }
  }

  /**
   * Spawn a Claude Code process for a task.
   * Returns PID of the spawned process.
   */
  async dispatch(
    task: Task,
    agentFileName: string,
    projectDir: string,
    options?: DispatchOptions,
  ): Promise<number> {
    const resultFile = this.getResultFile(task.session_id, task.id);
    const stderrFile = this.getStderrFile(task.session_id, task.id);
    const sessionUuid = this.sessionIdToUuid(task.session_id, task.id);

    // Ensure tasks directory exists
    const tasksDir = join(this.homeDir, "workspaces", task.session_id, "tasks");
    mkdirSync(tasksDir, { recursive: true });

    // Build claude command arguments
    const args = [
      "-p", task.prompt,
      "--agent", agentFileName,
      "--session-id", sessionUuid,
      "--output-format", "json",
      "--output-file", resultFile,
    ];

    if (options?.model) {
      args.push("--model", options.model);
    }

    // Build environment
    const env: Record<string, string> = {
      ...process.env as Record<string, string>,
      CLAUDE_BRIDGE_HOME: this.homeDir,
      ...options?.env,
    };

    // Open stderr file for writing
    const stderrFd = openSync(stderrFile, "w");

    // Spawn detached process
    const proc = Bun.spawn(["claude", ...args], {
      cwd: projectDir,
      stdout: "ignore",
      stderr: stderrFd,
      env,
    });

    // Unref so the process doesn't keep the parent alive
    proc.unref();

    return proc.pid;
  }

  /**
   * Cancel a running task.
   * Graceful: SIGTERM → wait timeout → SIGKILL.
   * Returns true if the process was killed.
   */
  async cancel(pid: number, graceful: boolean = true, timeout: number = 10): Promise<boolean> {
    if (!this.isRunning(pid)) {
      return false;
    }

    try {
      if (graceful) {
        process.kill(pid, "SIGTERM");
        // Wait for process to die
        const start = Date.now();
        while (Date.now() - start < timeout * 1000) {
          if (!this.isRunning(pid)) return true;
          await Bun.sleep(100);
        }
        // Force kill if still alive
        if (this.isRunning(pid)) {
          process.kill(pid, "SIGKILL");
          await Bun.sleep(100);
        }
      } else {
        process.kill(pid, "SIGKILL");
        await Bun.sleep(100);
      }
      return true;
    } catch {
      return false;
    }
  }
}
