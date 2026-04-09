/**
 * W1.3: Skills & Smoke Test
 *
 * Validates skills have correct frontmatter and the MCP server
 * module can be imported correctly.
 */
import { describe, test, expect } from "bun:test";
import { existsSync, readFileSync } from "fs";
import { join } from "path";

const ROOT = join(import.meta.dir, "../..");

function parseSkillFrontmatter(path: string): Record<string, string> {
  const content = readFileSync(join(ROOT, path), "utf-8");
  const match = content.match(/^---\n([\s\S]*?)\n---/);
  if (!match?.[1]) return {};
  const result: Record<string, string> = {};
  for (const line of match[1].split("\n")) {
    const [key, ...rest] = line.split(":");
    if (key && rest.length > 0) {
      result[key.trim()] = rest.join(":").trim();
    }
  }
  return result;
}

describe("W1.3: Skills & Smoke Test", () => {
  describe("Skills", () => {
    test("skills/dispatch.md exists", () => {
      expect(existsSync(join(ROOT, "skills/dispatch.md"))).toBe(true);
    });

    test("skills/status.md exists", () => {
      expect(existsSync(join(ROOT, "skills/status.md"))).toBe(true);
    });

    test("dispatch.md has name frontmatter", () => {
      const fm = parseSkillFrontmatter("skills/dispatch.md");
      expect(fm["name"]).toBe("dispatch");
    });

    test("dispatch.md has description frontmatter", () => {
      const fm = parseSkillFrontmatter("skills/dispatch.md");
      expect(fm["description"]).toBeDefined();
      expect(fm["description"]!.length).toBeGreaterThan(5);
    });

    test("status.md has name frontmatter", () => {
      const fm = parseSkillFrontmatter("skills/status.md");
      expect(fm["name"]).toBe("status");
    });

    test("status.md has description frontmatter", () => {
      const fm = parseSkillFrontmatter("skills/status.md");
      expect(fm["description"]).toBeDefined();
      expect(fm["description"]!.length).toBeGreaterThan(5);
    });
  });

  describe("MCP Server Module", () => {
    test("can import startServer", async () => {
      const mod = await import("../../src/mcp/server.js");
      expect(typeof mod.startServer).toBe("function");
    });

    test("can import TOOL_NAMES", async () => {
      const mod = await import("../../src/mcp/tools.js");
      expect(mod.TOOL_NAMES).toBeArray();
      expect(mod.TOOL_NAMES.length).toBe(24);
    });

    test("can import TOOL_DEFINITIONS", async () => {
      const mod = await import("../../src/mcp/tools.js");
      expect(mod.TOOL_DEFINITIONS).toBeArray();
      expect(mod.TOOL_DEFINITIONS.length).toBe(24);
    });

    test("can import buildCliArgs", async () => {
      const mod = await import("../../src/mcp/tools.js");
      expect(typeof mod.buildCliArgs).toBe("function");
    });

    test("can import executeTool", async () => {
      const mod = await import("../../src/mcp/tools.js");
      expect(typeof mod.executeTool).toBe("function");
    });
  });

  describe("Plugin structure completeness", () => {
    const requiredFiles = [
      ".claude-plugin/plugin.json",
      "mcp.json",
      "package.json",
      "tsconfig.json",
      "src/mcp/server.ts",
      "src/mcp/tools.ts",
      "src/mcp/index.ts",
      "skills/dispatch.md",
      "skills/status.md",
    ];

    for (const file of requiredFiles) {
      test(`${file} exists`, () => {
        expect(existsSync(join(ROOT, file))).toBe(true);
      });
    }
  });
});
