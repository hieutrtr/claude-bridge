/**
 * W4.2: LoopOrchestrator Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { LoopOrchestrator } from "../../src/orchestration/loop.js";
import { LoopEvaluator } from "../../src/orchestration/evaluator.js";
import { BridgeDatabase } from "../../src/data/db.js";
import type { IDispatcher } from "../../src/execution/interfaces.js";

// Fake dispatcher: orchestrator tests exercise state-machine logic, not real
// subprocess spawning. Each `dispatch` returns a synthetic pid and records the
// call so tests can inspect it if needed.
function makeFakeDispatcher(): IDispatcher & { calls: number } {
  const disp = {
    calls: 0,
    async dispatch() { disp.calls++; return 12345 + disp.calls; },
    async cancel() { return true; },
    isRunning() { return false; },
    sessionIdToUuid(sid: string) { return sid; },
    getResultFile(sid: string, id: number) { return `/tmp/${sid}-${id}.result.json`; },
    getStderrFile(sid: string, id: number) { return `/tmp/${sid}-${id}.stderr`; },
  };
  return disp;
}

function setup() {
  const tmpDir = mkdtempSync(join(tmpdir(), "bridge-loop-"));
  const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  const evaluator = new LoopEvaluator();
  const dispatcher = makeFakeDispatcher();
  const orchestrator = new LoopOrchestrator(tmpDir, db, evaluator, dispatcher);
  // Create test agent
  db.createAgent("be", tmpDir, "be--project", "Backend dev");
  return { tmpDir, db, evaluator, orchestrator, dispatcher };
}

function teardown(ctx: { tmpDir: string; db: BridgeDatabase }) {
  ctx.db.close();
  rmSync(ctx.tmpDir, { recursive: true, force: true });
}

describe("W4.2: LoopOrchestrator", () => {
  describe("startLoop", () => {
    test("creates loop and first iteration", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be",
        "Fix all tests",
        "command:true",
        { maxIterations: 5 },
      );

      expect(loopId).toBeTruthy();
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("running");
      expect(loop.goal).toBe("Fix all tests");
      expect(loop.done_when).toBe("command:true");
      expect(loop.max_iterations).toBe(5);
      expect(loop.current_iteration).toBe(1);

      // Should have created first iteration
      const iterations = ctx.db.getLoopIterations(loopId);
      expect(iterations.length).toBe(1);
      expect(iterations[0]!.iteration_num).toBe(1);

      teardown(ctx);
    });

    test("validates done condition", async () => {
      const ctx = setup();
      await expect(
        ctx.orchestrator.startLoop("be", "goal", "invalid_type:args"),
      ).rejects.toThrow();
      teardown(ctx);
    });

    test("rejects if agent has active loop", async () => {
      const ctx = setup();
      await ctx.orchestrator.startLoop("be", "goal1", "command:true");
      await expect(
        ctx.orchestrator.startLoop("be", "goal2", "command:true"),
      ).rejects.toThrow();
      teardown(ctx);
    });

    test("respects maxConsecutiveFailures default", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "command:true");
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.max_consecutive_failures).toBe(3);
      teardown(ctx);
    });

    test("persists channel info and propagates to iteration tasks", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "command:true", {
        channel: "telegram", channelChatId: "42", userId: "u1",
      });
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.channel).toBe("telegram");
      expect(loop.channel_chat_id).toBe("42");
      expect(loop.user_id).toBe("u1");

      // Iteration task should inherit the channel info
      const iter = ctx.db.getLoopIterations(loopId)[0]!;
      const taskId = parseInt(iter.task_id!, 10);
      const task = ctx.db.getTask(taskId)!;
      expect(task.channel_chat_id).toBe("42");
      expect(task.user_id).toBe("u1");
      teardown(ctx);
    });

    test("respects maxCostUsd", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "command:true", {
        maxCostUsd: 1.5,
      });
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.max_cost_usd).toBe(1.5);
      teardown(ctx);
    });
  });

  describe("onTaskComplete", () => {
    test("marks loop done when condition passes", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "manual:");

      // Simulate task completion with manual approval behavior
      // For manual conditions, onTaskComplete should set pending_approval
      const iterations = ctx.db.getLoopIterations(loopId);
      const taskId = iterations[0]!.task_id!;

      await ctx.orchestrator.onTaskComplete(loopId, taskId, "Done", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      // Manual condition → pending_approval
      expect(loop.pending_approval).toBe(1);
      teardown(ctx);
    });

    test("dispatches next iteration when condition fails", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:nonexistent.txt",
        { maxIterations: 5 },
      );

      const iterations = ctx.db.getLoopIterations(loopId);
      const taskId = iterations[0]!.task_id!;

      await ctx.orchestrator.onTaskComplete(loopId, taskId, "Partial progress", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.current_iteration).toBe(2);
      expect(loop.status).toBe("running");
      teardown(ctx);
    });

    test("emits end-of-loop notification when reaching terminal state", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:nonexistent.txt",
        { maxIterations: 1, channel: "telegram", channelChatId: "99" },
      );
      const iter = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter.task_id!, "failed", 0.02);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("failed");

      const notifs = ctx.db.getPendingNotifications();
      const loopEnd = notifs.find((n) => n.message.includes(`Loop ${loopId}`));
      expect(loopEnd).toBeTruthy();
      expect(loopEnd!.chat_id).toBe("99");
      expect(loopEnd!.message).toContain("failed");
      teardown(ctx);
    });

    test("marks loop failed when max iterations exceeded", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:nonexistent.txt",
        { maxIterations: 1 },
      );

      const iterations = ctx.db.getLoopIterations(loopId);
      const taskId = iterations[0]!.task_id!;

      await ctx.orchestrator.onTaskComplete(loopId, taskId, "Failed", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("failed");
      expect(loop.finish_reason).toContain("max iterations");
      teardown(ctx);
    });

    test("tracks consecutive failures", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:nonexistent.txt",
        { maxIterations: 10, maxConsecutiveFailures: 2 },
      );

      // First iteration fails (task failed, not just condition)
      const iter1 = ctx.db.getLoopIterations(loopId);
      const task1Id = iter1[0]!.task_id!;
      // Simulate task failure
      const taskNum = parseInt(task1Id, 10);
      ctx.db.updateTask(taskNum, { status: "failed", exit_code: 1 });
      await ctx.orchestrator.onTaskComplete(loopId, task1Id, "", 0.01);

      let loop = ctx.db.getLoop(loopId)!;
      expect(loop.consecutive_failures).toBe(1);
      expect(loop.status).toBe("running");

      // Second iteration also fails
      const iter2 = ctx.db.getLoopIterations(loopId);
      const task2Id = iter2[iter2.length - 1]!.task_id!;
      const taskNum2 = parseInt(task2Id, 10);
      ctx.db.updateTask(taskNum2, { status: "failed", exit_code: 1 });
      await ctx.orchestrator.onTaskComplete(loopId, task2Id, "", 0.01);

      loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("failed");
      expect(loop.finish_reason).toContain("consecutive failures");
      teardown(ctx);
    });

    test("accumulates cost", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:nonexistent.txt",
        { maxIterations: 5 },
      );

      const iter1 = ctx.db.getLoopIterations(loopId);
      await ctx.orchestrator.onTaskComplete(loopId, iter1[0]!.task_id!, "progress", 0.05);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.total_cost_usd).toBe(0.05);
      teardown(ctx);
    });

    test("stops on cost limit", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:nonexistent.txt",
        { maxIterations: 100, maxCostUsd: 0.10 },
      );

      const iter1 = ctx.db.getLoopIterations(loopId);
      await ctx.orchestrator.onTaskComplete(loopId, iter1[0]!.task_id!, "progress", 0.15);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("failed");
      expect(loop.finish_reason).toContain("cost");
      teardown(ctx);
    });
  });

  describe("cancelLoop", () => {
    test("cancels a running loop", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "command:true");

      const result = await ctx.orchestrator.cancelLoop(loopId);
      expect(result).toBe(true);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("cancelled");
      teardown(ctx);
    });

    test("returns false for non-running loop", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "command:true");
      ctx.db.updateLoop(loopId, { status: "done" });

      const result = await ctx.orchestrator.cancelLoop(loopId);
      expect(result).toBe(false);
      teardown(ctx);
    });
  });

  describe("approveLoop", () => {
    test("approves a pending loop", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "manual:");

      // Simulate reaching pending_approval state
      ctx.db.updateLoop(loopId, { pending_approval: 1, status: "running" });

      const result = await ctx.orchestrator.approveLoop(loopId);
      expect(result).toBe(true);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("done");
      expect(loop.pending_approval).toBe(0);
      teardown(ctx);
    });

    test("returns false when not pending", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "command:true");

      const result = await ctx.orchestrator.approveLoop(loopId);
      expect(result).toBe(false);
      teardown(ctx);
    });
  });

  describe("rejectLoop", () => {
    test("rejects pending loop and dispatches next iteration", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "manual:",
        { maxIterations: 5 },
      );
      ctx.db.updateLoop(loopId, { pending_approval: 1 });

      const result = await ctx.orchestrator.rejectLoop(loopId, "Try harder");
      expect(result).toBe(true);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.pending_approval).toBe(0);
      expect(loop.current_iteration).toBe(2);
      teardown(ctx);
    });
  });

  describe("decideLoopType", () => {
    test("respects explicit user preference", () => {
      const ctx = setup();
      expect(ctx.orchestrator.decideLoopType("goal", "command:true", "agent")).toBe("agent");
      expect(ctx.orchestrator.decideLoopType("goal", "command:true", "bridge")).toBe("bridge");
      teardown(ctx);
    });

    test("manual/llm_judge → bridge", () => {
      const ctx = setup();
      expect(ctx.orchestrator.decideLoopType("goal", "manual:")).toBe("bridge");
      expect(ctx.orchestrator.decideLoopType("goal", "llm_judge:rubric")).toBe("bridge");
      teardown(ctx);
    });

    test("command with high iterations → agent", () => {
      const ctx = setup();
      expect(ctx.orchestrator.decideLoopType("goal", "command:test", null, 10)).toBe("agent");
      teardown(ctx);
    });

    test("command with low iterations → bridge", () => {
      const ctx = setup();
      expect(ctx.orchestrator.decideLoopType("goal", "command:test", null, 3)).toBe("bridge");
      teardown(ctx);
    });
  });

  describe("formatLoopList", () => {
    test("formats empty list", () => {
      const ctx = setup();
      const result = ctx.orchestrator.formatLoopList([]);
      expect(result).toContain("No");
      teardown(ctx);
    });

    test("formats loop entries", () => {
      const ctx = setup();
      const loops = [{
        loop_id: "abc", agent: "be", project: "/p", goal: "Fix tests",
        done_when: "command:test", loop_type: "bridge", status: "running" as const,
        max_iterations: 5, max_consecutive_failures: 3, current_iteration: 2,
        consecutive_failures: 0, total_cost_usd: 0.05, max_cost_usd: null,
        pending_approval: 0, started_at: "2024-01-01", finished_at: null,
        finish_reason: null, current_task_id: null,
      }];
      const result = ctx.orchestrator.formatLoopList(loops);
      expect(result).toContain("Fix tests");
      expect(result).toContain("running");
      teardown(ctx);
    });
  });

  describe("formatLoopHistory", () => {
    test("formats loop with iterations", () => {
      const ctx = setup();
      const loop = {
        loop_id: "abc", agent: "be", project: "/p", goal: "Fix tests",
        done_when: "command:test", loop_type: "bridge", status: "done" as const,
        max_iterations: 5, max_consecutive_failures: 3, current_iteration: 2,
        consecutive_failures: 0, total_cost_usd: 0.10, max_cost_usd: null,
        pending_approval: 0, started_at: "2024-01-01", finished_at: "2024-01-02",
        finish_reason: "done", current_task_id: null,
      };
      const iterations = [{
        id: 1, loop_id: "abc", iteration_num: 1, task_id: "1",
        prompt: "Fix tests", result_summary: "Fixed 3 tests",
        done_check_passed: 0, cost_usd: 0.05,
        started_at: "2024-01-01", finished_at: "2024-01-01",
        status: "done",
      }, {
        id: 2, loop_id: "abc", iteration_num: 2, task_id: "2",
        prompt: "Fix remaining tests", result_summary: "All tests pass",
        done_check_passed: 1, cost_usd: 0.05,
        started_at: "2024-01-01", finished_at: "2024-01-02",
        status: "done",
      }];
      const result = ctx.orchestrator.formatLoopHistory(loop, iterations);
      expect(result).toContain("Fix tests");
      expect(result).toContain("#1");
      expect(result).toContain("#2");
      teardown(ctx);
    });
  });

  describe("getLoopStatus", () => {
    test("returns null for non-existent loop", async () => {
      const ctx = setup();
      const result = await ctx.orchestrator.getLoopStatus("nonexistent");
      expect(result).toBeNull();
      teardown(ctx);
    });

    test("returns loop for existing loop", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop("be", "goal", "command:true");
      const result = await ctx.orchestrator.getLoopStatus(loopId);
      expect(result).not.toBeNull();
      expect(result!.loop_id).toBe(loopId);
      teardown(ctx);
    });
  });
});
