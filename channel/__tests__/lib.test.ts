import { describe, test, expect, beforeEach, afterEach, mock } from "bun:test";
import { Database } from "bun:sqlite";
import { writeFileSync, mkdirSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

import {
  loadAllowlist,
  isAllowed,
  initInboundTracking,
  trackInbound,
  acknowledgeInbound,
  getInbound,
  pushMessage,
  processRetries,
  processOutbound,
  handleReply,
  type McpNotifier,
} from "../lib";

// --- Helpers ---

function tmpDb(): Database {
  const db = new Database(":memory:");
  initInboundTracking(db);
  return db;
}

function tmpDir(): string {
  const dir = join(tmpdir(), `bridge-test-${Date.now()}-${Math.random().toString(36).slice(2)}`);
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

// --- Access Control ---

describe("loadAllowlist", () => {
  test("returns users from valid file", () => {
    const dir = tmpDir();
    const path = join(dir, "access.json");
    writeFileSync(path, JSON.stringify({ allowFrom: ["123", "456"] }));
    expect(loadAllowlist(path)).toEqual(["123", "456"]);
    rmSync(dir, { recursive: true });
  });

  test("returns empty array for missing file", () => {
    expect(loadAllowlist("/nonexistent/path/access.json")).toEqual([]);
  });

  test("returns empty array for malformed JSON", () => {
    const dir = tmpDir();
    const path = join(dir, "access.json");
    writeFileSync(path, "not json {{{");
    expect(loadAllowlist(path)).toEqual([]);
    rmSync(dir, { recursive: true });
  });
});

describe("isAllowed", () => {
  test("allowed user passes", () => {
    const dir = tmpDir();
    const path = join(dir, "access.json");
    writeFileSync(path, JSON.stringify({ allowFrom: ["123"] }));
    expect(isAllowed("123", path)).toBe(true);
    rmSync(dir, { recursive: true });
  });

  test("non-allowed user blocked", () => {
    const dir = tmpDir();
    const path = join(dir, "access.json");
    writeFileSync(path, JSON.stringify({ allowFrom: ["123"] }));
    expect(isAllowed("999", path)).toBe(false);
    rmSync(dir, { recursive: true });
  });

  test("empty allowlist allows all", () => {
    const dir = tmpDir();
    const path = join(dir, "access.json");
    writeFileSync(path, JSON.stringify({ allowFrom: [] }));
    expect(isAllowed("anyone", path)).toBe(true);
    rmSync(dir, { recursive: true });
  });

  test("missing file allows all", () => {
    expect(isAllowed("anyone", "/nonexistent")).toBe(true);
  });
});

// --- Inbound Tracking ---

describe("trackInbound", () => {
  test("inserts row with correct fields", () => {
    const db = tmpDb();
    const id = trackInbound(db, "12345", "u1", "hieu", "hello bot", "msg1");
    const row = getInbound(db, id)!;
    expect(row.chat_id).toBe("12345");
    expect(row.user_id).toBe("u1");
    expect(row.username).toBe("hieu");
    expect(row.message_text).toBe("hello bot");
    expect(row.message_id).toBe("msg1");
    expect(row.status).toBe("pushed");
    expect(row.retry_count).toBe(0);
    expect(row.pushed_at).toBeTruthy();
    db.close();
  });

  test("returns incrementing ids", () => {
    const db = tmpDb();
    const id1 = trackInbound(db, "123", "u1", "hieu", "msg1", "1");
    const id2 = trackInbound(db, "123", "u1", "hieu", "msg2", "2");
    expect(id2).toBeGreaterThan(id1);
    db.close();
  });

  test("multiple messages tracked independently", () => {
    const db = tmpDb();
    trackInbound(db, "123", "u1", "hieu", "first", "1");
    trackInbound(db, "123", "u1", "hieu", "second", "2");
    trackInbound(db, "123", "u1", "hieu", "third", "3");
    const all = db.query("SELECT * FROM inbound_tracking").all();
    expect(all.length).toBe(3);
    db.close();
  });
});

describe("acknowledgeInbound", () => {
  test("sets status to acknowledged", () => {
    const db = tmpDb();
    const id = trackInbound(db, "123", "u1", "hieu", "hello", "1");
    const ok = acknowledgeInbound(db, id);
    expect(ok).toBe(true);
    const row = getInbound(db, id)!;
    expect(row.status).toBe("acknowledged");
    expect(row.acknowledged_at).toBeTruthy();
    db.close();
  });

  test("returns false for invalid id", () => {
    const db = tmpDb();
    expect(acknowledgeInbound(db, 99999)).toBe(false);
    db.close();
  });

  test("is idempotent", () => {
    const db = tmpDb();
    const id = trackInbound(db, "123", "u1", "hieu", "hello", "1");
    acknowledgeInbound(db, id);
    acknowledgeInbound(db, id); // no throw
    expect(getInbound(db, id)!.status).toBe("acknowledged");
    db.close();
  });
});

// --- Push Message ---

describe("pushMessage", () => {
  test("calls notifier with correct method", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 1, "123", "u1", "hieu", "hello", "msg1", "2026-01-01T00:00:00Z");
    expect(notifier.calls.length).toBe(1);
    expect(notifier.calls[0].method).toBe("notifications/claude/channel");
  });

  test("passes content as message text", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 1, "123", "u1", "hieu", "tell backend to fix bug", "msg1", "2026-01-01T00:00:00Z");
    expect(notifier.calls[0].params.content).toBe("tell backend to fix bug");
  });

  test("includes all meta fields", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 42, "123", "u1", "hieu", "hello", "msg99", "2026-01-01T12:00:00Z");
    const meta = notifier.calls[0].params.meta;
    expect(meta.chat_id).toBe("123");
    expect(meta.user_id).toBe("u1");
    expect(meta.user).toBe("hieu");
    expect(meta.message_id).toBe("msg99");
    expect(meta.ts).toBe("2026-01-01T12:00:00Z");
    expect(meta.tracking_id).toBe("42");
  });

  test("tracking_id is a string", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 7, "123", "u1", "hieu", "hello", "1", "2026-01-01T00:00:00Z");
    expect(typeof notifier.calls[0].params.meta.tracking_id).toBe("string");
  });
});

