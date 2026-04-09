/**
 * Message formatting for Telegram: Markdown → HTML conversion, chunking, and send helpers.
 *
 * Pipeline: markdownText → convertMarkdownToTelegramHtml → chunkTelegramMessage → sendMessage (HTML)
 * Fallback: if Telegram rejects HTML → stripHtmlTags → sendMessage (plain text)
 */

const CHUNK_LIMIT = 4000;
const PRE_OPEN = "<pre><code>";
const PRE_CLOSE = "</code></pre>";

/**
 * Convert markdown tables to plain text lines.
 * Telegram HTML does not support <table> tags; complex table HTML gets rejected.
 * Each data row becomes "cell1 | cell2 | ..." — separator rows (|---|) are dropped.
 */
function convertMarkdownTables(text: string): string {
  const lines = text.split("\n");
  const result: string[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    // A table starts with a pipe-delimited row followed by a separator row
    if (
      /^\s*\|.+\|/.test(line) &&
      i + 1 < lines.length &&
      /^\s*\|[\s\-:|]+\|/.test(lines[i + 1])
    ) {
      // Collect all consecutive lines that are part of this table
      const tableLines: string[] = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) {
        tableLines.push(lines[i]);
        i++;
      }
      // Convert: skip separator rows, format data rows as "cell1 | cell2"
      for (const tableLine of tableLines) {
        if (/^\s*\|[\s\-:|]+\|\s*$/.test(tableLine)) continue;
        const cells = tableLine.split("|").map((c) => c.trim()).filter((c) => c !== "");
        if (cells.length > 0) result.push(cells.join(" | "));
      }
    } else {
      result.push(line);
      i++;
    }
  }

  return result.join("\n");
}

/**
 * Convert Markdown text to Telegram HTML format.
 *
 * Processing order (important to avoid conflicts):
 * 1. Extract and protect fenced code blocks (```...```) with placeholders
 * 2. Extract and protect inline code (`...`) with placeholders
 * 3. Convert markdown tables to plain text (tables not supported in Telegram HTML)
 * 4. Escape HTML entities (&, <, >) in non-code text
 * 5. Restore inline code with escaped content
 * 6. Convert headings (# → <b>)
 * 7. Convert bold (**text** or __text__)
 * 8. Convert italic (*text* or _text_)
 * 9. Convert strikethrough (~~text~~)
 * 10. Convert links ([label](url))
 * 11. Restore code blocks with escaped content
 */
export function convertMarkdownToTelegramHtml(text: string): string {
  // Step 1: Extract fenced code blocks
  const codeBlocks: string[] = [];
  let result = text.replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(code);
    return `\x00CB${idx}\x00`;
  });

  // Step 2: Extract inline code blocks (before HTML escaping to avoid double-escaping)
  const inlineCodes: string[] = [];
  result = result.replace(/`([^`\n]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(code);
    return `\x00IC${idx}\x00`;
  });

  // Step 3: Convert markdown tables to plain text (Telegram doesn't support HTML tables)
  result = convertMarkdownTables(result);

  // Step 4: Escape HTML entities in non-code text
  result = result
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Step 5: Restore inline code with escaped content
  result = result.replace(/\x00IC(\d+)\x00/g, (_, idx) => {
    const code = inlineCodes[Number(idx)];
    const escaped = code
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    return `<code>${escaped}</code>`;
  });

  // Step 6: Convert headings (# Title → <b>Title</b>)
  result = result.replace(/^#{1,6}\s+(.+)$/gm, "<b>$1</b>");

  // Step 7: Convert bold (**text** or __text__)
  result = result.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
  result = result.replace(/(?<![_\w])__([^_\n]+)__(?![_\w])/g, "<b>$1</b>");

  // Step 8: Convert italic (*text* or _text_) — after bold to avoid conflict
  result = result.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<i>$1</i>");
  result = result.replace(/(?<![_\w])_([^_\n]+)_(?![_\w])/g, "<i>$1</i>");

  // Step 9: Convert strikethrough
  result = result.replace(/~~([^~\n]+)~~/g, "<s>$1</s>");

  // Step 10: Convert links [label](url)
  result = result.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');

  // Step 11: Restore code blocks with HTML-escaped content
  result = result.replace(/\x00CB(\d+)\x00/g, (_, idx) => {
    const code = codeBlocks[Number(idx)];
    const escaped = code
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
    // Remove trailing newline added by fenced block syntax
    return `${PRE_OPEN}${escaped.replace(/\n$/, "")}${PRE_CLOSE}`;
  });

  return result;
}

