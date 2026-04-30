# Phase 4: INBOX_DIR Cleanup, Size Limits, Error Handling

> Uu tien: **Quan trong cho production** — tranh day disk, bao mat, va stability.

---

## Muc tieu

1. Tu dong cleanup file cu trong `INBOX_DIR` (> 24h)
2. Enforce file size limit (reject > 20MB truoc khi download)
3. Error handling day du: timeout, network errors, expired file_id
4. Structured logging cho tat ca file events

## Files can modify/create

| File | Thay doi |
|---|---|
| `channel/server.ts` | Them cleanup interval, size check truoc download |
| `channel/lib.ts` | Them `cleanupInbox()`, `FILE_SIZE_LIMIT`, nang cap `downloadTelegramFile()` voi size check |

## Tung buoc implement

### Buoc 1: File size limit constant + validation

**File:** `channel/lib.ts` — them constant va update `downloadTelegramFile()`

```typescript
/** Maximum file size in bytes (20MB — Telegram Bot API limit) */
export const FILE_SIZE_LIMIT = 20 * 1024 * 1024; // 20MB
```

Update `downloadTelegramFile()` signature — them optional `fileSizeBytes` parameter:

```typescript
export async function downloadTelegramFile(
  getFile: (fileId: string) => Promise<{ file_path?: string; file_unique_id: string }>,
  token: string,
  fileId: string,
  inboxDir: string,
  extOverride?: string,
  fileSizeBytes?: number  // <-- THEM
): Promise<string | undefined> {
  // Size check TRUOC khi download
  if (fileSizeBytes && fileSizeBytes > FILE_SIZE_LIMIT) {
    const sizeMB = (fileSizeBytes / 1024 / 1024).toFixed(1);
    process.stderr.write(
      `bridge channel: file too large (${sizeMB}MB > ${FILE_SIZE_LIMIT / 1024 / 1024}MB), skipping download\n`
    );
    return undefined;
  }

  try {
    const file = await getFile(fileId);
    if (!file.file_path) {
      process.stderr.write("bridge channel: getFile returned no file_path — file may have expired\n");
      return undefined;
    }

    const url = `https://api.telegram.org/file/bot${token}/${file.file_path}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout

    try {
      const res = await fetch(url, { signal: controller.signal });
      clearTimeout(timeoutId);

      if (!res.ok) {
        process.stderr.write(`bridge channel: file download HTTP ${res.status}\n`);
        return undefined;
      }

      const buf = Buffer.from(await res.arrayBuffer());

      // Double-check actual size
      if (buf.length > FILE_SIZE_LIMIT) {
        process.stderr.write(
          `bridge channel: downloaded file exceeds limit (${buf.length} bytes), discarding\n`
        );
        return undefined;
      }

      const ext = extOverride ?? file.file_path.split(".").pop() ?? "bin";
      const safeExt = ext.replace(/[^a-zA-Z0-9]/g, "");
      const safeUniqueId = file.file_unique_id.replace(/[^a-zA-Z0-9_-]/g, "");
      const filename = `${Date.now()}-${safeUniqueId}.${safeExt}`;
      const localPath = join(inboxDir, filename);

      const { mkdirSync, writeFileSync } = await import("fs");
      mkdirSync(inboxDir, { recursive: true });
      writeFileSync(localPath, buf);

      process.stderr.write(`bridge channel: downloaded ${localPath} (${buf.length} bytes)\n`);
      return localPath;
    } catch (err: any) {
      clearTimeout(timeoutId);
      if (err.name === "AbortError") {
        process.stderr.write("bridge channel: file download timed out after 30s\n");
      } else {
        process.stderr.write(`bridge channel: file download network error: ${err}\n`);
      }
      return undefined;
    }
  } catch (err) {
    process.stderr.write(`bridge channel: getFile API error: ${err}\n`);
    return undefined;
  }
}
```

**Thay doi so voi Phase 1:**
- Them `fileSizeBytes` parameter de check truoc khi download
- Them `AbortController` voi 30s timeout cho fetch
- Them double-check kich thuoc sau download
- Sanitize extension (loai bo ky tu dac biet)
- Structured error messages (phan biet timeout, HTTP error, network error, API error)

### Buoc 2: Update callers — truyen file size

**File:** `channel/server.ts`

**Photo handler** — photos co `file_size` tren `PhotoSize`:

```typescript
// Trong bot.on("message:photo", ...) handler:
const imagePath = await downloadTelegramFile(
  (fid) => ctx.api.getFile(fid),
  TOKEN,
  best.file_id,
  INBOX_DIR,
  undefined,
  best.file_size  // <-- THEM: truyen file size de check limit
);
```

**download_attachment handler** — can truyen size tu args hoac tu getFile:

```typescript
case "download_attachment": {
  const { file_id } = args as { file_id: string };
  if (!file_id) {
    return { content: [{ type: "text", text: "Error: file_id is required" }], isError: true };
  }

  // Note: khong co file_size o day vi chi co file_id
  // Size check se xay ra sau khi download (double-check trong downloadTelegramFile)
  const localPath = await downloadTelegramFile(
    (fid) => bot.api.getFile(fid),
    TOKEN,
    file_id,
    INBOX_DIR
  );

  if (!localPath) {
    return {
      content: [{
        type: "text",
        text: "Error: failed to download file. Possible causes:\n" +
              "- File has expired (Telegram files expire after ~1 hour)\n" +
              "- File exceeds 20MB size limit\n" +
              "- Network error or timeout"
      }],
      isError: true,
    };
  }

  return { content: [{ type: "text", text: localPath }] };
}
```

### Buoc 3: INBOX_DIR cleanup function

**File:** `channel/lib.ts` — them function moi

```typescript
/**
 * Clean up old files in INBOX_DIR.
 * Deletes files older than maxAgeMs (default 24 hours).
 * Returns number of files deleted.
 */
