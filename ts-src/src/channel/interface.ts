/**
 * Channel Abstraction — common interface for all messaging platforms.
 *
 * Each platform (Telegram, Discord, Slack) implements ChannelAdapter.
 * This enables multi-channel support without changing core logic.
 */

// --- Message Types ---

export interface ChannelMessage {
  id: string;
  text: string;
  senderId: string;
  senderName: string;
  chatId: string;
  threadId?: string;
  replyToMessageId?: string;
  files?: ChannelFile[];
  timestamp: number;
}

export interface ChannelFile {
  name: string;
  url: string;
  mimeType: string;
  size: number;
}

export interface SendOpts {
  threadId?: string;
  parseMode?: string;
  replyToMessageId?: string;
}

// --- Formatter ---

export interface IMessageFormatter {
  formatCodeBlock(code: string, language?: string): string;
  formatBold(text: string): string;
  formatItalic(text: string): string;
  formatLink(url: string, text: string): string;
  formatList(items: string[]): string;
  escapeSpecialChars(text: string): string;
  chunkMessage(text: string): string[];
}

// --- Channel Adapter ---

export interface IChannelAdapter {
  /** Platform name (e.g. "telegram", "discord", "slack") */
  readonly platform: string;

  /** Maximum message length for this platform */
  readonly maxMessageLength: number;

  /** Platform capabilities */
  readonly supportsThreads: boolean;
  readonly supportsReactions: boolean;
  readonly supportsFileUpload: boolean;
  readonly markdownFormat: "standard" | "slack-mrkdwn" | "html";

  // --- Lifecycle ---
  start(): Promise<void>;
  stop(): Promise<void>;

  // --- Messaging ---
  sendMessage(chatId: string, text: string, opts?: SendOpts): Promise<string>;
  editMessage(chatId: string, messageId: string, text: string): Promise<void>;
  deleteMessage(chatId: string, messageId: string): Promise<void>;

  // --- Reactions (optional) ---
  addReaction?(chatId: string, messageId: string, emoji: string): Promise<void>;

  // --- File handling ---
  downloadFile(fileId: string, destPath: string): Promise<void>;

  // --- Events ---
  onMessage(handler: (msg: ChannelMessage) => void): void;
  onCommand(
    handler: (cmd: string, args: string, msg: ChannelMessage) => void,
  ): void;
}
