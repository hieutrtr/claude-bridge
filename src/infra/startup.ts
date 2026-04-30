/**
 * Startup Orchestrator — wires MCP server, ProcessWatcher, and notification loop.
 *
 * Single entry point for starting all background services.
 */

import { join } from "path";
import { homedir } from "os";
import { BridgeDatabase } from "../data/db.js";
import { ProcessWatcher } from "../execution/watcher.js";
import { Dispatcher } from "../execution/dispatcher.js";
import { Notifier } from "../execution/notify.js";
import { LoopOrchestrator } from "../orchestration/loop.js";
import { LoopEvaluator } from "../orchestration/evaluator.js";
import { Scheduler } from "../orchestration/scheduler.js";
import { startServer } from "../mcp/server.js";

// Watcher is the primary completion path (see watcher.ts for why the stop hook
// can't read the result). 5s keeps end-to-end completion latency low.
const WATCHER_INTERVAL_MS = 5_000;
const NOTIFICATION_INTERVAL_MS = 5_000;
const SCHEDULER_INTERVAL_MS = 60_000;

export class StartupOrchestrator {
  private watcher: ProcessWatcher | null = null;
  private scheduler: Scheduler | null = null;
  private notificationTimer: ReturnType<typeof setInterval> | null = null;
  private db: BridgeDatabase | null = null;

  constructor(private homeDir: string = process.env["CLAUDE_BRIDGE_HOME"] ?? join(homedir(), ".claude-bridge")) {}

  /** Start all background services alongside the MCP server. */
  async start(): Promise<void> {
    const dbPath = join(this.homeDir, "bridge.db");
    this.db = new BridgeDatabase(dbPath);

    // Start process watcher — dispatcher + orchestrator callback are required
    // so the watcher can parse the result file, advance goal loops, and/or
    // dequeue follow-up tasks in one shot when claude exits.
    const dispatcher = new Dispatcher(this.homeDir);
    const orchestrator = new LoopOrchestrator(
      this.homeDir, this.db, new LoopEvaluator(), dispatcher,
    );
    this.watcher = new ProcessWatcher(
      this.homeDir, this.db, dispatcher,
      (loopId, taskId, summary, cost) =>
        orchestrator.onTaskComplete(loopId, String(taskId), summary, cost),
    );
    this.watcher.start(WATCHER_INTERVAL_MS);
    process.stderr.write(`[startup] ProcessWatcher started (${WATCHER_INTERVAL_MS / 1000}s interval)\n`);

    // Start scheduler — polls `schedules` table and dispatches due rows
    // through the same startTask path as `bridge dispatch`. Without this
    // wiring, `bridge schedule-add` rows would never fire.
    this.scheduler = new Scheduler(this.homeDir, this.db, dispatcher);
    this.scheduler.start(SCHEDULER_INTERVAL_MS);
    process.stderr.write(`[startup] Scheduler started (${SCHEDULER_INTERVAL_MS / 1000}s interval)\n`);

    // Start notification processing loop
    this.startNotificationLoop();
    process.stderr.write("[startup] Notification loop started (5s interval)\n");

    // Start MCP server (blocks on stdio transport)
    await startServer();
  }

  private startNotificationLoop(): void {
    if (!this.db) return;

    const notifier = new Notifier(this.homeDir);
    const db = this.db;

    const timer = setInterval(async () => {
      try {
        const pending = db.getPendingNotifications();
        for (const notification of pending) {
          const sent = await notifier.notify({
            chat_id: notification.chat_id,
            message: notification.message,
          });
          if (sent) {
            db.markNotificationSent(notification.id);
          } else {
            db.markNotificationFailed(notification.id);
          }
        }
      } catch (err) {
        process.stderr.write(`[notify-loop] Error: ${err}\n`);
      }
    }, NOTIFICATION_INTERVAL_MS);

    // Unref so the timer doesn't keep the process alive
    if (typeof timer === "object" && "unref" in timer) {
      (timer as NodeJS.Timeout).unref();
    }
    this.notificationTimer = timer;
  }

  /** Stop all background services. */
  stop(): void {
    if (this.watcher) {
      this.watcher.stop();
      this.watcher = null;
    }
    if (this.scheduler) {
      this.scheduler.stop();
      this.scheduler = null;
    }
    if (this.notificationTimer) {
      clearInterval(this.notificationTimer);
      this.notificationTimer = null;
    }
    if (this.db) {
      this.db.close();
      this.db = null;
    }
  }
}
