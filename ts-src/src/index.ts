/**
 * Claude Bridge — main entry point.
 *
 * Re-exports all public APIs from each layer.
 */

// Types
export type * from "./types.js";

// Config
export { ConfigProvider } from "./config.js";

// Data Layer
export {
  BridgeDatabase,
  SessionManager,
  type IDatabase,
  type ISessionManager,
  type IConfigProvider,
} from "./data/index.js";

// Execution Layer
export {
  Dispatcher,
  CompletionHandler,
  ProcessWatcher,
  Notifier,
  type IDispatcher,
  type ICompletionHandler,
  type IProcessWatcher,
  type INotifier,
} from "./execution/index.js";

// Channel Layer
export {
  type IChannelAdapter,
  type IMessageFormatter,
  type ChannelMessage,
  TelegramAdapter,
  TelegramFormatter,
  DiscordAdapter,
  DiscordFormatter,
  SlackAdapter,
  SlackFormatter,
} from "./channel/index.js";

// Orchestration Layer
export {
  LoopOrchestrator,
  LoopEvaluator,
  Scheduler,
  type ILoopOrchestrator,
  type ILoopEvaluator,
  type IScheduler,
} from "./orchestration/index.js";

// MCP Layer
export { startServer } from "./mcp/index.js";
