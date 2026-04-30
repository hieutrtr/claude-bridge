/**
 * Tests for telegram-inbound polling retry behavior.
 *
 * Regression: a single 409 Conflict / 502 / network blip used to silently
 * stop polling forever — the MCP server stayed alive but no messages arrived,
 * forcing users to /mcp reconnect after every long-running task.
 */

import { describe, expect, mock, test, beforeAll } from "bun:test";
import { mkdtempSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";

// Track Bot lifecycle across instances created during the retry loop.
const lifecycle = {
  startCalls: 0,
  stopCalls: 0,
  catchHandlers: [] as Array<(err: Error) => void>,
  // Each call to bot.start() pulls one outcome off this queue. "ok" → resolves
  // after onStart fires (simulating a healthy then graceful stop). "fail" →
  // rejects synchronously (simulating a polling-startup error like 409).
  outcomes: [] as Array<"ok" | "fail">,
  resetForTest(): void {
    this.startCalls = 0;
    this.stopCalls = 0;
    this.outcomes = [];
    this.catchHandlers = [];
  },
};

// Mock grammy before importing telegram-inbound so the module picks up the fake.
beforeAll(() => {
  mock.module("grammy", () => {
    class FakeBot {
      private resolveStop: (() => void) | null = null;
      // grammy's Bot exposes .on/.catch/.start/.stop and a .api object — only
      // the surface used by telegram-inbound needs to be faked.
      on(_event: string, _handler: unknown): void {}
      catch(handler: (err: Error) => void): void {
        lifecycle.catchHandlers.push(handler);
      }
      api = {
        getFile: async () => ({ file_path: "x.txt", file_unique_id: "u" }),
      };
      async start(opts: { onStart?: () => void } = {}): Promise<void> {
        lifecycle.startCalls += 1;
        const outcome = lifecycle.outcomes.shift() ?? "ok";
        if (outcome === "fail") {
          throw new Error("simulated 409 conflict");
        }
        opts.onStart?.();
        // Wait for stop() to be called before resolving (mimics real grammy).
        await new Promise<void>((res) => { this.resolveStop = res; });
      }
      async stop(): Promise<void> {
        lifecycle.stopCalls += 1;
        this.resolveStop?.();
      }
    }
    return { Bot: FakeBot };
  });
});

// Import AFTER mock is registered.
const { startTelegramInbound } = await import("../../src/mcp/telegram-inbound.ts");
const { MessageDatabase } = await import("../../src/data/message-db.ts");

function makeDeps() {
  const tmp = mkdtempSync(join(tmpdir(), "tg-inbound-"));
  const messageDb = new MessageDatabase(join(tmp, "messages.db"));
  return {
    bridgeHome: tmp,
    messageDb,
    notifier: { notification: () => {} },
    allowlist: ["123"],
  };
}

describe("startTelegramInbound polling retry", () => {
  test("first start succeeds → polling runs once until stop()", async () => {
    lifecycle.resetForTest();
    lifecycle.outcomes = ["ok"];
    const deps = makeDeps();

    const handle = await startTelegramInbound({ token: "t", ...deps });
    expect(lifecycle.startCalls).toBe(1);

    await handle.stop();
    expect(lifecycle.stopCalls).toBe(1);
  });

  test("polling failure → retry loop calls start() again", async () => {
    lifecycle.resetForTest();
    // First attempt fails immediately; second attempt succeeds and stays up.
    lifecycle.outcomes = ["fail", "ok"];
    const deps = makeDeps();

    const handle = await startTelegramInbound({ token: "t", ...deps });

    // Wait long enough for the 1s backoff to elapse and the second start to fire.
    await new Promise((r) => setTimeout(r, 1500));
    expect(lifecycle.startCalls).toBeGreaterThanOrEqual(2);

    await handle.stop();
  }, 10_000);

  test("stop() during backoff sleep exits promptly without another start", async () => {
    lifecycle.resetForTest();
    // First fails — loop will sleep 1s before retrying. stop() should
    // interrupt that sleep so the loop exits without a second start.
    lifecycle.outcomes = ["fail"];
    const deps = makeDeps();

    const handle = await startTelegramInbound({ token: "t", ...deps });
    expect(lifecycle.startCalls).toBe(1);

    const t0 = Date.now();
    await handle.stop();
    const elapsed = Date.now() - t0;

    // Without interruptible sleep this would block ~1000ms. Allow a generous
    // margin for slow CI but still tighter than the backoff.
    expect(elapsed).toBeLessThan(800);
    expect(lifecycle.startCalls).toBe(1);
  }, 10_000);
});
