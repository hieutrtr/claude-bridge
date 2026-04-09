/**
 * Channel Layer — multi-platform messaging adapters.
 */

export type {
  IChannelAdapter,
  IMessageFormatter,
  ChannelMessage,
  ChannelFile,
  SendOpts,
} from "./interface.js";
export { isAllowed, loadAllowlist } from "./core.js";
export { TelegramAdapter } from "./telegram/adapter.js";
export { TelegramFormatter } from "./telegram/format.js";
export { DiscordAdapter } from "./discord/adapter.js";
export { DiscordFormatter } from "./discord/format.js";
export { SlackAdapter } from "./slack/adapter.js";
export { SlackFormatter } from "./slack/format.js";
