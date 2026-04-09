/**
 * Scheduler — cron-based recurring task dispatch.
 *
 * Replaces Python's scheduler.py.
 *
 * TODO: Implement in Wave 4 migration.
 */

import type { IScheduler } from "./interfaces.js";

export class Scheduler implements IScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;

  start(): void {
    throw new Error("Not implemented");
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  getNextRun(cronExpression: string): Date {
    throw new Error("Not implemented");
  }
}
