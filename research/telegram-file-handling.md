# Nghiên cứu: Nhận file từ Telegram qua Claude Bridge Channel

> Ngày: 2026-04-02
> Mục tiêu: Phân tích cách implement file attachment handling trong claude-bridge channel server

---

## 1. Telegram Bot API — File Handling

### 1.1 Các loại message chứa file

| Message type | Field chính | Có `file_name`? | Có `mime_type`? | Ghi chú |
|---|---|---|---|---|
| `photo` | `PhotoSize[]` | ❌ | ❌ (luôn JPEG) | Mảng nhiều kích thước, phần tử cuối = lớn nhất |
| `document` | `Document` | ✅ | ✅ | File tổng quát — PDF, ZIP, code, v.v. |
| `video` | `Video` | ✅ | ✅ | Có thêm `width`, `height`, `duration` |
| `voice` | `Voice` | ❌ | ✅ (OGG/OPUS) | Tin nhắn thoại |
| `audio` | `Audio` | ✅ | ✅ | File nhạc, có `title`, `performer` |
| `video_note` | `VideoNote` | ❌ | ❌ | Video tròn (Telegram circles) |
| `sticker` | `Sticker` | ❌ | ❌ | Có `emoji`, `set_name` |
| `animation` | `Animation` | ✅ | ✅ | GIF |

Tất cả đều có chung: `file_id`, `file_unique_id`, `file_size`.

### 1.2 Download flow

```
1. Nhận message → lấy file_id
2. Gọi getFile(file_id) → nhận file_path
3. Download: GET https://api.telegram.org/file/bot<TOKEN>/<file_path>
4. Lưu local
```

### 1.3 Giới hạn

| | Regular Bot API | Local Bot API Server |
|---|---|---|
| **Download** | 20 MB | Không giới hạn |
| **Upload** | 50 MB | 2000 MB |

**Đủ cho use case dev:** code files, screenshots, logs, config files đều dưới 20MB.

### 1.4 Photo — chọn resolution

```typescript
// Photos trả về mảng PhotoSize[] từ nhỏ → lớn
// Phần tử cuối = resolution cao nhất
const best = ctx.message.photo[ctx.message.photo.length - 1]
```

---

## 2. Official Telegram Plugin — Reference Implementation

Claude Code đã có plugin chính thức tại:
`~/.claude/plugins/cache/claude-plugins-official/telegram/0.0.4/server.ts`

### 2.1 Cách plugin xử lý file

**Photo (eager download):**
```typescript
bot.on('message:photo', async ctx => {
  const caption = ctx.message.caption ?? '(photo)'
  await handleInbound(ctx, caption, async () => {
    const best = photos[photos.length - 1]
    const file = await ctx.api.getFile(best.file_id)
    // Download → lưu vào INBOX_DIR
    const path = join(INBOX_DIR, `${Date.now()}-${best.file_unique_id}.${ext}`)
    writeFileSync(path, buf)
    return path  // → meta.image_path
  })
})
```

**Document, voice, video, etc. (deferred download):**
```typescript
bot.on('message:document', async ctx => {
  const doc = ctx.message.document
  await handleInbound(ctx, text, undefined, {
    kind: 'document',
    file_id: doc.file_id,      // → meta.attachment_file_id
    size: doc.file_size,        // → meta.attachment_size
    mime: doc.mime_type,        // → meta.attachment_mime
    name: safeName(doc.file_name), // → meta.attachment_name
  })
})
```

**Download tool (on-demand):**
```typescript
case 'download_attachment': {
  const file = await bot.api.getFile(file_id)
  const url = `https://api.telegram.org/file/bot${TOKEN}/${file.file_path}`
  const buf = Buffer.from(await (await fetch(url)).arrayBuffer())
  const path = join(INBOX_DIR, `${Date.now()}-${uniqueId}.${ext}`)
  writeFileSync(path, buf)
  return { content: [{ type: 'text', text: path }] }
}
```

### 2.2 MCP notification format (với file)

```typescript
mcp.notification({
  method: 'notifications/claude/channel',
  params: {
    content: text,
    meta: {
      chat_id, message_id, user, user_id, ts,
      // Photo → đã download, gửi path
      image_path: '/path/to/downloaded/photo.jpg',
      // Document/video/voice → chưa download, gửi metadata
      attachment_kind: 'document',
      attachment_file_id: 'BAADBBxxxx',
      attachment_size: '1234567',
      attachment_mime: 'application/pdf',
      attachment_name: 'report.pdf',
    },
  },
})
```

Claude Code nhận dạng `<channel>` tag:
- Có `image_path` → Claude tự `Read` file (multimodal)
- Có `attachment_file_id` → Claude gọi `download_attachment` tool → `Read` file

### 2.3 Security

- **Filename sanitization:** `< > [ ] \r \n ;` → `_`
- **Path access control:** Không cho gửi file từ config dir (`.env`, `access.json`)
- **Deferred download:** Không download file cho message bị reject bởi access control

---

## 3. Bridge Channel Server — Hiện trạng

### 3.1 Chỉ xử lý text

```typescript
// channel/server.ts:347 — ONLY message:text
bot.on("message:text", async (ctx) => { ... })
```

Không có handler nào cho `message:photo`, `message:document`, v.v.

### 3.2 pushMessage chỉ gửi text

```typescript
// channel/lib.ts:122-146
export function pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts) {
  notifier.notification({
    method: "notifications/claude/channel",
    params: {
      content: text,
      meta: { chat_id, message_id, user, user_id, ts, tracking_id }
      // ❌ Không có image_path, attachment_file_id, v.v.
    },
  });
}
```

### 3.3 Database không có cột file

```sql
-- inbound_tracking chỉ có:
-- id, chat_id, user_id, username, message_text, message_id, status, ...
-- ❌ Không có: file_id, file_type, file_path, file_size, mime_type
```

### 3.4 Không có download tool

Các MCP tools hiện tại: `reply`, `bridge_dispatch`, `bridge_status`, `bridge_agents`, v.v.
Không có `download_attachment` hay bất kỳ tool nào liên quan đến file.

---

## 4. Đề xuất giải pháp

### 4.1 Chiến lược tổng thể

Áp dụng cùng pattern của official plugin nhưng adapt cho bridge architecture:

```
                    ┌── Photo: eager download → image_path in meta
