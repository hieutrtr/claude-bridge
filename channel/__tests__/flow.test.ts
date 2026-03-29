/**
 * Integration tests for the full message flow:
 * Telegram message → bot handler → track → push → acknowledge
 *
 * These tests simulate what happens when grammy delivers a message
 * to the bot.on('message:text') handler.
 */

import { describe, test, expect } from "bun:test";
import { Database } from "bun:sqlite";
import { writeFileSync, mkdirSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

import {
  initInboundTracking,
  isAllowed,
  trackInbound,
  acknowledgeInbound,
  getInbound,
  pushMessage,
  processRetries,
  type McpNotifier,
} from "../lib";

// --- Helpers ---

function tmpDb(): Database {
  const db = new Database(":memory:");
  initInboundTracking(db);
  return db;
}

function tmpDir(): string {
  const dir = join(tmpdir(), `bridge-flow-${Date.now()}-${Math.random().toString(36).slice(2)}`);
  mkdirSync(dir, { recursive: true });
  return dir;
}

function mockNotifier(): McpNotifier & { calls: any[] } {
  const calls: any[] = [];
  return {
    calls,
    notification(msg: any) {
      calls.push(msg);
    },
  };
}

// Simulate what bot.on('message:text') does in server.ts
function simulateTelegramMessage(
  db: Database,
  notifier: McpNotifier,
  accessPath: string,
  ctx: {
    chatId: string;
    userId: string;
    username: string;
    text: string;
    messageId: string;
    date: number;
  }
): number | null {
  if (!isAllowed(ctx.userId, accessPath)) {
    return null; // rejected
  }

  try {
    const ts = new Date(ctx.date * 1000).toISOString();
    const trackingId = trackInbound(db, ctx.chatId, ctx.userId, ctx.username, ctx.text, ctx.messageId);
    pushMessage(notifier, trackingId, ctx.chatId, ctx.userId, ctx.username, ctx.text, ctx.messageId, ts);
    return trackingId;
  } catch {
    return null;
  }
}

// --- Full Flow Tests ---

describe("Telegram → Bot Handler → Track → Push", () => {
  test("single message delivered successfully", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    const trackingId = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345",
      userId: "12345",
      username: "hieu",
      text: "dispatch backend fix the bug",
      messageId: "101",
      date: 1700000000,
    });

    expect(trackingId).not.toBeNull();

    // Verify tracked in DB
    const row = getInbound(db, trackingId!)!;
    expect(row.chat_id).toBe("12345");
    expect(row.message_text).toBe("dispatch backend fix the bug");
    expect(row.status).toBe("pushed");

    // Verify pushed to MCP
    expect(notifier.calls.length).toBe(1);
    expect(notifier.calls[0].params.content).toBe("dispatch backend fix the bug");
    expect(notifier.calls[0].params.meta.chat_id).toBe("12345");
    expect(notifier.calls[0].params.meta.tracking_id).toBe(String(trackingId));

    rmSync(dir, { recursive: true });
    db.close();
  });

  test("two consecutive messages both delivered", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    const id1 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "first message", messageId: "101", date: 1700000000,
    });

    const id2 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "second message", messageId: "102", date: 1700000001,
    });

    expect(id1).not.toBeNull();
    expect(id2).not.toBeNull();
    expect(id1).not.toBe(id2);

    // Both tracked
    expect(getInbound(db, id1!)!.message_text).toBe("first message");
    expect(getInbound(db, id2!)!.message_text).toBe("second message");

    // Both pushed
    expect(notifier.calls.length).toBe(2);
    expect(notifier.calls[0].params.content).toBe("first message");
    expect(notifier.calls[1].params.content).toBe("second message");

    rmSync(dir, { recursive: true });
    db.close();
  });

  test("non-allowed user rejected", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    const result = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "99999", userId: "99999", username: "hacker",
      text: "hello", messageId: "1", date: 1700000000,
    });

    expect(result).toBeNull();
    expect(notifier.calls.length).toBe(0);

    rmSync(dir, { recursive: true });
    db.close();
  });

  test("allowed user after rejected user still works", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    // Rejected
    simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "99999", userId: "99999", username: "hacker",
      text: "bad", messageId: "1", date: 1700000000,
    });

    // Allowed
    const id = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "good", messageId: "2", date: 1700000001,
    });

    expect(id).not.toBeNull();
    expect(notifier.calls.length).toBe(1);
    expect(notifier.calls[0].params.content).toBe("good");

    rmSync(dir, { recursive: true });
    db.close();
  });
});

