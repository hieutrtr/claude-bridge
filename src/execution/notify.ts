/**
 * Notifier — sends task completion notifications to configured channels.
 *
 * Formats messages and delivers via Telegram Bot API.
 * Matches Python notify.py behavior.
 */

import { existsSync, readFileSync } from "fs";
import { join } from "path";
import type { Task, Notification } from "../types.js";
import type { INotifier } from "./interfaces.js";

export class Notifier implements INotifier {
  constructor(private homeDir: string) {}

  formatMessage(task: Task, agentName: string): string {
    const status = task.status === "done" ? "✅ done" : `❌ ${task.status}`;
    const parts: string[] = [`[${agentName}] ${status}`];

    if (task.prompt) {
      const shortPrompt = task.prompt.length > 80 ? task.prompt.slice(0, 80) + "..." : task.prompt;
      parts.push(`Task: ${shortPrompt}`);
    }

    if (task.status === "done" && task.result_summary) {
      const shortSummary = task.result_summary.length > 200
        ? task.result_summary.slice(0, 200) + "..."
        : task.result_summary;
      parts.push(`Result: ${shortSummary}`);
    }

    if (task.status !== "done" && task.error_message) {
      parts.push(`Error: ${task.error_message}`);
    }

    const meta: string[] = [];
    if (task.cost_usd !== null) {
      meta.push(`$${task.cost_usd.toFixed(2)}`);
    }
    if (task.duration_ms !== null) {
      const secs = Math.round(task.duration_ms / 1000);
      if (secs >= 60) {
        meta.push(`${Math.floor(secs / 60)}m${secs % 60}s`);
      } else {
        meta.push(`${secs}s`);
      }
    }
    if (task.num_turns !== null) {
      meta.push(`${task.num_turns} turns`);
    }
    if (meta.length > 0) {
      parts.push(meta.join(" | "));
    }

    return parts.join("\n");
  }

  getBotToken(): string | null {
    // Check config.json first
    const configPath = join(this.homeDir, "config.json");
    if (existsSync(configPath)) {
      try {
        const config = JSON.parse(readFileSync(configPath, "utf-8")) as Record<string, unknown>;
        if (config["telegram_token"]) {
          return config["telegram_token"] as string;
        }
      } catch { /* ignore */ }
    }
    // Fall back to env
    return process.env["TELEGRAM_BOT_TOKEN"] ?? null;
  }

  async notify(notification: Pick<Notification, "chat_id" | "message">): Promise<boolean> {
    const token = this.getBotToken();
    if (!token) return false;

    try {
      const resp = await fetch(
        `https://api.telegram.org/bot${token}/sendMessage`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: notification.chat_id,
            text: notification.message,
            parse_mode: "HTML",
          }),
        },
      );
      return resp.ok;
    } catch {
      return false;
    }
  }

  async retryFailed(): Promise<void> {
    // Will be implemented when integrated with DB in later waves
  }
}
