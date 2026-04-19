/**
 * Telegram inbound handler — grammy bot that pushes messages into the MCP
 * channel via `notifications/claude/channel`.
 *
 * Ported from legacy/channel/server.ts. Uses our MessageDatabase for inbound
 * tracking (matches the `inbound_messages` table in `messages.db`).
 */

import { Bot } from "grammy";
import { mkdirSync, writeFileSync, existsSync, readFileSync } from "fs";
import { join } from "path";
import type { MessageDatabase } from "../data/message-db.js";
import { buildInboundMeta, safeName } from "./channel-format.js";

/** 20MB — Telegram Bot API file download limit. */
export const FILE_SIZE_LIMIT = 20 * 1024 * 1024;

export interface McpNotifier {
  notification(msg: { method: string; params: Record<string, unknown> }): void | Promise<void>;
}

export interface StartTelegramInboundOptions {
  token: string;
  notifier: McpNotifier;
  messageDb: MessageDatabase;
  bridgeHome: string;
  /** Optional allowlist of user IDs. If omitted, config.json is used. */
  allowlist?: string[];
}

export interface InboundHandle {
  stop(): Promise<void>;
  /** Test-only: the grammy Bot instance (not typed to avoid tight coupling). */
  bot: Bot;
}

/** Load allowlist from config.json — fail-closed if no entries configured. */
function loadAllowlist(bridgeHome: string): string[] {
  const configPath = join(bridgeHome, "config.json");
  if (!existsSync(configPath)) return [];
  try {
    const data = JSON.parse(readFileSync(configPath, "utf8")) as {
      allowFrom?: (string | number)[];
      telegram_chat_id?: string | number | null;
    };
    if (data.allowFrom && data.allowFrom.length > 0) {
      return data.allowFrom.map(String);
    }
    if (data.telegram_chat_id !== undefined && data.telegram_chat_id !== null) {
      return [String(data.telegram_chat_id)];
    }
  } catch {
    /* ignore */
  }
  return [];
}

function isAllowed(userId: string, allowlist: string[]): boolean {
  if (allowlist.length === 0) return false; // fail-closed
  return allowlist.includes(userId);
}

/**
 * Download a Telegram file to {bridgeHome}/inbox/{ts}-{unique_id}.{ext}.
 * Returns the local path, or undefined on failure / size limit exceeded.
 */
async function downloadTelegramFile(
  getFile: (fileId: string) => Promise<{ file_path?: string; file_unique_id: string }>,
  token: string,
  fileId: string,
  inboxDir: string,
  extOverride?: string,
  fileSizeBytes?: number,
): Promise<string | undefined> {
  if (fileSizeBytes && fileSizeBytes > FILE_SIZE_LIMIT) {
    process.stderr.write(
      `[telegram-inbound] file too large (${(fileSizeBytes / 1024 / 1024).toFixed(1)}MB), skipping\n`,
    );
    return undefined;
  }

  try {
    const file = await getFile(fileId);
    if (!file.file_path) {
      process.stderr.write("[telegram-inbound] getFile returned no file_path\n");
      return undefined;
    }

    const url = `https://api.telegram.org/file/bot${token}/${file.file_path}`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30_000);
    try {
      const res = await fetch(url, { signal: controller.signal });
      clearTimeout(timeout);
      if (!res.ok) {
        process.stderr.write(`[telegram-inbound] download HTTP ${res.status}\n`);
        return undefined;
      }
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length > FILE_SIZE_LIMIT) return undefined;

      const ext = (extOverride ?? file.file_path.split(".").pop() ?? "bin").replace(/[^a-zA-Z0-9]/g, "");
      const uniqueId = file.file_unique_id.replace(/[^a-zA-Z0-9_-]/g, "");
      mkdirSync(inboxDir, { recursive: true });
      const localPath = join(inboxDir, `${Date.now()}-${uniqueId}.${ext}`);
      writeFileSync(localPath, buf);
      return localPath;
    } catch (err) {
      clearTimeout(timeout);
      process.stderr.write(`[telegram-inbound] download error: ${(err as Error).message}\n`);
      return undefined;
    }
  } catch (err) {
    process.stderr.write(`[telegram-inbound] getFile error: ${(err as Error).message}\n`);
    return undefined;
  }
}

