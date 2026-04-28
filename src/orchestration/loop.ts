/**
 * Loop Orchestrator — iterative task execution with done conditions.
 *
 * State machine: running → (dispatch → evaluate → decide) → completed/failed/cancelled
 *
 * Plan-first mode (default): iteration 1 is a planning iteration — the agent
 * returns a structured JSON plan instead of doing the work. Iterations 2..N+1
 * each execute one sub-task from the plan. This gives the user early per-step
 * reports instead of the agent dumping everything into iter 1. Opt out with
 * planFirst: false.
 */

import type { Loop, LoopIteration, LoopPlan, LoopPlanStep } from "../types.js";
import type { IDatabase } from "../data/interfaces.js";
import type { IDispatcher } from "../execution/interfaces.js";
import { startTask } from "../execution/dispatcher.js";
import type { ILoopOrchestrator, ILoopEvaluator } from "./interfaces.js";

const MAX_FEEDBACK_CHARS = 2000;

export class LoopOrchestrator implements ILoopOrchestrator {
  constructor(
    private homeDir: string,
    private db: IDatabase,
    private evaluator: ILoopEvaluator,
    private dispatcher?: IDispatcher,
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
      channel?: string;
      channelChatId?: string;
      userId?: string;
      planFirst?: boolean;
      passThreshold?: number;
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
    const planFirst = options?.planFirst ?? true;

    // Plan-first forces bridge loop: an "agent" loop runs everything inside a
    // single claude session so we can't split iterations for early reports.
    let loopType = options?.loopType
      ?? this.decideLoopType(goal, doneCondition, null, maxIterations);
    if (planFirst && loopType === "agent") {
      loopType = "bridge";
    }
    const maxCostUsd = options?.maxCostUsd ?? null;
    const passThreshold = Math.max(1, options?.passThreshold ?? 1);

    // Create loop — persist channel info so each iteration task inherits it and
    // so end-of-loop notifications can be routed back to the originating user.
    const loopId = this.db.createLoop(
      agentName,
      agent.project_dir,
      goal,
      doneCondition,
      loopType,
      maxIterations,
      maxConsecutiveFailures,
      maxCostUsd,
      options?.channel ?? null,
      options?.channelChatId ?? null,
      options?.userId ?? null,
      planFirst,
      passThreshold,
    );

    // Dispatch first iteration — planning iter if planFirst, else execution iter.
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

    // Check cost limit — applies before every other branch so a runaway plan
    // can still be stopped.
    if (loop.max_cost_usd !== null && newTotalCost >= loop.max_cost_usd) {
      this.finalizeLoop(
        loop,
        "failed",
        `Exceeded cost limit: $${newTotalCost.toFixed(2)} >= $${loop.max_cost_usd.toFixed(2)}`,
        newTotalCost,
      );
      return;
    }

    // Planning iteration path — parse the plan and dispatch the first execution
    // iter. Done-condition evaluation and failure-count tracking don't apply:
    // planning produces no code, so it can't satisfy a goal or "fail" in the
    // same sense.
    if (this.isPlanningIteration(loop, currentIter)) {
      await this.handlePlanningCompletion(loop, resultSummary, newTotalCost);
      return;
    }

    // Check if task itself failed (non-zero exit)
    const task = this.db.getTask(parseInt(taskId, 10));
    const taskFailed = task?.status === "failed";

    // Track consecutive failures (only for execution iterations)
    let consecutiveFailures = loop.consecutive_failures;
    if (taskFailed) {
      consecutiveFailures += 1;
    } else {
      consecutiveFailures = 0;
    }
    this.db.updateLoop(loopId, { consecutive_failures: consecutiveFailures });

    // Check consecutive failure limit
    if (consecutiveFailures >= loop.max_consecutive_failures) {
      this.finalizeLoop(
        loop,
        "failed",
        `Too many consecutive failures (${consecutiveFailures})`,
        newTotalCost,
      );
      return;
    }

    // Evaluate done condition
    const condition = this.evaluator.parseDoneCondition(loop.done_when);

    if (condition.type === "manual") {
      // Manual → pending approval (non-terminal; loop stays "running" until
      // user decides via approveLoop/rejectLoop).
      this.db.updateLoop(loopId, { pending_approval: 1 });
      if (currentIter) {
        this.db.updateLoopIteration(currentIter.id, { done_check_passed: 0 });
      }
      this.emitLoopNotification(loop,
        `⏸ Loop ${loop.loop_id} pending approval at iter ${loop.current_iteration}/${loop.max_iterations}. Approve or reject to continue.`);
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

    // Consecutive-pass tracking. Goal: stochastic conditions (`llm_judge`,
    // flaky `command:`) shouldn't false-positive a loop into early
    // termination after a single PASS. The user opts into a higher bar with
    // `pass_threshold`; default 1 preserves "first PASS wins" behavior.
    // The counter resets on any non-PASS verdict.
    let newConsecutivePasses = loop.consecutive_passes;
    if (passed) {
      newConsecutivePasses += 1;
      this.db.updateLoop(loopId, { consecutive_passes: newConsecutivePasses });
      if (newConsecutivePasses >= loop.pass_threshold) {
        this.finalizeLoop(loop, "done", reason, newTotalCost);
        return;
      }
      // PASS but threshold not met → continue to next iter. Notify so the
      // user understands why a "PASS" iteration didn't terminate the loop.
      this.emitLoopNotification(
        loop,
        `🟢 Loop ${loop.loop_id} verdict PASS (${newConsecutivePasses}/${loop.pass_threshold}) at iter ${loop.current_iteration} — keep going to confirm.`,
      );
    } else if (loop.consecutive_passes > 0) {
      // Reset on any non-PASS so the streak must be unbroken.
      newConsecutivePasses = 0;
      this.db.updateLoop(loopId, { consecutive_passes: 0 });
    }

    // If the plan is exhausted and the done condition still hasn't passed,
    // fail explicitly rather than looping forever on phantom steps.
    if (this.isPlanExhausted(loop)) {
      this.finalizeLoop(
        loop,
        "failed",
        "Plan exhausted but done condition still not satisfied",
        newTotalCost,
      );
      return;
    }

    // Check max iterations
    if (loop.current_iteration >= loop.max_iterations) {
      this.finalizeLoop(
        loop,
        "failed",
        `Exceeded max iterations (${loop.max_iterations})`,
        newTotalCost,
      );
      return;
    }

    // Dispatch next iteration
    const feedback = this.generateFeedback(iterations);
    await this.dispatchIteration(loopId, loop.current_iteration + 1, feedback);
  }

  /**
   * Mark the loop terminal and send an end-of-loop notification. Used for
   * `done`, `failed`, and `cancelled` transitions — anywhere the loop is
   * leaving the `running` state.
   */
  private finalizeLoop(
    loop: Loop,
    status: "done" | "failed" | "cancelled",
    reason: string,
    totalCostUsd?: number,
  ): void {
    this.db.updateLoop(loop.loop_id, {
      status,
      finished_at: new Date().toISOString(),
      finish_reason: reason,
    });
    const emoji = status === "done" ? "✅" : status === "failed" ? "❌" : "🚫";
    const cost = (totalCostUsd ?? loop.total_cost_usd);
    const costStr = cost > 0 ? ` • $${cost.toFixed(2)}` : "";
    this.emitLoopNotification(
      loop,
      `${emoji} Loop ${loop.loop_id} ${status} at iter ${loop.current_iteration}/${loop.max_iterations}${costStr}: ${reason}`,
    );
  }

  /**
   * Queue a notification for a loop state change. No-op if the loop has no
   * channel/chat_id (loops started from CLI without --chat-id).
   */
  private emitLoopNotification(loop: Loop, message: string): void {
    if (!loop.channel_chat_id || !loop.current_task_id) return;
    const taskIdNum = parseInt(loop.current_task_id, 10);
    if (Number.isNaN(taskIdNum)) return;
    const channel = loop.channel ?? "telegram";
    this.db.createNotification(taskIdNum, channel, loop.channel_chat_id, message);
  }

  async cancelLoop(loopId: string): Promise<boolean> {
    const loop = this.db.getLoop(loopId);
    if (!loop || (loop.status !== "running" && loop.pending_approval !== 1)) {
      return false;
    }

    this.db.updateLoop(loopId, { pending_approval: 0 });
    this.finalizeLoop(loop, "cancelled", "Cancelled by user");
    return true;
  }

  async approveLoop(loopId: string): Promise<boolean> {
    const loop = this.db.getLoop(loopId);
    if (!loop || loop.pending_approval !== 1) {
      return false;
    }

    this.db.updateLoop(loopId, { pending_approval: 0 });
    this.finalizeLoop(loop, "done", "Approved by user");
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

    const plan = this.getPlan(loop);
    if (plan) {
      lines.push("");
      lines.push(`Plan (${plan.steps.length} steps${plan.truncated ? ", truncated" : ""}):`);
      for (const step of plan.steps) {
        lines.push(`  ${step.id}. ${step.title}`);
      }
    }

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

  // --- Plan-first helpers ---

  /** True iff the completed iteration was the planning iteration. */
  private isPlanningIteration(loop: Loop, iter: LoopIteration | undefined): boolean {
    if (!iter) return false;
    if (loop.plan_enabled !== 1) return false;
    // A planning iter is iter #1 AND the plan hasn't been stored yet. Once the
    // plan is stored, iter 1 becomes an execution iter (shouldn't happen in
    // normal flow, but guards against replays).
    return iter.iteration_num === 1 && !loop.plan;
  }

  /**
   * Parse the plan from the planning iteration's summary and dispatch the
   * first execution iteration. On parse failure, fall back to legacy mode:
   * disable plan_enabled and dispatch iter 2 as a regular execution iter.
   */
  private async handlePlanningCompletion(
    loop: Loop,
    resultSummary: string,
    totalCost: number,
  ): Promise<void> {
    const parsed = this.parsePlan(resultSummary, loop.max_iterations);

    if (!parsed) {
      // Fallback: turn plan-first off for the rest of the loop and continue.
      // Notify so the user knows why we didn't split into sub-tasks.
      this.db.updateLoop(loop.loop_id, { plan_enabled: 0 });
      this.emitLoopNotification(
        loop,
        `⚠ Loop ${loop.loop_id}: could not parse plan from iter 1 output — falling back to single-shot execution.`,
      );
      if (loop.current_iteration >= loop.max_iterations) {
        this.finalizeLoop(
          loop,
          "failed",
          "Plan parse failed and no iterations left for fallback execution",
          totalCost,
        );
        return;
      }
      await this.dispatchIteration(loop.loop_id, loop.current_iteration + 1, null);
      return;
    }

    // Store plan. Refresh loop state before emitting notifications so any
    // downstream reader sees the plan.
    this.db.updateLoop(loop.loop_id, { plan: JSON.stringify(parsed) });
    const stepsList = parsed.steps.map((s) => `${s.id}. ${s.title}`).join("\n");
    const truncatedNote = parsed.truncated
      ? ` (truncated to fit max_iterations=${loop.max_iterations})`
      : "";
    this.emitLoopNotification(
      loop,
      `📋 Loop ${loop.loop_id} plan${truncatedNote}:\n${stepsList}`,
    );

    if (loop.current_iteration >= loop.max_iterations) {
      this.finalizeLoop(
        loop,
        "failed",
        "No iterations left after planning",
        totalCost,
      );
      return;
    }

    await this.dispatchIteration(loop.loop_id, loop.current_iteration + 1, null);
  }

  /**
   * Extract and validate the plan JSON from the agent's summary. Looks for a
   * fenced ```json block first, then falls back to the first balanced JSON
   * object that contains a "steps" array. Returns null if no valid plan found.
   */
  private parsePlan(summary: string, maxIterations: number): LoopPlan | null {
    const candidates: string[] = [];

    // Prefer fenced ```json ... ``` blocks. Match non-greedy across newlines.
    const fencedRe = /```(?:json)?\s*\n([\s\S]*?)```/gi;
    let m: RegExpExecArray | null;
    while ((m = fencedRe.exec(summary)) !== null) {
      candidates.push(m[1]!);
    }

    // Fallback: raw JSON object literals containing "steps".
    if (candidates.length === 0) {
      const stepsIdx = summary.indexOf('"steps"');
      if (stepsIdx >= 0) {
        const braceStart = summary.lastIndexOf("{", stepsIdx);
        if (braceStart >= 0) {
          const braceEnd = this.findMatchingBrace(summary, braceStart);
          if (braceEnd > braceStart) {
            candidates.push(summary.slice(braceStart, braceEnd + 1));
          }
        }
      }
    }

    for (const raw of candidates) {
      try {
        const obj = JSON.parse(raw) as unknown;
        const plan = this.validatePlan(obj, maxIterations);
        if (plan) return plan;
      } catch {
        // try next candidate
      }
    }
    return null;
  }

  private findMatchingBrace(text: string, openIdx: number): number {
    let depth = 0;
    let inString = false;
    let escape = false;
    for (let i = openIdx; i < text.length; i++) {
      const ch = text[i]!;
      if (escape) { escape = false; continue; }
      if (ch === "\\") { escape = true; continue; }
      if (ch === '"') { inString = !inString; continue; }
      if (inString) continue;
      if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) return i;
      }
    }
    return -1;
  }

