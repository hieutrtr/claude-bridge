# Phase 1: Photo Eager Download + image_path in meta

> Uu tien: **MVP** — Photo la file type pho bien nhat tu mobile, Claude multimodal doc anh truc tiep.

---

## Muc tieu

Khi user gui anh tu Telegram, Bridge Channel Server:
1. Download anh ngay lap tuc (eager) ve `INBOX_DIR`
2. Push MCP notification voi `image_path` trong meta
3. Claude Code tu `Read` file anh va hieu noi dung (multimodal)

## Files can modify/create

| File | Thay doi |
|---|---|
| `channel/server.ts` | Them `INBOX_DIR` constant, them `bot.on('message:photo')` handler |
| `channel/lib.ts` | Mo rong `pushMessage()` nhan optional `extraMeta`, them `downloadTelegramFile()` helper |

## Tung buoc implement

### Buoc 1: Dinh nghia INBOX_DIR

**File:** `channel/server.ts` — sau dong 52 (sau `CONFIG_FILE`)

```typescript
const INBOX_DIR = join(homedir(), ".claude-bridge", "inbox");
mkdirSync(INBOX_DIR, { recursive: true });
```

> `INBOX_DIR` dat cung cap voi `messages.db` trong `~/.claude-bridge/`.
> `mkdirSync` voi `recursive: true` dam bao thu muc ton tai.

### Buoc 2: Mo rong `pushMessage()` nhan extra meta

**File:** `channel/lib.ts` — function `pushMessage` (dong 122-146)

Them parameter `extraMeta` de truyen them `image_path`, `attachment_file_id`, v.v. ma khong pha vo signature hien tai.

```typescript
export function pushMessage(
  notifier: McpNotifier,
  trackingId: number,
  chatId: string,
  userId: string,
  username: string,
  text: string,
  messageId: string,
  ts: string,
  extraMeta?: Record<string, string | undefined>  // <-- THEM
): void {
  const meta: Record<string, string> = {
    chat_id: chatId,
    message_id: messageId,
    user: username,
    user_id: userId,
    ts,
    tracking_id: String(trackingId),
  };

  // Merge extra meta (image_path, attachment_*, ...)
  if (extraMeta) {
    for (const [k, v] of Object.entries(extraMeta)) {
      if (v !== undefined) meta[k] = v;
    }
  }

  notifier.notification({
    method: "notifications/claude/channel",
    params: { content: text, meta },
  });
}
```

**Backward compatible:** cac caller hien tai khong truyen `extraMeta` van hoat dong binh thuong.

### Buoc 3: Them helper `downloadTelegramFile()`

**File:** `channel/lib.ts` — them function moi sau `pushMessage`

