# File Receiving — Milestone Report

**Date:** 2026-04-03
**Status:** COMPLETE

## Overview

Full file-receiving pipeline for Telegram implemented across 4 phases. Claude Code can now receive photos (eager download), documents/voice/audio/video/animations (deferred download via `download_attachment` tool), and stickers (text-only). Production hardening includes 20MB size limits, 30s download timeout, INBOX_DIR cleanup, and structured error handling.

## Task Summary

| Task | Status | Tests | Gaps Fixed | Notes |
|------|--------|-------|------------|-------|
| FR1.T1 — Photo eager download | done | 6 | `pushMessage` extraMeta, `downloadTelegramFile`, INBOX_DIR | MVP: photos auto-downloaded, path in `image_path` meta |
| FR2.T1 — Document deferred download | done | 6 | `safeName()`, `download_attachment` MCP tool, document handler | Deferred pattern: metadata only, download on-demand |
| FR3.T1 — Voice/Audio/Video/Sticker/Animation | done | 0 (manual) | 6 new handlers | All follow document deferred pattern; sticker is text-only |
| FR4.T1 — Cleanup, size limits, hardening | done | 10 | `FILE_SIZE_LIMIT`, `cleanupInbox()`, timeout, extension sanitize | Production: 20MB limit, 30s timeout, 6h cleanup |

**Total tests:** 66 pass (in `channel/__tests__/lib.test.ts`)

## Architecture Summary

```
Photo       → eager download → image_path in meta → Claude reads file directly
Document    → deferred → attachment_file_id in meta → download_attachment tool
Voice/Audio → deferred → attachment_file_id in meta → download_attachment tool
Video/VNote → deferred → attachment_file_id in meta → download_attachment tool
Animation   → deferred → attachment_file_id in meta → download_attachment tool
Sticker     → text-only → emoji description, no attachment
```

## Key Design Decisions

1. **Eager vs Deferred:** Photos eagerly downloaded (most common, always viewable by Claude). All other types deferred (download only when Claude needs them) — saves bandwidth and storage.
2. **Size limit enforcement:** Pre-download check (when Telegram provides `file_size`) + post-download double-check. User gets a Telegram reply when file is too large.
3. **Extension sanitization:** `ext.replace(/[^a-zA-Z0-9]/g, "")` prevents injection via crafted file extensions.
4. **Cleanup strategy:** On startup + every 6h, files >24h deleted. Interval cleared on shutdown. Handles missing dir, permission errors gracefully.

## Gaps Discovered and Fixed

- `downloadTelegramFile()` had no timeout — could hang forever on slow networks (fixed: 30s AbortController)
- No extension sanitization — malicious file extensions could pass through (fixed: regex cleanup)
- `getFile` returning no `file_path` was silently swallowed — now logged with "may have expired" context
- `download_attachment` error message was vague — now lists 3 possible causes (expiry, size, network)

## Files Changed

| File | Phases | Lines Changed |
|------|--------|--------------|
| `channel/lib.ts` | 1, 2, 4 | +150 (extraMeta, downloadTelegramFile, safeName, cleanupInbox, FILE_SIZE_LIMIT) |
| `channel/server.ts` | 1, 2, 3, 4 | +250 (photo/document/voice/audio/video/sticker/animation handlers, cleanup interval, size checks) |
| `channel/__tests__/lib.test.ts` | 1, 2, 4 | +200 (66 tests total) |

## Acceptance Criteria Verification

- [x] Photos: eager download, `image_path` in meta
- [x] Documents: deferred, `attachment_file_id` + `download_attachment` tool
- [x] Voice/Audio/Video/VideoNote/Animation: deferred, attachment meta
- [x] Sticker: text-only (emoji + set name)
- [x] `FILE_SIZE_LIMIT` = 20MB, exported from `lib.ts`
- [x] File > 20MB rejected before download (when `file_size` known)
- [x] File > 20MB discarded after download (double-check)
- [x] User notified via Telegram when file too large
- [x] 30s download timeout with clear error message
- [x] `cleanupInbox()` deletes files > 24h
- [x] Cleanup on startup + every 6h, interval cleared on shutdown
- [x] All errors logged with `bridge channel:` prefix
- [x] No errors crash server
- [x] `safeName()` strips dangerous characters from filenames

## Blockers

None — all 4 phases complete.

## Next Steps

- Integration testing with real Telegram bot (manual)
- Consider adding file type restrictions (e.g., reject executables)
- Consider compression for large photos before storage
