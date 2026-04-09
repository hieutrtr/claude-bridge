/**
 * Telegram Message Formatter — HTML formatting for Telegram Bot API.
 *
 * Will be refactored from existing channel/format.ts.
 *
 * TODO: Implement in Phase 2 by extracting from existing format.ts.
 */

import type { IMessageFormatter } from "../interface.js";

export class TelegramFormatter implements IMessageFormatter {
  private readonly maxLength = 4096;

  formatCodeBlock(code: string, language?: string): string {
    const lang = language ? ` class="language-${language}"` : "";
    return `<pre><code${lang}>${this.escapeSpecialChars(code)}</code></pre>`;
  }

  formatBold(text: string): string {
    return `<b>${text}</b>`;
  }

  formatItalic(text: string): string {
    return `<i>${text}</i>`;
  }

  formatLink(url: string, text: string): string {
    return `<a href="${url}">${text}</a>`;
  }

  formatList(items: string[]): string {
    return items.map((item) => `• ${item}`).join("\n");
  }

  escapeSpecialChars(text: string): string {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  chunkMessage(text: string): string[] {
    if (text.length <= this.maxLength) return [text];
    // TODO: Smart chunking that respects HTML tags
    const chunks: string[] = [];
    for (let i = 0; i < text.length; i += this.maxLength) {
      chunks.push(text.slice(i, i + this.maxLength));
    }
    return chunks;
  }
}
