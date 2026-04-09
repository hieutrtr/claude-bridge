/**
 * Telegram Channel Adapter — implements IChannelAdapter for Telegram.
 *
 * Uses grammy SDK for Telegram Bot API.
 * Will be refactored from existing channel/server.ts + channel/lib.ts.
 *
 * TODO: Implement in Phase 2 by extracting from existing channel code.
 */

import type {
  IChannelAdapter,
  ChannelMessage,
  SendOpts,
} from "../interface.js";

export class TelegramAdapter implements IChannelAdapter {
  readonly platform = "telegram" as const;
  readonly maxMessageLength = 4096;
  readonly supportsThreads = false;
  readonly supportsReactions = true;
  readonly supportsFileUpload = true;
  readonly markdownFormat = "html" as const;

  private messageHandlers: Array<(msg: ChannelMessage) => void> = [];
  private commandHandlers: Array<
    (cmd: string, args: string, msg: ChannelMessage) => void
  > = [];

  constructor(private token: string) {}

  async start(): Promise<void> {
    throw new Error("Not implemented");
  }

  async stop(): Promise<void> {
    throw new Error("Not implemented");
  }

  async sendMessage(
    chatId: string,
    text: string,
    opts?: SendOpts,
  ): Promise<string> {
    throw new Error("Not implemented");
  }

  async editMessage(
    chatId: string,
    messageId: string,
    text: string,
  ): Promise<void> {
    throw new Error("Not implemented");
  }

  async deleteMessage(chatId: string, messageId: string): Promise<void> {
    throw new Error("Not implemented");
  }

  async addReaction(
    chatId: string,
    messageId: string,
    emoji: string,
  ): Promise<void> {
    throw new Error("Not implemented");
  }

  async downloadFile(fileId: string, destPath: string): Promise<void> {
    throw new Error("Not implemented");
  }

  onMessage(handler: (msg: ChannelMessage) => void): void {
    this.messageHandlers.push(handler);
  }

  onCommand(
    handler: (cmd: string, args: string, msg: ChannelMessage) => void,
  ): void {
    this.commandHandlers.push(handler);
  }
}
