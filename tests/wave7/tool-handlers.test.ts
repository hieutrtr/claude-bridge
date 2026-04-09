/**
 * W7.1: Native MCP Tool Handlers Tests
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
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-mcp-"));
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

describe("W7.1: Native MCP Tool Handlers", () => {
  describe("bridge_agents", () => {
    test("returns no agents message when empty", async () => {
      const result = await executeToolNative("bridge_agents", {});
      expect(result.content[0]!.text).toContain("No agents");
    });

    test("lists agents", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.createAgent("fe", "/q", "fe--q", "f");
      const result = await executeToolNative("bridge_agents", {});
      expect(result.content[0]!.text).toContain("be");
      expect(result.content[0]!.text).toContain("fe");
    });
  });

  describe("bridge_dispatch", () => {
    test("dispatches task to idle agent", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_dispatch", {
        agent: "be",
        prompt: "add tests",
      });
      expect(result.content[0]!.text).toContain("dispatched");
      expect(result.isError).toBeUndefined();
    });

    test("queues task when agent busy", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const taskId = db.createTask({ session_id: "be--p", prompt: "existing" });
      db.updateTask(taskId, { status: "running" });

      const result = await executeToolNative("bridge_dispatch", {
        agent: "be",
        prompt: "add tests",
      });
      expect(result.content[0]!.text).toContain("queued");
    });

    test("returns error for missing agent", async () => {
      const result = await executeToolNative("bridge_dispatch", {
        agent: "ghost",
        prompt: "test",
      });
      expect(result.isError).toBe(true);
    });
  });

  describe("bridge_status", () => {
    test("shows global status", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_status", {});
      expect(result.content[0]!.text).toContain("Agents: 1");
    });

    test("shows agent status", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_status", { agent: "be" });
      expect(result.content[0]!.text).toContain("be");
    });
  });

  describe("bridge_history", () => {
    test("shows task history", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.createTask({ session_id: "be--p", prompt: "task 1" });
      const result = await executeToolNative("bridge_history", { agent: "be" });
      expect(result.content[0]!.text).toContain("task 1");
    });
  });

  describe("bridge_kill", () => {
    test("reports no running task", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_kill", { agent: "be" });
      expect(result.content[0]!.text).toContain("No running task");
    });
  });

  describe("bridge_loop", () => {
    test("starts a loop", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_loop", {
        agent: "be",
        goal: "Fix tests",
        done_when: "command:true",
      });
      expect(result.content[0]!.text).toContain("Started loop");
    });
  });

  describe("bridge_loop_list", () => {
    test("lists loops", async () => {
      const result = await executeToolNative("bridge_loop_list", {});
      expect(result.content[0]!.text).toContain("No loops");
    });
  });

  describe("bridge_schedule_add", () => {
    test("creates schedule", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const result = await executeToolNative("bridge_schedule_add", {
        agent_name: "be",
        prompt: "run tests",
        interval_minutes: 60,
      });
      expect(result.content[0]!.text).toContain("Schedule");
      expect(result.content[0]!.text).toContain("created");
    });
  });

  describe("bridge_schedule_list", () => {
    test("shows empty list", async () => {
      const result = await executeToolNative("bridge_schedule_list", {});
      expect(result.content[0]!.text).toContain("No schedules");
    });
  });

  describe("bridge_get_messages", () => {
    test("shows no pending messages", async () => {
      const result = await executeToolNative("bridge_get_messages", {});
      expect(result.content[0]!.text).toContain("No pending");
    });
  });

  describe("bridge_get_notifications", () => {
    test("shows no pending notifications", async () => {
      const result = await executeToolNative("bridge_get_notifications", {});
      expect(result.content[0]!.text).toContain("No pending");
    });
  });

  describe("unknown tool", () => {
    test("returns error", async () => {
      const result = await executeToolNative("nonexistent_tool", {});
      expect(result.isError).toBe(true);
    });
  });
});
