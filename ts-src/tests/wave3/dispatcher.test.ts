/**
 * W3.2: Dispatcher Tests
 *
 * Tests Dispatcher methods without spawning real claude processes.
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { Dispatcher } from "../../src/execution/dispatcher.js";

let tmpDir: string;
let dispatcher: Dispatcher;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-dispatch-"));
  dispatcher = new Dispatcher(tmpDir);
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W3.2: Dispatcher", () => {
  describe("sessionIdToUuid", () => {
    test("returns valid UUID format", () => {
      const uuid = dispatcher.sessionIdToUuid("backend--api");
      expect(uuid).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    });

    test("same input produces same UUID", () => {
      const uuid1 = dispatcher.sessionIdToUuid("backend--api");
      const uuid2 = dispatcher.sessionIdToUuid("backend--api");
      expect(uuid1).toBe(uuid2);
    });

    test("different inputs produce different UUIDs", () => {
      const uuid1 = dispatcher.sessionIdToUuid("backend--api");
      const uuid2 = dispatcher.sessionIdToUuid("frontend--ui");
      expect(uuid1).not.toBe(uuid2);
    });

    test("with taskId produces different UUID", () => {
      const uuid1 = dispatcher.sessionIdToUuid("backend--api");
      const uuid2 = dispatcher.sessionIdToUuid("backend--api", 42);
      expect(uuid1).not.toBe(uuid2);
    });
  });

  describe("getResultFile", () => {
    test("returns correct path", () => {
      const path = dispatcher.getResultFile("backend--api", 42);
      expect(path).toBe(join(tmpDir, "workspaces", "backend--api", "tasks", "42.result.json"));
    });
  });

  describe("getStderrFile", () => {
    test("returns correct path", () => {
      const path = dispatcher.getStderrFile("backend--api", 42);
      expect(path).toBe(join(tmpDir, "workspaces", "backend--api", "tasks", "42.stderr"));
    });
  });

  describe("isRunning", () => {
    test("returns true for current process PID", () => {
      expect(dispatcher.isRunning(process.pid)).toBe(true);
    });

    test("returns false for nonexistent PID", () => {
      expect(dispatcher.isRunning(999999)).toBe(false);
    });
  });

  describe("cancel", () => {
    test("returns false for nonexistent PID", async () => {
      const result = await dispatcher.cancel(999999);
      expect(result).toBe(false);
    });

    test("kills a real spawned process", async () => {
      // Spawn a sleep process to kill
      const proc = Bun.spawn(["sleep", "60"], { stdout: "ignore", stderr: "ignore" });
      const pid = proc.pid;
      expect(dispatcher.isRunning(pid)).toBe(true);

      const killed = await dispatcher.cancel(pid, true, 2);
      expect(killed).toBe(true);
      // Give OS a moment to clean up
      await Bun.sleep(100);
      expect(dispatcher.isRunning(pid)).toBe(false);
    });
  });

  describe("dispatch", () => {
    test("spawns a process and returns PID", async () => {
      // Use a mock task that runs a simple command instead of claude
      const task = {
        id: 1,
        session_id: "test--proj",
        prompt: "echo hello",
        status: "pending" as const,
        position: null,
        pid: null,
        result_file: null,
        result_summary: null,
        cost_usd: null,
        duration_ms: null,
        num_turns: null,
        exit_code: null,
        error_message: null,
        model: null,
        task_type: "standard" as const,
        parent_task_id: null,
        channel: "cli",
        channel_chat_id: null,
        channel_message_id: null,
        user_id: null,
        created_at: new Date().toISOString(),
        started_at: null,
        completed_at: null,
        reported: 0,
      };

      // Create the tasks directory
      const { mkdirSync } = await import("fs");
      mkdirSync(join(tmpDir, "workspaces", "test--proj", "tasks"), { recursive: true });

      // Dispatch with a test command override env
      const pid = await dispatcher.dispatch(task, "bridge--test--proj", "/tmp", {
        env: { BRIDGE_TEST_MODE: "true" },
      });
      expect(pid).toBeGreaterThan(0);

      // Clean up
      await dispatcher.cancel(pid);
    });
  });
});
