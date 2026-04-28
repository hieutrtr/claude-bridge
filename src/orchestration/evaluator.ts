/**
 * Loop Evaluator — assesses whether a loop iteration satisfies the done condition.
 *
 * Supports: command, file_exists, file_contains, llm_judge, manual.
 * Matches Python loop_evaluator.py behavior.
 */

import { existsSync, readFileSync } from "fs";
import { join, isAbsolute } from "path";
import type { DoneCondition, ILoopEvaluator } from "./interfaces.js";

const VALID_TYPES = new Set(["command", "file_exists", "file_contains", "llm_judge", "manual"]);

/**
 * Strict verdict parser for `llm_judge` output. Exported for unit testing
 * without spawning the real `claude` CLI.
 *
 * Looks at the first non-empty line of the model's response and requires it
 * to start with `PASS` or `FAIL` as a whole word. Substring matching (the
 * earlier behavior) was wrong because "DOES NOT PASS" or "PASSPHRASE" would
 * read as PASS, and "FAILED" as FAIL. The prompt template asks the model for
 * "exactly one word: PASS or FAIL" — this parser is the contract enforcer.
 *
 * Returns `[true, fullOutput]` for PASS, `[false, fullOutput]` for FAIL, and
 * `[false, "LLM judge response unclear: <slice>"]` for everything else
 * (including empty stdout from a killed process). Loop treats unclear as
 * FAIL, so the loop continues to the next iteration.
 */
export function parseJudgeVerdict(rawOutput: string): [boolean, string] {
  const trimmed = rawOutput.trim();
  const firstLine = trimmed.split("\n")[0]?.toUpperCase() ?? "";
  const verdictMatch = firstLine.match(/^\s*(PASS|FAIL)\b/);
  if (verdictMatch?.[1] === "PASS") return [true, trimmed];
  if (verdictMatch?.[1] === "FAIL") return [false, trimmed];
  // Slice 2000 to match evalCommand's output truncation. Earlier 200-char
  // slice often cut off the model's explanation on line 2.
  return [false, `LLM judge response unclear: ${rawOutput.slice(0, 2000)}`];
}

const LLM_JUDGE_PROMPT = `You are evaluating whether a task result meets a rubric.

Rubric: {rubric}

Task result:
{result}

Respond with exactly one word: PASS or FAIL
Then on the next line, briefly explain why.`;

export class LoopEvaluator implements ILoopEvaluator {
  parseDoneCondition(conditionStr: string): DoneCondition {
    if (!conditionStr || !conditionStr.includes(":")) {
      throw new Error(`Invalid done condition format: "${conditionStr}". Expected "type:args"`);
    }

    const colonIdx = conditionStr.indexOf(":");
    const type = conditionStr.slice(0, colonIdx);
    const rest = conditionStr.slice(colonIdx + 1);

    if (!VALID_TYPES.has(type)) {
      throw new Error(`Unknown done condition type: "${type}". Valid types: ${[...VALID_TYPES].join(", ")}`);
    }

    if (type === "file_contains") {
      // file_contains:path:pattern — split on second colon
      const secondColon = rest.indexOf(":");
      if (secondColon === -1) {
        throw new Error(`file_contains requires path:pattern format`);
      }
      return {
        type: type as DoneCondition["type"],
        args: [rest.slice(0, secondColon), rest.slice(secondColon + 1)],
      };
    }

    return {
      type: type as DoneCondition["type"],
      args: [rest],
    };
  }

  validateDoneCondition(conditionStr: string): [boolean, string] {
    try {
      const cond = this.parseDoneCondition(conditionStr);
      if (cond.type === "file_contains" && cond.args.length < 2) {
        return [false, "file_contains requires path and pattern"];
      }
      return [true, ""];
    } catch (err) {
      return [false, (err as Error).message];
    }
  }

