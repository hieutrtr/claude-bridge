/**
 * Discord Channel Adapter — implements IChannelAdapter for Discord.
 *
 * Uses discord.js SDK with WebSocket gateway.
 *
 * TODO: Implement in Phase 3.
 */

import type {
  IChannelAdapter,
  ChannelMessage,
  SendOpts,
} from "../interface.js";

export class DiscordAdapter implements IChannelAdapter {
  readonly platform = "discord" as const;
  readonly maxMessageLength = 2000;
  readonly supportsThreads = true;
  readonly supportsReactions = true;
  readonly supportsFileUpload = true;
  readonly markdownFormat = "standard" as const;

  private messageHandlers: Array<(msg: ChannelMessage) => void> = [];
  private commandHandlers: Array<
    (cmd: string, args: string, msg: ChannelMessage) => void
  > = [];

  constructor(private token: string) {}

  async start(): Promise<void> {
    throw new Error("Not implemented — Phase 3");
  }
  async stop(): Promise<void> {
    throw new Error("Not implemented — Phase 3");
  }
  async sendMessage(chatId: string, text: string, opts?: SendOpts): Promise<string> {
    throw new Error("Not implemented — Phase 3");
  }
  async editMessage(chatId: string, messageId: string, text: string): Promise<void> {
    throw new Error("Not implemented — Phase 3");
  }
  async deleteMessage(chatId: string, messageId: string): Promise<void> {
    throw new Error("Not implemented — Phase 3");
  }
  async addReaction(chatId: string, messageId: string, emoji: string): Promise<void> {
    throw new Error("Not implemented — Phase 3");
  }
  async downloadFile(fileId: string, destPath: string): Promise<void> {
    throw new Error("Not implemented — Phase 3");
  }
  onMessage(handler: (msg: ChannelMessage) => void): void {
    this.messageHandlers.push(handler);
  }
  onCommand(handler: (cmd: string, args: string, msg: ChannelMessage) => void): void {
    this.commandHandlers.push(handler);
  }
}