/**
 * Start the grammy bot and wire inbound handlers.
 *
 * Returns a handle whose `.stop()` cleanly stops polling.
 */
export async function startTelegramInbound(
  opts: StartTelegramInboundOptions,
): Promise<InboundHandle> {
  const { token, notifier, messageDb, bridgeHome } = opts;
  const inboxDir = join(bridgeHome, "inbox");
  mkdirSync(inboxDir, { recursive: true });

  const allowlist = opts.allowlist ?? loadAllowlist(bridgeHome);

  const bot = new Bot(token);

  bot.catch((err) => {
    process.stderr.write(`[telegram-inbound] grammy error: ${err.message}\n`);
  });

  // Helper: run trackInbound + push notification.
  const pushInbound = (
    chatId: string,
    userId: string,
    username: string,
    text: string,
    messageId: string,
    ts: string,
    extra?: {
      imagePath?: string;
      attachmentKind?: string;
      attachmentFileId?: string;
      attachmentMime?: string;
      attachmentName?: string;
      attachmentSize?: string | number;
    },
  ): number => {
    const trackingId = messageDb.createInbound(
      "telegram", chatId, userId, text, messageId, username,
    );
    const meta = buildInboundMeta({
      chatId, userId, username, messageId,
      trackingId, ts,
      imagePath: extra?.imagePath,
      attachmentKind: extra?.attachmentKind,
      attachmentFileId: extra?.attachmentFileId,
      attachmentMime: extra?.attachmentMime,
      attachmentName: extra?.attachmentName,
      attachmentSize: extra?.attachmentSize,
    });
    try {
      const p = notifier.notification({
        method: "notifications/claude/channel",
        params: { content: text, meta },
      });
      if (p && typeof (p as Promise<void>).catch === "function") {
        (p as Promise<void>).catch((err) =>
          process.stderr.write(`[telegram-inbound] notification error: ${err}\n`),
        );
      }
      messageDb.markInboundDelivered(trackingId);
    } catch (err) {
      process.stderr.write(`[telegram-inbound] push error: ${(err as Error).message}\n`);
    }
    return trackingId;
  };

  bot.on("message:text", async (ctx) => {
    const chatId = String(ctx.chat.id);
    const userId = String(ctx.from.id);
    if (!isAllowed(userId, allowlist)) return;

    const username = ctx.from.username ?? userId;
    const text = ctx.message.text;
    const messageId = String(ctx.message.message_id);
    const ts = new Date(ctx.message.date * 1000).toISOString();
    try {
      pushInbound(chatId, userId, username, text, messageId, ts);
    } catch (err) {
      process.stderr.write(`[telegram-inbound] text handler: ${err}\n`);
    }
  });

  bot.on("message:photo", async (ctx) => {
    const chatId = String(ctx.chat.id);
    const userId = String(ctx.from.id);
    if (!isAllowed(userId, allowlist)) return;

    const username = ctx.from.username ?? userId;
    const caption = ctx.message.caption ?? "(photo)";
    const messageId = String(ctx.message.message_id);
    const ts = new Date(ctx.message.date * 1000).toISOString();

    try {
      const photos = ctx.message.photo;
      const best = photos[photos.length - 1];
      if (!best) return;
      const imagePath = await downloadTelegramFile(
        (fid) => ctx.api.getFile(fid),
        token, best.file_id, inboxDir, undefined, best.file_size,
      );
      pushInbound(chatId, userId, username, caption, messageId, ts, { imagePath });
    } catch (err) {
      process.stderr.write(`[telegram-inbound] photo handler: ${err}\n`);
    }
  });

  bot.on("message:document", async (ctx) => {
    const chatId = String(ctx.chat.id);
    const userId = String(ctx.from.id);
    if (!isAllowed(userId, allowlist)) return;

    const username = ctx.from.username ?? userId;
    const messageId = String(ctx.message.message_id);
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const doc = ctx.message.document;
    const name = safeName(doc.file_name);
    if (doc.file_size && doc.file_size > FILE_SIZE_LIMIT) return;

    const text = ctx.message.caption ?? `(document: ${name ?? "file"})`;
    try {
      pushInbound(chatId, userId, username, text, messageId, ts, {
        attachmentKind: "document",
        attachmentFileId: doc.file_id,
        attachmentMime: doc.mime_type,
        attachmentName: name,
        attachmentSize: doc.file_size,
      });
    } catch (err) {
      process.stderr.write(`[telegram-inbound] document handler: ${err}\n`);
    }
  });

  bot.on("message:voice", async (ctx) => {
    const chatId = String(ctx.chat.id);
    const userId = String(ctx.from.id);
    if (!isAllowed(userId, allowlist)) return;

    const username = ctx.from.username ?? userId;
    const messageId = String(ctx.message.message_id);
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const voice = ctx.message.voice;
    const text = ctx.message.caption ?? `(voice message, ${voice.duration}s)`;
    try {
      pushInbound(chatId, userId, username, text, messageId, ts, {
        attachmentKind: "voice",
        attachmentFileId: voice.file_id,
        attachmentMime: voice.mime_type ?? "audio/ogg",
        attachmentSize: voice.file_size,
      });
    } catch (err) {
      process.stderr.write(`[telegram-inbound] voice handler: ${err}\n`);
    }
  });

  bot.on("message:audio", async (ctx) => {
    const chatId = String(ctx.chat.id);
    const userId = String(ctx.from.id);
    if (!isAllowed(userId, allowlist)) return;

    const username = ctx.from.username ?? userId;
    const messageId = String(ctx.message.message_id);
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const audio = ctx.message.audio;
    const name = safeName(audio.file_name);
    const title = audio.title ?? name ?? "audio";
    const text = ctx.message.caption ?? `(audio: ${title})`;
    try {
      pushInbound(chatId, userId, username, text, messageId, ts, {
        attachmentKind: "audio",
        attachmentFileId: audio.file_id,
        attachmentMime: audio.mime_type,
        attachmentName: name,
        attachmentSize: audio.file_size,
      });
    } catch (err) {
      process.stderr.write(`[telegram-inbound] audio handler: ${err}\n`);
    }
  });

  // Start polling with drop_pending_updates so we don't replay old messages.
  // bot.start() resolves when polling stops — we fire-and-forget here and let
  // stop() await the returned promise.
  let resolveStarted: () => void = () => {};
  const started = new Promise<void>((res) => { resolveStarted = res; });

  const startPromise: Promise<void> = bot.start({
    drop_pending_updates: true,
    onStart: () => {
      process.stderr.write("[telegram-inbound] polling started\n");
      resolveStarted();
    },
  }).catch((err: Error) => {
    process.stderr.write(`[telegram-inbound] polling failed: ${err.message}\n`);
    // Unblock startTelegramInbound even on auth failure.
    resolveStarted();
  });

  // Wait for either onStart or auth failure — with a 3s timeout so a
  // missing/bad token doesn't hang the MCP server startup.
  const timeout = new Promise<void>((res) => {
    const t = setTimeout(res, 3000);
    const maybeUnref = (t as unknown as { unref?: () => void }).unref;
    if (typeof maybeUnref === "function") maybeUnref.call(t);
  });
  await Promise.race([started, timeout]);

  return {
    bot,
    stop: async () => {
      try { await bot.stop(); } catch { /* ignore */ }
      try { await startPromise; } catch { /* ignore */ }
    },
  };
}
