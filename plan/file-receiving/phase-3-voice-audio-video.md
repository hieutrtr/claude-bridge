# Phase 3: Voice / Audio / Video / Sticker Handlers

> Uu tien: **Nice-to-have** — it dung hon photo/document nhung can de tranh bot ignore message.

---

## Muc tieu

1. Xu ly tat ca cac loai file con lai tu Telegram: voice, audio, video, video_note, sticker, animation
2. Tat ca dung **deferred download** (cung pattern voi document o Phase 2)
3. Sticker va video_note chi gui text description (khong co file_name, it gia tri)

## Files can modify/create

| File | Thay doi |
|---|---|
| `channel/server.ts` | Them 5 handler: `message:voice`, `message:audio`, `message:video`, `message:video_note`, `message:sticker` |

> Khong can modify `channel/lib.ts` — reuse hoan toan `pushMessage()` voi `extraMeta` va `downloadTelegramFile()` tu Phase 1-2.

## Tung buoc implement

### Buoc 1: Voice handler

**File:** `channel/server.ts` — sau `bot.on("message:document", ...)`

```typescript
bot.on("message:voice", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const voice = ctx.message.voice;
    const duration = voice.duration;
    const text = ctx.message.caption ?? `(voice message, ${duration}s)`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "voice",
      attachment_file_id: voice.file_id,
      attachment_size: voice.file_size ? String(voice.file_size) : undefined,
      attachment_mime: voice.mime_type ?? "audio/ogg",
    });

    process.stderr.write(`bridge channel: voice received from ${username} (${duration}s)\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: voice handler error: ${err}\n`);
  }
});
```

> **Note:** Voice message luon la OGG/OPUS. Claude khong the transcribe truc tiep nhung co the thong bao cho user va download file neu can.

### Buoc 2: Audio handler

