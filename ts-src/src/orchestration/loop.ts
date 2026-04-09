/**
 * Loop Orchestrator — iterative task execution with done conditions.
 *
 * State machine: running → (dispatch → evaluate → decide) → completed/failed
 * Replaces Python's loop_orchestrator.py.
 *
 * TODO: Implement in Wave 4 migration.
 */

import type { Loop } from "../types.js";
import type { ILoopOrchestrator } from "./interfaces.js";

export class LoopOrchestrator implements ILoopOrchestrator {
  constructor(private homeDir: string) {}

  async startLoop(
    agentName: string,
    goal: string,
    doneCondition: string,
    maxIterations?: number,
  ): Promise<Loop> {
    throw new Error("Not implemented");
  }

  async resumeLoop(loopId: number): Promise<void> {
    throw new Error("Not implemented");
  }

  async pauseLoop(loopId: number): Promise<void> {
    throw new Error("Not implemented");
  }

  async cancelLoop(loopId: number): Promise<void> {
    throw new Error("Not implemented");
  }

  async getLoopStatus(loopId: number): Promise<Loop | null> {
    throw new Error("Not implemented");
  }
}
