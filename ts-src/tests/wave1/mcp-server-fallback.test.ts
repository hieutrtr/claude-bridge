/**
 * W1.2: MCP Server with Python Fallback Tests
 *
 * Tests that all 24 tools are registered and that the fallback
 * mechanism (shelling out to bridge-cli) works correctly.
 */
import { describe, test, expect } from "bun:test";
import { TOOL_NAMES, TOOL_DEFINITIONS, buildCliArgs } from "../../src/mcp/tools.js";

describe("W1.2: MCP Server with Python Fallback", () => {
  describe("Tool registry", () => {
    test("exports TOOL_NAMES with all 24 tools", () => {
      expect(TOOL_NAMES).toBeArray();
      expect(TOOL_NAMES.length).toBe(24);
    });

    test("all expected tool names are present", () => {
      const expected = [
        "bridge_dispatch",
        "bridge_status",
        "bridge_agents",
        "bridge_history",
        "bridge_kill",
        "bridge_create_agent",
        "bridge_get_messages",
        "bridge_acknowledge",
        "bridge_reply",
        "bridge_get_notifications",
        "bridge_loop",
        "bridge_loop_status",
        "bridge_loop_cancel",
        "bridge_loop_approve",
        "bridge_loop_reject",
        "bridge_loop_list",
        "bridge_loop_history",
        "bridge_loop_notify",
        "bridge_parse_loop_command",
        "bridge_schedule_add",
        "bridge_schedule_remove",
        "bridge_schedule_list",
        "bridge_schedule_pause",
        "bridge_schedule_resume",
      ];
      for (const name of expected) {
        expect(TOOL_NAMES).toContain(name);
      }
    });
  });

  describe("Tool definitions", () => {
    test("exports TOOL_DEFINITIONS with all 24 tools", () => {
      expect(TOOL_DEFINITIONS).toBeArray();
      expect(TOOL_DEFINITIONS.length).toBe(24);
    });

    test("each definition has name, description, and inputSchema", () => {
      for (const def of TOOL_DEFINITIONS) {
        expect(def.name).toBeString();
        expect(def.description).toBeString();
        expect(def.description.length).toBeGreaterThan(5);
        expect(def.inputSchema).toBeDefined();
        expect(def.inputSchema.type).toBe("object");
      }
    });

    test("bridge_dispatch has required agent and prompt params", () => {
      const def = TOOL_DEFINITIONS.find((d) => d.name === "bridge_dispatch")!;
      expect(def).toBeDefined();
      expect(def.inputSchema.required).toContain("agent");
      expect(def.inputSchema.required).toContain("prompt");
      expect(def.inputSchema.properties!["agent"]).toBeDefined();
      expect(def.inputSchema.properties!["prompt"]).toBeDefined();
    });

    test("bridge_status has optional agent param", () => {
      const def = TOOL_DEFINITIONS.find((d) => d.name === "bridge_status")!;
      expect(def).toBeDefined();
      expect(def.inputSchema.properties!["agent"]).toBeDefined();
      // agent is optional — not in required
      expect(def.inputSchema.required ?? []).not.toContain("agent");
    });

    test("bridge_loop has required agent, goal, done_when params", () => {
      const def = TOOL_DEFINITIONS.find((d) => d.name === "bridge_loop")!;
      expect(def).toBeDefined();
      expect(def.inputSchema.required).toContain("agent");
      expect(def.inputSchema.required).toContain("goal");
      expect(def.inputSchema.required).toContain("done_when");
    });

    test("bridge_schedule_add has required agent_name, prompt, interval_minutes", () => {
      const def = TOOL_DEFINITIONS.find((d) => d.name === "bridge_schedule_add")!;
      expect(def).toBeDefined();
      expect(def.inputSchema.required).toContain("agent_name");
      expect(def.inputSchema.required).toContain("prompt");
      expect(def.inputSchema.required).toContain("interval_minutes");
    });
  });

  describe("CLI argument builder", () => {
    test("bridge_dispatch builds correct args", () => {
      const args = buildCliArgs("bridge_dispatch", {
        agent: "backend",
        prompt: "add tests",
      });
      expect(args).toEqual(["dispatch", "backend", "add tests"]);
    });

    test("bridge_dispatch includes optional model", () => {
      const args = buildCliArgs("bridge_dispatch", {
        agent: "backend",
        prompt: "add tests",
        model: "sonnet",
      });
      expect(args).toEqual(["dispatch", "backend", "add tests", "--model", "sonnet"]);
    });

    test("bridge_status with no args", () => {
      const args = buildCliArgs("bridge_status", {});
      expect(args).toEqual(["status"]);
    });

    test("bridge_status with agent filter", () => {
      const args = buildCliArgs("bridge_status", { agent: "backend" });
      expect(args).toEqual(["status", "--agent", "backend"]);
    });

    test("bridge_agents builds correct args", () => {
      const args = buildCliArgs("bridge_agents", {});
      expect(args).toEqual(["list-agents"]);
    });

    test("bridge_history builds correct args", () => {
      const args = buildCliArgs("bridge_history", { agent: "backend", limit: 5 });
      expect(args).toEqual(["history", "backend", "--limit", "5"]);
    });

    test("bridge_kill builds correct args", () => {
      const args = buildCliArgs("bridge_kill", { agent: "backend" });
      expect(args).toEqual(["kill", "backend"]);
    });

    test("bridge_create_agent builds correct args", () => {
      const args = buildCliArgs("bridge_create_agent", {
        name: "backend",
        path: "/projects/api",
        purpose: "API dev",
      });
      expect(args).toEqual([
        "create-agent", "backend", "/projects/api", "--purpose", "API dev",
      ]);
    });

    test("bridge_loop builds correct args", () => {
      const args = buildCliArgs("bridge_loop", {
        agent: "backend",
        goal: "fix tests",
        done_when: "command:pytest",
        max_iterations: 5,
      });
      expect(args).toEqual([
        "loop", "start", "backend", "fix tests",
        "--done-when", "command:pytest",
        "--max-iterations", "5",
      ]);
    });

    test("bridge_loop_cancel builds correct args", () => {
      const args = buildCliArgs("bridge_loop_cancel", { loop_id: "42" });
      expect(args).toEqual(["loop", "cancel", "42"]);
    });

    test("bridge_schedule_add builds correct args", () => {
      const args = buildCliArgs("bridge_schedule_add", {
        agent_name: "backend",
        prompt: "check status",
        interval_minutes: 30,
      });
      expect(args).toEqual([
        "schedule", "add", "backend", "check status",
        "--interval", "30",
      ]);
    });

    test("bridge_schedule_remove builds correct args", () => {
      const args = buildCliArgs("bridge_schedule_remove", { name_or_id: "news-update" });
      expect(args).toEqual(["schedule", "remove", "news-update"]);
    });

    test("bridge_schedule_list builds correct args", () => {
      const args = buildCliArgs("bridge_schedule_list", {});
      expect(args).toEqual(["schedule", "list"]);
    });

    test("bridge_schedule_pause builds correct args", () => {
      const args = buildCliArgs("bridge_schedule_pause", { name_or_id: "3" });
      expect(args).toEqual(["schedule", "pause", "3"]);
    });

    test("bridge_schedule_resume builds correct args", () => {
      const args = buildCliArgs("bridge_schedule_resume", { name_or_id: "3" });
      expect(args).toEqual(["schedule", "resume", "3"]);
    });

    test("unknown tool throws", () => {
      expect(() => buildCliArgs("unknown_tool", {})).toThrow();
    });
  });
});
