# Phase 2: Document Deferred Download + download_attachment MCP Tool

> Uu tien: **Cao** — Document (PDF, ZIP, code file) la use case quan trong thu 2 sau photo.

---

## Muc tieu

1. Khi user gui document tu Telegram, chi gui **metadata** (file_id, size, mime, name) trong MCP notification — **khong download ngay**
2. Them MCP tool `download_attachment` de Claude goi khi can download file
3. Claude nhan `attachment_file_id` trong `<channel>` tag → goi `download_attachment` → nhan local path → `Read` file

## Files can modify/create

| File | Thay doi |
|---|---|
| `channel/server.ts` | Them `bot.on('message:document')` handler, them `download_attachment` tool definition + handler |
| `channel/lib.ts` | Them `safeName()` utility function |

## Tung buoc implement

### Buoc 1: Them `safeName()` utility

**File:** `channel/lib.ts` — them function moi (sau `downloadTelegramFile`)

```typescript
/**
 * Sanitize filename from Telegram — strip dangerous characters.
 * Returns undefined if input is undefined/null.
 */
export function safeName(name: string | undefined | null): string | undefined {
  if (!name) return undefined;
  // Strip dangerous characters: < > [ ] \r \n ; / \ : * ? " |
  return name.replace(/[<>\[\]\r\n;/\\:*?"|]/g, "_").trim() || undefined;
}
```

> Dung cung pattern voi official Telegram plugin. Khong dung ten goc lam filename luu file — chi dung de hien thi.

### Buoc 2: Them `message:document` handler

**File:** `channel/server.ts` — sau `bot.on("message:photo", ...)` handler

```typescript
bot.on("message:document", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) {
    process.stderr.write(`bridge channel: rejected document from non-allowed user ${userId}\n`);
    return;
  }

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const doc = ctx.message.document;
    const name = safeName(doc.file_name);
    const text = ctx.message.caption ?? `(document: ${name ?? "file"})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "document",
      attachment_file_id: doc.file_id,
      attachment_size: doc.file_size ? String(doc.file_size) : undefined,
      attachment_mime: doc.mime_type,
      attachment_name: name,
    });

    process.stderr.write(
      `bridge channel: document received from ${username}: ${name ?? "unnamed"} ` +
      `(${doc.mime_type}, ${doc.file_size} bytes)\n`
    );
  } catch (err) {
    process.stderr.write(`bridge channel: document handler error: ${err}\n`);
  }
});
```

> **Key: Deferred download** — chi gui metadata, KHONG download file. Tiet kiem bandwidth va thoi gian xu ly.

### Buoc 3: Them `download_attachment` tool definition

**File:** `channel/server.ts` — trong `ListToolsRequestSchema` handler (sau tool `bridge_check_messages`, truoc `]`)

```typescript
{
  name: "download_attachment",
  description: "Download a file attachment from Telegram. Returns the local file path. Use when a channel message has attachment_file_id.",
  inputSchema: {
    type: "object" as const,
    properties: {
      file_id: {
        type: "string",
        description: "The attachment_file_id from the channel message meta",
      },
    },
    required: ["file_id"],
  },
},
```

### Buoc 4: Them `download_attachment` tool handler

**File:** `channel/server.ts` — trong `CallToolRequestSchema` handler, them case truoc `default:`

```typescript
case "download_attachment": {
  const { file_id } = args as { file_id: string };
  if (!file_id) {
    return { content: [{ type: "text", text: "Error: file_id is required" }], isError: true };
  }

  const localPath = await downloadTelegramFile(
    (fid) => bot.api.getFile(fid),
    TOKEN,
    file_id,
    INBOX_DIR
  );

  if (!localPath) {
    return {
      content: [{ type: "text", text: "Error: failed to download file — it may have expired (Telegram files expire after ~1 hour)" }],
      isError: true,
    };
  }

  return { content: [{ type: "text", text: localPath }] };
}
```

> Reuse `downloadTelegramFile()` tu Phase 1 — cung logic download, cung INBOX_DIR.

### Buoc 5: Update import trong server.ts

**File:** `channel/server.ts` — import block

Them `safeName` vao import:

```typescript
import {
  // ... existing imports ...
  downloadTelegramFile,
  safeName,  // <-- THEM
} from "./lib";
```

### Buoc 6: Update MCP instructions

**File:** `channel/server.ts` — instructions array

Them huong dan cho Claude cach xu ly attachments:

```typescript
instructions: [
  'Messages from Telegram arrive as <channel source="bridge" chat_id="..." user="..." tracking_id="..." ts="...">.',
  'If the tag has an image_path attribute, Read that file — it is a photo the sender attached.',
  'If the tag has attachment_file_id, call download_attachment with that file_id to fetch the file, then Read the returned path.',
  "After processing each message: call bridge_acknowledge(tracking_id), then bridge_get_notifications(), then bridge_check_messages().",
  // ... (giu nguyen cac dong cu)
].join("\n"),
```

## Test cases

### Manual test (integration)

1. **Happy path - PDF:** Gui file PDF tu Telegram → verify Claude nhan meta `attachment_kind=document`, `attachment_file_id`, `attachment_name` → Claude goi `download_attachment` → file duoc download → Claude `Read` file
2. **Happy path - ZIP:** Gui file ZIP → verify metadata tuong tu
3. **Code file:** Gui file `.py` → verify `attachment_mime=text/x-python`
4. **Document voi caption:** Gui file + caption "review this" → verify `content` = "review this"
5. **Document khong caption:** Gui file `report.pdf` khong caption → verify `content` = "(document: report.pdf)"
6. **Expired file_id:** Doi > 1 gio roi goi `download_attachment` → verify error message ro rang
7. **Access denied:** Gui file tu user khong duoc phep → verify bi reject, khong gui meta

### Unit test

```typescript
// test: safeName
test("safeName strips dangerous characters", () => {
  expect(safeName("report<script>.pdf")).toBe("report_script_.pdf");
  expect(safeName("path/../../etc/passwd")).toBe("path_.._.._etc_passwd");
  expect(safeName(undefined)).toBeUndefined();
  expect(safeName("")).toBeUndefined();
  expect(safeName("normal-file.pdf")).toBe("normal-file.pdf");
});

