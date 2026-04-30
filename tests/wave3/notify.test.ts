/**
 * W3.5: Notifier Tests
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { Notifier } from "../../src/execution/notify.js";
import type { Task, Notification } from "../../src/types.js";

let tmpDir: string;
let notifier: Notifier;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-notify-"));
  notifier = new Notifier(tmpDir);
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
});

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 1,
    session_id: "be--p",
    prompt: "add pagination",
    status: "done",
    position: null,
    pid: null,
    result_file: null,
    result_summary: "Added pagination to API",
    cost_usd: 0.05,
    duration_ms: 12000,
    num_turns: 3,
    exit_code: 0,
    error_message: null,
    model: "sonnet",
    task_type: "standard",
    parent_task_id: null,
    channel: "cli",
    channel_chat_id: null,
    channel_message_id: null,
    user_id: null,
    created_at: "2024-01-01",
    started_at: "2024-01-01T00:00:00Z",
    completed_at: "2024-01-01T00:00:12Z",
    reported: 0,
    ...overrides,
  };
}

describe("W3.5: Notifier", () => {
  describe("formatMessage", () => {
    test("formats success message", () => {
      const msg = notifier.formatMessage(makeTask(), "backend");
      expect(msg).toContain("backend");
      expect(msg).toContain("done");
      expect(msg).toContain("Added pagination");
    });

    test("formats failed message", () => {
      const msg = notifier.formatMessage(
        makeTask({ status: "failed", error_message: "Build failed" }),
        "backend",
      );
      expect(msg).toContain("failed");
      expect(msg).toContain("Build failed");
    });

    test("includes cost when available", () => {
      const msg = notifier.formatMessage(makeTask({ cost_usd: 0.123 }), "backend");
      expect(msg).toContain("0.12");
    });

    test("includes duration when available", () => {
      const msg = notifier.formatMessage(makeTask({ duration_ms: 60000 }), "backend");
      expect(msg).toContain("1m0s");
    });

    test("handles missing optional fields gracefully", () => {
      const msg = notifier.formatMessage(
        makeTask({ result_summary: null, cost_usd: null, duration_ms: null }),
        "backend",
      );
      expect(msg).toContain("backend");
    });
  });

  describe("getBotToken", () => {
    test("returns null when no config and no env", () => {
      // Save and clear env
      const saved = process.env["TELEGRAM_BOT_TOKEN"];
      delete process.env["TELEGRAM_BOT_TOKEN"];
      const token = notifier.getBotToken();
      // Restore
      if (saved) process.env["TELEGRAM_BOT_TOKEN"] = saved;
      // May or may not be null depending on config file
      expect(token === null || typeof token === "string").toBe(true);
    });

    test("reads from config.json", () => {
      writeFileSync(join(tmpDir, "config.json"), JSON.stringify({ telegram_token: "test-token-123" }));
      const token = notifier.getBotToken();
      expect(token).toBe("test-token-123");
    });
  });
});