Telegram message ───┤
                    └── Others: deferred → attachment_file_id in meta
                                              │
                            Claude Code gọi download_attachment tool
                                              │
                                         Lưu vào INBOX_DIR
                                              │
                            Claude Read file → xử lý/dispatch
```

### 4.2 Photo — Eager download

**Tại sao eager?** Claude là multimodal — khi nhận `image_path`, Claude tự đọc ảnh và hiểu nội dung ngay. Không cần thêm bước.

```typescript
bot.on('message:photo', async (ctx) => {
  const caption = ctx.message.caption ?? '(photo)'
  const photos = ctx.message.photo
  const best = photos[photos.length - 1]

  let imagePath: string | undefined
  try {
    const file = await ctx.api.getFile(best.file_id)
    if (file.file_path) {
      const url = `https://api.telegram.org/file/bot${TOKEN}/${file.file_path}`
      const res = await fetch(url)
      const buf = Buffer.from(await res.arrayBuffer())
      const ext = file.file_path.split('.').pop() ?? 'jpg'
      imagePath = join(INBOX_DIR, `${Date.now()}-${best.file_unique_id}.${ext}`)
      mkdirSync(INBOX_DIR, { recursive: true })
      writeFileSync(imagePath, buf)
    }
  } catch (err) {
    process.stderr.write(`bridge channel: photo download failed: ${err}\n`)
  }

  // Track + push with image_path
  const trackingId = trackInbound(db, chatId, userId, username, caption, messageId, imagePath)
  pushMessage(notifier, trackingId, chatId, userId, username, caption, messageId, ts, { image_path: imagePath })
})
```

### 4.3 Document/Audio/Video/Voice — Deferred download

**Tại sao deferred?** Tiết kiệm bandwidth + quota. Chỉ download khi Claude thực sự cần.

```typescript
bot.on('message:document', async (ctx) => {
  const doc = ctx.message.document
  const name = safeName(doc.file_name)
  const text = ctx.message.caption ?? `(document: ${name ?? 'file'})`

  const trackingId = trackInbound(db, chatId, userId, username, text, messageId)
  pushMessage(notifier, trackingId, chatId, userId, username, text, messageId, ts, {
    attachment_kind: 'document',
    attachment_file_id: doc.file_id,
    attachment_size: String(doc.file_size),
    attachment_mime: doc.mime_type,
    attachment_name: name,
  })
})
```

### 4.4 Download attachment tool

Thêm tool `download_attachment` vào channel server:

```typescript
{
  name: 'download_attachment',
  description: 'Download file attachment từ Telegram message. Trả về local path.',
  inputSchema: {
    type: 'object',
    properties: {
      file_id: { type: 'string', description: 'attachment_file_id từ inbound meta' },
    },
    required: ['file_id'],
  },
}

// Handler:
case 'download_attachment': {
  const file_id = args.file_id as string
  const file = await bot.api.getFile(file_id)
  if (!file.file_path) throw new Error('No file_path — file may have expired')
  const url = `https://api.telegram.org/file/bot${TOKEN}/${file.file_path}`
  const res = await fetch(url)
  const buf = Buffer.from(await res.arrayBuffer())
  const ext = (file.file_path.split('.').pop() ?? 'bin').replace(/[^a-zA-Z0-9]/g, '')
  const uniqueId = (file.file_unique_id ?? 'dl').replace(/[^a-zA-Z0-9_-]/g, '')
  const path = join(INBOX_DIR, `${Date.now()}-${uniqueId}.${ext}`)
  mkdirSync(INBOX_DIR, { recursive: true })
  writeFileSync(path, buf)
  return { content: [{ type: 'text', text: path }] }
}
```

### 4.5 Xử lý từng loại file

| File type | Strategy | Claude sẽ làm gì |
|---|---|---|
| **Photo** | Eager download → `image_path` | Read (multimodal) → hiểu nội dung ảnh |
| **Document** | Deferred → `download_attachment` | Download → Read → phân tích nội dung |
| **Voice** | Deferred → `download_attachment` | Download → có thể cần STT service |
| **Audio** | Deferred → metadata only | Thông báo nhận, ít khi cần xử lý |
| **Video** | Deferred → metadata only | Thông báo nhận, ít khi cần xử lý |
| **Sticker** | Text only `(sticker 😀)` | Hiểu context emoji |

**Ưu tiên cho MVP:** Photo + Document. Voice/Audio/Video là nice-to-have.

### 4.6 Dispatch với file context

Khi bridge bot dispatch task cho agent, file path cần được include trong prompt:

```
User gửi screenshot + "fix this bug"
  → Bridge bot nhận: text="fix this bug", image_path="/inbox/123-abc.jpg"
  → Bridge bot Read ảnh → hiểu bug
  → Dispatch: "fix this bug — screenshot at /inbox/123-abc.jpg shows [mô tả]"
