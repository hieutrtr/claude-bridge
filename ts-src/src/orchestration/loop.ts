/**
 * Loop Orchestrator — iterative task execution with done conditions.
 *
 * State machine: running → (dispatch → evaluate → decide) → completed/failed/cancelled
 * Matches Python loop_orchestrator.py behavior.
 */

import type { Loop, LoopIteration } from "../types.js";
import type { IDatabase } from "../data/interfaces.js";
import type { ILoopOrchestrator, ILoopEvaluator, AgentLoopResult } from "./interfaces.js";

const COST_WARNING_THRESHOLD = 0.80;
const MAX_FEEDBACK_CHARS = 2000;

export class LoopOrchestrator implements ILoopOrchestrator {
  constructor(
    private homeDir: string,
    private db: IDatabase,
    private evaluator: ILoopEvaluator,
  ) {}

  async startLoop(
    agentName: string,
    goal: string,
    doneCondition: string,
    options?: {
      maxIterations?: number;
      maxConsecutiveFailures?: number;
      loopType?: string;
      maxCostUsd?: number | null;
    },
  ): Promise<string> {
    // Validate done condition
    const [valid, err] = this.evaluator.validateDoneCondition(doneCondition);
    if (!valid) {
      throw new Error(`Invalid done condition: ${err}`);
    }

    // Check for existing active loop
    const existing = this.db.getActiveLoopForAgent(agentName);
    if (existing) {
      throw new Error(`Agent "${agentName}" already has an active loop: ${existing.loop_id}`);
    }

    // Get agent info
    const agent = this.db.getAgent(agentName);
    if (!agent) {
      throw new Error(`Agent "${agentName}" not found`);
    }

    const maxIterations = options?.maxIterations ?? 10;
    const maxConsecutiveFailures = options?.maxConsecutiveFailures ?? 3;
    const loopType = options?.loopType ?? this.decideLoopType(goal, doneCondition, null, maxIterations);
    const maxCostUsd = options?.maxCostUsd ?? null;

    // Create loop
    const loopId = this.db.createLoop(
      agentName,
      agent.project_dir,
      goal,
      doneCondition,
      loopType,
      maxIterations,
      maxConsecutiveFailures,
      maxCostUsd,
    );

    // Dispatch first iteration
    await this.dispatchIteration(loopId, 1, null);

    return loopId;
  }

  async onTaskComplete(
    loopId: string,
    taskId: string,
    resultSummary: string,
    costUsd: number = 0,
  ): Promise<void> {
    const loop = this.db.getLoop(loopId);
    if (!loop || loop.status !== "running") return;

    // Update iteration
    const iterations = this.db.getLoopIterations(loopId);
    const currentIter = iterations.find((it) => it.task_id === taskId);
    if (currentIter) {
      this.db.updateLoopIteration(currentIter.id, {
        result_summary: resultSummary,
        cost_usd: costUsd,
        finished_at: new Date().toISOString(),
        status: "done",
      });
    }

    // Accumulate cost
    const newTotalCost = loop.total_cost_usd + costUsd;
    this.db.updateLoop(loopId, { total_cost_usd: newTotalCost });

    // Check cost limit
    if (loop.max_cost_usd !== null && newTotalCost >= loop.max_cost_usd) {
      this.db.updateLoop(loopId, {
        status: "failed",
        finished_at: new Date().toISOString(),
        finish_reason: `Exceeded cost limit: $${newTotalCost.toFixed(2)} >= $${loop.max_cost_usd.toFixed(2)}`,
      });
      return;
    }

    // Check if task itself failed (non-zero exit)
    const task = this.db.getTask(parseInt(taskId, 10));
    const taskFailed = task?.status === "failed";

    // Track consecutive failures
    let consecutiveFailures = loop.consecutive_failures;
    if (taskFailed) {
      consecutiveFailures += 1;
    } else {
      consecutiveFailures = 0;
    }
    this.db.updateLoop(loopId, { consecutive_failures: consecutiveFailures });

    // Check consecutive failure limit
    if (consecutiveFailures >= loop.max_consecutive_failures) {
      this.db.updateLoop(loopId, {
        status: "failed",
        finished_at: new Date().toISOString(),
        finish_reason: `Too many consecutive failures (${consecutiveFailures})`,
      });
      return;
    }

    // Evaluate done condition
    const condition = this.evaluator.parseDoneCondition(loop.done_when);

    if (condition.type === "manual") {
      // Manual → pending approval
      this.db.updateLoop(loopId, { pending_approval: 1 });
      if (currentIter) {
        this.db.updateLoopIteration(currentIter.id, { done_check_passed: 0 });
      }
      return;
    }

    const [passed, reason] = await this.evaluator.evaluate(
      condition,
      loop.project,
      { resultSummary },
    );

    if (currentIter) {
      this.db.updateLoopIteration(currentIter.id, { done_check_passed: passed ? 1 : 0 });
    }

    if (passed) {
      // Done!
      this.db.updateLoop(loopId, {
        status: "done",
        finished_at: new Date().toISOString(),
        finish_reason: reason,
      });
      return;
    }

    // Check max iterations
    if (loop.current_iteration >= loop.max_iterations) {
      this.db.updateLoop(loopId, {
        status: "failed",
        finished_at: new Date().toISOString(),
        finish_reason: `Exceeded max iterations (${loop.max_iterations})`,
      });
      return;
    }

    // Dispatch next iteration
    const feedback = this.generateFeedback(iterations);
    await this.dispatchIteration(loopId, loop.current_iteration + 1, feedback);
  }