export function cleanupInbox(inboxDir: string, maxAgeMs: number = 24 * 60 * 60 * 1000): number {
  const { readdirSync, statSync, unlinkSync, existsSync } = require("fs");

  if (!existsSync(inboxDir)) return 0;

  const now = Date.now();
  let deleted = 0;

  try {
    const files = readdirSync(inboxDir) as string[];
    for (const file of files) {
      const filePath = join(inboxDir, file);
      try {
        const stat = statSync(filePath);
        if (!stat.isFile()) continue;

        const age = now - stat.mtimeMs;
        if (age > maxAgeMs) {
          unlinkSync(filePath);
          deleted++;
          process.stderr.write(`bridge channel: cleaned up ${file} (age: ${Math.round(age / 3600000)}h)\n`);
        }
      } catch (err) {
        // Skip files that can't be stat'd or deleted
        process.stderr.write(`bridge channel: cleanup skip ${file}: ${err}\n`);
      }
    }
  } catch (err) {
    process.stderr.write(`bridge channel: cleanup error: ${err}\n`);
  }

  return deleted;
}
```

### Buoc 4: Tich hop cleanup vao server

**File:** `channel/server.ts`

**Them import:**
```typescript
import {
  // ... existing ...
  cleanupInbox,
  FILE_SIZE_LIMIT,
} from "./lib";
```

**Startup cleanup + interval** — trong `main()`, sau outbound/retry intervals:

```typescript
// Cleanup inbox on startup
cleanupInbox(INBOX_DIR);

