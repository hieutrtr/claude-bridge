import { describe, test, expect, beforeEach, afterEach, mock } from "bun:test";
import { Database } from "bun:sqlite";
import { writeFileSync, mkdirSync, rmSync, utimesSync, existsSync, readdirSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";

import {
  loadAllowlist,
  isAllowed,
  initInboundTracking,
  trackInbound,
  acknowledgeInbound,
  getInbound,
  getPendingInbound,
  pushMessage,
  downloadTelegramFile,
  safeName,
  processRetries,
  processOutbound,
  handleReply,
  cleanupInbox,
  FILE_SIZE_LIMIT,
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

// --- Get Pending ---

describe("getPendingInbound", () => {
  test("returns only pushed messages", () => {
    const db = tmpDb();
    const id1 = trackInbound(db, "123", "u1", "hieu", "msg1", "1");
    const id2 = trackInbound(db, "123", "u1", "hieu", "msg2", "2");
    acknowledgeInbound(db, id1);

    const pending = getPendingInbound(db);
    expect(pending.length).toBe(1);
    expect(pending[0].id).toBe(id2);
    db.close();
  });

  test("returns empty when all acknowledged", () => {
    const db = tmpDb();
    const id1 = trackInbound(db, "123", "u1", "hieu", "msg1", "1");
    acknowledgeInbound(db, id1);
    expect(getPendingInbound(db).length).toBe(0);
    db.close();
  });

  test("returns empty when no messages", () => {
    const db = tmpDb();
    expect(getPendingInbound(db).length).toBe(0);
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

  test("includes extraMeta in notification", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 1, "123", "456", "alice", "hello", "789", "2026-01-01T00:00:00Z", {
      image_path: "/inbox/photo.jpg",
    });
    expect(notifier.calls[0].params.meta.image_path).toBe("/inbox/photo.jpg");
  });

  test("without extraMeta still works (backward compatible)", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 1, "123", "456", "alice", "hello", "789", "2026-01-01T00:00:00Z");
    expect(notifier.calls[0].params.meta.image_path).toBeUndefined();
    // Core fields still present
    expect(notifier.calls[0].params.meta.chat_id).toBe("123");
    expect(notifier.calls[0].params.meta.user).toBe("alice");
  });

  test("extraMeta with undefined values are filtered out", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 1, "123", "456", "alice", "hello", "789", "2026-01-01T00:00:00Z", {
      image_path: undefined,
      attachment_file_id: "some-id",
    });
    const meta = notifier.calls[0].params.meta;
    expect("image_path" in meta).toBe(false);
    expect(meta.attachment_file_id).toBe("some-id");
  });
});

// --- Download Telegram File ---

describe("downloadTelegramFile", () => {
  test("saves file to inbox and returns path", async () => {
    const dir = tmpDir();
    const fileContent = new Uint8Array([0x89, 0x50, 0x4e, 0x47]); // PNG header bytes

    // Mock getFile
    const getFile = async (fileId: string) => ({
      file_path: "photos/file_42.jpg",
      file_unique_id: "abc123",
    });

    // Mock global fetch
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({
      ok: true,
      arrayBuffer: async () => fileContent.buffer,
    })) as any;

    try {
      const result = await downloadTelegramFile(getFile, "BOT_TOKEN", "file-id-1", dir);
      expect(result).toBeDefined();
      expect(result!.startsWith(dir)).toBe(true);
      expect(result!).toContain("abc123");
      expect(result!.endsWith(".jpg")).toBe(true);

      // Verify file exists and has correct content
      const { readFileSync } = await import("fs");
      const written = readFileSync(result!);
      expect(written.length).toBe(fileContent.length);
    } finally {
      globalThis.fetch = originalFetch;
      rmSync(dir, { recursive: true });
    }
  });

  test("returns undefined when getFile fails", async () => {
    const dir = tmpDir();
    const getFile = async () => { throw new Error("API error"); };

    try {
      const result = await downloadTelegramFile(getFile as any, "TOKEN", "fid", dir);
      expect(result).toBeUndefined();
    } finally {
      rmSync(dir, { recursive: true });
    }
  });

  test("returns undefined when file_path is missing", async () => {
    const dir = tmpDir();
    const getFile = async () => ({ file_path: undefined as any, file_unique_id: "abc" });

    try {
      const result = await downloadTelegramFile(getFile, "TOKEN", "fid", dir);
      expect(result).toBeUndefined();
    } finally {
      rmSync(dir, { recursive: true });
    }
  });

  test("returns undefined on HTTP error", async () => {
    const dir = tmpDir();
    const getFile = async () => ({ file_path: "photos/f.jpg", file_unique_id: "abc" });

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({ ok: false, status: 404 })) as any;

    try {
      const result = await downloadTelegramFile(getFile, "TOKEN", "fid", dir);
      expect(result).toBeUndefined();
    } finally {
      globalThis.fetch = originalFetch;
      rmSync(dir, { recursive: true });
    }
  });

  test("filename format is timestamp-uniqueId.ext", async () => {
    const dir = tmpDir();
    const getFile = async () => ({ file_path: "photos/file.png", file_unique_id: "UniqueXYZ" });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer,
    })) as any;

    try {
      const result = await downloadTelegramFile(getFile, "TOKEN", "fid", dir);
      expect(result).toBeDefined();
      const filename = result!.split("/").pop()!;
      // Format: {timestamp}-{uniqueId}.{ext}
      expect(filename).toMatch(/^\d+-UniqueXYZ\.png$/);
    } finally {
      globalThis.fetch = originalFetch;
      rmSync(dir, { recursive: true });
    }
  });

  test("uses extOverride when provided", async () => {
    const dir = tmpDir();
    const getFile = async () => ({ file_path: "photos/file.bin", file_unique_id: "abc" });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1]).buffer,
    })) as any;

    try {
      const result = await downloadTelegramFile(getFile, "TOKEN", "fid", dir, "jpg");
      expect(result).toBeDefined();
      expect(result!.endsWith(".jpg")).toBe(true);
    } finally {
      globalThis.fetch = originalFetch;
      rmSync(dir, { recursive: true });
    }
  });

  test("sanitizes file_unique_id in filename", async () => {
    const dir = tmpDir();
    const getFile = async () => ({ file_path: "photos/f.jpg", file_unique_id: "abc/../../evil" });
    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({
      ok: true,
      arrayBuffer: async () => new Uint8Array([1]).buffer,
    })) as any;

    try {
      const result = await downloadTelegramFile(getFile, "TOKEN", "fid", dir);
      expect(result).toBeDefined();
      const filename = result!.split("/").pop()!;
      // Should not contain path traversal characters
      expect(filename).not.toContain("/");
      expect(filename).not.toContain("..");
    } finally {
      globalThis.fetch = originalFetch;
      rmSync(dir, { recursive: true });
    }
  });
});

