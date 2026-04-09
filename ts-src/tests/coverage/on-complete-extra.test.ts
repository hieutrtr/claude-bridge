/**
 * Extra coverage tests for src/execution/on-complete.ts
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { CompletionHandler } from "../../src/execution/on-complete.js";
import { BridgeDatabase } from "../../src/data/db.js";

let tmpDir: string;
let db: BridgeDatabase;
let handler: CompletionHandler;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-complete-cov-"));
  db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  handler = new CompletionHandler(tmpDir, db);
});

afterEach(() => {
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("on-complete.ts coverage", () => {
  describe("handleCompletion", () => {
    test("skips when task not found", async () => {
      // Should not throw when task doesn't exist
      await handler.handleCompletion("be--p", 999, {
        exitCode: 0,
        summary: "Done",
        costUsd: null,
        durationMs: null,
        numTurns: null,
      });
      // No error = pass
    });

    test("sets error_message to Unknown when summary is null on failure", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running" });

      await handler.handleCompletion("be--p", taskId, {
        exitCode: 1,
        summary: null,
        costUsd: null,
        durationMs: null,
        numTurns: null,
      });

      const task = db.getTask(taskId)!;
      expect(task.status).toBe("failed");
      expect(task.error_message).toBe("Unknown error");
    });

    test("creates notification with cost info", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({
        session_id: "be--p",
        prompt: "test",
        channel: "telegram",
        channel_chat_id: "456",
      });
      db.updateTask(taskId, { status: "running" });

      await handler.handleCompletion("be--p", taskId, {
        exitCode: 0,
        summary: "Task completed",
        costUsd: 0.12,
        durationMs: 5000,
        numTurns: 3,
      });

      const notifications = db.getPendingNotifications();
      expect(notifications.length).toBe(1);
      expect(notifications[0]!.message).toContain("$0.12");
    });

    test("no notification when no channel_chat_id", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running" });

      await handler.handleCompletion("be--p", taskId, {
        exitCode: 0,
        summary: "Done",
        costUsd: null,
        durationMs: null,
        numTurns: null,
      });

      const notifications = db.getPendingNotifications();
      expect(notifications.length).toBe(0);
    });
  });

  describe("main()", () => {
    test("processes result file", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running" });

      const resultFile = join(tmpDir, "result.json");
      writeFileSync(
        resultFile,
        JSON.stringify({
          result: "Completed successfully",
          cost_usd: 0.03,
          duration_ms: 8000,
          num_turns: 2,
          is_error: false,
        }),
      );

      await handler.main(["be--p", String(taskId), resultFile]);

      const task = db.getTask(taskId)!;
      expect(task.status).toBe("done");
      expect(task.result_summary).toBe("Completed successfully");
    });

    test("handles missing result file gracefully", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running" });

      await handler.main(["be--p", String(taskId), "/nonexistent/result.json"]);

      const task = db.getTask(taskId)!;
      expect(task.status).toBe("done"); // default exitCode is 0
    });

    test("handles no result file arg", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.updateTask(taskId, { status: "running" });

      await handler.main(["be--p", String(taskId)]);

      const task = db.getTask(taskId)!;
      expect(task.status).toBe("done");
    });

    test("exits with error for insufficient args", async () => {
      // Mock process.exit to prevent actual exit
      const origExit = process.exit;
      let exitCode: number | undefined;
      process.exit = ((code: number) => {
        exitCode = code;
        throw new Error("process.exit called");
      }) as typeof process.exit;

      const origStderr = process.stderr.write;
      process.stderr.write = (() => true) as typeof process.stderr.write;

      try {
        await handler.main(["only-one-arg"]);
      } catch (e) {
        expect((e as Error).message).toBe("process.exit called");
      }

      process.exit = origExit;
      process.stderr.write = origStderr;
      expect(exitCode).toBe(1);
    });
  });
});