  private validatePlan(obj: unknown, maxIterations: number): LoopPlan | null {
    if (!obj || typeof obj !== "object") return null;
    const record = obj as Record<string, unknown>;
    const rawSteps = record["steps"];
    if (!Array.isArray(rawSteps) || rawSteps.length === 0) return null;

    const steps: LoopPlanStep[] = [];
    for (let i = 0; i < rawSteps.length; i++) {
      const s = rawSteps[i];
      if (!s || typeof s !== "object") continue;
      const sr = s as Record<string, unknown>;
      const title = typeof sr["title"] === "string" ? (sr["title"] as string).trim() : "";
      const description = typeof sr["description"] === "string"
        ? (sr["description"] as string).trim()
        : "";
      if (!title || !description) continue;
      const step: LoopPlanStep = {
        id: typeof sr["id"] === "number" ? (sr["id"] as number) : steps.length + 1,
        title,
        description,
      };
      const verification = typeof sr["verification"] === "string"
        ? (sr["verification"] as string).trim()
        : "";
      if (verification) step.verification = verification;
      steps.push(step);
    }

    if (steps.length === 0) return null;

    // Cap plan at (maxIterations - 1) — we already used iter 1 for planning.
    const maxExecSteps = Math.max(1, maxIterations - 1);
    let truncated = false;
    if (steps.length > maxExecSteps) {
      steps.length = maxExecSteps;
      truncated = true;
    }

    // Renumber for consistency regardless of what the agent produced.
    for (let i = 0; i < steps.length; i++) {
      steps[i]!.id = i + 1;
    }

    const plan: LoopPlan = { steps };
    if (truncated) plan.truncated = true;
    return plan;
  }

