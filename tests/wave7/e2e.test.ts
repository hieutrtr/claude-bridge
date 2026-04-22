/**
 * W7.4: Full E2E Integration Test
 *
 * End-to-end: create agent → dispatch → complete → verify state.
 * All native TS, no Python dependency.
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, mkdirSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";
import { MessageDatabase } from "../../src/data/message-db.js";
import { SessionManager } from "../../src/data/session.js";
import { LoopOrchestrator } from "../../src/orchestration/loop.js";
import { LoopEvaluator } from "../../src/orchestration/evaluator.js";
import { CompletionHandler } from "../../src/execution/on-complete.js";
import { Notifier } from "../../src/execution/notify.js";

describe("W7.4: E2E Integration", () => {
  test("full lifecycle: create agent → dispatch → complete → verify", () => {
    const tmpDir = mkdtempSync(join(tmpdir(), "bridge-e2e-"));
    const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
    const session = new SessionManager(tmpDir);

    // 1. Create agent
    const sessionId = session.deriveSessionId("backend", "/projects/api");
    db.createAgent("backend", "/projects/api", sessionId, "bridge--" + sessionId, "API dev");

    const agent = db.getAgent("backend")!;
    expect(agent.name).toBe("backend");
    expect(agent.state).toBe("created");

    // 2. Dispatch task
    const taskId = db.createTask({
      session_id: sessionId,
      prompt: "Add pagination to /users endpoint",
      channel: "telegram",
      channel_chat_id: "12345",
    });
    db.updateTask(taskId, { status: "running", pid: 99999 });
    db.updateAgentState(sessionId, "busy");

    expect(db.getAgent("backend")!.state).toBe("busy");
    expect(db.getRunningTask(sessionId)!.id).toBe(taskId);

    // 3. Complete task (simulating on-complete handler)
    const handler = new CompletionHandler(tmpDir, db);
    // Manually update since we can't await handleCompletion with mock
    db.updateTask(taskId, {
      status: "done",
      result_summary: "Added pagination with cursor-based approach",
      cost_usd: 0.05,
      duration_ms: 15000,
      num_turns: 4,
      exit_code: 0,
      completed_at: new Date().toISOString(),
    });
    db.updateAgentState(sessionId, "idle");

    // 4. Verify final state
    const task = db.getTask(taskId)!;
    expect(task.status).toBe("done");
    expect(task.result_summary).toContain("pagination");
    expect(task.cost_usd).toBe(0.05);

    expect(db.getAgent("backend")!.state).toBe("idle");

    // 5. Verify notification can be created
    db.createNotification(taskId, "telegram", "12345", "Task done: pagination added");
    const notifications = db.getPendingNotifications();
    expect(notifications.length).toBe(1);
    expect(notifications[0]!.message).toContain("pagination");

    db.close();
    rmSync(tmpDir, { recursive: true, force: true });
  });

  test("loop lifecycle: start → iterate → complete", async () => {
    const tmpDir = mkdtempSync(join(tmpdir(), "bridge-e2e-"));
    const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
    const evaluator = new LoopEvaluator();
    // Fake dispatcher — this test exercises the orchestrator state machine,
    // not real claude spawning.
    const fakeDispatcher = {
      calls: 0,
      async dispatch() { fakeDispatcher.calls++; return 9000 + fakeDispatcher.calls; },
      async cancel() { return true; },
      isRunning() { return false; },
      sessionIdToUuid(sid: string) { return sid; },
      getResultFile(sid: string, id: number) { return `/tmp/${sid}-${id}.result.json`; },
      getStderrFile(sid: string, id: number) { return `/tmp/${sid}-${id}.stderr`; },
    };
    const orchestrator = new LoopOrchestrator(tmpDir, db, evaluator, fakeDispatcher);

    // Setup agent — session_id must match what dispatchIteration creates
    // dispatchIteration uses: `${agent}--${basename(project)}`
    // So project must end with "project" and agent session must be "be--project"
    // Use tmpDir as the actual project (with "project" symlink) to allow command execution
    const projectDir = join(tmpDir, "project");
    mkdirSync(projectDir, { recursive: true });
    db.createAgent("be", projectDir, "be--project", "f");

    // Start loop
    // planFirst:false → iter 1 is an execution iter (this test predates
    // plan-first; the plan path is covered separately in wave4).
    const loopId = await orchestrator.startLoop(
      "be", "Pass all tests", "command:true",
      { maxIterations: 3, planFirst: false },
    );

    let loop = db.getLoop(loopId)!;
    expect(loop.status).toBe("running");
    expect(loop.current_iteration).toBe(1);

    // Simulate first iteration completion — condition passes (command:true)
    const iterations = db.getLoopIterations(loopId);
    const taskId = iterations[0]!.task_id!;
    await orchestrator.onTaskComplete(loopId, taskId, "All tests passing", 0.03);

    // Loop should be done since command:true always passes
    loop = db.getLoop(loopId)!;
    expect(loop.status).toBe("done");
    expect(loop.total_cost_usd).toBe(0.03);

    db.close();
    rmSync(tmpDir, { recursive: true, force: true });
  });

  test("dual database: bridge + messages", () => {
    const tmpDir = mkdtempSync(join(tmpdir(), "bridge-e2e-"));
    const bridgeDb = new BridgeDatabase(join(tmpDir, "bridge.db"));
    const msgDb = new MessageDatabase(join(tmpDir, "messages.db"));

    // Create agent and task
    bridgeDb.createAgent("be", "/p", "be--p", "f");
    const taskId = bridgeDb.createTask({ session_id: "be--p", prompt: "test" });

    // Create inbound message (positional: platform, chatId, userId, messageText, messageId, username)
    msgDb.createInbound("telegram", "12345", "user1", "Run tests on backend", "100", "Alice");

    // Verify both DBs independent
    expect(bridgeDb.getTask(taskId)).not.toBeNull();
    const pending = msgDb.getPendingInbound();
    expect(pending.length).toBe(1);
    expect(pending[0]!.message_text).toContain("Run tests");

    // Process message
    msgDb.markInboundAcknowledged(pending[0]!.id);
    // After acknowledge, message no longer pending
    expect(msgDb.getPendingInbound().length).toBe(0);

    bridgeDb.close();
    msgDb.close();
    rmSync(tmpDir, { recursive: true, force: true });
  });

  test("cost tracking across multiple tasks", () => {
    const tmpDir = mkdtempSync(join(tmpdir(), "bridge-e2e-"));
    const db = new BridgeDatabase(join(tmpDir, "bridge.db"));

    db.createAgent("be", "/p", "be--p", "f");

    // Create 3 completed tasks with costs
    for (let i = 0; i < 3; i++) {
      const taskId = db.createTask({ session_id: "be--p", prompt: `task ${i}` });
      db.updateTask(taskId, {
        status: "done",
        cost_usd: 0.05,
        completed_at: new Date().toISOString(),
      });
    }

    const summary = db.getCostSummary("be--p");
    expect(summary.task_count).toBe(3);
    expect(summary.total_cost_usd).toBeCloseTo(0.15, 2);
    expect(summary.avg_cost_usd).toBeCloseTo(0.05, 2);

    db.close();
    rmSync(tmpDir, { recursive: true, force: true });
  });
});
