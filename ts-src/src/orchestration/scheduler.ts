/**
 * Scheduler — cron-based recurring task dispatch.
 *
 * Polls for due schedules and dispatches tasks.
 * Matches Python scheduler.py behavior.
 */

import type { Schedule } from "../types.js";
import type { IScheduler } from "./interfaces.js";
import type { IDatabase } from "../data/interfaces.js";

const MAX_CONSECUTIVE_ERRORS = 5;
const MAX_BACKOFF_MULTIPLIER = 8;

export class Scheduler implements IScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private homeDir: string,
    private db: IDatabase,
  ) {}

  start(intervalMs: number = 60_000): void {
    this.stop();
    const timer = setInterval(() => {
      this.runOnce().catch((err) => {
        process.stderr.write(`[scheduler] Error: ${err}\n`);
      });
    }, intervalMs);
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

  computeNextRun(schedule: Schedule, now?: Date, isError?: boolean): Date {
    const ref = now ?? new Date();
    const intervalMs = (schedule.interval_minutes ?? 60) * 60 * 1000;

    if (isError) {
      // Exponential backoff: 2^errors * interval, capped at 8x
      const multiplier = Math.min(
        Math.pow(2, schedule.consecutive_errors),
        MAX_BACKOFF_MULTIPLIER,
      );
      return new Date(ref.getTime() + multiplier * intervalMs);
    }

    // Anchor-based: last_run + interval
    if (schedule.last_run_at) {
      const lastRun = new Date(schedule.last_run_at).getTime();
      return new Date(lastRun + intervalMs);
    }

    // No last run: now + interval
    return new Date(ref.getTime() + intervalMs);
  }

  async dispatchForSchedule(schedule: Schedule): Promise<number> {
    const taskId = this.db.createTask({
      session_id: `${schedule.agent_name}--scheduled`,
      prompt: schedule.prompt,
      channel: schedule.channel,
      channel_chat_id: schedule.channel_chat_id ?? undefined,
      user_id: schedule.user_id ?? undefined,
    });

    const now = new Date();
    this.db.updateScheduleSuccess(schedule.id, now);

    return taskId;
  }

  async runOnce(): Promise<void> {
    const now = new Date();
    const due = this.db.getDueSchedules(now);

    for (const schedule of due) {
      // Skip schedules with too many consecutive errors
      if (schedule.consecutive_errors >= MAX_CONSECUTIVE_ERRORS) {
        continue;
      }

      try {
        await this.dispatchForSchedule(schedule);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        this.db.updateScheduleError(schedule.id, msg);
      }
    }
  }
}
