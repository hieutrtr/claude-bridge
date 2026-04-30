/**
 * Discord Message Formatter — standard Markdown for Discord.
 *
 * TODO: Implement in Phase 3.
 */

import type { IMessageFormatter } from "../interface.js";

export class DiscordFormatter implements IMessageFormatter {
  private readonly maxLength = 2000;

  formatCodeBlock(code: string, language?: string): string {
    return `\`\`\`${language ?? ""}\n${code}\n\`\`\``;
  }
  formatBold(text: string): string {
    return `**${text}**`;
  }
  formatItalic(text: string): string {
    return `*${text}*`;
  }
  formatLink(url: string, text: string): string {
    return `[${text}](${url})`;
  }
  formatList(items: string[]): string {
    return items.map((item) => `- ${item}`).join("\n");
  }
  escapeSpecialChars(text: string): string {
    return text.replace(/([*_~`|\\])/g, "\\$1");
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
