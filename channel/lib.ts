/**
 * Bridge Channel Library — extracted testable functions.
 *
 * All functions accept their dependencies as parameters (db, mcp, bot)
 * so they can be tested without starting the full server.
 */

import type { Server } from "@modelcontextprotocol/sdk/server/index.js";
import type { Bot } from "grammy";
import { Database } from "bun:sqlite";
import { readFileSync, mkdirSync, writeFileSync, readdirSync, statSync, unlinkSync, existsSync } from "fs";
import { execSync } from "child_process";
import { join } from "path";

/** Maximum file size in bytes (20MB — Telegram Bot API limit) */
export const FILE_SIZE_LIMIT = 20 * 1024 * 1024;

// --- Types ---

export interface InboundRow {
  id: number;
  chat_id: string;
  user_id: string;
  username: string;
  message_text: string;
  message_id: string;
  status: string;
  retry_count: number;
  pushed_at: string;
  acknowledged_at: string | null;
}

export interface OutboundRow {
  id: number;
  chat_id: string;
  message_text: string;
  reply_to_message_id: string | null;
  source: string;
  status: string;
  retry_count: number;
  max_retries: number;
  sent_at: string | null;
}

// --- Database Setup ---

export function initInboundTracking(db: Database): void {
  db.run("PRAGMA journal_mode=WAL");
  db.run(`CREATE TABLE IF NOT EXISTS inbound_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT,
    message_text TEXT NOT NULL,
    message_id TEXT,
    status TEXT DEFAULT 'pushed',
    retry_count INTEGER DEFAULT 0,
    pushed_at TEXT,
    acknowledged_at TEXT
  )`);
}

// --- Access Control ---

export function loadAllowlist(configPath: string): string[] {
  try {
    const data = JSON.parse(readFileSync(configPath, "utf8"));
    // Support both config.json format (telegram_chat_id) and legacy access.json (allowFrom)
    if (data.telegram_chat_id) {
      return [String(data.telegram_chat_id)];
    }
    return data.allowFrom ?? [];
  } catch {
    return [];
  }
}

export function isAllowed(userId: string, accessPath: string): boolean {
  const allowed = loadAllowlist(accessPath);
  if (allowed.length === 0) return true;
  return allowed.includes(userId);
}

// --- Inbound Tracking ---

export function trackInbound(
  db: Database,
  chatId: string,
  userId: string,
  username: string,
  text: string,
  messageId: string
): number {
  const stmt = db.prepare(
    "INSERT INTO inbound_tracking (chat_id, user_id, username, message_text, message_id, pushed_at) VALUES (?, ?, ?, ?, ?, datetime('now'))"
  );
  return Number(stmt.run(chatId, userId, username, text, messageId).lastInsertRowid);
}

export function acknowledgeInbound(db: Database, trackingId: number): boolean {
  const row = db.query("SELECT * FROM inbound_tracking WHERE id = ?").get(trackingId);
  if (!row) return false;
  db.run(
    "UPDATE inbound_tracking SET status = 'acknowledged', acknowledged_at = datetime('now') WHERE id = ?",
    [trackingId]
  );
  return true;
}

export function getInbound(db: Database, trackingId: number): InboundRow | null {
  return db.query("SELECT * FROM inbound_tracking WHERE id = ?").get(trackingId) as InboundRow | null;
}

export function getPendingInbound(db: Database): InboundRow[] {
  return db.query(
    "SELECT * FROM inbound_tracking WHERE status = 'pushed' ORDER BY id"
  ).all() as InboundRow[];
}

// --- Push Message ---

export interface McpNotifier {
  notification(msg: { method: string; params: Record<string, any> }): void;
}

export function pushMessage(
  notifier: McpNotifier,
  trackingId: number,
  chatId: string,
  userId: string,
  username: string,
  text: string,
  messageId: string,
  ts: string,
  extraMeta?: Record<string, string | undefined>
): void {
  const meta: Record<string, string> = {
    chat_id: chatId,
    message_id: messageId,
    user: username,
    user_id: userId,
    ts,
    tracking_id: String(trackingId),
  };

  // Merge extra meta (image_path, attachment_*, ...)
  if (extraMeta) {
    for (const [k, v] of Object.entries(extraMeta)) {
      if (v !== undefined) meta[k] = v;
    }
  }

  notifier.notification({
    method: "notifications/claude/channel",
    params: { content: text, meta },
  });
}

