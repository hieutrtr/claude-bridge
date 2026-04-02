# FR4-T1: File Receiving Phase 4 — INBOX_DIR Cleanup, Size Limits, Error Handling

> **Phase:** File Receiving Phase 4
> **Priority:** Production (final phase)
> **Estimated effort:** 1-2 hours

## Refs

- Plan: plan/file-receiving/phase-4-cleanup.md
- Phase 1: specs/tasks/FR1-T1.md (completed — pushMessage extraMeta, downloadTelegramFile, INBOX_DIR)
- Phase 2: specs/tasks/FR2-T1.md (completed — safeName, download_attachment tool, document handler)
- Phase 3: specs/tasks/FR3-T1.md (completed — voice/audio/video/video_note/sticker/animation handlers)
- Modules: channel/lib.ts, channel/server.ts
- Dependencies: FR1-T1, FR2-T1, FR3-T1

## What This Task Does

Add production hardening to the file-receiving pipeline:
1. `cleanupInbox()` — deletes files older than 24h from INBOX_DIR
2. `FILE_SIZE_LIMIT` constant (20MB) — enforced before and after download
3. Upgrade `downloadTelegramFile()` with `fileSizeBytes` param, AbortController 30s timeout, double-check size after download, sanitize extension
4. Integrate cleanup on startup + setInterval every 6h, update photo handler to pass `file_size`, update document handler to reject oversized files with Telegram reply, improve `download_attachment` error message

## Key Architecture Constraints

- `FILE_SIZE_LIMIT` = 20 * 1024 * 1024 (20MB — Telegram Bot API limit)
- Size check BEFORE download when `fileSizeBytes` is provided
- Double-check actual buffer size AFTER download
- 30s timeout via AbortController on fetch
- Extension sanitized: `ext.replace(/[^a-zA-Z0-9]/g, "")`
- `cleanupInbox()` handles non-existent dir (returns 0), skips non-files
- Cleanup interval cleared on shutdown
- All errors logged with `bridge channel:` prefix, never crash server

## Test Plan

Happy path:
- `cleanupInbox` deletes files older than maxAgeMs
- `FILE_SIZE_LIMIT` equals 20MB (20 * 1024 * 1024)
- `downloadTelegramFile` works normally when fileSizeBytes is under limit

Edge cases:
- `cleanupInbox` returns 0 for non-existent directory
- `cleanupInbox` skips files newer than maxAgeMs
- `downloadTelegramFile` rejects file when fileSizeBytes exceeds limit (returns undefined, never calls getFile)

Errors:
- Download timeout after 30s (AbortController)
- Network errors during download
- getFile API errors

## Gaps in Existing Code

- No `FILE_SIZE_LIMIT` constant
- No `cleanupInbox()` function
- `downloadTelegramFile()` has no size check, no timeout, no extension sanitization
- No cleanup interval in server startup/shutdown
- Photo handler doesn't pass `file_size` to download
- Document handler doesn't reject oversized files with user notification
- `download_attachment` error message doesn't mention size limit
