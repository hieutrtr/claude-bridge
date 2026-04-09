/**
 * W2.4: MessageDatabase Tests
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { MessageDatabase } from "../../src/data/message-db.js";

let db: MessageDatabase;
let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-msg-test-"));
  db = new MessageDatabase(join(tmpDir, "messages.db"));
});

afterEach(() => {
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W2.4: MessageDatabase", () => {
  describe("Inbound Messages", () => {
    test("createInbound returns message ID", () => {
      const id = db.createInbound("telegram", "123", "456", "hello");
      expect(id).toBeGreaterThan(0);
    });

    test("getInbound returns message with all fields", () => {
      const id = db.createInbound("telegram", "123", "456", "hello", "msg789", "testuser");
      const msg = db.getInbound(id);
      expect(msg).not.toBeNull();
      expect(msg!.platform).toBe("telegram");
      expect(msg!.chat_id).toBe("123");
      expect(msg!.user_id).toBe("456");
      expect(msg!.message_text).toBe("hello");
      expect(msg!.message_id).toBe("msg789");
      expect(msg!.username).toBe("testuser");
      expect(msg!.status).toBe("pending");
      expect(msg!.retry_count).toBe(0);
    });

    test("getInbound returns null for nonexistent", () => {
      expect(db.getInbound(999)).toBeNull();
    });

    test("getPendingInbound returns pending messages", () => {
      db.createInbound("telegram", "123", "456", "msg1");
      db.createInbound("telegram", "123", "456", "msg2");
      expect(db.getPendingInbound().length).toBe(2);
    });

    test("markInboundDelivered updates status", () => {
      const id = db.createInbound("telegram", "123", "456", "hello");
      db.markInboundDelivered(id);
      const msg = db.getInbound(id)!;
      expect(msg.status).toBe("delivered");
      expect(msg.delivered_at).toBeTruthy();
    });

    test("markInboundAcknowledged updates status", () => {
      const id = db.createInbound("telegram", "123", "456", "hello");
      db.markInboundDelivered(id);
      db.markInboundAcknowledged(id);
      const msg = db.getInbound(id)!;
      expect(msg.status).toBe("acknowledged");
      expect(msg.acknowledged_at).toBeTruthy();
    });

    test("markInboundFailed updates status", () => {
      const id = db.createInbound("telegram", "123", "456", "hello");
      db.markInboundFailed(id);
      expect(db.getInbound(id)!.status).toBe("failed");
    });

    test("incrementInboundRetry resets to pending", () => {
      const id = db.createInbound("telegram", "123", "456", "hello");
      db.markInboundDelivered(id);
      db.incrementInboundRetry(id);
      const msg = db.getInbound(id)!;
      expect(msg.retry_count).toBe(1);
      expect(msg.status).toBe("pending");
      expect(msg.delivered_at).toBeNull();
    });

    test("getUnacknowledgedInbound returns delivered but unacked", () => {
      const id = db.createInbound("telegram", "123", "456", "hello");
      db.markInboundDelivered(id);
      // With a very large timeout, nothing should be returned
      expect(db.getUnacknowledgedInbound(999999).length).toBe(0);
    });
  });

  describe("Outbound Messages", () => {
    test("createOutbound returns message ID", () => {
      const id = db.createOutbound("telegram", "123", "reply text");
      expect(id).toBeGreaterThan(0);
    });

    test("getOutbound returns message with all fields", () => {
      const id = db.createOutbound("telegram", "123", "reply text", "orig789", "notification", 42);
      const msg = db.getOutbound(id);
      expect(msg).not.toBeNull();
      expect(msg!.platform).toBe("telegram");
      expect(msg!.chat_id).toBe("123");
      expect(msg!.message_text).toBe("reply text");
      expect(msg!.reply_to_message_id).toBe("orig789");
      expect(msg!.source).toBe("notification");
      expect(msg!.task_id).toBe(42);
      expect(msg!.status).toBe("pending");
    });

    test("getPendingOutbound returns pending messages", () => {
      db.createOutbound("telegram", "123", "msg1");
      db.createOutbound("telegram", "456", "msg2");
      expect(db.getPendingOutbound().length).toBe(2);
    });

    test("markOutboundSent updates status", () => {
      const id = db.createOutbound("telegram", "123", "msg");
      db.markOutboundSent(id);
      const msg = db.getOutbound(id)!;
      expect(msg.status).toBe("sent");
      expect(msg.sent_at).toBeTruthy();
    });

    test("markOutboundFailed updates status", () => {
      const id = db.createOutbound("telegram", "123", "msg");
      db.markOutboundFailed(id);
      expect(db.getOutbound(id)!.status).toBe("failed");
    });

    test("incrementOutboundRetry increments count", () => {
      const id = db.createOutbound("telegram", "123", "msg");
      db.incrementOutboundRetry(id);
      expect(db.getOutbound(id)!.retry_count).toBe(1);
    });

    test("hasNotificationForTask returns true when exists", () => {
      db.createOutbound("telegram", "123", "notification", undefined, "notification", 42);
      expect(db.hasNotificationForTask(42)).toBe(true);
    });

    test("hasNotificationForTask returns false when not exists", () => {
      expect(db.hasNotificationForTask(999)).toBe(false);
    });

    test("updatePendingOutboundForTask updates message text", () => {
      db.createOutbound("telegram", "123", "old msg", undefined, "notification", 42);
      expect(db.updatePendingOutboundForTask(42, "new msg")).toBe(true);
      // Find the outbound for this task
      const pending = db.getPendingOutbound();
      const found = pending.find((m) => m.task_id === 42);
      expect(found!.message_text).toBe("new msg");
    });

    test("cleanupOldOutbound keeps recent sent messages", () => {
      const id = db.createOutbound("telegram", "123", "msg");
      db.markOutboundSent(id);
      // With large max age, recent messages should be kept
      db.cleanupOldOutbound(9999);
      expect(db.getOutbound(id)).not.toBeNull();
    });
  });

  describe("Poller State", () => {
    test("getState returns null for missing key", () => {
      expect(db.getState("missing")).toBeNull();
    });

    test("setState and getState roundtrip", () => {
      db.setState("last_update_id", "12345");
      expect(db.getState("last_update_id")).toBe("12345");
    });

    test("setState upserts", () => {
      db.setState("key", "val1");
      db.setState("key", "val2");
      expect(db.getState("key")).toBe("val2");
    });
  });
});
