/**
 * W7.3: BridgeBotMdGenerator Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, readFileSync, existsSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { generateBridgeBotMd, writeBridgeBotMd } from "../../src/mcp/bridge-md.js";

describe("W7.3: BridgeBotMdGenerator", () => {
  test("generates CLAUDE.md with tool docs", () => {
    const md = generateBridgeBotMd();
    expect(md).toContain("Bridge Bot");
    expect(md).toContain("bridge_dispatch");
    expect(md).toContain("bridge_status");
    expect(md).toContain("bridge_loop");
    expect(md).toContain("bridge_schedule_add");
    expect(md).toContain("Behavior Rules");
  });

  test("includes custom instance name", () => {
    const md = generateBridgeBotMd({ instanceName: "My Bridge" });
    expect(md).toContain("My Bridge");
  });

  test("writes to bot directory", () => {
    const tmpDir = mkdtempSync(join(tmpdir(), "bridge-md-"));
    const path = writeBridgeBotMd(tmpDir);
    expect(existsSync(path)).toBe(true);
    const content = readFileSync(path, "utf-8");
    expect(content).toContain("Bridge Bot");
    rmSync(tmpDir, { recursive: true, force: true });
  });
});
