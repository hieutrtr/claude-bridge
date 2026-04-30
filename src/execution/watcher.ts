/**
 * Process Watcher — completion processor and liveness fallback.
 *
 * This is the primary completion path: Claude Code's Stop hook fires while
 * claude is still running (blocking on the hook), so claude hasn't flushed
 * stdout to the result file yet — the hook can't read the result. The watcher
 * runs AFTER claude exits and stdout is flushed, so it can parse the result
 * file and finalize the task. Stop hook stays wired only as an optimistic
 * fast-path (in case claude happened to flush early), otherwise it's a no-op.
 */

import type { IProcessWatcher, IDispatcher } from "./interfaces.js";
import type { IDatabase } from "../data/interfaces.js";
import { CompletionHandler, type LoopCompletionCallback } from "./on-complete.js";

const DEFAULT_TIMEOUT_MINUTES = 360; // 6 hours

export class ProcessWatcher implements IProcessWatcher {
  private timer: ReturnType<typeof setInterval> | null = null;
  private completionHandler: CompletionHandler | null = null;

  constructor(
    private homeDir: string,
    private db: IDatabase,
    private dispatcher?: IDispatcher,
    onLoopTaskComplete?: LoopCompletionCallback,
  ) {
    if (dispatcher) {
      this.completionHandler = new CompletionHandler(homeDir, db, dispatcher, onLoopTaskComplete);
    }
  }

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
        // Claude has exited — stdout is now flushed. Try to parse the result
        // file and finalize via the completion handler (which also dequeues
        // any queued follow-up). If we have no handler (unit test without a
        // dispatcher) or no valid result, fall back to marking failed.
        let handled = false;
        if (this.completionHandler && this.dispatcher) {
          const resultFile = this.dispatcher.getResultFile(task.session_id, task.id);
          const parsed = await this.completionHandler.parseResultFile(resultFile);
          if (parsed) {
            await this.completionHandler.handleCompletion(task.session_id, task.id, parsed);
            handled = true;
          }
        }
        if (!handled) {
          this.db.updateTask(task.id, {
            status: "failed",
            error_message: `Process ${task.pid} died without writing a result`,
            completed_at: new Date().toISOString(),
          });
          this.db.updateAgentState(task.session_id, "idle");
        }
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
