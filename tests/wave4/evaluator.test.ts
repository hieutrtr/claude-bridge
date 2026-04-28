/**
 * W4.3: LoopEvaluator Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { LoopEvaluator, parseJudgeVerdict } from "../../src/orchestration/evaluator.js";

const evaluator = new LoopEvaluator();

describe("W4.3: LoopEvaluator", () => {
  describe("parseDoneCondition", () => {
    test("parses command condition", () => {
      const cond = evaluator.parseDoneCondition("command:npm test");
      expect(cond.type).toBe("command");
      expect(cond.args).toEqual(["npm test"]);
    });

    test("parses file_exists condition", () => {
      const cond = evaluator.parseDoneCondition("file_exists:dist/index.js");
      expect(cond.type).toBe("file_exists");
      expect(cond.args).toEqual(["dist/index.js"]);
    });

    test("parses file_contains condition with path and pattern", () => {
      const cond = evaluator.parseDoneCondition("file_contains:README.md:## Installation");
      expect(cond.type).toBe("file_contains");
      expect(cond.args).toEqual(["README.md", "## Installation"]);
    });

    test("parses llm_judge condition", () => {
      const cond = evaluator.parseDoneCondition("llm_judge:Code has proper error handling");
      expect(cond.type).toBe("llm_judge");
      expect(cond.args).toEqual(["Code has proper error handling"]);
    });

    test("parses manual condition", () => {
      const cond = evaluator.parseDoneCondition("manual:");
      expect(cond.type).toBe("manual");
      expect(cond.args).toEqual([""]);
    });

    test("throws on unknown type", () => {
      expect(() => evaluator.parseDoneCondition("unknown:arg")).toThrow();
    });

    test("throws on empty string", () => {
      expect(() => evaluator.parseDoneCondition("")).toThrow();
    });

    test("throws on missing colon", () => {
      expect(() => evaluator.parseDoneCondition("command")).toThrow();
    });
  });

  describe("validateDoneCondition", () => {
    test("valid command condition", () => {
      const [valid, err] = evaluator.validateDoneCondition("command:npm test");
      expect(valid).toBe(true);
      expect(err).toBe("");
    });

    test("valid file_exists condition", () => {
      const [valid] = evaluator.validateDoneCondition("file_exists:some/path");
      expect(valid).toBe(true);
    });

    test("valid file_contains condition", () => {
      const [valid] = evaluator.validateDoneCondition("file_contains:path:pattern");
      expect(valid).toBe(true);
    });

    test("invalid: unknown type", () => {
      const [valid, err] = evaluator.validateDoneCondition("bad:type");
      expect(valid).toBe(false);
      expect(err).toContain("Unknown");
    });

    test("invalid: empty string", () => {
      const [valid, err] = evaluator.validateDoneCondition("");
      expect(valid).toBe(false);
      expect(err.length).toBeGreaterThan(0);
    });

    test("invalid: file_contains missing pattern", () => {
      const [valid, err] = evaluator.validateDoneCondition("file_contains:pathonly");
      expect(valid).toBe(false);
      expect(err).toContain("pattern");
    });
  });

  describe("evaluate", () => {
    let tmpDir: string;

    test("command: passes when exit code 0", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "command", args: ["true"] },
        tmpDir,
      );
      expect(passed).toBe(true);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("command: fails when exit code non-zero", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "command", args: ["false"] },
        tmpDir,
      );
      expect(passed).toBe(false);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("command: respects timeout", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "command", args: ["sleep 60"] },
        tmpDir,
        { timeout: 1 },
      );
      expect(passed).toBe(false);
      expect(reason.toLowerCase().includes("timeout") || reason.toLowerCase().includes("timed out")).toBe(true);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("file_exists: passes when file exists", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      writeFileSync(join(tmpDir, "target.txt"), "hello");
      const [passed] = await evaluator.evaluate(
        { type: "file_exists", args: ["target.txt"] },
        tmpDir,
      );
      expect(passed).toBe(true);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("file_exists: fails when file missing", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      const [passed] = await evaluator.evaluate(
        { type: "file_exists", args: ["missing.txt"] },
        tmpDir,
      );
      expect(passed).toBe(false);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("file_contains: passes when pattern found", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      writeFileSync(join(tmpDir, "readme.md"), "# Title\n## Installation\nsteps here");
      const [passed] = await evaluator.evaluate(
        { type: "file_contains", args: ["readme.md", "## Installation"] },
        tmpDir,
      );
      expect(passed).toBe(true);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("file_contains: fails when pattern not found", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      writeFileSync(join(tmpDir, "readme.md"), "# Title\n");
      const [passed] = await evaluator.evaluate(
        { type: "file_contains", args: ["readme.md", "## Installation"] },
        tmpDir,
      );
      expect(passed).toBe(false);
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("file_contains: fails when file missing", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "file_contains", args: ["missing.md", "pattern"] },
        tmpDir,
      );
      expect(passed).toBe(false);
      expect(reason).toContain("not found");
      rmSync(tmpDir, { recursive: true, force: true });
    });

    test("manual: always returns false (needs human approval)", async () => {
      tmpDir = mkdtempSync(join(tmpdir(), "bridge-eval-"));
      const [passed, reason] = await evaluator.evaluate(
        { type: "manual", args: [""] },
        tmpDir,
      );
      expect(passed).toBe(false);
      expect(reason).toContain("manual");
      rmSync(tmpDir, { recursive: true, force: true });
    });
  });

  describe("parseJudgeVerdict (strict)", () => {
    // Unit tests for the verdict parser. We don't spawn the real `claude`
    // CLI here — that's exercised by integration only. These tests close the
    // historical substring traps ("DOES NOT PASS" reading as PASS, etc.).

    test("PASS as first word → passes", () => {
      const [passed, reason] = parseJudgeVerdict("PASS\nThe code looks correct.");
      expect(passed).toBe(true);
      expect(reason).toContain("PASS");
    });

    test("FAIL as first word → fails (with full reason returned)", () => {
      const [passed, reason] = parseJudgeVerdict("FAIL\nMissing tests.");
      expect(passed).toBe(false);
      expect(reason).toContain("Missing tests");
    });

    test("'DOES NOT PASS' is NOT treated as PASS", () => {
      const [passed, reason] = parseJudgeVerdict("DOES NOT PASS\nrubric not satisfied");
      expect(passed).toBe(false);
      expect(reason.toLowerCase()).toContain("unclear");
    });

    test("'PASSPHRASE' is NOT treated as PASS", () => {
      const [passed] = parseJudgeVerdict("PASSPHRASE required\nrubric mentions secrets");
      expect(passed).toBe(false);
    });

    test("'FAILED to satisfy' is NOT treated as FAIL (word-boundary check)", () => {
      // FAILED starts with FAIL followed by E (word char) → \b doesn't match
      // → ambiguous → loop continues. Better to be cautious here than to
      // false-finalize on a verbose model.
      const [passed, reason] = parseJudgeVerdict("FAILED to satisfy rubric");
      expect(passed).toBe(false);
      expect(reason.toLowerCase()).toContain("unclear");
    });

    test("PASS with leading whitespace still counts", () => {
      const [passed] = parseJudgeVerdict("   PASS\nlooks good");
      expect(passed).toBe(true);
    });

    test("Empty output → unclear → fails (so loop continues)", () => {
      const [passed, reason] = parseJudgeVerdict("");
      expect(passed).toBe(false);
      expect(reason.toLowerCase()).toContain("unclear");
    });

    test("Lowercase verdict is honored (uppercased before match)", () => {
      const [passed] = parseJudgeVerdict("pass\nyes");
      expect(passed).toBe(true);
    });

    test("Verdict on line 2 onwards → unclear (only first line is examined)", () => {
      const [passed, reason] = parseJudgeVerdict("Verdict:\nPASS\nThe rubric matches.");
      expect(passed).toBe(false);
      expect(reason.toLowerCase()).toContain("unclear");
    });

    test("Unclear reason slices to 2000 chars (not 200)", () => {
      const long = "X".repeat(3000);
      const [, reason] = parseJudgeVerdict(long);
      // 2000 chars of X plus the prefix label
      expect(reason.length).toBeGreaterThan(2000);
      expect(reason.length).toBeLessThan(2100);
    });
  });

  describe("describe condition", () => {
    test("command description", () => {
      const cond = evaluator.parseDoneCondition("command:npm test");
      expect(cond.type).toBe("command");
      // The condition should be parseable and usable
    });
  });
});
