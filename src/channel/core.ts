/**
 * Channel Core — shared logic for all channel adapters.
 *
 * Access control, message queuing, inbound tracking.
 * Extracted from current Telegram-specific code.
 *
 * TODO: Extract shared logic from channel/lib.ts in Phase 2.
 */

import type { ChannelMessage, IChannelAdapter } from "./interface.js";

/** Access control — check if a user/chat is allowed */
export function isAllowed(
  senderId: string,
  chatId: string,
  allowlist: Set<string>,
): boolean {
  return allowlist.has(senderId) || allowlist.has(chatId);
}

/** Load allowlist from access.json */
export function loadAllowlist(accessPath: string): Set<string> {
  // TODO: Implement in Phase 2
  return new Set();
}