// --- safeName ---

describe("safeName", () => {
  test("strips dangerous characters", () => {
    expect(safeName("report<script>.pdf")).toBe("report_script_.pdf");
    expect(safeName("path/../../etc/passwd")).toBe("path_.._.._etc_passwd");
  });

  test("returns undefined for undefined input", () => {
    expect(safeName(undefined)).toBeUndefined();
  });

  test("returns undefined for null input", () => {
    expect(safeName(null)).toBeUndefined();
  });

  test("returns undefined for empty string", () => {
    expect(safeName("")).toBeUndefined();
  });

  test("returns undefined when only dangerous chars", () => {
    expect(safeName("/<>:*?|")).toBeUndefined();
  });

  test("leaves safe filenames unchanged", () => {
    expect(safeName("normal-file.pdf")).toBe("normal-file.pdf");
    expect(safeName("report_2024.docx")).toBe("report_2024.docx");
    expect(safeName("my file (1).txt")).toBe("my file (1).txt");
  });

  test("strips path separators", () => {
    expect(safeName("path\\to\\file.txt")).toBe("path_to_file.txt");
    expect(safeName("dir/file.txt")).toBe("dir_file.txt");
  });

  test("strips newlines and semicolons", () => {
    expect(safeName("file\nname.txt")).toBe("file_name.txt");
    expect(safeName("file\rname.txt")).toBe("file_name.txt");
    expect(safeName("file;name.txt")).toBe("file_name.txt");
  });

  test("strips square brackets", () => {
    expect(safeName("file[1].txt")).toBe("file_1_.txt");
  });
});

// --- pushMessage with document attachment meta ---

