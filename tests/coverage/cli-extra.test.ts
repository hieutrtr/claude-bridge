/**
 * Extra coverage tests for src/cli/index.ts
 * Covers: main(), loop commands, schedule commands, arg parsing helpers
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";
import {
  COMMAND_HANDLERS,
  main,
  getBridgeHome,
  loadConfig,
  saveConfig,
  type CommandContext,
} from "../../src/cli/index.js";
import type { BridgeConfig } from "../../src/types.js";

let tmpDir: string;
let db: BridgeDatabase;
let output: string[];
let errOutput: string[];
let originalLog: typeof console.log;
let originalStderr: typeof process.stderr.write;
let originalEnv: string | undefined;

function makeCtx(args: string[]): CommandContext {
  return {
    db,
    bridgeHome: tmpDir,
    config: {
      home_dir: tmpDir,
      db_path: join(tmpDir, "bridge.db"),
      bot_dir: null,
      telegram_token: null,
      telegram_chat_id: null,
    },
    args,
  };
}

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-cov-"));
  db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  output = [];
  errOutput = [];
  originalLog = console.log;
  originalStderr = process.stderr.write;
  originalEnv = process.env["CLAUDE_BRIDGE_HOME"];
  process.env["CLAUDE_BRIDGE_HOME"] = tmpDir;
  console.log = (...args: unknown[]) => output.push(args.map(String).join(" "));
  process.stderr.write = ((s: string) => {
    errOutput.push(s);
    return true;
  }) as typeof process.stderr.write;
});

afterEach(() => {
  console.log = originalLog;
  process.stderr.write = originalStderr;
  if (originalEnv) {
    process.env["CLAUDE_BRIDGE_HOME"] = originalEnv;
  } else {
    delete process.env["CLAUDE_BRIDGE_HOME"];
  }
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("cli/index.ts coverage", () => {
  describe("getBridgeHome", () => {
    test("reads CLAUDE_BRIDGE_HOME env", () => {
      const home = getBridgeHome();
      expect(home).toBe(tmpDir);
    });
  });

  describe("loadConfig / saveConfig", () => {
    test("returns empty config when file missing", () => {
      const cfg = loadConfig(tmpDir);
      expect(typeof cfg).toBe("object");
    });

    test("saves and loads config", () => {
      const config = {
        home_dir: tmpDir,
        db_path: join(tmpDir, "bridge.db"),
        bot_dir: "/tmp/bot",
        telegram_token: "test-token",
        telegram_chat_id: "123",
      } as BridgeConfig;
      saveConfig(tmpDir, config);
      const loaded = loadConfig(tmpDir);
      expect(loaded.telegram_token).toBe("test-token");
    });

    test("handles invalid JSON gracefully", () => {
      writeFileSync(join(tmpDir, "config.json"), "not json");
      const cfg = loadConfig(tmpDir);
      expect(typeof cfg).toBe("object");
    });
  });

  describe("main()", () => {
    test("prints usage with --help", async () => {
      const code = await main(["--help"]);
      expect(code).toBe(0);
    });

    test("prints usage with no args", async () => {
      const code = await main([]);
      expect(code).toBe(0);
    });

    test("returns 1 for unknown command", async () => {
      const code = await main(["nonexistent-command"]);
      expect(code).toBe(1);
    });

    test("executes list-agents command via main", async () => {
      const code = await main(["list-agents"]);
      expect(code).toBe(0);
    });
  });

  describe("memory command", () => {
    test("missing agent name returns error", async () => {
      const code = await COMMAND_HANDLERS["memory"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("agent not found returns error", async () => {
      const code = await COMMAND_HANDLERS["memory"]!(makeCtx(["ghost"]));
      expect(code).toBe(1);
    });

    test("returns memory report for existing agent", async () => {
      db.createAgent("be", "/tmp", "be--tmp", "f");
      const code = await COMMAND_HANDLERS["memory"]!(makeCtx(["be"]));
      expect(code).toBe(0);
    });
  });

  describe("loop command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["loop"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("starts loop with valid args", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      const code = await COMMAND_HANDLERS["loop"]!(makeCtx([
        "be", "Fix tests", "--done-when", "command:true",
        "--max", "5", "--type", "iterate",
        "--max-cost", "1.0",
      ]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("Started loop");
    });
  });

  describe("loop-status command", () => {
    test("shows no active loops", async () => {
      const code = await COMMAND_HANDLERS["loop-status"]!(makeCtx([]));
      expect(code).toBe(0);
    });

    test("shows specific loop by id", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      // Start a loop to get a loop_id
      const code1 = await COMMAND_HANDLERS["loop"]!(makeCtx([
        "be", "Fix tests", "--done-when", "command:true",
      ]));
      expect(code1).toBe(0);

      // Get loop id from output
      const match = output.join("\n").match(/Started loop (\S+)/);
      if (match) {
        output = [];
        const code2 = await COMMAND_HANDLERS["loop-status"]!(makeCtx(["--loop-id", match[1]!]));
        expect(code2).toBe(0);
      }
    });

    test("returns error for nonexistent loop", async () => {
      const code = await COMMAND_HANDLERS["loop-status"]!(makeCtx(["--loop-id", "nonexistent"]));
      expect(code).toBe(1);
    });
  });

  describe("loop-cancel command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["loop-cancel"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("returns error for nonexistent loop", async () => {
      const code = await COMMAND_HANDLERS["loop-cancel"]!(makeCtx(["nonexistent"]));
      expect(code).toBe(1);
    });
  });

  describe("loop-approve command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["loop-approve"]!(makeCtx([]));
      expect(code).toBe(1);
    });
  });

  describe("loop-reject command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["loop-reject"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("with feedback flag", async () => {
      const code = await COMMAND_HANDLERS["loop-reject"]!(makeCtx(["nonexistent", "--feedback", "needs work"]));
      expect(code).toBe(1);
    });
  });

  describe("loop-list command", () => {
    test("lists loops", async () => {
      const code = await COMMAND_HANDLERS["loop-list"]!(makeCtx([]));
      expect(code).toBe(0);
    });

    test("lists loops with --active flag", async () => {
      const code = await COMMAND_HANDLERS["loop-list"]!(makeCtx(["--active"]));
      expect(code).toBe(0);
    });

    test("lists loops for specific agent", async () => {
      const code = await COMMAND_HANDLERS["loop-list"]!(makeCtx(["be"]));
      expect(code).toBe(0);
    });
  });

  describe("loop-history command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["loop-history"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("returns error for nonexistent loop", async () => {
      const code = await COMMAND_HANDLERS["loop-history"]!(makeCtx(["nonexistent"]));
      expect(code).toBe(1);
    });
  });

  describe("schedule-remove command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["schedule-remove"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("returns error for nonexistent schedule", async () => {
      const code = await COMMAND_HANDLERS["schedule-remove"]!(makeCtx(["nonexistent"]));
      expect(code).toBe(1);
    });
  });

  describe("schedule-list command", () => {
    test("lists with agent filter", async () => {
      const code = await COMMAND_HANDLERS["schedule-list"]!(makeCtx(["--agent", "be"]));
      expect(code).toBe(0);
    });

    test("lists all with --all flag", async () => {
      const code = await COMMAND_HANDLERS["schedule-list"]!(makeCtx(["--all"]));
      expect(code).toBe(0);
    });

    test("lists schedules with data", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.addSchedule("test-sched", "be", "run tests", 60);
      const code = await COMMAND_HANDLERS["schedule-list"]!(makeCtx([]));
      expect(code).toBe(0);
      expect(output.join("\n")).toContain("test-sched");
    });
  });

  describe("schedule-pause command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["schedule-pause"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("pauses existing schedule", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.addSchedule("pause-test", "be", "run tests", 60);
      const code = await COMMAND_HANDLERS["schedule-pause"]!(makeCtx(["pause-test"]));
      expect(code).toBe(0);
    });
  });

  describe("schedule-resume command", () => {
    test("missing args returns error", async () => {
      const code = await COMMAND_HANDLERS["schedule-resume"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("resumes existing schedule", async () => {
      db.createAgent("be", "/p", "be--p", "f");
      db.addSchedule("resume-test", "be", "run tests", 60);
      db.pauseSchedule("resume-test");
      const code = await COMMAND_HANDLERS["schedule-resume"]!(makeCtx(["resume-test"]));
      expect(code).toBe(0);
    });
  });

  describe("kill command with missing args", () => {
    test("missing agent returns error", async () => {
      const code = await COMMAND_HANDLERS["kill"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("agent not found returns error", async () => {
      const code = await COMMAND_HANDLERS["kill"]!(makeCtx(["ghost"]));
      expect(code).toBe(1);
    });
  });

  describe("history command edge cases", () => {
    test("missing agent returns error", async () => {
      const code = await COMMAND_HANDLERS["history"]!(makeCtx([]));
      expect(code).toBe(1);
    });

    test("agent not found returns error", async () => {
      const code = await COMMAND_HANDLERS["history"]!(makeCtx(["ghost"]));
      expect(code).toBe(1);
    });
  });

  describe("dispatch missing args", () => {
    test("missing prompt returns error", async () => {
      const code = await COMMAND_HANDLERS["dispatch"]!(makeCtx(["be"]));
      expect(code).toBe(1);
    });
  });
});
