/**
 * Loop Evaluator — assesses whether a loop iteration satisfies the done condition.
 *
 * May invoke Claude to evaluate results.
 * Replaces Python's loop_evaluator.py.
 *
 * TODO: Implement in Wave 4 migration.
 */

import type { Loop, Task } from "../types.js";
import type { ILoopEvaluator } from "./interfaces.js";

export class LoopEvaluator implements ILoopEvaluator {
  async evaluate(
    loop: Loop,
    latestTask: Task,
    taskSummary: string,
  ): Promise<{ isDone: boolean; reason: string }> {
    throw new Error("Not implemented");
  }
}
