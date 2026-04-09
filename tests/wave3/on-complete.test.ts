/**
 * W3.3: CompletionHandler Tests
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { CompletionHandler } from "../../src/execution/on-complete.js";
import { BridgeDatabase } from "../../src/data/db.js";

let tmpDir: string;
let db: BridgeDatabase;
let handler: CompletionHandler;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-complete-"));
  db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  handler = new CompletionHandler(tmpDir, db);
});

afterEach(() => {
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W3.3: CompletionHandler", () => {
  describe("parseResultFile", () => {
    test("parses valid result JSON", async () => {
      const resultFile = join(tmpDir, "result.json");
      writeFileSync(resultFile, JSON.stringify({
        result: "Task completed successfully",
        cost_usd: 0.05,
        duration_ms: 12000,
        num_turns: 3,
        is_error: false,
      }));
      const result = await handler.parseResultFile(resultFile);
      expect(result).not.toBeNull();
      expect(result!.summary).toBe("Task completed successfully");
      expect(result!.costUsd).toBe(0.05);
      expect(result!.durationMs).toBe(12000);
      expect(result!.numTurns).toBe(3);
      expect(result!.exitCode).toBe(0);
    });

    test("handles error result", async () => {
      const resultFile = join(tmpDir, "result.json");
      writeFileSync(resultFile, JSON.stringify({
        result: "Error occurred",
        is_error: true,
      }));
      const result = await handler.parseResultFile(resultFile);
      expect(result).not.toBeNull();
      expect(result!.exitCode).toBe(1);
    });

    test("returns null for missing file", async () => {
      const result = await handler.parseResultFile(join(tmpDir, "missing.json"));
      expect(result).toBeNull();
    });

    test("returns null for invalid JSON", async () => {
      const resultFile = join(tmpDir, "bad.json");
      writeFileSync(resultFile, "not json");
      const result = await handler.parseResultFile(resultFile);
      expect(result).toBeNull();
    });
  });

  describe("handleCompletion", () => {
    test("updates task status to done", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running", pid: 9999 });

      await handler.handleCompletion("be--p", taskId, {
        exitCode: 0,
        summary: "Done",
        costUsd: 0.05,
        durationMs: 5000,
        numTurns: 2,
      });

      const task = db.getTask(taskId)!;
      expect(task.status).toBe("done");
      expect(task.result_summary).toBe("Done");
      expect(task.cost_usd).toBe(0.05);
      expect(task.duration_ms).toBe(5000);
      expect(task.completed_at).toBeTruthy();
    });

    test("updates task status to failed on non-zero exit", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running", pid: 9999 });

      await handler.handleCompletion("be--p", taskId, {
        exitCode: 1,
        summary: "Error occurred",
        costUsd: null,
        durationMs: null,
        numTurns: null,
      });

      const task = db.getTask(taskId)!;
      expect(task.status).toBe("failed");
      expect(task.error_message).toBe("Error occurred");
    });

    test("updates agent state to idle", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.updateAgentState("be--p", "running");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running" });

      await handler.handleCompletion("be--p", taskId, {
        exitCode: 0, summary: "Done", costUsd: null, durationMs: null, numTurns: null,
      });

      expect(db.getAgentBySession("be--p")!.state).toBe("idle");
    });

    test("creates notification when channel_chat_id is set", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({
        session_id: "be--p", prompt: "test", channel: "telegram", channel_chat_id: "123",
      });
      db.updateTask(taskId, { status: "running" });

      await handler.handleCompletion("be--p", taskId, {
        exitCode: 0, summary: "Done", costUsd: 0.05, durationMs: 5000, numTurns: 2,
      });

      const notifications = db.getPendingNotifications();
      expect(notifications.length).toBe(1);
      expect(notifications[0]!.chat_id).toBe("123");
    });
  });
});