  async cancelLoop(loopId: string): Promise<boolean> {
    const loop = this.db.getLoop(loopId);
    if (!loop || (loop.status !== "running" && loop.pending_approval !== 1)) {
      return false;
    }

    this.db.updateLoop(loopId, {
      status: "cancelled",
      finished_at: new Date().toISOString(),
      finish_reason: "Cancelled by user",
      pending_approval: 0,
    });
    return true;
  }

  async approveLoop(loopId: string): Promise<boolean> {
    const loop = this.db.getLoop(loopId);
    if (!loop || loop.pending_approval !== 1) {
      return false;
    }

    this.db.updateLoop(loopId, {
      status: "done",
      finished_at: new Date().toISOString(),
      finish_reason: "Approved by user",
      pending_approval: 0,
    });
    return true;
  }

  async rejectLoop(loopId: string, feedback?: string): Promise<boolean> {
    const loop = this.db.getLoop(loopId);
    if (!loop || loop.pending_approval !== 1) {
      return false;
    }

    this.db.updateLoop(loopId, { pending_approval: 0 });

    // Check max iterations
    if (loop.current_iteration >= loop.max_iterations) {
      this.db.updateLoop(loopId, {
        status: "failed",
        finished_at: new Date().toISOString(),
        finish_reason: `Exceeded max iterations (${loop.max_iterations})`,
      });
      return true;
    }

    // Dispatch next iteration with user feedback
    await this.dispatchIteration(
      loopId,
      loop.current_iteration + 1,
      feedback ?? null,
    );
    return true;
  }

  async getLoopStatus(loopId: string): Promise<Loop | null> {
    return this.db.getLoop(loopId);
  }

  decideLoopType(
    goal: string,
    doneWhen: string,
    userPreference?: string | null,
    maxIterations: number = 5,
  ): string {
    // Explicit override wins
    if (userPreference === "agent" || userPreference === "bridge") {
      return userPreference;
    }

    // Parse condition type
    const colonIdx = doneWhen.indexOf(":");
    const condType = colonIdx >= 0 ? doneWhen.slice(0, colonIdx) : doneWhen;

    // Manual/llm_judge → always bridge (needs external evaluation)
    if (condType === "manual" || condType === "llm_judge") {
      return "bridge";
    }

    // High iterations → agent (fewer round-trips)
    if (maxIterations > 5) {
      return "agent";
    }

    // Command/file conditions with low iterations → bridge
    return "bridge";
  }

