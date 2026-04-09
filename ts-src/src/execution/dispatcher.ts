/**
 * Dispatcher — spawns Claude Code processes for tasks.
 *
 * Uses Bun.spawn() with detached: true for process isolation.
 * Replaces Python's dispatcher.py.
 *
 * TODO: Implement full logic in Wave 3 migration.
 */

import type { Task } from "../types.js";
import type { IDispatcher, DispatchOptions } from "./interfaces.js";

export class Dispatcher implements IDispatcher {
  constructor(private homeDir: string) {}

  async dispatch(task: Task, options?: DispatchOptions): Promise<number> {
    throw new Error("Not implemented");
  }

  async cancel(task: Task): Promise<void> {
    throw new Error("Not implemented");
  }

  isRunning(pid: number): boolean {
    try {
      process.kill(pid, 0);
      return true;
    } catch {
      return false;
    }
  }
}
