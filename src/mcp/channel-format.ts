/**
 * Channel meta formatter — builds the `meta` map passed to
 * `notifications/claude/channel` notifications.
 *
 * Claude Code renders these into a `<channel source="bridge" chat_id="..."
 * tracking_id="..." ts="...">...</channel>` tag in the model's context.
 *
 * Minimal reimplementation inspired by legacy/channel/format.ts. We do NOT
 * import from legacy/ — this file owns the meta shape for the ported flow.
 */

export type ChannelMeta = Record<string, string>;

export interface BuildInboundMetaInput {
  chatId: string;
  userId: string;
  username: string;
  messageId: string;
  trackingId: number | string;
  ts: string;
  source?: string; // default "bridge"
  imagePath?: string;
  attachmentKind?: string;
  attachmentFileId?: string;
  attachmentMime?: string;
  attachmentName?: string;
  attachmentSize?: string | number;
}

/** Build the meta object for an inbound channel notification. */
export function buildInboundMeta(input: BuildInboundMetaInput): ChannelMeta {
  const meta: ChannelMeta = {
    source: input.source ?? "bridge",
    chat_id: input.chatId,
    user: input.username,
    user_id: input.userId,
    message_id: input.messageId,
    tracking_id: String(input.trackingId),
    ts: input.ts,
  };
  if (input.imagePath) meta["image_path"] = input.imagePath;
  if (input.attachmentKind) meta["attachment_kind"] = input.attachmentKind;
  if (input.attachmentFileId) meta["attachment_file_id"] = input.attachmentFileId;
  if (input.attachmentMime) meta["attachment_mime"] = input.attachmentMime;
  if (input.attachmentName) meta["attachment_name"] = input.attachmentName;
  if (input.attachmentSize !== undefined) meta["attachment_size"] = String(input.attachmentSize);
  return meta;
}

/** Sanitize a filename coming from Telegram (strip shell/path metacharacters). */
export function safeName(name: string | undefined | null): string | undefined {
  if (!name) return undefined;
  const cleaned = name.replace(/[<>\[\]\r\n;/\\:*?"|]/g, "_").trim();
  if (!cleaned || /^_+$/.test(cleaned)) return undefined;
  return cleaned;
}