  private getPlan(loop: Loop): LoopPlan | null {
    if (!loop.plan) return null;
    try {
      return JSON.parse(loop.plan) as LoopPlan;
    } catch {
      return null;
    }
  }

  /** When plan-first is active and every step has been dispatched. */
  private isPlanExhausted(loop: Loop): boolean {
    if (loop.plan_enabled !== 1) return false;
    const plan = this.getPlan(loop);
    if (!plan) return false;
    // Iter 1 = planning, iters 2..plan.steps.length+1 = execution.
    return loop.current_iteration >= plan.steps.length + 1;
  }

  // --- Private dispatch helpers ---

  private async dispatchIteration(
    loopId: string,
    iterationNum: number,
    feedback: string | null,
  ): Promise<void> {
    const loop = this.db.getLoop(loopId)!;
    const agent = this.db.getAgent(loop.agent);
    if (!agent) throw new Error(`Loop ${loopId}: agent "${loop.agent}" not found`);

    const prompt = this.buildPrompt(loop, iterationNum, feedback);

    // Create task row for this iteration (uses agent's canonical session_id,
    // not a reconstructed one, so it always matches). Inherit the loop's
    // channel info so handleCompletion emits a per-iteration notification.
    const taskId = this.db.createTask({
      session_id: agent.session_id,
      prompt,
      task_type: "loop",
      channel: loop.channel ?? undefined,
      channel_chat_id: loop.channel_chat_id ?? undefined,
      user_id: loop.user_id ?? undefined,
    });

    this.db.createLoopIteration(loopId, iterationNum, prompt);
    const iterations = this.db.getLoopIterations(loopId);
    const thisIter = iterations.find((it) => it.iteration_num === iterationNum);
    if (thisIter) {
      this.db.updateLoopIteration(thisIter.id, { task_id: String(taskId) });
    }

    this.db.updateLoop(loopId, {
      current_iteration: iterationNum,
      current_task_id: String(taskId),
    });

    // Actually spawn claude. Without this, the task row sits `pending` forever
    // and the loop never makes progress — this was the original loop bug.
    if (!this.dispatcher) {
      throw new Error("LoopOrchestrator: dispatcher not configured — cannot run iterations");
    }
    const task = this.db.getTask(taskId);
    if (!task) throw new Error(`Task #${taskId} vanished after create`);
    try {
      await startTask(this.db, this.dispatcher, task, agent);
    } catch (err) {
      // startTask already marked the task failed; mark the loop too and
      // notify the channel (re-read to pick up current_task_id just set above).
      const fresh = this.db.getLoop(loopId);
      if (fresh) {
        this.finalizeLoop(fresh, "failed", `Dispatch failed: ${(err as Error).message}`);
      }
      throw err;
    }
  }

