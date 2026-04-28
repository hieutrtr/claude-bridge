/**
 * Markdown → Telegram HTML converter.
 *
 * Telegram's HTML parse_mode supports a small tag subset (b/i/u/s/code/pre/a/blockquote/tg-spoiler).
 * Claude Code emits CommonMark; rendering it raw leaves users seeing literal `**bold**`.
 *
 * Conversion order matters:
 *   1. Extract fenced + inline code so their content isn't re-parsed.
 *   2. Walk lines for block-level constructs (heading, list, blockquote, hr) — these use
 *      `# > -` markers that would be mangled by HTML escaping.
 *   3. HTML-escape leaf text, then apply inline transforms (bold/italic/link/strike).
 *   4. Restore code placeholders (already pre-escaped).
 */

const FENCE_RE = /```(\w+)?\r?\n?([\s\S]*?)```/g;
const INLINE_CODE_RE = /`([^`\n]+)`/g;
const FENCE_PLACEHOLDER = /\u0000FENCE(\d+)\u0000/g;
const INLINE_PLACEHOLDER = /\u0000INLINE(\d+)\u0000/g;

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function escapeAttr(s: string): string {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

function transformInline(s: string): string {
  // Images first (so the leading `!` isn't swallowed by the link rule).
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_, alt) =>
    alt ? `[image: ${alt}]` : "[image]",
  );
  // Links — text may contain other inline markup, processed in a later pass below.
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_, text, url) =>
    `<a href="${escapeAttr(url)}">${text}</a>`,
  );
  // Bold (** or __) — must precede italic so a single * inside ** isn't matched first.
  s = s.replace(/\*\*([^*\n][^*\n]*?)\*\*/g, "<b>$1</b>");
  s = s.replace(/__([^_\n][^_\n]*?)__/g, "<b>$1</b>");
  // Italic (single * / _) — guard with non-word lookarounds so snake_case stays intact.
  s = s.replace(/(?<![*\w])\*([^*\n]+?)\*(?![*\w])/g, "<i>$1</i>");
  s = s.replace(/(?<![_\w])_([^_\n]+?)_(?![_\w])/g, "<i>$1</i>");
  s = s.replace(/~~([^~\n]+?)~~/g, "<s>$1</s>");
  return s;
}

export function mdToTelegramHtml(md: string): string {
  if (!md) return "";

  const codeBlocks: string[] = [];
  const inlineCodes: string[] = [];

  let s = md.replace(FENCE_RE, (_match, lang: string | undefined, code: string) => {
    const trimmed = code.replace(/\n$/, "");
    const langClass = lang ? ` class="language-${escapeAttr(lang)}"` : "";
    codeBlocks.push(`<pre><code${langClass}>${escapeHtml(trimmed)}</code></pre>`);
    return `\u0000FENCE${codeBlocks.length - 1}\u0000`;
  });

  s = s.replace(INLINE_CODE_RE, (_match, code: string) => {
    inlineCodes.push(`<code>${escapeHtml(code)}</code>`);
    return `\u0000INLINE${inlineCodes.length - 1}\u0000`;
  });

  const lines = s.split("\n");
  const out: string[] = [];
  let quoteBuf: string[] = [];

  const flushQuote = () => {
    if (quoteBuf.length > 0) {
      out.push(`<blockquote>${quoteBuf.join("\n")}</blockquote>`);
      quoteBuf = [];
    }
  };

  const renderInlineText = (raw: string): string => transformInline(escapeHtml(raw));

  for (const rawLine of lines) {
    const heading = rawLine.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      flushQuote();
      out.push(`<b>${renderInlineText(heading[2]!)}</b>`);
      continue;
    }
    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(rawLine)) {
      flushQuote();
      out.push("———");
      continue;
    }
    const quote = rawLine.match(/^>\s?(.*)$/);
    if (quote) {
      quoteBuf.push(renderInlineText(quote[1]!));
      continue;
    }
    flushQuote();
    const ul = rawLine.match(/^(\s*)[-*+]\s+(.+)$/);
    if (ul) {
      const indent = " ".repeat(ul[1]!.length);
      out.push(`${indent}• ${renderInlineText(ul[2]!)}`);
      continue;
    }
    const ol = rawLine.match(/^(\s*)(\d+)\.\s+(.+)$/);
    if (ol) {
      const indent = " ".repeat(ol[1]!.length);
      out.push(`${indent}${ol[2]}. ${renderInlineText(ol[3]!)}`);
      continue;
    }
    out.push(renderInlineText(rawLine));
  }
  flushQuote();
  s = out.join("\n");

  s = s.replace(INLINE_PLACEHOLDER, (_, i: string) => inlineCodes[+i] ?? "");
  s = s.replace(FENCE_PLACEHOLDER, (_, i: string) => codeBlocks[+i] ?? "");

  // Collapse 3+ consecutive newlines to 2 (Telegram already renders \n\n as a paragraph gap).
  s = s.replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

export const _internal = { escapeHtml, escapeAttr };