/**
 * Download a file from Telegram Bot API to a local directory.
 * Returns local file path on success, undefined on failure.
 *
 * @param getFile - Injected function to call Telegram getFile API (testable)
 * @param token - Bot token for constructing download URL
 * @param fileId - Telegram file_id to download
 * @param inboxDir - Directory to save downloaded file
 * @param extOverride - Override file extension (optional)
 * @param fileSizeBytes - Known file size for pre-download rejection (optional)
 */
export async function downloadTelegramFile(
  getFile: (fileId: string) => Promise<{ file_path?: string; file_unique_id: string }>,
  token: string,
  fileId: string,
  inboxDir: string,
  extOverride?: string,
  fileSizeBytes?: number
): Promise<string | undefined> {
  // Size check BEFORE download
  if (fileSizeBytes && fileSizeBytes > FILE_SIZE_LIMIT) {
    const sizeMB = (fileSizeBytes / 1024 / 1024).toFixed(1);
    process.stderr.write(
      `bridge channel: file too large (${sizeMB}MB > ${FILE_SIZE_LIMIT / 1024 / 1024}MB), skipping download\n`
    );
    return undefined;
  }

  try {
    const file = await getFile(fileId);
    if (!file.file_path) {
      process.stderr.write("bridge channel: getFile returned no file_path — file may have expired\n");
      return undefined;
    }

    const url = `https://api.telegram.org/file/bot${token}/${file.file_path}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout

    try {
      const res = await fetch(url, { signal: controller.signal });
      clearTimeout(timeoutId);

      if (!res.ok) {
        process.stderr.write(`bridge channel: file download HTTP ${res.status}\n`);
        return undefined;
      }

      const buf = Buffer.from(await res.arrayBuffer());

      // Double-check actual size after download
      if (buf.length > FILE_SIZE_LIMIT) {
        process.stderr.write(
          `bridge channel: downloaded file exceeds limit (${buf.length} bytes), discarding\n`
        );
        return undefined;
      }

      const ext = extOverride ?? file.file_path.split(".").pop() ?? "bin";
      const safeExt = ext.replace(/[^a-zA-Z0-9]/g, "");
      const safeUniqueId = file.file_unique_id.replace(/[^a-zA-Z0-9_-]/g, "");
      const filename = `${Date.now()}-${safeUniqueId}.${safeExt}`;
      const localPath = join(inboxDir, filename);

      mkdirSync(inboxDir, { recursive: true });
      writeFileSync(localPath, buf);

      process.stderr.write(`bridge channel: downloaded file to ${localPath} (${buf.length} bytes)\n`);
      return localPath;
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (err.name === "AbortError") {
        process.stderr.write("bridge channel: file download timed out after 30s\n");
      } else {
        process.stderr.write(`bridge channel: file download network error: ${err}\n`);
      }
      return undefined;
    }
  } catch (err) {
    process.stderr.write(`bridge channel: getFile API error: ${err}\n`);
    return undefined;
  }
}

/**
 * Clean up old files in INBOX_DIR.
 * Deletes files older than maxAgeMs (default 24 hours).
 * Returns number of files deleted.
 */
export function cleanupInbox(inboxDir: string, maxAgeMs: number = 24 * 60 * 60 * 1000): number {
  if (!existsSync(inboxDir)) return 0;

  const now = Date.now();
  let deleted = 0;

  try {
    const files = readdirSync(inboxDir);
    for (const file of files) {
      const filePath = join(inboxDir, file);
      try {
        const stat = statSync(filePath);
        if (!stat.isFile()) continue;

        const age = now - stat.mtimeMs;
        if (age > maxAgeMs) {
          unlinkSync(filePath);
          deleted++;
          process.stderr.write(`bridge channel: cleaned up ${file} (age: ${Math.round(age / 3600000)}h)\n`);
        }
      } catch (err) {
        // Skip files that can't be stat'd or deleted
        process.stderr.write(`bridge channel: cleanup skip ${file}: ${err}\n`);
      }
    }
  } catch (err) {
    process.stderr.write(`bridge channel: cleanup error: ${err}\n`);
  }

  return deleted;
}

// --- Filename Sanitization ---

/**
 * Sanitize filename from Telegram — strip dangerous characters.
 * Returns undefined if input is undefined/null/empty.
 */
export function safeName(name: string | undefined | null): string | undefined {
  if (!name) return undefined;
  // Strip dangerous characters: < > [ ] \r \n ; / \ : * ? " |
  const cleaned = name.replace(/[<>\[\]\r\n;/\\:*?"|]/g, "_").trim();
  // If nothing meaningful remains (empty or all underscores), return undefined
  if (!cleaned || /^_+$/.test(cleaned)) return undefined;
  return cleaned;
}

// --- Retry Engine ---

export function processRetries(
  db: Database,
  notifier: McpNotifier,
  sendApology: (chatId: string, text: string) => Promise<void>,
  timeoutMs: number,
  maxRetries: number
): { retried: number; failed: number } {
  const timeoutSec = timeoutMs / 1000;
  const unacked = db
    .query(
      `SELECT * FROM inbound_tracking
       WHERE status = 'pushed'
       AND (julianday('now') - julianday(pushed_at)) * 86400 > ?
       ORDER BY id`
    )
    .all(timeoutSec) as InboundRow[];

  let retried = 0;
  let failed = 0;

  for (const msg of unacked) {
    if (msg.retry_count >= maxRetries) {
      db.run("UPDATE inbound_tracking SET status = 'failed' WHERE id = ?", [msg.id]);
      sendApology(
        msg.chat_id,
        "Sorry, your message could not be delivered to the Bridge Bot. Please try again."
      ).catch(() => {});
      failed++;
    } else {
      db.run(
        "UPDATE inbound_tracking SET retry_count = retry_count + 1, pushed_at = datetime('now') WHERE id = ?",
        [msg.id]
      );
      pushMessage(
        notifier,
        msg.id,
        msg.chat_id,
        msg.user_id,
        msg.username,
        msg.message_text,
        msg.message_id,
        new Date().toISOString()
      );
      retried++;
    }
  }

  return { retried, failed };
}

// --- Outbound ---

export async function processOutbound(
  db: Database,
  notifier: McpNotifier,
  sendMessage: (chatId: string, text: string) => Promise<void>
): Promise<{ sent: number; failed: number }> {
  const hasTable = db
    .query("SELECT name FROM sqlite_master WHERE type='table' AND name='outbound_messages'")
    .get();
  if (!hasTable) return { sent: 0, failed: 0 };

  const pending = db
    .query("SELECT * FROM outbound_messages WHERE status = 'pending' ORDER BY created_at LIMIT 10")
    .all() as OutboundRow[];

  let sent = 0;
  let failed = 0;

  for (const msg of pending) {
    try {
      await sendMessage(msg.chat_id, msg.message_text);
      db.run(
        "UPDATE outbound_messages SET status = 'sent', sent_at = datetime('now') WHERE id = ?",
        [msg.id]
      );
      if (msg.source === "notification") {
        notifier.notification({
          method: "notifications/claude/channel",
          params: {
            content: msg.message_text,
            meta: { source: "task_completion", chat_id: msg.chat_id },
          },
        });
      }
      sent++;
    } catch {
      const retryCount = msg.retry_count + 1;
      if (retryCount >= msg.max_retries) {
        db.run(
          "UPDATE outbound_messages SET status = 'failed', retry_count = ? WHERE id = ?",
          [retryCount, msg.id]
        );
        failed++;
      } else {
        db.run(
          "UPDATE outbound_messages SET retry_count = ? WHERE id = ?",
          [retryCount, msg.id]
        );
      }
    }
  }

  return { sent, failed };
}

// --- Bridge CLI ---

export function bridgeCli(srcPath: string, command: string, args: string[] = []): string {
  const escapedArgs = args.map((a) => `"${a.replace(/"/g, '\\"')}"`).join(" ");
  // Try installed bridge-cli first, fall back to PYTHONPATH mode
  let cmd: string;
  try {
    execSync("which bridge-cli", { encoding: "utf8" });
    cmd = `bridge-cli ${command} ${escapedArgs}`;
  } catch {
    const pythonPath = process.env.PYTHON_PATH ?? "python3";
    cmd = `PYTHONPATH=${srcPath} ${pythonPath} -m claude_bridge.cli ${command} ${escapedArgs}`;
  }
  try {
    return execSync(cmd, { timeout: 30000, encoding: "utf8" }).trim();
  } catch (err: any) {
    throw new Error(err.stderr?.trim() || err.message);
  }
}

// --- Reply ---

export async function handleReply(
  sendMessage: (chatId: string, text: string, opts?: any) => Promise<void>,
  chatId: string,
  text: string,
  replyTo?: string,
  accessPath?: string
): Promise<string> {
  if (accessPath && !isAllowed(chatId, accessPath)) {
    return "Error: chat not in allowlist";
  }

  const chunks = text.length > 4096 ? text.match(/.{1,4096}/gs) ?? [text] : [text];
  for (const chunk of chunks) {
    await sendMessage(chatId, chunk, replyTo ? { reply_parameters: { message_id: Number(replyTo) } } : undefined);
  }
  return "sent";
}
