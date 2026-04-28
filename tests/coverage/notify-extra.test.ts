/**
 * Extra coverage tests for src/execution/notify.ts
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { Notifier } from "../../src/execution/notify.js";
import type { Task } from "../../src/types.js";

let tmpDir: string;
let notifier: Notifier;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-notify-cov-"));
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

describe("notify.ts coverage", () => {
  describe("formatMessage", () => {
    test("truncates long prompt with ellipsis", () => {
      const longPrompt = "x".repeat(200);
      const msg = notifier.formatMessage(makeTask({ prompt: longPrompt }), "backend");
      expect(msg).toContain("…");
      expect(msg).not.toContain("x".repeat(200));
    });

    test("long result summary is included verbatim — converter wraps in blockquote", () => {
      const longSummary = "y".repeat(300);
      const msg = notifier.formatMessage(makeTask({ result_summary: longSummary }), "backend");
      expect(msg).toContain("y".repeat(300));
      // Markdown blockquote prefix per line.
      expect(msg).toMatch(/^> y/m);
    });

    test("includes num_turns", () => {
      const msg = notifier.formatMessage(makeTask({ num_turns: 7 }), "backend");
      expect(msg).toContain("7 turns");
    });

    test("handles short duration (< 60s)", () => {
      const msg = notifier.formatMessage(makeTask({ duration_ms: 30000 }), "backend");
      expect(msg).toContain("30s");
    });

    test("shows error for non-done status as a markdown blockquote", () => {
      const msg = notifier.formatMessage(
        makeTask({ status: "failed", error_message: "Build failed", result_summary: null }),
        "backend",
      );
      expect(msg).toContain("Build failed");
      expect(msg).toMatch(/^> Build failed/m);
      expect(msg).toContain("❌");
    });

    test("no result_summary and no error keeps body empty", () => {
      const msg = notifier.formatMessage(
        makeTask({ status: "failed", result_summary: null, error_message: null }),
        "backend",
      );
      expect(msg).not.toMatch(/^> /m);
    });

    test("includes all meta fields", () => {
      const msg = notifier.formatMessage(
        makeTask({ cost_usd: 1.23, duration_ms: 120000, num_turns: 5 }),
        "backend",
      );
      expect(msg).toContain("$1.23");
      expect(msg).toContain("2m0s");
      expect(msg).toContain("5 turns");
    });

    test("no meta when all null", () => {
      const msg = notifier.formatMessage(
        makeTask({ cost_usd: null, duration_ms: null, num_turns: null }),
        "backend",
      );
      // Meta appears as a trailing italic markdown line (`_$x · ...s · ...turns_`).
      expect(msg).not.toContain("turns_");
      expect(msg).not.toContain("$0");
    });
  });

  describe("getBotToken", () => {
    test("reads from env when no config", () => {
      const saved = process.env["TELEGRAM_BOT_TOKEN"];
      process.env["TELEGRAM_BOT_TOKEN"] = "env-token-123";
      const token = notifier.getBotToken();
      if (saved) {
        process.env["TELEGRAM_BOT_TOKEN"] = saved;
      } else {
        delete process.env["TELEGRAM_BOT_TOKEN"];
      }
      expect(token).toBe("env-token-123");
    });

    test("config takes precedence over env", () => {
      writeFileSync(join(tmpDir, "config.json"), JSON.stringify({ telegram_token: "config-token" }));
      const saved = process.env["TELEGRAM_BOT_TOKEN"];
      process.env["TELEGRAM_BOT_TOKEN"] = "env-token";
      const token = notifier.getBotToken();
      if (saved) {
        process.env["TELEGRAM_BOT_TOKEN"] = saved;
      } else {
        delete process.env["TELEGRAM_BOT_TOKEN"];
      }
      expect(token).toBe("config-token");
    });

    test("handles invalid config JSON", () => {
      writeFileSync(join(tmpDir, "config.json"), "not json");
      const saved = process.env["TELEGRAM_BOT_TOKEN"];
      delete process.env["TELEGRAM_BOT_TOKEN"];
      const token = notifier.getBotToken();
      if (saved) process.env["TELEGRAM_BOT_TOKEN"] = saved;
      expect(token).toBeNull();
    });
  });

  describe("notify", () => {
    test("returns false when no token available", async () => {
      // Clear env and config
      const saved = process.env["TELEGRAM_BOT_TOKEN"];
      delete process.env["TELEGRAM_BOT_TOKEN"];
      const result = await notifier.notify({ chat_id: "123", message: "test" });
      if (saved) process.env["TELEGRAM_BOT_TOKEN"] = saved;
      expect(result).toBe(false);
    });
  });

  describe("retryFailed", () => {
    test("is a no-op", async () => {
      await notifier.retryFailed();
      // No error = pass
    });
  });
});