describe("pushMessage with attachment meta", () => {
  test("includes all document attachment fields", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 1, "123", "456", "alice", "report.pdf", "789", "2026-01-01T00:00:00Z", {
      attachment_kind: "document",
      attachment_file_id: "BAADBBxxxx",
      attachment_size: "1234567",
      attachment_mime: "application/pdf",
      attachment_name: "report.pdf",
    });
    const meta = notifier.calls[0].params.meta;
    expect(meta.attachment_kind).toBe("document");
    expect(meta.attachment_file_id).toBe("BAADBBxxxx");
    expect(meta.attachment_size).toBe("1234567");
    expect(meta.attachment_mime).toBe("application/pdf");
    expect(meta.attachment_name).toBe("report.pdf");
  });

  test("filters undefined attachment fields", () => {
    const notifier = mockNotifier();
    pushMessage(notifier, 1, "123", "456", "alice", "(document: file)", "789", "2026-01-01T00:00:00Z", {
      attachment_kind: "document",
      attachment_file_id: "BAADBBxxxx",
      attachment_size: undefined,
      attachment_mime: undefined,
      attachment_name: undefined,
    });
    const meta = notifier.calls[0].params.meta;
    expect(meta.attachment_kind).toBe("document");
    expect(meta.attachment_file_id).toBe("BAADBBxxxx");
    expect("attachment_size" in meta).toBe(false);
    expect("attachment_mime" in meta).toBe(false);
    expect("attachment_name" in meta).toBe(false);
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

// --- Phase 4: cleanupInbox ---

describe("cleanupInbox", () => {
  test("deletes files older than maxAgeMs", () => {
    const dir = tmpDir();
    // Create old file (mtime = 25h ago)
    const oldFile = join(dir, "old.jpg");
    writeFileSync(oldFile, "old content");
    const pastTime = new Date(Date.now() - 25 * 3600 * 1000);
    utimesSync(oldFile, pastTime, pastTime);

    // Create new file (just created)
    const newFile = join(dir, "new.jpg");
    writeFileSync(newFile, "new content");

    const deleted = cleanupInbox(dir, 24 * 3600 * 1000);

    expect(deleted).toBe(1);
    expect(existsSync(oldFile)).toBe(false);
    expect(existsSync(newFile)).toBe(true);
    rmSync(dir, { recursive: true });
  });

  test("returns 0 for non-existent directory", () => {
    const deleted = cleanupInbox("/tmp/nonexistent-inbox-test-" + Date.now());
    expect(deleted).toBe(0);
  });

  test("skips files newer than maxAgeMs", () => {
    const dir = tmpDir();
    for (let i = 0; i < 3; i++) {
      writeFileSync(join(dir, `recent-${i}.jpg`), "data");
    }
    const deleted = cleanupInbox(dir, 24 * 3600 * 1000);
    expect(deleted).toBe(0);
    expect(readdirSync(dir).length).toBe(3);
    rmSync(dir, { recursive: true });
  });

  test("returns 0 for empty directory", () => {
    const dir = tmpDir();
    const deleted = cleanupInbox(dir, 24 * 3600 * 1000);
    expect(deleted).toBe(0);
    rmSync(dir, { recursive: true });
  });

  test("deletes multiple old files at once", () => {
    const dir = tmpDir();
    for (let i = 0; i < 3; i++) {
      const f = join(dir, `old-${i}.jpg`);
      writeFileSync(f, "old");
      const pastTime = new Date(Date.now() - 48 * 3600 * 1000);
      utimesSync(f, pastTime, pastTime);
    }
    writeFileSync(join(dir, "new.jpg"), "new");

    const deleted = cleanupInbox(dir, 24 * 3600 * 1000);
    expect(deleted).toBe(3);
    expect(readdirSync(dir).length).toBe(1);
    rmSync(dir, { recursive: true });
  });
});

// --- Phase 4: FILE_SIZE_LIMIT ---

describe("FILE_SIZE_LIMIT", () => {
  test("equals 20MB (20 * 1024 * 1024)", () => {
    expect(FILE_SIZE_LIMIT).toBe(20 * 1024 * 1024);
  });
});

// --- Phase 4: downloadTelegramFile size rejection ---

describe("downloadTelegramFile with fileSizeBytes", () => {
  test("rejects file over size limit without calling getFile", async () => {
    let getFileCalled = false;
    const mockGetFile = async (_fileId: string) => {
      getFileCalled = true;
      return { file_path: "photos/test.jpg", file_unique_id: "abc123" };
    };

    const result = await downloadTelegramFile(
      mockGetFile,
      "fake-token",
      "fake-file-id",
      "/tmp/inbox-test",
      undefined,
      25 * 1024 * 1024 // 25MB — over the 20MB limit
    );

    expect(result).toBeUndefined();
    expect(getFileCalled).toBe(false);
  });

  test("allows file under size limit (proceeds to getFile)", async () => {
    let getFileCalled = false;
    const mockGetFile = async (_fileId: string) => {
      getFileCalled = true;
      return { file_path: undefined as string | undefined, file_unique_id: "abc123" };
    };

    const result = await downloadTelegramFile(
      mockGetFile,
      "fake-token",
      "fake-file-id",
      "/tmp/inbox-test",
      undefined,
      5 * 1024 * 1024 // 5MB — under limit
    );

    expect(result).toBeUndefined(); // undefined because file_path missing
    expect(getFileCalled).toBe(true); // but getFile WAS called
  });

  test("allows download when fileSizeBytes is not provided", async () => {
    let getFileCalled = false;
    const mockGetFile = async (_fileId: string) => {
      getFileCalled = true;
      return { file_path: undefined as string | undefined, file_unique_id: "abc123" };
    };

    const result = await downloadTelegramFile(
      mockGetFile,
      "fake-token",
      "fake-file-id",
      "/tmp/inbox-test"
    );

    expect(result).toBeUndefined();
    expect(getFileCalled).toBe(true);
  });

  test("file at exactly the limit is allowed", async () => {
    let getFileCalled = false;
    const mockGetFile = async (_fileId: string) => {
      getFileCalled = true;
      return { file_path: undefined as string | undefined, file_unique_id: "abc" };
    };

    await downloadTelegramFile(
      mockGetFile,
      "fake-token",
      "fake-file-id",
      "/tmp/inbox-test",
      undefined,
      FILE_SIZE_LIMIT // exactly 20MB — should be allowed
    );

    expect(getFileCalled).toBe(true);
  });
});
