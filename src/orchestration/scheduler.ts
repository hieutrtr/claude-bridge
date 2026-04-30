/**
 * Scheduler — cron-based recurring task dispatch.
 *
 * Polls for due schedules and dispatches tasks.
 * Matches Python scheduler.py behavior.
 */

import type { Schedule } from "../types.js";
import type { IScheduler } from "./interfaces.js";
import type { IDatabase } from "../data/interfaces.js";
import type { IDispatcher } from "../execution/interfaces.js";
import { startTask } from "../execution/dispatcher.js";

const MAX_CONSECUTIVE_ERRORS = 5;
const MAX_BACKOFF_MULTIPLIER = 8;

export class Scheduler implements IScheduler {
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(
    private homeDir: string,
    private db: IDatabase,
    private dispatcher?: IDispatcher,
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
    // Real dispatch path: resolve the agent's actual session_id, atomically
    // reserve it, and spawn claude via startTask (same path as `bridge dispatch`
    // and the MCP `bridge_dispatch` tool). If the agent is busy, queue the task
    // so the existing dequeue path in on-complete/watcher picks it up later.
    if (this.dispatcher) {
      const agent = this.db.getAgent(schedule.agent_name);
      if (!agent) {
        throw new Error(`Agent "${schedule.agent_name}" not found`);
      }

      const result = this.db.atomicCheckAndCreateTask(
        agent.session_id,
        schedule.prompt,
        schedule.channel,
        schedule.channel_chat_id ?? undefined,
        undefined,
        schedule.user_id ?? undefined,
      );

      let taskId: number;
      if (result.isBusy) {
        taskId = this.db.createTask({
          session_id: agent.session_id,
          prompt: schedule.prompt,
          channel: schedule.channel,
          channel_chat_id: schedule.channel_chat_id ?? undefined,
          user_id: schedule.user_id ?? undefined,
        });
        this.db.updateTask(taskId, { status: "queued" });
      } else {
        taskId = result.taskId!;
        const task = this.db.getTask(taskId);
        if (!task) throw new Error(`Task #${taskId} vanished after create`);
        await startTask(this.db, this.dispatcher, task, agent);
      }

      this.db.updateScheduleSuccess(schedule.id, new Date());
      return taskId;
    }

    // Legacy fallback when no dispatcher is supplied (used by tests that don't
    // want to spawn a real claude subprocess). Inserts a pending row on a
    // virtual session_id; nothing claims it.
    const taskId = this.db.createTask({
      session_id: `${schedule.agent_name}--scheduled`,
      prompt: schedule.prompt,
      channel: schedule.channel,
      channel_chat_id: schedule.channel_chat_id ?? undefined,
      user_id: schedule.user_id ?? undefined,
    });
    this.db.updateScheduleSuccess(schedule.id, new Date());
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