// --- Retry Engine ---

describe("processRetries", () => {
  test("does not re-push messages within timeout", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    trackInbound(db, "123", "u1", "hieu", "hello", "1");
    // Just inserted — pushed_at is now, timeout is 30s
    const result = processRetries(db, notifier, async () => {}, 30000, 5);
    expect(result.retried).toBe(0);
    expect(notifier.calls.length).toBe(0);
    db.close();
  });

  test("re-pushes messages past timeout", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const id = trackInbound(db, "123", "u1", "hieu", "hello", "1");
    // Set pushed_at to 60 seconds ago
    db.run("UPDATE inbound_tracking SET pushed_at = datetime('now', '-60 seconds') WHERE id = ?", [id]);

    const result = processRetries(db, notifier, async () => {}, 30000, 5);
    expect(result.retried).toBe(1);
    expect(notifier.calls.length).toBe(1);
    expect(getInbound(db, id)!.retry_count).toBe(1);
    db.close();
  });

  test("marks failed after max retries", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const apologies: string[] = [];
    const id = trackInbound(db, "123", "u1", "hieu", "hello", "1");
    db.run("UPDATE inbound_tracking SET pushed_at = datetime('now', '-60 seconds'), retry_count = 5 WHERE id = ?", [id]);

    const result = processRetries(
      db, notifier,
      async (chatId, text) => { apologies.push(text); },
      30000, 5
    );
    expect(result.failed).toBe(1);
    expect(getInbound(db, id)!.status).toBe("failed");
    expect(apologies.length).toBe(1);
    db.close();
  });

  test("does not re-push acknowledged messages", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const id = trackInbound(db, "123", "u1", "hieu", "hello", "1");
    db.run("UPDATE inbound_tracking SET pushed_at = datetime('now', '-60 seconds') WHERE id = ?", [id]);
    acknowledgeInbound(db, id);

    const result = processRetries(db, notifier, async () => {}, 30000, 5);
    expect(result.retried).toBe(0);
    expect(notifier.calls.length).toBe(0);
    db.close();
  });

  test("multiple unacked messages all re-pushed", () => {
    const db = tmpDb();
    const notifier = mockNotifier();
    const id1 = trackInbound(db, "123", "u1", "hieu", "msg1", "1");
    const id2 = trackInbound(db, "123", "u1", "hieu", "msg2", "2");
    db.run("UPDATE inbound_tracking SET pushed_at = datetime('now', '-60 seconds')");

    const result = processRetries(db, notifier, async () => {}, 30000, 5);
    expect(result.retried).toBe(2);
    expect(notifier.calls.length).toBe(2);
    db.close();
  });
});

// --- Reply ---

describe("handleReply", () => {
  test("sends short message as single chunk", async () => {
    const sent: string[] = [];
    const result = await handleReply(
      async (chatId, text) => { sent.push(text); },
      "123", "hello"
    );
    expect(result).toBe("sent");
    expect(sent.length).toBe(1);
    expect(sent[0]).toBe("hello");
  });

  test("chunks message over 4096 chars", async () => {
    const sent: string[] = [];
    const longMsg = "x".repeat(5000);
    await handleReply(
      async (chatId, text) => { sent.push(text); },
      "123", longMsg
    );
    expect(sent.length).toBe(2);
    expect(sent[0].length).toBe(4096);
    expect(sent[1].length).toBe(904);
  });

  test("exact 4096 chars not split", async () => {
    const sent: string[] = [];
    await handleReply(
      async (chatId, text) => { sent.push(text); },
      "123", "x".repeat(4096)
    );
    expect(sent.length).toBe(1);
  });

  test("non-allowed chat returns error", async () => {
    const dir = tmpDir();
    const path = join(dir, "access.json");
    writeFileSync(path, JSON.stringify({ allowFrom: ["123"] }));

    const result = await handleReply(
      async () => {}, "999", "hello", undefined, path
    );
    expect(result).toContain("Error");
    rmSync(dir, { recursive: true });
  });

  test("includes reply_to when provided", async () => {
    const opts: any[] = [];
    await handleReply(
      async (chatId, text, o) => { opts.push(o); },
      "123", "hello", "42"
    );
    expect(opts[0]).toBeTruthy();
    expect(opts[0].reply_parameters.message_id).toBe(42);
  });
});