/**
 * Split HTML string into chunks that fit within Telegram's message size limit.
 * Fence-aware: avoids splitting inside <pre><code>...</code></pre> blocks.
 * Prefers paragraph boundaries (\n\n), then line breaks (\n), then hard split.
 */
export function chunkTelegramMessage(html: string, limit = CHUNK_LIMIT): string[] {
  if (html.length <= limit) return [html];

  const chunks: string[] = [];
  let remaining = html;

  while (remaining.length > limit) {
    const preStart = remaining.indexOf(PRE_OPEN);
    const preEnd = preStart !== -1 ? remaining.indexOf(PRE_CLOSE, preStart) : -1;
    const blockEnd = preEnd !== -1 ? preEnd + PRE_CLOSE.length : -1;

    // Code block starts before the limit but would be split by it
    const blockSplitsChunk =
      preStart !== -1 && preStart < limit && (blockEnd === -1 || blockEnd > limit);

    let splitAt: number;

    if (blockSplitsChunk) {
      if (preStart === 0) {
        // Oversized code block — hard split (unavoidable)
        splitAt = limit;
      } else {
        // Split before the code block at a paragraph/line boundary
        const beforeBlock = remaining.substring(0, preStart);
        const nnIdx = beforeBlock.lastIndexOf("\n\n");
        const nIdx = beforeBlock.lastIndexOf("\n");
        if (nnIdx !== -1) {
          splitAt = nnIdx + 2;
        } else if (nIdx !== -1) {
          splitAt = nIdx + 1;
        } else {
          splitAt = preStart;
        }
      }
    } else {
      // No problematic code block — prefer paragraph, newline, or hard split
      const candidate = remaining.substring(0, limit);
      const nnIdx = candidate.lastIndexOf("\n\n");
      const nIdx = candidate.lastIndexOf("\n");
      if (nnIdx !== -1) {
        splitAt = nnIdx + 2;
      } else if (nIdx !== -1) {
        splitAt = nIdx + 1;
      } else {
        splitAt = limit;
      }
    }

    // Safety: prevent infinite loop if nothing makes progress
    if (splitAt <= 0) splitAt = limit;

    chunks.push(remaining.substring(0, splitAt));
    remaining = remaining.substring(splitAt);
  }

  if (remaining.length > 0) chunks.push(remaining);

  return chunks;
}

/**
 * Detect Telegram HTML entity parse errors.
 */
export function isTelegramHtmlParseError(err: unknown): boolean {
  if (!err) return false;
  const msg = err instanceof Error ? err.message : String(err);
  return /can't parse|parse entities|find end of the entity/i.test(msg);
}

/**
 * Strip HTML tags, unescape HTML entities, and clean up residual markdown symbols.
 * Used for plain-text fallback when Telegram rejects HTML parse mode.
 * Removes <tags>, unescapes &entities;, and strips **bold**, ##headings, etc.
 */
export function stripHtmlTags(html: string): string {
  return html
    .replace(/<[^>]+>/g, "")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    // Strip residual markdown symbols (safety net for patterns not yet converted)
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\*\*([^*\n]+)\*\*/g, "$1")
    .replace(/(?<![_\w])__([^_\n]+)__(?![_\w])/g, "$1")
    .replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "$1")
    .replace(/(?<![_\w])_([^_\n]+)_(?![_\w])/g, "$1")
    .replace(/~~([^~\n]+)~~/g, "$1")
    .replace(/`([^`\n]+)`/g, "$1");
}

/**
 * Convert markdown → HTML → chunk → send with HTML parse_mode.
 * Falls back to plain text if Telegram rejects the HTML.
 * opts (reply_parameters etc.) is only passed to the first chunk.
 */
export async function sendTelegramChunked(
  sendFn: (chatId: string, text: string, opts?: any) => Promise<void>,
  chatId: string,
  markdownText: string,
  opts?: { reply_parameters?: { message_id: number } }
): Promise<void> {
  if (!markdownText || !markdownText.trim()) return;

  const html = convertMarkdownToTelegramHtml(markdownText);
  const chunks = chunkTelegramMessage(html);

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    const chunkOpts =
      i === 0 && opts
        ? { parse_mode: "HTML", ...opts }
        : { parse_mode: "HTML" };

    try {
      await sendFn(chatId, chunk, chunkOpts);
    } catch (err) {
      if (isTelegramHtmlParseError(err)) {
        // Fallback: strip HTML tags and send as plain text
        const plainText = stripHtmlTags(chunk);
        const plainOpts = i === 0 && opts ? opts : undefined;
        await sendFn(chatId, plainText, plainOpts);
      } else {
        throw err;
      }
    }
  }
}