```typescript
/**
 * Download a file from Telegram Bot API to INBOX_DIR.
 * Returns local file path on success, undefined on failure.
 */
export async function downloadTelegramFile(
  getFile: (fileId: string) => Promise<{ file_path?: string; file_unique_id: string }>,
  token: string,
  fileId: string,
  inboxDir: string,
  extOverride?: string
): Promise<string | undefined> {
  try {
    const file = await getFile(fileId);
    if (!file.file_path) return undefined;

    const url = `https://api.telegram.org/file/bot${token}/${file.file_path}`;
    const res = await fetch(url);
    if (!res.ok) {
      process.stderr.write(`bridge channel: file download HTTP ${res.status}\n`);
      return undefined;
    }

    const buf = Buffer.from(await res.arrayBuffer());
    const ext = extOverride ?? file.file_path.split(".").pop() ?? "bin";
    const safeUniqueId = file.file_unique_id.replace(/[^a-zA-Z0-9_-]/g, "");
    const filename = `${Date.now()}-${safeUniqueId}.${ext}`;
    const localPath = join(inboxDir, filename);

    const { mkdirSync, writeFileSync } = await import("fs");
    mkdirSync(inboxDir, { recursive: true });
    writeFileSync(localPath, buf);

    process.stderr.write(`bridge channel: downloaded file to ${localPath} (${buf.length} bytes)\n`);
    return localPath;
  } catch (err) {
    process.stderr.write(`bridge channel: file download error: ${err}\n`);
    return undefined;
  }
}
```

> **Luu y:** `getFile` duoc inject de co the mock trong test. Khong goi truc tiep `bot.api.getFile`.

### Buoc 4: Them `message:photo` handler

**File:** `channel/server.ts` — sau `bot.on("message:text", ...)` handler (sau dong 368)

```typescript
bot.on("message:photo", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const caption = ctx.message.caption ?? "(photo)";
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) {
    process.stderr.write(`bridge channel: rejected photo from non-allowed user ${userId}\n`);
    return;
  }

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();

    // Download highest resolution photo
    const photos = ctx.message.photo;
    const best = photos[photos.length - 1];
    const imagePath = await downloadTelegramFile(
      (fid) => ctx.api.getFile(fid),
      TOKEN,
      best.file_id,
      INBOX_DIR
    );

    const trackingId = trackInbound(msgDb, chatId, userId, username, caption, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, caption, messageId, ts, {
      image_path: imagePath,
    });

    process.stderr.write(`bridge channel: photo received from ${username}, path=${imagePath}\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: photo handler error: ${err}\n`);
  }
});
```

> **Key:** `photos[photos.length - 1]` la resolution cao nhat — day la convention cua Telegram Bot API.

### Buoc 5: Update import trong server.ts

**File:** `channel/server.ts` — dong 24-35 (import block)

Them `downloadTelegramFile` vao import:

```typescript
import {
  initInboundTracking,
  isAllowed,
  trackInbound,
  acknowledgeInbound,
  getPendingInbound,
  pushMessage,
  processRetries,
  processOutbound,
  bridgeCli,
  handleReply,
  downloadTelegramFile,  // <-- THEM
} from "./lib";
```

### Buoc 6: Update MCP instructions

**File:** `channel/server.ts` — instructions array (dong 80-86)

Them dong huong dan Claude cach xu ly `image_path`:

```typescript
instructions: [
  'Messages from Telegram arrive as <channel source="bridge" chat_id="..." user="..." tracking_id="..." ts="...">.',
  'If the tag has an image_path attribute, Read that file — it is a photo the sender attached.',
  "After processing each message: call bridge_acknowledge(tracking_id), then bridge_get_notifications(), then bridge_check_messages().",
  // ... (giu nguyen cac dong cu)
].join("\n"),
```

## Test cases

### Manual test (integration)

1. **Happy path:** Gui anh tu Telegram → check stderr co log `photo received` + `downloaded file` → verify file ton tai trong `~/.claude-bridge/inbox/` → verify Claude nhan `image_path` va doc anh
2. **Photo voi caption:** Gui anh + caption "fix this bug" → verify `content` = "fix this bug" (khong phai "(photo)")
3. **Photo khong caption:** Gui anh khong caption → verify `content` = "(photo)"
4. **Access denied:** Gui anh tu user khong duoc phep → verify bi reject, khong download

### Unit test (channel/lib.ts)

```typescript
// test: pushMessage voi extraMeta
test("pushMessage includes extraMeta in notification", () => {
  const notifications: any[] = [];
  const notifier = { notification: (msg: any) => notifications.push(msg) };
  pushMessage(notifier, 1, "123", "456", "alice", "hello", "789", "2024-01-01T00:00:00Z", {
    image_path: "/inbox/photo.jpg",
  });
  expect(notifications[0].params.meta.image_path).toBe("/inbox/photo.jpg");
});

// test: pushMessage khong extraMeta van chay
test("pushMessage without extraMeta still works", () => {
  const notifications: any[] = [];
  const notifier = { notification: (msg: any) => notifications.push(msg) };
  pushMessage(notifier, 1, "123", "456", "alice", "hello", "789", "2024-01-01T00:00:00Z");
  expect(notifications[0].params.meta.image_path).toBeUndefined();
});

// test: downloadTelegramFile
test("downloadTelegramFile saves file to inbox", async () => {
  // Mock getFile + fetch
  // Verify file written to correct path
  // Verify filename format: {timestamp}-{uniqueId}.{ext}
});
```

## Acceptance criteria

- [ ] `INBOX_DIR` (`~/.claude-bridge/inbox/`) duoc tao khi server start
- [ ] Gui anh tu Telegram → file duoc download ve `INBOX_DIR`
- [ ] MCP notification chua `image_path` tro den file da download
- [ ] Claude Code nhan `image_path` trong `<channel>` tag va co the `Read` anh
- [ ] Caption duoc truyen lam `content` (fallback "(photo)" neu khong co caption)
- [ ] `pushMessage()` backward compatible — caller cu khong bi anh huong
- [ ] Access control van hoat dong — user khong duoc phep thi khong download
- [ ] Error khi download khong crash server (log + continue)
- [ ] File name an toan (dung `file_unique_id`, khong dung ten goc)

## Dependencies

- **Khong phu thuoc phase nao truoc** — day la phase dau tien
- Phase 2 se mo rong `pushMessage()` extraMeta pattern da tao o day
- Phase 2 se reuse `downloadTelegramFile()` cho `download_attachment` tool