```typescript
bot.on("message:audio", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const audio = ctx.message.audio;
    const name = safeName(audio.file_name);
    const title = audio.title ?? name ?? "audio";
    const text = ctx.message.caption ?? `(audio: ${title})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "audio",
      attachment_file_id: audio.file_id,
      attachment_size: audio.file_size ? String(audio.file_size) : undefined,
      attachment_mime: audio.mime_type,
      attachment_name: name,
    });

    process.stderr.write(`bridge channel: audio received from ${username}: ${title}\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: audio handler error: ${err}\n`);
  }
});
```

### Buoc 3: Video handler

```typescript
bot.on("message:video", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const video = ctx.message.video;
    const name = safeName(video.file_name);
    const text = ctx.message.caption ?? `(video: ${name ?? "video"}, ${video.duration}s)`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "video",
      attachment_file_id: video.file_id,
      attachment_size: video.file_size ? String(video.file_size) : undefined,
      attachment_mime: video.mime_type,
      attachment_name: name,
    });

    process.stderr.write(`bridge channel: video received from ${username}: ${name ?? "video"} (${video.duration}s)\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: video handler error: ${err}\n`);
  }
});
```

### Buoc 4: Video Note handler (Telegram circles)

```typescript
bot.on("message:video_note", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const vn = ctx.message.video_note;
    const text = `(video note, ${vn.duration}s)`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "video_note",
      attachment_file_id: vn.file_id,
      attachment_size: vn.file_size ? String(vn.file_size) : undefined,
    });

    process.stderr.write(`bridge channel: video_note received from ${username} (${vn.duration}s)\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: video_note handler error: ${err}\n`);
  }
});
```

### Buoc 5: Sticker handler (text-only, khong download)

```typescript
bot.on("message:sticker", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const sticker = ctx.message.sticker;
    const emoji = sticker.emoji ?? "";
    const setName = sticker.set_name ?? "";
    const text = `(sticker ${emoji}${setName ? ` from ${setName}` : ""})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts);
    // Sticker: chi gui text, KHONG gui attachment meta
    // Ly do: sticker it gia tri khi download, emoji du thong tin

    process.stderr.write(`bridge channel: sticker received from ${username}: ${emoji}\n`);
  } catch (err) {
    process.stderr.write(`bridge channel: sticker handler error: ${err}\n`);
  }
});
```

### Buoc 6 (Optional): Animation (GIF) handler

```typescript
bot.on("message:animation", async (ctx) => {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  try {
    const ts = new Date(ctx.message.date * 1000).toISOString();
    const anim = ctx.message.animation;
    const name = safeName(anim.file_name);
    const text = ctx.message.caption ?? `(GIF: ${name ?? "animation"})`;

    const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
    const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };
    pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
      attachment_kind: "animation",
      attachment_file_id: anim.file_id,
      attachment_size: anim.file_size ? String(anim.file_size) : undefined,
      attachment_mime: anim.mime_type,
      attachment_name: name,
    });
  } catch (err) {
    process.stderr.write(`bridge channel: animation handler error: ${err}\n`);
  }
});
```

## Refactoring co hoi: Extract common handler

Tat ca cac handler deu co chung pattern. Co the extract:

```typescript
type AttachmentMeta = {
  kind: string;
  file_id: string;
  size?: number;
  mime?: string;
  name?: string;
};

async function handleFileMessage(
  ctx: any,
  text: string,
  attachment?: AttachmentMeta
) {
  const chatId = String(ctx.chat.id);
  const userId = String(ctx.from.id);
  const username = ctx.from.username ?? userId;
  const messageId = String(ctx.message.message_id);

  if (!isAllowed(userId, CONFIG_FILE)) return;

  const ts = new Date(ctx.message.date * 1000).toISOString();
  const trackingId = trackInbound(msgDb, chatId, userId, username, text, messageId);
  const notifier: import("./lib").McpNotifier = { notification: (msg) => queuedNotification(msg) };

  const extraMeta = attachment ? {
    attachment_kind: attachment.kind,
    attachment_file_id: attachment.file_id,
    attachment_size: attachment.size ? String(attachment.size) : undefined,
    attachment_mime: attachment.mime,
    attachment_name: attachment.name,
  } : undefined;

  pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, extraMeta);
}
```

> **Quyet dinh:** Refactor nay la optional. Co the lam o Phase 4 (cleanup) hoac de nguyen inline cho ro rang.

## Test cases

### Manual test

1. **Voice:** Gui voice message → verify Claude nhan `(voice message, Ns)` voi `attachment_kind=voice`
2. **Audio:** Gui file nhac → verify Claude nhan metadata voi title
3. **Video:** Gui video → verify Claude nhan metadata
4. **Video Note:** Gui video tron → verify nhan text mo ta
5. **Sticker:** Gui sticker → verify Claude nhan emoji text, KHONG co `attachment_file_id`
6. **GIF:** Gui GIF → verify metadata tuong tu document
7. **Download voice:** Claude goi `download_attachment` cho voice → verify download thanh cong, tra ve `.ogg` path

### Edge cases

- File > 20MB (Telegram Bot API limit) → `getFile` se fail → verify error handled gracefully
- Voice message rat ngan (1s) → verify vẫn xu ly binh thuong
- Sticker khong co emoji → verify fallback text hop ly

## Acceptance criteria

- [ ] Voice message → MCP notification voi `attachment_kind=voice`, `attachment_file_id`
- [ ] Audio file → MCP notification voi `attachment_kind=audio` + metadata
- [ ] Video file → MCP notification voi `attachment_kind=video` + metadata
- [ ] Video note → MCP notification voi `attachment_kind=video_note`
- [ ] Sticker → MCP notification chi co text (khong co attachment meta)
- [ ] Animation/GIF → MCP notification voi `attachment_kind=animation`
- [ ] Tat ca file types co the download qua `download_attachment` tool (tru sticker)
- [ ] Access control van hoat dong cho tat ca handler
- [ ] Khong handler nao crash server khi gap loi

## Dependencies

- **Phu thuoc Phase 1:** `INBOX_DIR`, `downloadTelegramFile()`, `pushMessage()` voi `extraMeta`
- **Phu thuoc Phase 2:** `safeName()`, `download_attachment` tool (reuse cho voice/audio/video download)
- Phase 4 se cleanup va polish tat ca handler nay
