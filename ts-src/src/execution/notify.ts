/**
 * Notifier — sends task completion notifications to configured channels.
 *
 * Uses fetch() for HTTP POST to channel webhooks.
 * Replaces Python's notify.py.
 *
 * TODO: Implement full logic in Wave 3 migration.
 */

import type { Notification } from "../types.js";
import type { INotifier } from "./interfaces.js";

export class Notifier implements INotifier {
  constructor(private homeDir: string) {}

  async notify(notification: Notification): Promise<void> {
    throw new Error("Not implemented");
  }
}
