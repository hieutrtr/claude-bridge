/**
 * Extra coverage tests for src/mcp/tool-handlers.ts
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";
import { executeToolNative } from "../../src/mcp/tool-handlers.js";

let tmpDir: string;
let db: BridgeDatabase;
let originalEnv: string | undefined;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-mcp-cov-"));
  db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  originalEnv = process.env["CLAUDE_BRIDGE_HOME"];
  process.env["CLAUDE_BRIDGE_HOME"] = tmpDir;
});

afterEach(() => {
  db.close();
  if (originalEnv) {
    process.env["CLAUDE_BRIDGE_HOME"] = originalEnv;
  } else {
    delete process.env["CLAUDE_BRIDGE_HOME"];
  }
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("tool-handlers.ts coverage", () => {
  describe("bridge_status", () => {
    test("shows agent with running task", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "running task here" });
      db.updateTask(taskId, { status: "running", pid: 9999 });

      const result = await executeToolNative("bridge_status", { agent: "be" });
      expect(result.content[0]!.text).toContain("Running");
    });

    test("returns error for missing agent", async () => {
      const result = await executeToolNative("bridge_status", { agent: "ghost" });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_history", () => {
    test("returns no tasks message", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_history", { agent: "be" });
      expect(result.content[0]!.text).toContain("No tasks");
    });

    test("returns error for missing agent", async () => {
      const result = await executeToolNative("bridge_history", { agent: "ghost" });
      expect(result.isError).toBe(true);
    });

    test("shows tasks with cost", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "task with cost" });
      db.updateTask(taskId, { status: "done", cost_usd: 0.05 });
      const result = await executeToolNative("bridge_history", { agent: "be", limit: 5 });
      expect(result.content[0]!.text).toContain("0.05");
    });
  });

  describe("bridge_kill", () => {
    test("returns error for missing agent", async () => {
      const result = await executeToolNative("bridge_kill", { agent: "ghost" });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_acknowledge", () => {
    test("acknowledges a message", async () => {
      const result = await executeToolNative("bridge_acknowledge", { message_id: 999 });
      expect(result.content[0]!.text).toContain("Acknowledged");
    });
  });

  describe("bridge_reply", () => {
    test("fails without valid token", async () => {
      // Ensure no token is available so we don't make real HTTP calls
      const origToken = process.env["TELEGRAM_BOT_TOKEN"];
      delete process.env["TELEGRAM_BOT_TOKEN"];
      try {
        const result = await executeToolNative("bridge_reply", {
          chat_id: "123",
          text: "hello",
        });
        // Should fail since no telegram token is configured
        expect(result.isError).toBe(true);
      } finally {
        if (origToken) process.env["TELEGRAM_BOT_TOKEN"] = origToken;
      }
    });
  });

  describe("bridge_get_notifications", () => {
    test("shows notifications when present", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "test" });
      db.createNotification(taskId, "telegram", "123", "Test notification message");

      const result = await executeToolNative("bridge_get_notifications", {});
      expect(result.content[0]!.text).toContain("Test notification");
    });
  });

  describe("bridge_loop_status", () => {
    test("returns error for nonexistent loop", async () => {
      const result = await executeToolNative("bridge_loop_status", { loop_id: "nonexistent" });
      expect(result.isError).toBe(true);
    });

    test("lists running loops for agent", async () => {
      const result = await executeToolNative("bridge_loop_status", { agent: "be" });
      expect(result.content[0]!.text).toBeDefined();
    });
  });

  describe("bridge_loop_cancel", () => {
    test("returns error for nonexistent loop", async () => {
      const result = await executeToolNative("bridge_loop_cancel", { loop_id: "nonexistent" });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_loop_approve", () => {
    test("returns error when not pending", async () => {
      const result = await executeToolNative("bridge_loop_approve", { loop_id: "nonexistent" });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_loop_reject", () => {
    test("returns error when not pending", async () => {
      const result = await executeToolNative("bridge_loop_reject", {
        loop_id: "nonexistent",
        feedback: "needs work",
      });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_loop_history", () => {
    test("returns error for nonexistent loop", async () => {
      const result = await executeToolNative("bridge_loop_history", { loop_id: "nonexistent" });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_loop_notify", () => {
    test("returns error for nonexistent loop", async () => {
      const result = await executeToolNative("bridge_loop_notify", {
        loop_id: "nonexistent",
        chat_id: "123",
      });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_parse_loop_command", () => {
    test("parses command text", async () => {
      const result = await executeToolNative("bridge_parse_loop_command", {
        text: "run tests until all pass",
      });
      expect(result.content[0]!.text).toContain("Parsed");
    });
  });

  describe("bridge_schedule_remove", () => {
    test("returns error for nonexistent schedule", async () => {
      const result = await executeToolNative("bridge_schedule_remove", {
        name_or_id: "nonexistent",
      });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_schedule_pause", () => {
    test("returns error for nonexistent schedule", async () => {
      const result = await executeToolNative("bridge_schedule_pause", {
        name_or_id: "nonexistent",
      });
      expect(result.isError).toBe(true);
    });

    test("pauses existing schedule", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.addSchedule("test-sched", "be", "run tests", 60);
      const result = await executeToolNative("bridge_schedule_pause", {
        name_or_id: "test-sched",
      });
      expect(result.content[0]!.text).toContain("paused");
    });
  });

  describe("bridge_schedule_resume", () => {
    test("returns error for nonexistent schedule", async () => {
      const result = await executeToolNative("bridge_schedule_resume", {
        name_or_id: "nonexistent",
      });
      expect(result.isError).toBe(true);
    });

    test("resumes existing schedule", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.addSchedule("test-sched", "be", "run tests", 60);
      db.pauseSchedule("test-sched");
      const result = await executeToolNative("bridge_schedule_resume", {
        name_or_id: "test-sched",
      });
      expect(result.content[0]!.text).toContain("resumed");
    });
  });

  describe("bridge_schedule_list", () => {
    test("filters by agent_name", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.addSchedule("test-sched", "be", "run tests", 60);
      const result = await executeToolNative("bridge_schedule_list", { agent_name: "be" });
      expect(result.content[0]!.text).toContain("test-sched");
    });
  });

  describe("bridge_create_agent", () => {
    test("creates agent", async () => {
      const result = await executeToolNative("bridge_create_agent", {
        name: "newagent",
        path: "/tmp",
        purpose: "Test agent",
        model: "opus",
      });
      expect(result.content[0]!.text).toContain("Created agent");
    });

    test("rejects duplicate agent", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_create_agent", {
        name: "be",
        path: "/p",
      });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_get_messages", () => {
    test("returns messages when present", async () => {
      const { MessageDatabase } = await import("../../src/data/message-db.js");
      const msgDb = new MessageDatabase(join(tmpDir, "messages.db"));
      msgDb.createInbound("telegram", "123", "user1", "hello world", "msg-1", "testuser");
      msgDb.close();

      const result = await executeToolNative("bridge_get_messages", {});
      expect(result.content[0]!.text).toContain("testuser");
    });
  });
});
