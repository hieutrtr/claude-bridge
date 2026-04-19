/**
 * W5.1-W5.2: CLI Command Tests
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, mkdirSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";
import { COMMAND_HANDLERS, type CommandContext } from "../../src/cli/index.js";
import type { BridgeConfig } from "../../src/types.js";

let tmpDir: string;
let db: BridgeDatabase;
let output: string[];
let errOutput: string[];
let originalLog: typeof console.log;
let originalStderr: typeof process.stderr.write;

function makeCtx(args: string[]): CommandContext {
  return {
    db,
    bridgeHome: tmpDir,
    config: { home_dir: tmpDir, db_path: join(tmpDir, "bridge.db"), bot_dir: null, telegram_token: null, telegram_chat_id: null },
    args,
  };
}

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-"));
  db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  output = [];
  errOutput = [];
  originalLog = console.log;
  originalStderr = process.stderr.write;
  console.log = (...args: unknown[]) => output.push(args.map(String).join(" "));
  process.stderr.write = ((s: string) => { errOutput.push(s); return true; }) as typeof process.stderr.write;
});

afterEach(() => {
  console.log = originalLog;
  process.stderr.write = originalStderr;
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W5.1: Core Commands", () => {
  describe("create-agent", () => {
    test("creates agent successfully", async () => {
      const projectDir = mkdtempSync(join(tmpdir(), "project-"));
      const code = await COMMAND_HANDLERS["create-agent"]!(makeCtx(["testbe", projectDir, "--purpose", "Backend dev"]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("Created agent");

      const agent = db.getAgent("testbe");
      expect(agent).not.toBeNull();
      expect(agent!.name).toBe("testbe");
      rmSync(projectDir, { recursive: true, force: true });
    });

    test("rejects duplicate agent", async () => {
      const projectDir = mkdtempSync(join(tmpdir(), "project-"));
      db.createAgent("testbe", projectDir, "testbe--project", "f");
      const code = await COMMAND_HANDLERS["create-agent"]!(makeCtx(["testbe", projectDir]));
      expect(code).toBe(1);
      expect(errOutput.join("")).toContain("already exists");
      rmSync(projectDir, { recursive: true, force: true });
    });

    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["create-agent"]!(makeCtx([]));
      expect(code).toBe(1);
    });
  });

  describe("delete-agent", () => {
    test("deletes existing agent", async () => {
      db.createAgent("testbe", "/p", "testbe--p", "f");
      const code = await COMMAND_HANDLERS["delete-agent"]!(makeCtx(["testbe"]));
      expect(code).toBe(0);
      expect(db.getAgent("testbe")).toBeNull();
    });

    test("returns error for missing agent", async () => {
      const code = await COMMAND_HANDLERS["delete-agent"]!(makeCtx(["ghost"]));
      expect(code).toBe(1);
    });
  });

  describe("list-agents", () => {
    test("lists agents", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.createAgent("fe", "/q", "fe--q", "f");
      const code = await COMMAND_HANDLERS["list-agents"]!(makeCtx([]));
      expect(code).toBe(0);
      expect(output.length).toBeGreaterThanOrEqual(2);
    });

    test("shows empty message when no agents", async () => {
      const code = await COMMAND_HANDLERS["list-agents"]!(makeCtx([]));
      expect(code).toBe(0);
      expect(output.join("")).toContain("No agents");
    });
  });

  describe("status", () => {
    test("shows global status", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["status"]!(makeCtx([]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("Agents: 1");
    });

    test("shows agent status", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["status"]!(makeCtx(["be"]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("be");
    });
  });

  describe("dispatch", () => {
    test("dispatches task to idle agent", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["dispatch"]!(makeCtx(["be", "add pagination"]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("dispatched");
    });

    test("queues task for busy agent", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      // Create a running task so atomicCheckAndCreateTask sees agent as busy
      const runningId = db.createTask({ session_id: "be--p", prompt: "existing" });
      db.updateTask(runningId, { status: "running" });
      db.updateAgentState("be--p", "busy");
      const code = await COMMAND_HANDLERS["dispatch"]!(makeCtx(["be", "add pagination"]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("queued");
    });

    test("returns error for missing agent", async () => {
      const code = await COMMAND_HANDLERS["dispatch"]!(makeCtx(["ghost", "task"]));
      expect(code).toBe(1);
    });
  });
});

describe("W5.2: Extended Commands", () => {
  describe("kill", () => {
    test("reports no running task", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["kill"]!(makeCtx(["be"]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("No running task");
    });
  });

  describe("history", () => {
    test("shows task history", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.createTask({ session_id: "be--p", prompt: "task 1" });
      db.createTask({ session_id: "be--p", prompt: "task 2" });
      const code = await COMMAND_HANDLERS["history"]!(makeCtx(["be"]));
      expect(code).toBe(0);
      expect(output.length).toBeGreaterThanOrEqual(2);
    });

    test("shows empty for no tasks", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["history"]!(makeCtx(["be"]));
      expect(code).toBe(0);
      expect(output.join("")).toContain("No tasks");
    });
  });

  describe("cost", () => {
    test("shows cost summary", async () => {
      const code = await COMMAND_HANDLERS["cost"]!(makeCtx([]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("Cost summary");
    });
  });

  describe("set-model", () => {
    test("sets model", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["set-model"]!(makeCtx(["be", "opus"]));
      expect(code).toBe(0);
      const agent = db.getAgent("be");
      expect(agent!.model).toBe("opus");
    });

    test("rejects invalid model", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["set-model"]!(makeCtx(["be", "gpt4"]));
      expect(code).toBe(1);
    });
  });

  describe("schedule-add", () => {
    test("adds schedule", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["schedule-add"]!(makeCtx(["be", "run tests", "--every", "60"]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("created");
    });
  });

  describe("schedule-list", () => {
    test("lists schedules", async () => {
      const code = await COMMAND_HANDLERS["schedule-list"]!(makeCtx([]));
      expect(code).toBe(0);
    });
  });
});
