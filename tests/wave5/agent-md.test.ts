/**
 * W5.3: AgentMdGenerator Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, existsSync, readFileSync, mkdirSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import {
  generateAgentMd,
  writeAgentMd,
  deleteAgentMd,
  installStopHook,
} from "../../src/cli/agent-md.js";

describe("W5.3: AgentMdGenerator", () => {
  describe("generateAgentMd", () => {
    test("generates valid agent md with frontmatter", () => {
      const md = generateAgentMd("be--myapi", "be", "/projects/myapi", "Backend dev");
      expect(md).toContain("name: bridge--be--myapi");
      expect(md).toContain("model: sonnet");
      expect(md).toContain("isolation:");
      expect(md).toContain("worktree");
      expect(md).toContain("Backend dev");
      expect(md).toContain("on-complete");
    });

    test("uses specified model", () => {
      const md = generateAgentMd("be--myapi", "be", "/projects/myapi", "Backend dev", "opus");
      expect(md).toContain("model: opus");
    });

    test("includes stop hook with bridge home", () => {
      const md = generateAgentMd("be--myapi", "be", "/p", "dev", "sonnet", "/custom/home");
      expect(md).toContain("CLAUDE_BRIDGE_HOME=/custom/home");
    });
  });

  describe("writeAgentMd", () => {
    test("writes to bot dir", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-md-"));
      const path = writeAgentMd("be--myapi", "# Test", tmpDir);
      expect(existsSync(path)).toBe(true);
      expect(readFileSync(path, "utf-8")).toBe("# Test");
      expect(path).toContain("bridge--be--myapi.md");
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });

  describe("deleteAgentMd", () => {
    test("deletes from bot dir", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-md-"));
      const path = writeAgentMd("be--myapi", "# Test", tmpDir);
      expect(existsSync(path)).toBe(true);
      const ok = deleteAgentMd("be--myapi", tmpDir);
      expect(ok).toBe(true);
      expect(existsSync(path)).toBe(false);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("returns false when not found", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-md-"));
      const ok = deleteAgentMd("nonexistent", tmpDir);
      expect(ok).toBe(false);
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });

  describe("installStopHook", () => {
    test("creates settings file with stop hook in Claude Code schema", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-hook-"));
      const settingsPath = installStopHook(tmpDir, "be--myapi", "/home/bridge");
      expect(existsSync(settingsPath)).toBe(true);

      const settings = JSON.parse(readFileSync(settingsPath, "utf-8"));
      expect(settings.hooks.Stop).toBeDefined();
      expect(settings.hooks.Stop.length).toBe(1);
      const inner = settings.hooks.Stop[0].hooks;
      expect(Array.isArray(inner)).toBe(true);
      expect(inner[0].type).toBe("command");
      expect(inner[0].command).toContain("on-complete");
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("does not duplicate hook", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-hook-"));
      installStopHook(tmpDir, "be--myapi");
      installStopHook(tmpDir, "be--myapi");

      const settingsPath = join(tmpDir, ".claude", "settings.local.json");
      const settings = JSON.parse(readFileSync(settingsPath, "utf-8"));
      expect(settings.hooks.Stop.length).toBe(1);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("migrates legacy lowercase stop entry", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-hook-"));
      const settingsDir = join(tmpDir, ".claude");
      mkdirSync(settingsDir, { recursive: true });
      writeFileSync(
        join(settingsDir, "settings.local.json"),
        JSON.stringify({
          hooks: { stop: [{ command: "bridge on-complete --session-id be--myapi" }] },
        }),
        "utf-8",
      );

      installStopHook(tmpDir, "be--myapi");

      const settings = JSON.parse(readFileSync(join(settingsDir, "settings.local.json"), "utf-8"));
      expect(settings.hooks.stop).toBeUndefined();
      expect(settings.hooks.Stop.length).toBe(1);
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });
});
