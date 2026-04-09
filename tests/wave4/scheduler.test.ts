/**
 * W4.4: Scheduler Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { Scheduler } from "../../src/orchestration/scheduler.js";
import { BridgeDatabase } from "../../src/data/db.js";
import type { Schedule } from "../../src/types.js";

function setup() {
  const tmpDir = mkdtempSync(join(tmpdir(), "bridge-sched-"));
  const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  const scheduler = new Scheduler(tmpDir, db);
  return { tmpDir, db, scheduler };
}

function teardown(ctx: { tmpDir: string; db: BridgeDatabase; scheduler: Scheduler }) {
  ctx.scheduler.stop();
  ctx.db.close();
  rmSync(ctx.tmpDir, { recursive: true, force: true });
}

function makeSchedule(db: BridgeDatabase, overrides: Partial<{
  name: string; agent: string; prompt: string; interval: number;
}> = {}): number {
  const name = overrides.name ?? "test-schedule";
  const agent = overrides.agent ?? "be";
  db.createAgent(agent, "/p", `${agent}--p`, "f");
  return db.addSchedule(
    name,
    agent,
    overrides.prompt ?? "run tests",
    overrides.interval ?? 60,
  );
}

describe("W4.4: Scheduler", () => {
  describe("computeNextRun", () => {
    test("uses anchor-based computation on success", () => {
      const ctx = setup();
      const now = new Date("2024-06-15T12:00:00Z");
      const lastRun = new Date("2024-06-15T11:00:00Z");
      const schedule: Schedule = {
        id: 1, name: "test", agent_name: "be", prompt: "test",
        interval_minutes: 60, cron_expr: null, run_once: 0, enabled: 1,
        run_count: 1, consecutive_errors: 0,
        last_run_at: lastRun.toISOString(), next_run_at: null,
        last_error: null, channel: "cli", channel_chat_id: null,
        user_id: null, created_at: now.toISOString(), updated_at: now.toISOString(),
      };

      const next = ctx.scheduler.computeNextRun(schedule, now);
      // last_run + interval = 11:00 + 60min = 12:00
      expect(next.toISOString()).toBe("2024-06-15T12:00:00.000Z");
      teardown(ctx);
    });

    test("uses now + interval when no last_run", () => {
      const ctx = setup();
      const now = new Date("2024-06-15T12:00:00Z");
      const schedule: Schedule = {
        id: 1, name: "test", agent_name: "be", prompt: "test",
        interval_minutes: 30, cron_expr: null, run_once: 0, enabled: 1,
        run_count: 0, consecutive_errors: 0,
        last_run_at: null, next_run_at: null,
        last_error: null, channel: "cli", channel_chat_id: null,
        user_id: null, created_at: now.toISOString(), updated_at: now.toISOString(),
      };

      const next = ctx.scheduler.computeNextRun(schedule, now);
      expect(next.toISOString()).toBe("2024-06-15T12:30:00.000Z");
      teardown(ctx);
    });

    test("applies exponential backoff on error", () => {
      const ctx = setup();
      const now = new Date("2024-06-15T12:00:00Z");
      const schedule: Schedule = {
        id: 1, name: "test", agent_name: "be", prompt: "test",
        interval_minutes: 60, cron_expr: null, run_once: 0, enabled: 1,
        run_count: 3, consecutive_errors: 2,
        last_run_at: now.toISOString(), next_run_at: null,
        last_error: "err", channel: "cli", channel_chat_id: null,
        user_id: null, created_at: now.toISOString(), updated_at: now.toISOString(),
      };

      const next = ctx.scheduler.computeNextRun(schedule, now, true);
      // 2^2 * 60 = 240 min backoff
      const expectedMs = now.getTime() + 240 * 60 * 1000;
      expect(next.getTime()).toBe(expectedMs);
      teardown(ctx);
    });

    test("caps backoff at 8x interval", () => {
      const ctx = setup();
      const now = new Date("2024-06-15T12:00:00Z");
      const schedule: Schedule = {
        id: 1, name: "test", agent_name: "be", prompt: "test",
        interval_minutes: 60, cron_expr: null, run_once: 0, enabled: 1,
        run_count: 5, consecutive_errors: 10,
        last_run_at: now.toISOString(), next_run_at: null,
        last_error: "err", channel: "cli", channel_chat_id: null,
        user_id: null, created_at: now.toISOString(), updated_at: now.toISOString(),
      };

      const next = ctx.scheduler.computeNextRun(schedule, now, true);
      // Cap at 8x: 8 * 60 = 480 min
      const expectedMs = now.getTime() + 480 * 60 * 1000;
      expect(next.getTime()).toBe(expectedMs);
      teardown(ctx);
    });
  });

  describe("runOnce", () => {
    test("dispatches due schedule", async () => {
      const ctx = setup();
      const schedId = makeSchedule(ctx.db);
      // Set next_run_at to past so it's due
      const past = new Date(Date.now() - 60000).toISOString();
      ctx.db.updateScheduleSuccess(schedId, new Date(Date.now() - 120000));
      // Manually set next_run_at to past
      ctx.db.db.run("UPDATE schedules SET next_run_at = ? WHERE id = ?", [past, schedId]);

      await ctx.scheduler.runOnce();

      // Schedule should have been processed
      const sched = ctx.db.getScheduleById(schedId)!;
      // Either a task was created or the schedule was updated
      expect(sched.run_count).toBeGreaterThanOrEqual(1);
      teardown(ctx);
    });

    test("skips schedules with too many errors", async () => {
      const ctx = setup();
      const schedId = makeSchedule(ctx.db);
      const past = new Date(Date.now() - 60000).toISOString();
      ctx.db.db.run("UPDATE schedules SET next_run_at = ?, consecutive_errors = 5 WHERE id = ?", [past, schedId]);

      await ctx.scheduler.runOnce();

      // Should not increment run_count since it was skipped
      const sched = ctx.db.getScheduleById(schedId)!;
      expect(sched.consecutive_errors).toBe(5);
      teardown(ctx);
    });
  });

  describe("start/stop", () => {
    test("start and stop without error", () => {
      const ctx = setup();
      ctx.scheduler.start(60000);
      ctx.scheduler.stop();
      // No error = pass
      teardown(ctx);
    });

    test("stop is idempotent", () => {
      const ctx = setup();
      ctx.scheduler.stop();
      ctx.scheduler.stop();
      teardown(ctx);
    });
  });
});
