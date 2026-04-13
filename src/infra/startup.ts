/**
 * Startup Orchestrator — wires MCP server, ProcessWatcher, and notification loop.
 *
 * Single entry point for starting all background services.
 */

import { join } from "path";
import { homedir } from "os";
import { BridgeDatabase } from "../data/db.js";
import { ProcessWatcher } from "../execution/watcher.js";
import { Notifier } from "../execution/notify.js";
import { startServer } from "../mcp/server.js";

const WATCHER_INTERVAL_MS = 30_000; // 30 seconds
const NOTIFICATION_INTERVAL_MS = 5_000; // 5 seconds

export class StartupOrchestrator {
  private watcher: ProcessWatcher | null = null;
  private notificationTimer: ReturnType<typeof setInterval> | null = null;
  private db: BridgeDatabase | null = null;

  constructor(private homeDir: string = process.env["CLAUDE_BRIDGE_HOME"] ?? join(homedir(), ".claude-bridge")) {}

  /** Start all background services alongside the MCP server. */
  async start(): Promise<void> {
    const dbPath = join(this.homeDir, "bridge.db");
    this.db = new BridgeDatabase(dbPath);

    // Start process watcher
    this.watcher = new ProcessWatcher(this.homeDir, this.db);
    this.watcher.start(WATCHER_INTERVAL_MS);
    process.stderr.write("[startup] ProcessWatcher started (30s interval)\n");

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