```

Hoặc copy file vào worktree của agent:
```
  → Copy /inbox/123-abc.jpg → /worktree/agent/.claude-bridge-files/screenshot.jpg
  → Dispatch: "fix this bug — see .claude-bridge-files/screenshot.jpg"
```

### 4.7 Security concerns

1. **File size validation:** Check `file_size` trước khi download (reject > 20MB)
2. **Filename sanitization:** Strip ký tự nguy hiểm từ `file_name`
3. **Path traversal:** Dùng `file_unique_id` làm tên file, không dùng tên gốc
4. **Disk cleanup:** Cron job xóa file trong INBOX_DIR > 24h
5. **Access control:** Chỉ download file từ allowed users (gate trước download)
6. **MIME type validation:** Không execute file, chỉ read
7. **INBOX_DIR isolation:** Không cho gửi file ngoài INBOX_DIR ra Telegram

---

## 5. Implementation Plan

### Phase 1: Photo support (MVP) — ~2-3 giờ

**Files cần modify:**

| File | Thay đổi |
|---|---|
| `channel/server.ts` | Thêm `bot.on('message:photo')` handler |
| `channel/server.ts` | Thêm `INBOX_DIR` constant |
| `channel/lib.ts` | Mở rộng `pushMessage()` nhận optional attachment meta |
| `channel/lib.ts` | Mở rộng `trackInbound()` lưu file metadata |

**Steps:**
1. Tạo `INBOX_DIR` (`~/.claude-bridge/inbox/`)
2. Thêm `message:photo` handler — download eager, lưu vào INBOX_DIR
3. Mở rộng `pushMessage()` — thêm `image_path` vào meta
4. Mở rộng `trackInbound()` — thêm cột `attachment_type`, `attachment_path` vào DB
5. Test: gửi ảnh từ Telegram → verify Claude nhận được `image_path`

### Phase 2: Document + download tool — ~2-3 giờ

**Files cần modify/create:**

| File | Thay đổi |
|---|---|
| `channel/server.ts` | Thêm `message:document` handler |
| `channel/server.ts` | Thêm `download_attachment` tool definition + handler |
| `channel/lib.ts` | Helper: `safeName()` cho filename sanitization |

**Steps:**
1. Thêm `message:document` handler — deferred (chỉ gửi metadata)
2. Implement `download_attachment` MCP tool
3. Thêm `safeName()` utility function
4. Test: gửi PDF/ZIP → verify Claude có thể download + read

### Phase 3: Voice/Audio/Video — ~1-2 giờ

**Files cần modify:**

| File | Thay đổi |
|---|---|
| `channel/server.ts` | Thêm `message:voice`, `message:audio`, `message:video`, `message:video_note`, `message:sticker` handlers |

**Steps:**
1. Thêm handlers cho từng loại (tất cả deferred)
2. Voice message: download → lưu .ogg → Claude read metadata
3. Test edge cases: file quá lớn, expired file_id

### Phase 4: Cleanup + Polish — ~1 giờ

1. Cron job hoặc startup cleanup cho INBOX_DIR (xóa file > 24h)
2. File size limit enforcement (reject > 20MB early)
3. Error handling: file download timeout, network errors
4. Logging: file received/downloaded/cleaned events

### Tổng effort estimate: ~6-9 giờ

---

## 6. Quyết định mở

1. **Copy file vào worktree hay để INBOX_DIR?**
   - INBOX_DIR đơn giản hơn, nhưng agent trong worktree có thể không access được
   - Copy vào worktree an toàn hơn nhưng phức tạp hơn

2. **Voice message → STT?**
   - Nếu cần transcribe: tích hợp Whisper API (thêm dependency)
   - Nếu không: chỉ gửi metadata, Claude thông báo "received voice message, cannot transcribe"

3. **File retention policy?**
   - 24h? 7 ngày? Configurable?
   - Disk space monitoring?

4. **Tận dụng official plugin thay vì tự implement?**
   - Official plugin đã có đầy đủ file handling
   - Nhưng bridge cần custom tools (dispatch, status, agents)
   - Có thể: merge file handling code từ official plugin vào bridge channel
