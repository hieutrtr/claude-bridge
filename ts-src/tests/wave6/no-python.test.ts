/**
 * W6.4: Python Removal Verification
 *
 * Verifies no Python subprocess calls remain in the TS codebase.
 */
import { describe, test, expect } from "bun:test";
import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

function findTsFiles(dir: string, files: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (entry === "node_modules" || entry === "docs" || entry === "tests") continue;
    if (statSync(full).isDirectory()) {
      findTsFiles(full, files);
    } else if (full.endsWith(".ts") && !full.endsWith(".test.ts")) {
      files.push(full);
    }
  }
  return files;
}

describe("W6.4: Python Removal Verification", () => {
  const srcDir = join(import.meta.dir, "../../src");
  const tsFiles = findTsFiles(srcDir);

  test("found TS source files", () => {
    expect(tsFiles.length).toBeGreaterThan(0);
  });

  test("no python/python3 subprocess calls", () => {
    const pythonCalls: string[] = [];
    for (const file of tsFiles) {
      const content = readFileSync(file, "utf-8");
      // Check for python/python3 in spawn/exec calls
      // Allow references in comments and strings that are part of docs
      const lines = content.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i]!;
        // Skip comments and doc strings
        if (line.trim().startsWith("//") || line.trim().startsWith("*")) continue;
        // Check for actual subprocess invocations
        if (
          (line.includes("python3") || line.includes("python ")) &&
          (line.includes("spawn") || line.includes("exec") || line.includes("Bun.spawn"))
        ) {
          pythonCalls.push(`${file}:${i + 1}: ${line.trim()}`);
        }
      }
    }
    expect(pythonCalls).toEqual([]);
  });

  test("no bridge-cli Python references in subprocess calls", () => {
    const bridgeCliCalls: string[] = [];
    for (const file of tsFiles) {
      const content = readFileSync(file, "utf-8");
      const lines = content.split("\n");
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i]!;
        if (line.trim().startsWith("//") || line.trim().startsWith("*")) continue;
        // bridge-cli as Python invocation (not as the TS CLI)
        if (
          line.includes('"bridge-cli"') &&
          (line.includes("spawn") || line.includes("exec"))
        ) {
          // This is OK — it's the TS CLI calling itself
          // Only flag if it's calling python -m or python3
          if (line.includes("python")) {
            bridgeCliCalls.push(`${file}:${i + 1}: ${line.trim()}`);
          }
        }
      }
    }
    expect(bridgeCliCalls).toEqual([]);
  });
});
