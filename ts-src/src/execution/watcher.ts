/**
 * Process Watcher — polls for dead processes as fallback for missed stop hooks.
 *
 * Replaces Python's watcher.py.
 *
 * TODO: Implement full logic in Wave 3 migration.
 */

import type { IProcessWatcher } from "./interfaces.js";

export class ProcessWatcher implements IProcessWatcher {
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(private homeDir: string) {}

  start(intervalMs: number = 30_000): void {
    throw new Error("Not implemented");
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
}
