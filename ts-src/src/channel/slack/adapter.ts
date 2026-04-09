/**
 * Slack Channel Adapter — implements IChannelAdapter for Slack.
 *
 * Uses @slack/bolt SDK with Socket Mode (no public URL needed).
 *
 * TODO: Implement in Phase 6.
 */

import type {
  IChannelAdapter,
  ChannelMessage,
  SendOpts,
} from "../interface.js";

export class SlackAdapter implements IChannelAdapter {
  readonly platform = "slack" as const;
  readonly maxMessageLength = 40_000;
  readonly supportsThreads = true;
  readonly supportsReactions = true;
  readonly supportsFileUpload = true;
  readonly markdownFormat = "slack-mrkdwn" as const;

  private messageHandlers: Array<(msg: ChannelMessage) => void> = [];
  private commandHandlers: Array<
    (cmd: string, args: string, msg: ChannelMessage) => void
  > = [];

  constructor(
    private token: string,
    private appToken: string,
  ) {}

  async start(): Promise<void> {
    throw new Error("Not implemented — Phase 6");
  }
  async stop(): Promise<void> {
    throw new Error("Not implemented — Phase 6");
  }
  async sendMessage(chatId: string, text: string, opts?: SendOpts): Promise<string> {
    throw new Error("Not implemented — Phase 6");
  }
  async editMessage(chatId: string, messageId: string, text: string): Promise<void> {
    throw new Error("Not implemented — Phase 6");
  }
  async deleteMessage(chatId: string, messageId: string): Promise<void> {
    throw new Error("Not implemented — Phase 6");
  }
  async addReaction(chatId: string, messageId: string, emoji: string): Promise<void> {
    throw new Error("Not implemented — Phase 6");
  }
  async downloadFile(fileId: string, destPath: string): Promise<void> {
    throw new Error("Not implemented — Phase 6");
  }
  onMessage(handler: (msg: ChannelMessage) => void): void {
    this.messageHandlers.push(handler);
  }
  onCommand(handler: (cmd: string, args: string, msg: ChannelMessage) => void): void {
    this.commandHandlers.push(handler);
  }
}
