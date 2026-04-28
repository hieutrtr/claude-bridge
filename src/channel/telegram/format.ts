/**
 * Telegram Message Formatter — HTML formatting for Telegram Bot API.
 *
 * Telegram caps sendMessage text at 4096 UTF-16 code units. The TelegramFormatter
 * exposes primitives for building HTML and a chunker that respects top-level
 * `<pre>` / `<blockquote>` boundaries so multi-part sends stay parseable.
 */

import type { IMessageFormatter } from "../interface.js";
import { mdToTelegramHtml } from "./markdown-to-html.js";

const TAG_RE = /<(pre|blockquote)\b[^>]*>[\s\S]*?<\/\1>/g;

export class TelegramFormatter implements IMessageFormatter {
  readonly maxLength = 4096;

  formatCodeBlock(code: string, language?: string): string {
    const lang = language ? ` class="language-${this.escapeAttr(language)}"` : "";
    return `<pre><code${lang}>${this.escapeSpecialChars(code)}</code></pre>`;
  }

  formatInlineCode(text: string): string {
    return `<code>${this.escapeSpecialChars(text)}</code>`;
  }

  formatBold(text: string): string {
    return `<b>${text}</b>`;
  }

  formatItalic(text: string): string {
    return `<i>${text}</i>`;
  }

  formatBlockquote(text: string, expandable = false): string {
    return expandable
      ? `<blockquote expandable>${text}</blockquote>`
      : `<blockquote>${text}</blockquote>`;
  }

  formatLink(url: string, text: string): string {
    return `<a href="${this.escapeAttr(url)}">${text}</a>`;
  }

  formatList(items: string[]): string {
    return items.map((item) => `• ${item}`).join("\n");
  }

  escapeSpecialChars(text: string): string {
    return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  escapeAttr(text: string): string {
    return this.escapeSpecialChars(text).replace(/"/g, "&quot;");
  }

  /** Convert CommonMark to Telegram-safe HTML. */
  fromMarkdown(md: string): string {
    return mdToTelegramHtml(md);
  }

  chunkMessage(text: string, limit: number = this.maxLength): string[] {
    if (text.length <= limit) return [text];
    return chunkHtml(text, limit);
  }
}

/**
 * HTML-aware chunker: keeps top-level `<pre>`/`<blockquote>` blocks intact when
 * they fit, and re-wraps them across boundaries when they don't.
 */
export function chunkHtml(text: string, limit: number): string[] {
  if (text.length <= limit) return [text];

  // Split into atomic "blocks": top-level <pre>/<blockquote> stay whole; everything
  // else becomes a plain text segment that we can split on newlines if needed.
  const blocks: string[] = [];
  let last = 0;
  for (const m of text.matchAll(TAG_RE)) {
    if (m.index! > last) blocks.push(text.slice(last, m.index!));
    blocks.push(m[0]);
    last = m.index! + m[0].length;
  }
  if (last < text.length) blocks.push(text.slice(last));

  const chunks: string[] = [];
  let cur = "";

  const push = () => {
    if (cur.length > 0) {
      chunks.push(cur);
      cur = "";
    }
  };

  for (const block of blocks) {
    if (cur.length + block.length <= limit) {
      cur += block;
      continue;
    }
    push();
    if (block.length <= limit) {
      cur = block;
      continue;
    }
    // Block alone exceeds limit — split internally.
    if (/^<(pre|blockquote)\b/.test(block)) {
      for (const part of splitTaggedBlock(block, limit)) {
        if (part.length <= limit) chunks.push(part);
        else chunks.push(...splitPlain(part, limit));
      }
    } else {
      chunks.push(...splitPlain(block, limit));
    }
  }
  push();
  return chunks.filter((c) => c.length > 0);
}

function splitPlain(text: string, limit: number): string[] {
  const out: string[] = [];
  let remaining = text;
  while (remaining.length > limit) {
    let cut = remaining.lastIndexOf("\n\n", limit);
    if (cut <= 0) cut = remaining.lastIndexOf("\n", limit);
    if (cut <= 0) cut = remaining.lastIndexOf(" ", limit);
    if (cut <= 0) cut = limit;
    out.push(remaining.slice(0, cut).trimEnd());
    remaining = remaining.slice(cut).replace(/^\n+/, "");
  }
  if (remaining.length > 0) out.push(remaining);
  return out;
}

/**
 * Split a single oversized `<pre>...</pre>` or `<blockquote>...</blockquote>` block
 * by closing/reopening the wrapping tags (and any inner `<code>` for `<pre>`).
 */
function splitTaggedBlock(block: string, limit: number): string[] {
  const openMatch = block.match(/^<([a-z]+)([^>]*)>/);
  if (!openMatch) return [block];
  const tag = openMatch[1]!;
  const open = openMatch[0];
  const close = `</${tag}>`;
  let inner = block.slice(open.length, block.length - close.length);

  // <pre> may wrap a <code> with language class — preserve that wrapper.
  let innerOpen = "";
  let innerClose = "";
  const codeMatch = inner.match(/^<code\b[^>]*>([\s\S]*)<\/code>$/);
  if (tag === "pre" && codeMatch) {
    innerOpen = inner.slice(0, inner.indexOf(">") + 1);
    innerClose = "</code>";
    inner = codeMatch[1]!;
  }

  const wrapOpen = open + innerOpen;
  const wrapClose = innerClose + close;
  const innerLimit = limit - wrapOpen.length - wrapClose.length;
  if (innerLimit <= 0) return [block]; // pathological — caller will hard-split

  const out: string[] = [];
  let remaining = inner;
  while (remaining.length > innerLimit) {
    let cut = remaining.lastIndexOf("\n", innerLimit);
    if (cut <= 0) cut = remaining.lastIndexOf(" ", innerLimit);
    if (cut <= 0) cut = innerLimit;
    out.push(`${wrapOpen}${remaining.slice(0, cut)}${wrapClose}`);
    remaining = remaining.slice(cut).replace(/^\n+/, "");
  }
  if (remaining.length > 0) out.push(`${wrapOpen}${remaining}${wrapClose}`);
  return out;
}
