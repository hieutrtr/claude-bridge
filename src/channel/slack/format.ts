/**
 * Slack Message Formatter — mrkdwn syntax for Slack.
 *
 * Key differences from standard Markdown:
 * - Bold: *text* (not **text**)
 * - Italic: _text_ (not *text*)
 * - Links: <url|text> (not [text](url))
 * - No syntax highlighting in code blocks
 *
 * TODO: Implement in Phase 6.
 */

import type { IMessageFormatter } from "../interface.js";

export class SlackFormatter implements IMessageFormatter {
  private readonly maxLength = 40_000;

  formatCodeBlock(code: string, _language?: string): string {
    return `\`\`\`\n${code}\n\`\`\``;
  }
  formatBold(text: string): string {
    return `*${text}*`;
  }
  formatItalic(text: string): string {
    return `_${text}_`;
  }
  formatLink(url: string, text: string): string {
    return `<${url}|${text}>`;
  }
  formatList(items: string[]): string {
    return items.map((item) => `- ${item}`).join("\n");
  }
  escapeSpecialChars(text: string): string {
    return text.replace(/[&<>]/g, (c) => {
      const map: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
      return map[c] ?? c;
    });
  }
  chunkMessage(text: string): string[] {
    if (text.length <= this.maxLength) return [text];
    const chunks: string[] = [];
    for (let i = 0; i < text.length; i += this.maxLength) {
      chunks.push(text.slice(i, i + this.maxLength));
    }
    return chunks;
  }
}
