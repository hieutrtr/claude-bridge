/**
 * Completion Handler — stop hook callback when Claude Code finishes.
 *
 * Reads result files, updates task in DB, sends notification, dequeues next task.
 * Matches Python on_complete.py behavior.
 */

import { existsSync, readFileSync } from "fs";
import type { ICompletionHandler, CompletionResult, IDispatcher } from "./interfaces.js";
import type { IDatabase } from "../data/interfaces.js";
import { startTask } from "./dispatcher.js";

/**
 * Callback fired when a completed task belongs to an active loop. Decouples
 * CompletionHandler from LoopOrchestrator so the execution layer doesn't
 * import from orchestration. Callers wire this explicitly.
 */
export type LoopCompletionCallback = (
  loopId: string,
  taskId: number,
  resultSummary: string,
  costUsd: number,
) => Promise<void>;

export class CompletionHandler implements ICompletionHandler {
  constructor(
    private homeDir: string,
    private db: IDatabase,
    private dispatcher?: IDispatcher,
    private onLoopTaskComplete?: LoopCompletionCallback,
  ) {}

  async parseResultFile(resultFile: string): Promise<CompletionResult | null> {
    if (!existsSync(resultFile)) return null;

    try {
      const raw = readFileSync(resultFile, "utf-8");
      const data = JSON.parse(raw) as Record<string, unknown>;

      // claude's --output-format json uses `total_cost_usd`; older/legacy
      // payloads may use `cost_usd`. Accept either.
      const cost = (data["total_cost_usd"] as number | undefined)
        ?? (data["cost_usd"] as number | undefined)
        ?? null;
      return {
        exitCode: data["is_error"] ? 1 : 0,
        summary: (data["result"] as string | undefined) ?? null,
        costUsd: cost,
        durationMs: (data["duration_ms"] as number | undefined) ?? null,
        numTurns: (data["num_turns"] as number | undefined) ?? null,
      };
    } catch {
      return null;
    }
  }

  async handleCompletion(
    sessionId: string,
    taskId: number,
    result: CompletionResult,
  ): Promise<void> {
    const task = this.db.getTask(taskId);
    if (!task) return;

    const isSuccess = result.exitCode === 0;
    const now = new Date().toISOString();

    // Update task
    this.db.updateTask(taskId, {
      status: isSuccess ? "done" : "failed",
      result_summary: isSuccess ? result.summary : undefined,
      error_message: isSuccess ? undefined : (result.summary ?? "Unknown error"),
      cost_usd: result.costUsd ?? undefined,
      duration_ms: result.durationMs ?? undefined,
      num_turns: result.numTurns ?? undefined,
      exit_code: result.exitCode,
      completed_at: now,
    });

    // Update agent state to idle
    this.db.updateAgentState(sessionId, "idle");

    // Create notification if channel_chat_id is set
    if (task.channel_chat_id) {
      const status = isSuccess ? "done" : "failed";
      const summary = result.summary ?? "No summary";
      const costStr = result.costUsd !== null ? ` ($${result.costUsd.toFixed(2)})` : "";
      const message = `Task #${taskId} ${status}${costStr}: ${summary}`;
      this.db.createNotification(taskId, task.channel, task.channel_chat_id, message);
    }

    // If this task belonged to an active goal loop, let the orchestrator
    // decide the next step. The orchestrator may dispatch the next iteration
    // (which spawns a new task and flips the agent back to `running`), finish
    // the loop, or pause for manual approval.
    const agent = this.db.getAgentBySession(sessionId);
    let loopHandled = false;
    if (agent && this.onLoopTaskComplete) {
      const loop = this.db.getActiveLoopForAgent(agent.name);
      if (loop && loop.current_task_id === String(taskId)) {
        try {
          await this.onLoopTaskComplete(
            loop.loop_id,
            taskId,
            result.summary ?? "",
            result.costUsd ?? 0,
          );
          loopHandled = true;
        } catch (err) {
          process.stderr.write(`[on-complete] loop callback failed: ${err}\n`);
        }
      }
    }

    // Only dequeue if no loop took the agent. When the loop dispatches the
    // next iteration it claims the agent itself; dequeuing on top would
    // double-dispatch.
    if (!loopHandled) {
      const next = this.db.dequeueNextTask(sessionId);
      if (next && this.dispatcher && agent) {
        try {
          await startTask(this.db, this.dispatcher, next, agent);
        } catch {
          /* startTask already recorded the failure */
        }
      }
    }
  }

  async main(argv?: string[]): Promise<void> {
    // CLI entry point for stop hook
    // Expected args: session_id task_id [result_file]
    const args = argv ?? process.argv.slice(2);
    if (args.length < 2) {
      process.stderr.write("Usage: on-complete <session_id> <task_id> [result_file]\n");
      process.exit(1);
    }

    const sessionId = args[0]!;
    const taskId = parseInt(args[1]!, 10);
    const resultFile = args[2];

    let result: CompletionResult = {
      exitCode: 0,
      summary: null,
      costUsd: null,
      durationMs: null,
      numTurns: null,
    };

    if (resultFile) {
      const parsed = await this.parseResultFile(resultFile);
      if (parsed) result = parsed;
    }

    await this.handleCompletion(sessionId, taskId, result);
  }
}
