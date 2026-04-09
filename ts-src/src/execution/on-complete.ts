/**
 * Completion Handler — stop hook callback when Claude Code finishes.
 *
 * Reads result files, updates task in DB, sends notification.
 * Replaces Python's on_complete.py.
 *
 * TODO: Implement full logic in Wave 3 migration.
 */

import type { ICompletionHandler, CompletionResult } from "./interfaces.js";

export class CompletionHandler implements ICompletionHandler {
  constructor(
    private homeDir: string,
  ) {}

  async handleCompletion(
    sessionId: string,
    taskId: number,
    result: CompletionResult,
  ): Promise<void> {
    throw new Error("Not implemented");
  }
}