  async evaluate(
    condition: DoneCondition,
    projectDir: string,
    options?: { timeout?: number; resultSummary?: string },
  ): Promise<[boolean, string]> {
    const timeout = options?.timeout ?? 30;
    const resultSummary = options?.resultSummary ?? "";

    switch (condition.type) {
      case "command":
        return this.evalCommand(condition.args[0]!, projectDir, timeout);
      case "file_exists":
        return this.evalFileExists(condition.args[0]!, projectDir);
      case "file_contains":
        return this.evalFileContains(condition.args[0]!, condition.args[1]!, projectDir);
      case "llm_judge":
        return this.evalLlmJudge(condition.args[0]!, resultSummary, projectDir, timeout);
      case "manual":
        return [false, "Requires manual approval"];
      default:
        return [false, `Unknown condition type: ${condition.type}`];
    }
  }

  private async evalCommand(
    cmd: string,
    projectDir: string,
    timeoutSec: number,
  ): Promise<[boolean, string]> {
    try {
      const proc = Bun.spawn(["sh", "-c", cmd], {
        cwd: projectDir,
        stdout: "pipe",
        stderr: "pipe",
      });

      // Race against timeout
      const timeoutMs = timeoutSec * 1000;
      const timer = setTimeout(() => {
        try { proc.kill(); } catch { /* ok */ }
      }, timeoutMs);

      const exitCode = await proc.exited;
      clearTimeout(timer);

      if (exitCode === null || (proc.killed && exitCode !== 0)) {
        return [false, `Command timed out after ${timeoutSec}s`];
      }

      const stdout = await new Response(proc.stdout).text();
      const stderr = await new Response(proc.stderr).text();
      const output = (stdout + stderr).slice(0, 2000);

      return [exitCode === 0, output || (exitCode === 0 ? "Command succeeded" : "Command failed")];
    } catch (err) {
      return [false, `Command error: ${(err as Error).message}`];
    }
  }

  private async evalFileExists(
    filePath: string,
    projectDir: string,
  ): Promise<[boolean, string]> {
    const resolved = isAbsolute(filePath) ? filePath : join(projectDir, filePath);
    if (existsSync(resolved)) {
      return [true, `File exists: ${filePath}`];
    }
    return [false, `File not found: ${filePath}`];
  }

  private async evalFileContains(
    filePath: string,
    pattern: string,
    projectDir: string,
  ): Promise<[boolean, string]> {
    const resolved = isAbsolute(filePath) ? filePath : join(projectDir, filePath);
    if (!existsSync(resolved)) {
      return [false, `File not found: ${filePath}`];
    }

    try {
      const content = readFileSync(resolved, "utf-8");
      if (content.includes(pattern)) {
        return [true, `Pattern found in ${filePath}`];
      }
      return [false, `Pattern "${pattern}" not found in ${filePath}`];
    } catch (err) {
      return [false, `Error reading ${filePath}: ${(err as Error).message}`];
    }
  }

  private async evalLlmJudge(
    rubric: string,
    resultSummary: string,
    projectDir: string,
    timeoutSec: number,
  ): Promise<[boolean, string]> {
    const prompt = LLM_JUDGE_PROMPT
      .replace("{rubric}", rubric)
      .replace("{result}", resultSummary || "No result summary available");

    try {
      const proc = Bun.spawn(["claude", "--print", "-p", prompt], {
        cwd: projectDir,
        stdout: "pipe",
        stderr: "pipe",
      });

      const timer = setTimeout(() => {
        try { proc.kill(); } catch { /* ok */ }
      }, timeoutSec * 1000);

      const exitCode = await proc.exited;
      clearTimeout(timer);

      // Detect timeout explicitly so the user gets "judge timed out" instead
      // of the misleading "ambiguous" verdict that empty stdout would produce.
      if (exitCode === null || (proc.killed && exitCode !== 0)) {
        return [false, `LLM judge timed out after ${timeoutSec}s`];
      }

      const output = await new Response(proc.stdout).text();
      return parseJudgeVerdict(output);
    } catch {
      return [false, "LLM judge unavailable (claude CLI not found)"];
    }
  }
}