// test: pushMessage voi attachment meta
test("pushMessage includes attachment meta", () => {
  const notifications: any[] = [];
  const notifier = { notification: (msg: any) => notifications.push(msg) };
  pushMessage(notifier, 1, "123", "456", "alice", "report.pdf", "789", "2024-01-01T00:00:00Z", {
    attachment_kind: "document",
    attachment_file_id: "BAADBBxxxx",
    attachment_size: "1234567",
    attachment_mime: "application/pdf",
    attachment_name: "report.pdf",
  });
  const meta = notifications[0].params.meta;
  expect(meta.attachment_kind).toBe("document");
  expect(meta.attachment_file_id).toBe("BAADBBxxxx");
  expect(meta.attachment_name).toBe("report.pdf");
});
```

## Acceptance criteria

- [ ] Gui document tu Telegram → MCP notification chua `attachment_file_id`, `attachment_kind`, `attachment_mime`, `attachment_name`, `attachment_size`
- [ ] Claude Code nhan `attachment_file_id` trong `<channel>` tag
- [ ] Claude goi `download_attachment(file_id)` → file duoc download ve `INBOX_DIR` → tra ve local path
- [ ] Caption duoc truyen lam `content` (fallback "(document: {name})" neu khong co)
- [ ] `safeName()` strip ky tu nguy hiem tu filename
- [ ] File khong tu dong download — chi download khi Claude goi tool
- [ ] Error handling: file expired, download fail → error message ro rang
- [ ] Access control: user khong duoc phep → khong gui metadata

## Dependencies

- **Phu thuoc Phase 1:**
  - Dung `INBOX_DIR` constant da dinh nghia
  - Dung `downloadTelegramFile()` helper da tao
  - Dung `pushMessage()` voi `extraMeta` pattern da mo rong
- Phase 3 se dung cung pattern `attachment_*` meta cho voice/audio/video
