/**
 * Process Watcher — polls for dead processes as fallback for missed stop hooks.
 *
 * Checks running tasks, marks dead ones as failed, handles timeouts.
 * Matches Python watcher.py behavior.
 */

import type { IProcessWatcher } from "./interfaces.js";
import type { IDatabase } from "../data/interfaces.js";

const DEFAULT_TIMEOUT_MINUTES = 360; // 6 hours

export class ProcessWatcher implements IProcessWatcher {
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private homeDir: string,
    private db: IDatabase,
  ) {}

  start(intervalMs: number = 30_000): void {
    this.stop();
    const timer = setInterval(() => {
      this.checkOnce().catch((err) => {
        process.stderr.write(`[watcher] Error: ${err}\n`);
      });
    }, intervalMs);
    // Unref so the timer doesn't keep the process alive in tests
    if (typeof timer === "object" && "unref" in timer) {
      (timer as NodeJS.Timeout).unref();
    }
    this.timer = timer;
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  async checkOnce(timeoutMinutes: number = DEFAULT_TIMEOUT_MINUTES): Promise<void> {
    const running = this.db.getRunningTasks();

    for (const task of running) {
      if (!task.pid) continue;

      // Check if process is still alive
      const alive = this.isAlive(task.pid);

      // Check for timeout
      if (alive && task.started_at) {
        const started = new Date(task.started_at).getTime();
        const elapsed = (Date.now() - started) / (60 * 1000);
        if (elapsed > timeoutMinutes) {
          this.db.updateTask(task.id, {
            status: "timeout",
            error_message: `Task timed out after ${Math.round(elapsed)} minutes`,
            completed_at: new Date().toISOString(),
          });
          this.db.updateAgentState(task.session_id, "idle");
          // Try to kill the process
          try { process.kill(task.pid, "SIGTERM"); } catch { /* already dead */ }
          continue;
        }
      }

      if (!alive) {
        // Process died without stop hook firing
        this.db.updateTask(task.id, {
          status: "failed",
          error_message: `Process ${task.pid} died unexpectedly`,
          completed_at: new Date().toISOString(),
        });
        this.db.updateAgentState(task.session_id, "idle");
      }
    }
  }

  private isAlive(pid: number): boolean {
    try {
      process.kill(pid, 0);
      return true;
    } catch {
      return false;
    }
  }
}
