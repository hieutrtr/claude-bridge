/**
 * MessageDatabase — separate SQLite for channel I/O (inbound/outbound message queues).
 *
 * Matches Python message_db.py schema and operations.
 * Uses WAL mode. Stored at CLAUDE_BRIDGE_HOME/messages.db.
 */

import { Database } from "bun:sqlite";
import type { IMessageDatabase } from "./interfaces.js";
import type { InboundMessage, OutboundMessage } from "../types.js";

function utcnow(): string {
  return new Date().toISOString().replace("T", " ").replace("Z", "");
}

export class MessageDatabase implements IMessageDatabase {
  private db: Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath, { create: true });
    this.db.exec("PRAGMA journal_mode=WAL");
    this.db.exec("PRAGMA foreign_keys=ON");
    this.initSchema();
  }

  private initSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS inbound_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL DEFAULT 'telegram',
        chat_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        username TEXT,
        message_text TEXT NOT NULL,
        message_id TEXT,
        status TEXT DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 5,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivered_at TIMESTAMP,
        acknowledged_at TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS outbound_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL DEFAULT 'telegram',
        chat_id TEXT NOT NULL,
        message_text TEXT NOT NULL,
        reply_to_message_id TEXT,
        source TEXT DEFAULT 'bot',
        status TEXT DEFAULT 'pending',
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 3,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sent_at TIMESTAMP,
        task_id INTEGER
      );

      CREATE TABLE IF NOT EXISTS poller_state (
        key TEXT PRIMARY KEY,
        value TEXT
      );

      CREATE INDEX IF NOT EXISTS idx_inbound_status ON inbound_messages(status);
      CREATE INDEX IF NOT EXISTS idx_outbound_status ON outbound_messages(status);
    `);
  }

  // ===================== Inbound Operations =====================

  createInbound(
    platform: string,
    chatId: string,
    userId: string,
    messageText: string,
    messageId?: string,
    username?: string,
  ): number {
    const result = this.db.run(
      `INSERT INTO inbound_messages (platform, chat_id, user_id, message_text, message_id, username)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [platform, chatId, userId, messageText, messageId ?? null, username ?? null],
    );
    return Number(result.lastInsertRowid);
  }

  getInbound(id: number): InboundMessage | null {
    return (this.db.query("SELECT * FROM inbound_messages WHERE id = ?").get(id) as InboundMessage | null) ?? null;
  }

  getPendingInbound(): InboundMessage[] {
    return this.db.query(
      "SELECT * FROM inbound_messages WHERE status = 'pending' ORDER BY created_at",
    ).all() as InboundMessage[];
  }

  getUnacknowledgedInbound(timeoutSeconds: number = 3): InboundMessage[] {
    return this.db.query(
      `SELECT * FROM inbound_messages
       WHERE status = 'delivered'
       AND datetime(delivered_at, '+' || ? || ' seconds') < datetime('now')
       ORDER BY created_at`,
    ).all(timeoutSeconds) as InboundMessage[];
  }

  markInboundDelivered(id: number): void {
    this.db.run(
      "UPDATE inbound_messages SET status = 'delivered', delivered_at = ? WHERE id = ?",
      [utcnow(), id],
    );
  }

  markInboundAcknowledged(id: number): void {
    this.db.run(
      "UPDATE inbound_messages SET status = 'acknowledged', acknowledged_at = ? WHERE id = ?",
      [utcnow(), id],
    );
  }

  markInboundFailed(id: number): void {
    this.db.run("UPDATE inbound_messages SET status = 'failed' WHERE id = ?", [id]);
  }

  incrementInboundRetry(id: number): void {
    this.db.run(
      "UPDATE inbound_messages SET retry_count = retry_count + 1, status = 'pending', delivered_at = NULL WHERE id = ?",
      [id],
    );
  }

  // ===================== Outbound Operations =====================

  createOutbound(
    platform: string,
    chatId: string,
    messageText: string,
    replyToMessageId?: string,
    source: string = "bot",
    taskId?: number,
  ): number {
    const result = this.db.run(
      `INSERT INTO outbound_messages (platform, chat_id, message_text, reply_to_message_id, source, task_id)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [platform, chatId, messageText, replyToMessageId ?? null, source, taskId ?? null],
    );
    return Number(result.lastInsertRowid);
  }

  hasNotificationForTask(taskId: number): boolean {
    const row = this.db.query(
      "SELECT 1 FROM outbound_messages WHERE task_id = ? LIMIT 1",
    ).get(taskId);
    return row !== null;
  }

  updatePendingOutboundForTask(taskId: number, messageText: string, source: string = "notification"): boolean {
    const result = this.db.run(
      "UPDATE outbound_messages SET message_text = ?, source = ? WHERE task_id = ? AND status IN ('pending', 'notified')",
      [messageText, source, taskId],
    );
    return result.changes > 0;
  }

  getOutbound(id: number): OutboundMessage | null {
    return (this.db.query("SELECT * FROM outbound_messages WHERE id = ?").get(id) as OutboundMessage | null) ?? null;
  }

  getPendingOutbound(): OutboundMessage[] {
    return this.db.query(
      "SELECT * FROM outbound_messages WHERE status = 'pending' ORDER BY created_at",
    ).all() as OutboundMessage[];
  }

  markOutboundSent(id: number): void {
    this.db.run(
      "UPDATE outbound_messages SET status = 'sent', sent_at = ? WHERE id = ?",
      [utcnow(), id],
    );
  }

  markOutboundFailed(id: number): void {
    this.db.run("UPDATE outbound_messages SET status = 'failed' WHERE id = ?", [id]);
  }

  incrementOutboundRetry(id: number): void {
    this.db.run(
      "UPDATE outbound_messages SET retry_count = retry_count + 1 WHERE id = ?",
      [id],
    );
  }

  cleanupOldOutbound(maxAgeHours: number = 24): void {
    this.db.run(
      `DELETE FROM outbound_messages
       WHERE status IN ('sent', 'failed')
       AND datetime(created_at, '+' || ? || ' hours') < datetime('now')`,
      [maxAgeHours],
    );
  }

  // ===================== Poller State =====================

  getState(key: string): string | null {
    const row = this.db.query("SELECT value FROM poller_state WHERE key = ?").get(key) as { value: string } | null;
    return row?.value ?? null;
  }

  setState(key: string, value: string): void {
    this.db.run(
      "INSERT OR REPLACE INTO poller_state (key, value) VALUES (?, ?)",
      [key, value],
    );
  }

  // ===================== Lifecycle =====================

  close(): void {
    this.db.close();
  }
}
