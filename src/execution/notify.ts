/**
 * Notifier — sends task completion notifications to Telegram.
 *
 * Output is rendered as Telegram HTML so Markdown that Claude emits in
 * `result_summary` (e.g. `**bold**`, fenced code, `## headings`) renders
 * properly instead of leaking literal markup.
 */

import { existsSync, readFileSync } from "fs";
import { join } from "path";
import type { Task, Notification } from "../types.js";
import type { INotifier } from "./interfaces.js";
import { TelegramFormatter } from "../channel/telegram/format.js";
import { mdToTelegramHtml } from "../channel/telegram/markdown-to-html.js";

// TelegramFormatter is used internally for HTML-aware chunking via splitMessage().

// Telegram caps sendMessage at 4096 UTF-16 code units. Stay under to leave room
// for the `(i/n)` chunk header and emoji surrogate pairs.
const TELEGRAM_CHUNK_LIMIT = 3900;

export class Notifier implements INotifier {
  constructor(private homeDir: string) {}

  /**
   * Compose a task-completion message in Markdown. `notify()` converts to HTML
   * before sending, so this lives in the same Markdown vocabulary as every
   * other Notifier caller (bridge_reply, on-complete summary, loop status).
   */
  formatMessage(task: Task, agentName: string): string {
    const ok = task.status === "done";
    const icon = ok ? "✅" : "❌";
    const statusLabel = ok ? "done" : task.status;

    const headerParts: string[] = [`${icon} **${agentName}**`];
    headerParts.push(`_${statusLabel}_`);
    if (task.prompt) {
      const shortPrompt = task.prompt.length > 120
        ? task.prompt.slice(0, 120) + "…"
        : task.prompt;
      headerParts.push("`" + shortPrompt.replace(/`/g, "'") + "`");
    }

    const parts: string[] = [headerParts.join(" · ")];

    if (ok && task.result_summary) {
      // Quote each line so the converter wraps the body in <blockquote>.
      const quoted = task.result_summary
        .split("\n")
        .map((l) => `> ${l}`)
        .join("\n");
      parts.push("", quoted);
    }

    if (!ok && task.error_message) {
      parts.push("", `> ${task.error_message}`);
    }

    const meta: string[] = [];
    if (task.cost_usd !== null) meta.push(`$${task.cost_usd.toFixed(2)}`);
    if (task.duration_ms !== null) {
      const secs = Math.round(task.duration_ms / 1000);
      meta.push(secs >= 60 ? `${Math.floor(secs / 60)}m${secs % 60}s` : `${secs}s`);
    }
    if (task.num_turns !== null) meta.push(`${task.num_turns} turns`);
    if (meta.length > 0) parts.push("", `_${meta.join(" · ")}_`);

    return parts.join("\n");
  }

  getBotToken(): string | null {
    const configPath = join(this.homeDir, "config.json");
    if (existsSync(configPath)) {
      try {
        const config = JSON.parse(readFileSync(configPath, "utf-8")) as Record<string, unknown>;
        if (config["telegram_token"]) {
          return config["telegram_token"] as string;
        }
      } catch { /* ignore */ }
    }
    return process.env["TELEGRAM_BOT_TOKEN"] ?? null;
  }

  /**
   * Split a message into chunks no larger than `limit` UTF-16 code units.
   * HTML-aware: keeps `<pre>` / `<blockquote>` blocks intact and re-wraps them
   * across boundaries when an oversized block must be split.
   */
  static splitMessage(text: string, limit: number = TELEGRAM_CHUNK_LIMIT): string[] {
    if (text.length <= limit) return [text];
    return new TelegramFormatter().chunkMessage(text, limit);
  }

  async notify(notification: Pick<Notification, "chat_id" | "message">): Promise<boolean> {
    const token = this.getBotToken();
    if (!token) return false;

    // All callers (bridge_reply, on-complete summary, loop status) send Markdown.
    // Convert once here so `**bold**` / fenced code / lists render properly under
    // parse_mode: HTML instead of leaking literal markup.
    const html = mdToTelegramHtml(notification.message);
    const chunks = Notifier.splitMessage(html);
    const total = chunks.length;

    for (let i = 0; i < total; i++) {
      const header = total > 1 ? `<i>(${i + 1}/${total})</i>\n` : "";
      const text = `${header}${chunks[i]}`;
      const ok = await this.sendOne(token, notification.chat_id, text, i + 1, total);
      if (!ok) return false;
    }
    return true;
  }

  private async sendOne(
    token: string,
    chatId: string | number,
    text: string,
    part: number,
    total: number,
  ): Promise<boolean> {
    // Try HTML first; fall back to plain text if Telegram rejects entity parsing.
    const html = await this.postMessage(token, chatId, text, "HTML");
    if (html.ok) return true;

    if (html.parseError) {
      process.stderr.write(
        `[notify] HTML parse rejected by Telegram, falling back to plain text. ` +
        `chat=${chatId} part=${part}/${total} desc="${html.desc.slice(0, 200)}"\n`,
      );
      const plain = await this.postMessage(token, chatId, stripHtml(text), undefined);
      if (plain.ok) return true;
      this.logFailure(chatId, part, total, plain, text.length);
      return false;
    }

    this.logFailure(chatId, part, total, html, text.length);
    return false;
  }

  private async postMessage(
    token: string,
    chatId: string | number,
    text: string,
    parseMode: "HTML" | undefined,
  ): Promise<PostResult> {
    try {
      const body: Record<string, unknown> = {
        chat_id: chatId,
        text,
        disable_web_page_preview: true,
      };
      if (parseMode) body["parse_mode"] = parseMode;

      const resp = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const raw = await resp.text().catch(() => "");
      let json: { ok?: boolean; description?: string; error_code?: number } = {};
      try { json = JSON.parse(raw); } catch { /* non-JSON */ }
      const desc = json.description ?? raw;
      const httpOk = resp.ok && json.ok === true;
      return {
        ok: httpOk,
        status: resp.status,
        code: json.error_code,
        desc,
        parseError:
          !httpOk && /can't parse|can not parse|unsupported start tag|unexpected/i.test(desc),
      };
    } catch (err) {
      return {
        ok: false,
        status: 0,
        code: undefined,
        desc: err instanceof Error ? err.message : String(err),
        parseError: false,
      };
    }
  }

  private logFailure(
    chatId: string | number,
    part: number,
    total: number,
    res: PostResult,
    len: number,
  ): void {
    process.stderr.write(
      `[notify] Telegram http=${res.status} code=${res.code ?? "?"} ` +
      `chat=${chatId} part=${part}/${total} len=${len}: ${res.desc.slice(0, 300)}\n`,
    );
  }

  async retryFailed(): Promise<void> {
    // Will be implemented when integrated with DB in later waves
  }
}

interface PostResult {
  ok: boolean;
  status: number;
  code: number | undefined;
  desc: string;
  parseError: boolean;
}

/** Best-effort HTML stripper for the plain-text fallback path. */
function stripHtml(s: string): string {
  return s
    .replace(/<\/?(?:b|i|u|s|code|pre|blockquote|tg-spoiler)(?:\s[^>]*)?>/gi, "")
    .replace(/<a\s+[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi, "$2 ($1)")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&");
}