  formatLoopList(loops: Loop[]): string {
    if (loops.length === 0) {
      return "No loops found.";
    }

    const lines: string[] = [];
    for (const loop of loops) {
      const cost = loop.total_cost_usd > 0 ? ` ($${loop.total_cost_usd.toFixed(2)})` : "";
      lines.push(
        `[${loop.loop_id}] ${loop.agent} — ${loop.status} — iter ${loop.current_iteration}/${loop.max_iterations}${cost}`,
      );
      lines.push(`  Goal: ${loop.goal}`);
    }
    return lines.join("\n");
  }

  formatLoopHistory(loop: Loop, iterations: LoopIteration[]): string {
    const lines: string[] = [];
    const cost = loop.total_cost_usd > 0 ? ` ($${loop.total_cost_usd.toFixed(2)})` : "";
    lines.push(`Loop ${loop.loop_id} — ${loop.status}${cost}`);
    lines.push(`Goal: ${loop.goal}`);
    lines.push(`Done when: ${loop.done_when}`);
    lines.push("");

    for (const iter of iterations) {
      const passed = iter.done_check_passed ? "✅" : "❌";
      const iterCost = iter.cost_usd > 0 ? ` ($${iter.cost_usd.toFixed(2)})` : "";
      lines.push(`#${iter.iteration_num} ${passed}${iterCost} — ${iter.status}`);
      if (iter.result_summary) {
        const short = iter.result_summary.length > 100
          ? iter.result_summary.slice(0, 100) + "..."
          : iter.result_summary;
        lines.push(`  ${short}`);
      }
    }

    return lines.join("\n");
  }

  // --- Private helpers ---

  private async dispatchIteration(
    loopId: string,
    iterationNum: number,
    feedback: string | null,
  ): Promise<void> {
    const loop = this.db.getLoop(loopId)!;
    const prompt = this.buildIterationPrompt(loop.goal, iterationNum, feedback, loop.loop_type, loop.done_when);

    // Create task for this iteration
    const taskId = this.db.createTask({
      session_id: `${loop.agent}--${loop.project.split("/").pop() ?? loop.project}`,
      prompt,
    });

    // Create iteration record
    this.db.createLoopIteration(loopId, iterationNum, prompt);

    // Update iteration with task_id
    const iterations = this.db.getLoopIterations(loopId);
    const thisIter = iterations.find((it) => it.iteration_num === iterationNum);
    if (thisIter) {
      this.db.updateLoopIteration(thisIter.id, { task_id: String(taskId) });
    }

    // Update loop state
    this.db.updateLoop(loopId, {
      current_iteration: iterationNum,
      current_task_id: String(taskId),
    });
  }

  private buildIterationPrompt(
    goal: string,
    iterationNum: number,
    feedback: string | null,
    loopType: string,
    doneWhen: string,
  ): string {
    const parts: string[] = [goal];

    if (iterationNum > 1) {
      parts.push(`\n\nThis is iteration #${iterationNum} of a loop.`);
      if (feedback) {
        parts.push(`\nPrevious context:\n${feedback}`);
      }
    }

    if (loopType === "agent") {
      parts.push(`\n\nDone condition: ${doneWhen}`);
      parts.push("Please attempt to satisfy the done condition. If you make progress but don't fully succeed, describe what's left.");
    }

    return parts.join("");
  }

  private generateFeedback(iterations: LoopIteration[]): string {
    // Use last 2 iterations for feedback
    const recent = iterations.slice(-2);
    if (recent.length === 0) return "";

    const parts: string[] = [];
    for (const iter of recent) {
      if (iter.result_summary) {
        const summary = iter.result_summary.length > MAX_FEEDBACK_CHARS / 2
          ? iter.result_summary.slice(0, MAX_FEEDBACK_CHARS / 2) + "...[truncated]"
          : iter.result_summary;
        parts.push(`Iteration #${iter.iteration_num}: ${summary}`);
      }
    }

    const result = parts.join("\n\n");
    return result.length > MAX_FEEDBACK_CHARS
      ? result.slice(0, MAX_FEEDBACK_CHARS) + "...[truncated]"
      : result;
  }
}
