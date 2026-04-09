/**
 * W5.4: Memory Reader Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { readMemory, formatMemoryReport } from "../../src/cli/memory.js";

describe("W5.4: Memory Reader", () => {
  describe("readMemory", () => {
    test("returns not found for nonexistent dir", () => {
      const result = readMemory("/nonexistent/path/to/project");
      expect(result.found).toBe(false);
    });
  });

  describe("formatMemoryReport", () => {
    test("formats not-found report", () => {
      const report = formatMemoryReport("be", "/nonexistent");
      expect(report).toContain("No memory found");
    });
  });
});
