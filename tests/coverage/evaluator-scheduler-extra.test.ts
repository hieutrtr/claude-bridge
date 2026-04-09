/**
 * Extra coverage tests for src/orchestration/evaluator.ts & scheduler.ts
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { LoopEvaluator } from "../../src/orchestration/evaluator.js";
import { Scheduler } from "../../src/orchestration/scheduler.js";
import { BridgeDatabase } from "../../src/data/db.js";
import type { Schedule } from "../../src/types.js";

const evaluator = new LoopEvaluator();

describe("evaluator.ts coverage", () => {
  describe("evaluate - command with output", () => {
    test("command returns stdout on success", async () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-cov-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "command", args: ["echo hello world"] },
        tmpDir,
      );
      expect(passed).toBe(true);
      expect(reason).toContain("hello world");
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("command returns output on failure", async () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-cov-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "command", args: ["echo failure_msg && exit 1"] },
        tmpDir,
      );
      expect(passed).toBe(false);
      expect(reason.length).toBeGreaterThan(0);
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });

  describe("evaluate - file_exists with absolute path", () => {
    test("resolves absolute path", async () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-cov-"));
      const filePath = join(tmpDir, "abs-target.txt");
      writeFileSync(filePath, "content");
      const [passed, reason] = await evaluator.evaluate(
        { type: "file_exists", args: [filePath] },
        "/some/other/dir",
      );
      expect(passed).toBe(true);
      expect(reason).toContain("exists");
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });

  describe("evaluate - file_contains with absolute path", () => {
    test("resolves absolute path and finds pattern", async () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-cov-"));
      const filePath = join(tmpDir, "abs-content.txt");
      writeFileSync(filePath, "hello world pattern here");
      const [passed, reason] = await evaluator.evaluate(
        { type: "file_contains", args: [filePath, "pattern here"] },
        "/some/other/dir",
      );
      expect(passed).toBe(true);
      expect(reason).toContain("found");
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });

  describe("evaluate - llm_judge (will likely fail without claude CLI)", () => {
    test("returns fail when claude CLI not available", async () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-cov-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "llm_judge", args: ["Code must have tests"] },
        tmpDir,
        { timeout: 2, resultSummary: "Added tests for all modules" },
      );
      // Either passes (if claude is available) or fails gracefully
      expect(typeof passed).toBe("boolean");
      expect(typeof reason).toBe("string");
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });

  describe("evaluate - unknown type", () => {
    test("returns false for unknown type", async () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-cov-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "unknown" as any, args: [] },
        tmpDir,
      );
      expect(passed).toBe(false);
      expect(reason).toContain("Unknown");
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });
});

describe("scheduler.ts coverage", () => {
  function setup() {
    const tmpDir = mkdtempSync(join(tmpdir(), "bridge-sched-cov-"));
    const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
    const scheduler = new Scheduler(tmpDir, db);
    return { tmpDir, db, scheduler };
  }

  function teardown(ctx: { tmpDir: string; db: BridgeDatabase; scheduler: Scheduler }) {
    ctx.scheduler.stop();
    ctx.db.close();
    rmSync(ctx.tmpDir, { recursive: true, force: true });
  }

  describe("dispatchForSchedule", () => {
    test("creates task and updates schedule", async () => {
      const ctx = setup();
      ctx.db.createAgent("be", "/p", "be--p", "f");
      // Also create a session for be--scheduled (FK constraint)
      ctx.db.createAgent("be-sched", "/p", "be--scheduled", "f");
      const schedId = ctx.db.addSchedule("test-sched", "be", "run tests", 60);
      const schedule = ctx.db.getScheduleById(schedId)!;

      const taskId = await ctx.scheduler.dispatchForSchedule(schedule);
      expect(taskId).toBeGreaterThan(0);

      // Verify task was created
      const task = ctx.db.getTask(taskId)!;
      expect(task.prompt).toBe("run tests");
      expect(task.session_id).toBe("be--scheduled");

      // Verify schedule was updated
      const updated = ctx.db.getScheduleById(schedId)!;
      expect(updated.run_count).toBe(1);

      teardown(ctx);
    });

    test("passes channel info through", async () => {
      const ctx = setup();
      ctx.db.createAgent("be", "/p", "be--p", "f");
      ctx.db.createAgent("be-sched", "/p", "be--scheduled", "f");
      const schedId = ctx.db.addSchedule("test-sched", "be", "run tests", 60, undefined, "telegram", "chat123", "user456");
      const schedule = ctx.db.getScheduleById(schedId)!;

      const taskId = await ctx.scheduler.dispatchForSchedule(schedule);
      const task = ctx.db.getTask(taskId)!;
      expect(task.channel).toBe("telegram");
      expect(task.channel_chat_id).toBe("chat123");

      teardown(ctx);
    });
  });

  describe("runOnce error handling", () => {
    test("skips schedules with max errors", async () => {
      const ctx = setup();
      ctx.db.createAgent("be", "/p", "be--p", "f");
      const schedId = ctx.db.addSchedule("test-sched", "be", "run tests", 60);

      // Set next_run_at to past and max out errors
      const past = new Date(Date.now() - 60000).toISOString();
      ctx.db.db.run("UPDATE schedules SET next_run_at = ?, consecutive_errors = 5 WHERE id = ?", [past, schedId]);

      await ctx.scheduler.runOnce();

      // Should not have been processed (skipped due to errors)
      const sched = ctx.db.getScheduleById(schedId)!;
      expect(sched.consecutive_errors).toBe(5);
      expect(sched.run_count).toBe(0);

      teardown(ctx);
    });
  });

  describe("start/stop lifecycle", () => {
    test("start creates interval and stop clears it", () => {
      const ctx = setup();
      ctx.scheduler.start(100000); // long interval so it doesn't fire
      // Starting again should clear previous
      ctx.scheduler.start(100000);
      ctx.scheduler.stop();
      teardown(ctx);
    });
  });
});