describe("Full lifecycle: send → push → acknowledge → next message", () => {
  test("message 1 acknowledged, message 2 arrives and works", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    // Message 1
    const id1 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "/status", messageId: "101", date: 1700000000,
    })!;

    // Claude processes and acknowledges
    acknowledgeInbound(db, id1);
    expect(getInbound(db, id1)!.status).toBe("acknowledged");

    // Message 2
    const id2 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "/dispatch backend fix bug", messageId: "102", date: 1700000010,
    })!;

    // Both pushed
    expect(notifier.calls.length).toBe(2);
    // Message 2 is independent
    expect(getInbound(db, id2)!.status).toBe("pushed");
    expect(getInbound(db, id2)!.message_text).toBe("/dispatch backend fix bug");

    rmSync(dir, { recursive: true });
    db.close();
  });

  test("message 1 NOT acknowledged, retry fires, message 2 still works", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    // Message 1 — not acknowledged
    const id1 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "first", messageId: "101", date: 1700000000,
    })!;

    // Simulate time passing — set pushed_at to 60s ago
    db.run("UPDATE inbound_tracking SET pushed_at = datetime('now', '-60 seconds') WHERE id = ?", [id1]);

    // Retry engine fires
    processRetries(db, notifier, async () => {}, 30000, 5);

    // Message 1 was retried (pushed again)
    expect(getInbound(db, id1)!.retry_count).toBe(1);

    // Message 2 arrives
    const id2 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "second", messageId: "102", date: 1700000070,
    })!;

    // notifier: initial push(1) + retry(1) + initial push(2) = 3
    expect(notifier.calls.length).toBe(3);
    expect(notifier.calls[2].params.content).toBe("second");
    expect(getInbound(db, id2)!.status).toBe("pushed");

    rmSync(dir, { recursive: true });
    db.close();
  });

  test("10 rapid messages all delivered", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    const ids: number[] = [];
    for (let i = 0; i < 10; i++) {
      const id = simulateTelegramMessage(db, notifier, accessPath, {
        chatId: "12345", userId: "12345", username: "hieu",
        text: `message ${i}`, messageId: String(100 + i), date: 1700000000 + i,
      })!;
      ids.push(id);
    }

    // All 10 tracked
    expect(ids.length).toBe(10);
    expect(new Set(ids).size).toBe(10); // all unique

    // All 10 pushed
    expect(notifier.calls.length).toBe(10);
    for (let i = 0; i < 10; i++) {
      expect(notifier.calls[i].params.content).toBe(`message ${i}`);
    }

    // All in DB
    const all = db.query("SELECT * FROM inbound_tracking").all();
    expect(all.length).toBe(10);

    rmSync(dir, { recursive: true });
    db.close();
  });

  test("push error on message 1 does not prevent message 2", () => {
    const db = tmpDb();
    let callCount = 0;
    const notifier: McpNotifier & { calls: any[] } = {
      calls: [],
      notification(msg: any) {
        callCount++;
        this.calls.push(msg);
        if (callCount === 1) throw new Error("transport error");
      },
    };
    const dir = tmpDir();
    const accessPath = join(dir, "access.json");
    writeFileSync(accessPath, JSON.stringify({ allowFrom: ["12345"] }));

    // Message 1 — push throws
    const id1 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "first", messageId: "101", date: 1700000000,
    });
    // Returns null because the try/catch in simulateTelegramMessage catches it
    // But in the real server.ts, the try/catch around pushMessage prevents crash

    // Message 2 — should still work
    const id2 = simulateTelegramMessage(db, notifier, accessPath, {
      chatId: "12345", userId: "12345", username: "hieu",
      text: "second", messageId: "102", date: 1700000001,
    });

    // At least message 2 should be tracked (id1 may or may not depending on where error hits)
    expect(id2).not.toBeNull();
    if (id2) {
      expect(getInbound(db, id2)!.message_text).toBe("second");
    }

    rmSync(dir, { recursive: true });
    db.close();
  });
});