// --- Integration: Multiple Messages ---

describe("message flow integration", () => {
  test("two messages tracked and pushed independently", () => {
    const db = tmpDb();
    const notifier = mockNotifier();

    const id1 = trackInbound(db, "123", "u1", "hieu", "first message", "1");
    pushMessage(notifier, id1, "123", "u1", "hieu", "first message", "1", "2026-01-01T00:00:00Z");

    const id2 = trackInbound(db, "123", "u1", "hieu", "second message", "2");
    pushMessage(notifier, id2, "123", "u1", "hieu", "second message", "2", "2026-01-01T00:00:01Z");

    expect(notifier.calls.length).toBe(2);
    expect(notifier.calls[0].params.content).toBe("first message");
    expect(notifier.calls[1].params.content).toBe("second message");
    expect(id1).not.toBe(id2);
    db.close();
  });

  test("second message works before first is acknowledged", () => {
    const db = tmpDb();
    const notifier = mockNotifier();

    const id1 = trackInbound(db, "123", "u1", "hieu", "first", "1");
    pushMessage(notifier, id1, "123", "u1", "hieu", "first", "1", "2026-01-01T00:00:00Z");
    // Don't acknowledge id1

    const id2 = trackInbound(db, "123", "u1", "hieu", "second", "2");
    pushMessage(notifier, id2, "123", "u1", "hieu", "second", "2", "2026-01-01T00:00:01Z");

    expect(notifier.calls.length).toBe(2);
    expect(getInbound(db, id1)!.status).toBe("pushed");
    expect(getInbound(db, id2)!.status).toBe("pushed");
    db.close();
  });

  test("5 rapid messages all tracked", () => {
    const db = tmpDb();
    const notifier = mockNotifier();

    for (let i = 0; i < 5; i++) {
      const id = trackInbound(db, "123", "u1", "hieu", `msg${i}`, String(i));
      pushMessage(notifier, id, "123", "u1", "hieu", `msg${i}`, String(i), new Date().toISOString());
    }

    expect(notifier.calls.length).toBe(5);
    const all = db.query("SELECT * FROM inbound_tracking").all();
    expect(all.length).toBe(5);
    db.close();
  });

  test("notifier throws on first push — second still works", () => {
    const db = tmpDb();
    let callCount = 0;
    const notifier: McpNotifier = {
      notification(msg) {
        callCount++;
        if (callCount === 1) throw new Error("MCP transport error");
      },
    };

    const id1 = trackInbound(db, "123", "u1", "hieu", "first", "1");
    try {
      pushMessage(notifier, id1, "123", "u1", "hieu", "first", "1", "2026-01-01T00:00:00Z");
    } catch {
      // Expected
    }

    const id2 = trackInbound(db, "123", "u1", "hieu", "second", "2");
    pushMessage(notifier, id2, "123", "u1", "hieu", "second", "2", "2026-01-01T00:00:01Z");

    // id1 failed but id2 succeeded
    expect(callCount).toBe(2);
    // Both tracked in DB regardless
    expect(getInbound(db, id1)!.status).toBe("pushed");
    expect(getInbound(db, id2)!.status).toBe("pushed");
    db.close();
  });

  test("acknowledge then retry: acknowledged messages not retried", () => {
    const db = tmpDb();
    const notifier = mockNotifier();

    const id1 = trackInbound(db, "123", "u1", "hieu", "first", "1");
    pushMessage(notifier, id1, "123", "u1", "hieu", "first", "1", "2026-01-01T00:00:00Z");
    acknowledgeInbound(db, id1);

    const id2 = trackInbound(db, "123", "u1", "hieu", "second", "2");
    pushMessage(notifier, id2, "123", "u1", "hieu", "second", "2", "2026-01-01T00:00:01Z");

    // Set both to old pushed_at
    db.run("UPDATE inbound_tracking SET pushed_at = datetime('now', '-60 seconds')");

    // Retry engine should only retry id2 (id1 is acknowledged)
    const result = processRetries(db, notifier, async () => {}, 30000, 5);
    expect(result.retried).toBe(1);
    // notifier has 2 from initial push + 1 from retry = 3
    expect(notifier.calls.length).toBe(3);
    expect(notifier.calls[2].params.content).toBe("second");
    db.close();
  });
});
