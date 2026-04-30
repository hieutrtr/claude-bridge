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

// Most existing tests were written when iter 1 = execution. Plan-first is now
// the default, so these tests explicitly opt out via this wrapper. Plan-first
// behavior is covered in its own describe block below.
function startLegacyLoop(
  orchestrator: LoopOrchestrator,
  agent: string,
  goal: string,
  cond: string,
  opts: Parameters<LoopOrchestrator["startLoop"]>[3] = {},
): Promise<string> {
  return orchestrator.startLoop(agent, goal, cond, {
    ...opts,
    planFirst: opts.planFirst ?? false,
  });
}

function teardown(ctx: { tmpDir: string; db: BridgeDatabase }) {
  ctx.db.close();
  rmSync(ctx.tmpDir, { recursive: true, force: true });
}

describe("W4.2: LoopOrchestrator", () => {
  describe("startLoop", () => {
    test("creates loop and first iteration", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
        startLegacyLoop(ctx.orchestrator, "be", "goal", "invalid_type:args"),
      ).rejects.toThrow();
      teardown(ctx);
    });

    test("rejects if agent has active loop", async () => {
      const ctx = setup();
      await startLegacyLoop(ctx.orchestrator, "be", "goal1", "command:true");
      await expect(
        startLegacyLoop(ctx.orchestrator, "be", "goal2", "command:true"),
      ).rejects.toThrow();
      teardown(ctx);
    });

    test("respects maxConsecutiveFailures default", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "command:true");
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.max_consecutive_failures).toBe(3);
      teardown(ctx);
    });

    test("persists channel info and propagates to iteration tasks", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "command:true", {
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
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "command:true", {
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
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "manual:");

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
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "command:true");

      const result = await ctx.orchestrator.cancelLoop(loopId);
      expect(result).toBe(true);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("cancelled");
      teardown(ctx);
    });

    test("returns false for non-running loop", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "command:true");
      ctx.db.updateLoop(loopId, { status: "done" });

      const result = await ctx.orchestrator.cancelLoop(loopId);
      expect(result).toBe(false);
      teardown(ctx);
    });
  });

  describe("approveLoop", () => {
    test("approves a pending loop", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "manual:");

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
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "command:true");

      const result = await ctx.orchestrator.approveLoop(loopId);
      expect(result).toBe(false);
      teardown(ctx);
    });
  });

  describe("rejectLoop", () => {
    test("rejects pending loop and dispatches next iteration", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator, 
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
        channel: null, channel_chat_id: null, user_id: null,
        plan: null, plan_enabled: 0,
        pass_threshold: 1, consecutive_passes: 0,
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
        channel: null, channel_chat_id: null, user_id: null,
        plan: null, plan_enabled: 0,
        pass_threshold: 1, consecutive_passes: 0,
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
      const loopId = await startLegacyLoop(ctx.orchestrator, "be", "goal", "command:true");
      const result = await ctx.orchestrator.getLoopStatus(loopId);
      expect(result).not.toBeNull();
      expect(result!.loop_id).toBe(loopId);
      teardown(ctx);
    });
  });

  describe("consecutive-pass threshold", () => {
    test("default pass_threshold is 1 (legacy: first PASS wins)", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator,
        "be", "goal", "command:true", { maxIterations: 5 },
      );
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.pass_threshold).toBe(1);
      expect(loop.consecutive_passes).toBe(0);
      teardown(ctx);
    });

    test("pass_threshold=2 keeps loop running after first PASS", async () => {
      const ctx = setup();
      // command:true always passes — perfect for testing the threshold gate.
      const loopId = await startLegacyLoop(ctx.orchestrator,
        "be", "goal", "command:true",
        { maxIterations: 5, passThreshold: 2 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, "first attempt", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      // First PASS: counter at 1, threshold 2 → continue, NOT done.
      expect(loop.status).toBe("running");
      expect(loop.consecutive_passes).toBe(1);
      expect(loop.current_iteration).toBe(2);
      teardown(ctx);
    });

    test("pass_threshold=2 finalizes done after second consecutive PASS", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator,
        "be", "goal", "command:true",
        { maxIterations: 5, passThreshold: 2 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, "pass 1", 0.01);
      const iter2 = ctx.db.getLoopIterations(loopId).find((it) => it.iteration_num === 2)!;
      await ctx.orchestrator.onTaskComplete(loopId, iter2.task_id!, "pass 2", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("done");
      expect(loop.consecutive_passes).toBe(2);
      teardown(ctx);
    });

    test("non-PASS resets the consecutive counter", async () => {
      const ctx = setup();
      // Use file_exists with a path we toggle: present for iter 1 (pass),
      // absent for iter 2 (fail), present for iter 3 (pass) — counter must
      // reset between iter 2 and iter 3.
      const target = join(ctx.tmpDir, "marker.txt");
      const { writeFileSync, rmSync: rm } = require("fs") as typeof import("fs");
      writeFileSync(target, "x");

      const loopId = await startLegacyLoop(ctx.orchestrator,
        "be", "goal", "file_exists:marker.txt",
        { maxIterations: 5, passThreshold: 2 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, "iter1", 0.01);
      // After iter 1: counter=1, still running.
      expect(ctx.db.getLoop(loopId)!.consecutive_passes).toBe(1);

      // Iter 2 should fail (file removed).
      rm(target);
      const iter2 = ctx.db.getLoopIterations(loopId).find((it) => it.iteration_num === 2)!;
      await ctx.orchestrator.onTaskComplete(loopId, iter2.task_id!, "iter2", 0.01);
      // After iter 2: counter reset to 0.
      expect(ctx.db.getLoop(loopId)!.consecutive_passes).toBe(0);
      expect(ctx.db.getLoop(loopId)!.status).toBe("running");
      teardown(ctx);
    });

    test("PASS-but-not-yet-threshold emits a progress notification", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator,
        "be", "goal", "command:true",
        { maxIterations: 5, passThreshold: 3, channel: "telegram", channelChatId: "123" },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, "ok", 0.01);

      const notifs = ctx.db.getPendingNotifications();
      const passNote = notifs.find((n) => n.message.includes("verdict PASS"));
      expect(passNote).toBeTruthy();
      expect(passNote!.message).toContain("(1/3)");
      expect(passNote!.chat_id).toBe("123");
      teardown(ctx);
    });

    test("passThreshold less than 1 is clamped to 1", async () => {
      const ctx = setup();
      const loopId = await startLegacyLoop(ctx.orchestrator,
        "be", "goal", "command:true",
        { maxIterations: 5, passThreshold: 0 },
      );
      expect(ctx.db.getLoop(loopId)!.pass_threshold).toBe(1);
      teardown(ctx);
    });
  });

  describe("plan-first mode (default)", () => {
    const planJson = JSON.stringify({
      steps: [
        { id: 1, title: "Write model", description: "Create the Order model", verification: "file exists" },
        { id: 2, title: "Write API", description: "POST /orders endpoint", verification: "200 on test" },
        { id: 3, title: "Write tests", description: "Unit + integration", verification: "bun test passes" },
      ],
    });
    const planSummary = `Here's the plan:\n\n\`\`\`json\n${planJson}\n\`\`\`\n\nReady to execute.`;

    test("planFirst is the default", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "Build order system", "command:true", { maxIterations: 5 },
      );
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.plan_enabled).toBe(1);
      // Iter 1 prompt should be the planning prompt, not execution.
      const iter = ctx.db.getLoopIterations(loopId)[0]!;
      expect(iter.prompt).toContain("PLANNING ONLY");
      expect(iter.prompt).toContain("fenced JSON block");
      teardown(ctx);
    });

    test("forces bridge loop type when planFirst + loopType=agent both requested", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "command:true",
        { maxIterations: 5, loopType: "agent", planFirst: true },
      );
      expect(ctx.db.getLoop(loopId)!.loop_type).toBe("bridge");
      teardown(ctx);
    });

    test("parses plan from fenced JSON and dispatches execution iter 2", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "Build order system", "file_exists:never.txt", { maxIterations: 10 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;

      // Planning iter completes with a well-formed plan
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, planSummary, 0.02);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.plan).not.toBeNull();
      const parsed = JSON.parse(loop.plan!);
      expect(parsed.steps.length).toBe(3);

      // Should have advanced to iter 2 (first execution step)
      expect(loop.current_iteration).toBe(2);
      const iter2 = ctx.db.getLoopIterations(loopId).find((it) => it.iteration_num === 2)!;
      expect(iter2.prompt).toContain("Current step (1/3): Write model");
      expect(iter2.prompt).toContain("Focus on THIS step only");
      teardown(ctx);
    });

    test("done-condition is NOT evaluated on planning iter", async () => {
      const ctx = setup();
      // file_exists:never.txt → always fails, but planning iter should skip
      // the check and dispatch iter 2, not mark the loop failed.
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:never.txt", { maxIterations: 5 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, planSummary, 0.01);
      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("running");
      expect(loop.consecutive_failures).toBe(0);
      teardown(ctx);
    });

    test("caps plan at maxIterations-1 and marks truncated", async () => {
      const ctx = setup();
      const bigPlan = {
        steps: Array.from({ length: 8 }, (_, i) => ({
          id: i + 1,
          title: `Step ${i + 1}`,
          description: `Do step ${i + 1}`,
        })),
      };
      const summary = `\`\`\`json\n${JSON.stringify(bigPlan)}\n\`\`\``;
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:never.txt", { maxIterations: 4 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, summary, 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      const plan = JSON.parse(loop.plan!);
      expect(plan.steps.length).toBe(3); // maxIterations(4) - 1
      expect(plan.truncated).toBe(true);
      teardown(ctx);
    });

    test("falls back to legacy execution when plan parse fails", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:never.txt", { maxIterations: 5 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      // No JSON block → parser returns null → fallback
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, "I forgot to output JSON.", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.plan_enabled).toBe(0);
      expect(loop.plan).toBeNull();
      expect(loop.status).toBe("running");
      expect(loop.current_iteration).toBe(2);
      teardown(ctx);
    });

    test("fails loop when plan parse fails and no iterations left", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:never.txt", { maxIterations: 1 },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, "no plan here", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("failed");
      expect(loop.finish_reason).toContain("Plan parse failed");
      teardown(ctx);
    });

    test("fails when plan exhausted but done condition still not satisfied", async () => {
      const ctx = setup();
      const twoStepPlan = JSON.stringify({
        steps: [
          { id: 1, title: "A", description: "do a" },
          { id: 2, title: "B", description: "do b" },
        ],
      });
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:never.txt", { maxIterations: 10 },
      );
      // Iter 1 planning
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(
        loopId, iter1.task_id!,
        `\`\`\`json\n${twoStepPlan}\n\`\`\``, 0.01,
      );
      // Iter 2 = step 1
      const iter2 = ctx.db.getLoopIterations(loopId).find((it) => it.iteration_num === 2)!;
      await ctx.orchestrator.onTaskComplete(loopId, iter2.task_id!, "did a", 0.01);
      // Iter 3 = step 2
      const iter3 = ctx.db.getLoopIterations(loopId).find((it) => it.iteration_num === 3)!;
      await ctx.orchestrator.onTaskComplete(loopId, iter3.task_id!, "did b", 0.01);

      const loop = ctx.db.getLoop(loopId)!;
      expect(loop.status).toBe("failed");
      expect(loop.finish_reason).toContain("Plan exhausted");
      teardown(ctx);
    });

    test("emits plan notification when plan is persisted", async () => {
      const ctx = setup();
      const loopId = await ctx.orchestrator.startLoop(
        "be", "goal", "file_exists:never.txt",
        { maxIterations: 10, channel: "telegram", channelChatId: "123" },
      );
      const iter1 = ctx.db.getLoopIterations(loopId)[0]!;
      await ctx.orchestrator.onTaskComplete(loopId, iter1.task_id!, planSummary, 0.01);

      const notifs = ctx.db.getPendingNotifications();
      const planNote = notifs.find((n) => n.message.includes("plan"));
      expect(planNote).toBeTruthy();
      expect(planNote!.chat_id).toBe("123");
      expect(planNote!.message).toContain("Write model");
      teardown(ctx);
    });
  });
});
