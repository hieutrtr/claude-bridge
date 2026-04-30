/**
 * W1.1: Plugin Metadata & Structure Tests
 *
 * Validates that plugin.json, mcp.json, and package.json are correct
 * and consistent for Claude Code plugin installation.
 */
import { describe, test, expect } from "bun:test";
import { existsSync, readFileSync } from "fs";
import { join } from "path";

const ROOT = join(import.meta.dir, "../..");

function readJSON(relPath: string): Record<string, unknown> {
  const fullPath = join(ROOT, relPath);
  return JSON.parse(readFileSync(fullPath, "utf-8")) as Record<string, unknown>;
}

describe("W1.1: Plugin Metadata & Structure", () => {
  describe("File existence", () => {
    test("plugin.json exists", () => {
      expect(existsSync(join(ROOT, ".claude-plugin/plugin.json"))).toBe(true);
    });

    test("mcp.json exists", () => {
      expect(existsSync(join(ROOT, "mcp.json"))).toBe(true);
    });

    test("package.json exists", () => {
      expect(existsSync(join(ROOT, "package.json"))).toBe(true);
    });
  });

  describe("plugin.json", () => {
    const plugin = readJSON(".claude-plugin/plugin.json");

    test("has required name field", () => {
      expect(plugin["name"]).toBe("claude-bridge");
    });

    test("has required version field", () => {
      expect(typeof plugin["version"]).toBe("string");
      expect(plugin["version"]).toMatch(/^\d+\.\d+\.\d+(-[\w.]+)?$/);
    });

    test("has description", () => {
      expect(typeof plugin["description"]).toBe("string");
      expect((plugin["description"] as string).length).toBeGreaterThan(10);
    });

    test("has authors array", () => {
      expect(Array.isArray(plugin["authors"])).toBe(true);
      expect((plugin["authors"] as string[]).length).toBeGreaterThan(0);
    });

    test("has keywords array", () => {
      expect(Array.isArray(plugin["keywords"])).toBe(true);
    });

    test("has homepage", () => {
      expect(typeof plugin["homepage"]).toBe("string");
    });

    test("has license", () => {
      expect(typeof plugin["license"]).toBe("string");
    });
  });

  describe("mcp.json", () => {
    const mcp = readJSON("mcp.json") as {
      mcpServers?: Record<string, { command?: string; args?: string[]; env?: Record<string, string> }>;
    };

    test("has mcpServers with bridge entry", () => {
      expect(mcp.mcpServers).toBeDefined();
      expect(mcp.mcpServers!["bridge"]).toBeDefined();
    });

    test("bridge server uses bun command", () => {
      const bridge = mcp.mcpServers!["bridge"]!;
      expect(bridge.command).toBe("bun");
    });

    test("bridge server points to MCP server entry", () => {
      const bridge = mcp.mcpServers!["bridge"]!;
      expect(bridge.args).toBeDefined();
      const argsStr = bridge.args!.join(" ");
      expect(argsStr).toContain("mcp/server.ts");
    });

    test("bridge server has CLAUDE_BRIDGE_HOME env", () => {
      const bridge = mcp.mcpServers!["bridge"]!;
      expect(bridge.env).toBeDefined();
      expect(bridge.env!["CLAUDE_BRIDGE_HOME"]).toBeDefined();
    });
  });

  describe("package.json", () => {
    const pkg = readJSON("package.json");

    test("name is @hieutrtr/claude-bridge", () => {
      expect(pkg["name"]).toBe("@hieutrtr/claude-bridge");
    });

    test("has bin entry for bridge", () => {
      const bin = pkg["bin"] as Record<string, string>;
      expect(bin).toBeDefined();
      expect(bin["bridge"]).toBeDefined();
    });

    test("has test script using bun test", () => {
      const scripts = pkg["scripts"] as Record<string, string>;
      expect(scripts["test"]).toContain("bun test");
    });

    test("has required dependencies", () => {
      const deps = pkg["dependencies"] as Record<string, string>;
      expect(deps["@modelcontextprotocol/sdk"]).toBeDefined();
      expect(deps["grammy"]).toBeDefined();
      expect(deps["zod"]).toBeDefined();
    });

    test("type is module", () => {
      expect(pkg["type"]).toBe("module");
    });
  });

  describe("Version consistency", () => {
    test("plugin.json and package.json have matching versions", () => {
      const plugin = readJSON(".claude-plugin/plugin.json");
      const pkg = readJSON("package.json");
      expect(plugin["version"]).toBe(pkg["version"]);
    });
  });
});