// Periodic cleanup every 6 hours
const cleanupInterval = setInterval(() => {
  try {
    const deleted = cleanupInbox(INBOX_DIR);
    if (deleted > 0) {
      process.stderr.write(`bridge channel: inbox cleanup: ${deleted} files removed\n`);
    }
  } catch (err) {
    process.stderr.write(`bridge channel: cleanup interval error: ${err}\n`);
  }
}, 6 * 60 * 60 * 1000); // 6 hours
```

**Cleanup interval trong cleanup function:**
```typescript
function cleanup() {
  if (cleanedUp) return;
  cleanedUp = true;
  pollingActive = false;
  if (outboundInterval) clearInterval(outboundInterval);
  if (retryInterval) clearInterval(retryInterval);
  if (cleanupInterval) clearInterval(cleanupInterval);  // <-- THEM
  // ... rest unchanged
}
```

> **Luu y:** Khai bao `cleanupInterval` o scope cung cap voi `outboundInterval`.

### Buoc 5: Size limit thong bao cho user

**File:** `channel/server.ts` — trong cac file handler

Khi file qua lon, gui thong bao cho user:

```typescript
// Trong message:photo handler, sau downloadTelegramFile:
if (!imagePath && best.file_size && best.file_size > FILE_SIZE_LIMIT) {
  // Notify user
  await bot.api.sendMessage(chatId, 
    `Photo too large (${(best.file_size / 1024 / 1024).toFixed(1)}MB). ` +
    `Maximum: ${FILE_SIZE_LIMIT / 1024 / 1024}MB.`
  );
  return;
}
```

Tuong tu cho document handler — check `doc.file_size` truoc khi gui meta:

```typescript
// Trong message:document handler:
if (doc.file_size && doc.file_size > FILE_SIZE_LIMIT) {
  await bot.api.sendMessage(chatId,
    `File "${name ?? 'file'}" too large (${(doc.file_size / 1024 / 1024).toFixed(1)}MB). ` +
    `Maximum: ${FILE_SIZE_LIMIT / 1024 / 1024}MB.`
  );
  return;
}
```

## Test cases

### Unit test

```typescript
// test: cleanupInbox
test("cleanupInbox deletes old files", () => {
  const tmpDir = mkdtempSync(join(tmpdir(), "inbox-"));
  // Create old file (mtime = 25h ago)
  const oldFile = join(tmpDir, "old.jpg");
  writeFileSync(oldFile, "old");
  utimesSync(oldFile, new Date(Date.now() - 25 * 3600000), new Date(Date.now() - 25 * 3600000));
  // Create new file
  const newFile = join(tmpDir, "new.jpg");
  writeFileSync(newFile, "new");

  const deleted = cleanupInbox(tmpDir, 24 * 3600000);
  expect(deleted).toBe(1);
  expect(existsSync(oldFile)).toBe(false);
  expect(existsSync(newFile)).toBe(true);
});

// test: cleanupInbox with non-existent dir
test("cleanupInbox handles non-existent dir", () => {
  const deleted = cleanupInbox("/tmp/nonexistent-inbox-test");
  expect(deleted).toBe(0);
});

// test: downloadTelegramFile rejects oversized
test("downloadTelegramFile rejects file over size limit", async () => {
  const mockGetFile = async () => ({ file_path: "test.jpg", file_unique_id: "abc" });
  const result = await downloadTelegramFile(
    mockGetFile, "token", "file_id", "/tmp/inbox", undefined,
    25 * 1024 * 1024 // 25MB — over limit
  );
  expect(result).toBeUndefined();
});

// test: FILE_SIZE_LIMIT value
test("FILE_SIZE_LIMIT is 20MB", () => {
  expect(FILE_SIZE_LIMIT).toBe(20 * 1024 * 1024);
});
```

### Manual test (integration)

1. **Cleanup startup:** Tao file cu trong `~/.claude-bridge/inbox/` → restart server → verify file bi xoa
2. **Size limit - photo:** (Kho test vi photo thuong nho) → verify logic bang unit test
3. **Size limit - document:** Gui file > 20MB → verify nhan thong bao loi tu bot
4. **Download timeout:** (Simulate bang slow network) → verify error message ro rang
5. **Expired file:** Gui file, doi > 1 gio, goi `download_attachment` → verify error message

### Edge cases

- INBOX_DIR bi xoa giua cac lan chay → `mkdirSync` tao lai
- Permission denied khi xoa file → skip va log
- Empty INBOX_DIR → cleanup chay nhanh, return 0
- File dang bi doc boi Claude khi cleanup chay → race condition nho (acceptable — file da duoc read roi)

## Acceptance criteria

- [ ] `FILE_SIZE_LIMIT` = 20MB, duoc export tu `lib.ts`
- [ ] File > 20MB bi reject TRUOC khi download (khi co `file_size` tu Telegram)
- [ ] File > 20MB sau download bi discard (double-check)
- [ ] User nhan thong bao Telegram khi file qua lon
- [ ] Download co 30s timeout — timeout → error message ro rang
- [ ] `cleanupInbox()` xoa file > 24h trong INBOX_DIR
- [ ] Cleanup chay khi server start va moi 6 gio
- [ ] Cleanup interval duoc clear khi server shutdown
- [ ] Tat ca error cases duoc log voi prefix `bridge channel:` + context cu the
- [ ] Khong error nao crash server

## Dependencies

- **Phu thuoc Phase 1-3:** Tat ca file handlers da implement
- **Day la phase cuoi** — khong co phase nao phu thuoc phase nay
- Co the implement **song song voi Phase 3** neu Phase 1-2 da xong (vi chi modify `downloadTelegramFile()` va them `cleanupInbox()`)