  /**
   * Build the prompt for an iteration. Three modes:
   *   1. Planning iter (iter 1, plan_enabled, no plan stored yet)
   *   2. Execution iter with plan (iter 2+, plan available)
   *   3. Legacy execution iter (plan disabled or plan missing)
   */
  private buildPrompt(loop: Loop, iterationNum: number, feedback: string | null): string {
    if (loop.plan_enabled === 1 && iterationNum === 1 && !loop.plan) {
      return this.buildPlanningPrompt(loop);
    }

    const plan = this.getPlan(loop);
    if (plan) {
      // iter 1 was planning, so exec step index = iterationNum - 2
      const stepIdx = iterationNum - 2;
      const step = plan.steps[stepIdx];
      if (step) {
        return this.buildPlanExecutionPrompt(loop, plan, step, stepIdx + 1, feedback);
      }
      // No step for this iter — plan is exhausted. This shouldn't be reached
      // (onTaskComplete catches it first), but keep a defensive legacy prompt.
    }

    return this.buildLegacyIterationPrompt(
      loop.goal, iterationNum, feedback, loop.loop_type, loop.done_when,
    );
  }

  private buildPlanningPrompt(loop: Loop): string {
    return [
      `You are planning a multi-iteration task loop.`,
      ``,
      `Goal: ${loop.goal}`,
      `Done condition: ${loop.done_when}`,
      `Available iterations for execution: ${Math.max(1, loop.max_iterations - 1)}`,
      ``,
      `Break the goal into small, independently-reportable sub-tasks. Each sub-task should fit one iteration (~5-15 min of focused work) and produce a report the user can read. Prefer 3-7 steps. Do NOT produce a single giant step that redoes the whole goal.`,
      ``,
      `IMPORTANT: This iteration is for PLANNING ONLY. Do not edit files, run commands, or implement anything. The next iteration will execute step 1.`,
      ``,
      `Output the plan as a fenced JSON block with this exact shape:`,
      ``,
      "```json",
      `{`,
      `  "steps": [`,
      `    {`,
      `      "id": 1,`,
      `      "title": "Short imperative name",`,
      `      "description": "What to do in this step",`,
      `      "verification": "How to tell this step is complete"`,
      `    }`,
      `  ]`,
      `}`,
      "```",
      ``,
      `You may include a short prose intro, but the fenced JSON block is required — the bridge parses it to drive subsequent iterations.`,
    ].join("\n");
  }

  private buildPlanExecutionPrompt(
    loop: Loop,
    plan: LoopPlan,
    step: LoopPlanStep,
    currentStepNum: number,
    feedback: string | null,
  ): string {
    const stepsList = plan.steps
      .map((s) => `${s.id === step.id ? "→" : " "} ${s.id}. ${s.title}`)
      .join("\n");

    const parts: string[] = [
      `Loop goal: ${loop.goal}`,
      ``,
      `Plan (${plan.steps.length} steps):`,
      stepsList,
      ``,
      `Current step (${currentStepNum}/${plan.steps.length}): ${step.title}`,
      step.description,
    ];

    if (step.verification) {
      parts.push(``);
      parts.push(`Verification: ${step.verification}`);
    }

    parts.push(``);
    parts.push(
      `IMPORTANT: Focus on THIS step only. Do not work ahead on later steps — the loop will run those in subsequent iterations. When done, summarize what you did and whether verification passed.`,
    );

    if (feedback) {
      parts.push(``);
      parts.push(`Previous iterations:`);
      parts.push(feedback);
    }

    return parts.join("\n");
  }

  private buildLegacyIterationPrompt(
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
