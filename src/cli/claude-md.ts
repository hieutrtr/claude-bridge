/**
 * CLAUDE.md Initializer — auto-generates project CLAUDE.md via Claude CLI.
 *
 * Matches Python claude_md_init.py behavior.
 */

import { existsSync } from "fs";
import { join } from "path";

const INIT_PROMPT_NEW = `Analyze this codebase and create a comprehensive CLAUDE.md file that covers:
- Project overview and purpose
- Tech stack and key dependencies
- Build and test commands
- Code conventions and patterns
- Directory structure
Keep it concise and actionable. Focus on what a developer needs to be productive.`;

const INIT_PROMPT_APPEND = `Read the existing CLAUDE.md file. Then analyze the codebase for any important patterns,
conventions, or setup details not yet documented. Append any missing sections.
Do not duplicate existing content.`;

export interface InitResult {
  success: boolean;
  message: string;
  costUsd: number;
  error: string | null;
}

export async function initClaudeMd(
  projectDir: string,
  _agentName: string,
  _purpose: string,
  timeout: number = 120,
): Promise<InitResult> {
  const claudeMdPath = join(projectDir, "CLAUDE.md");
  const exists = existsSync(claudeMdPath);
  const prompt = exists ? INIT_PROMPT_APPEND : INIT_PROMPT_NEW;

  try {
    const proc = Bun.spawn(["claude", "-p", prompt], {
      cwd: projectDir,
      stdout: "pipe",
      stderr: "pipe",
    });

    const timer = setTimeout(() => {
      try { proc.kill(); } catch { /* ok */ }
    }, timeout * 1000);

    const exitCode = await proc.exited;
    clearTimeout(timer);

    if (exitCode === 0) {
      return {
        success: true,
        message: exists ? "Updated CLAUDE.md" : "Created CLAUDE.md",
        costUsd: 0,
        error: null,
      };
    }

    const stderr = await new Response(proc.stderr).text();
    return {
      success: false,
      message: "Claude CLI failed",
      costUsd: 0,
      error: stderr.slice(0, 500),
    };
  } catch (err) {
    return {
      success: false,
      message: "Failed to run Claude CLI",
      costUsd: 0,
      error: (err as Error).message,
    };
  }
}
