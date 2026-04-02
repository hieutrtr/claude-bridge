# FR1-T1: File Receiving Phase 1 — Photo Eager Download

> **Phase:** File Receiving Phase 1
> **Priority:** MVP
> **Estimated effort:** 2-3 hours

## Plan Reference

- `plan/file-receiving/phase-1-photo.md` — full implementation spec
- `research/telegram-file-handling.md` — Telegram Bot API analysis + official plugin reference

## Objective

When a user sends a photo from Telegram, Bridge Channel Server:
1. Downloads the photo eagerly to `INBOX_DIR` (~/.claude-bridge/inbox/)
2. Pushes MCP notification with `image_path` in meta
3. Claude Code reads the image file (multimodal) and understands the content

## Files to Modify

| File | Changes |
|---|---|
| `channel/lib.ts` | Extend `pushMessage()` with optional `extraMeta` param; add `downloadTelegramFile()` helper |
| `channel/server.ts` | Add `INBOX_DIR` constant; add `message:photo` handler; update imports; update MCP instructions |

## Architecture Constraints

- Backward compatible: existing callers of `pushMessage()` must work unchanged
- `downloadTelegramFile()` accepts injected `getFile` function (testable without bot)
- File naming: `{timestamp}-{file_unique_id}.{ext}` (no user-controlled filenames)
- Error in download must not crash server (log + continue, image_path = undefined)
- Access control gate before download (reject non-allowed users early)

## Test Plan

### Unit tests (`channel/__tests__/lib.test.ts`)

1. **pushMessage with extraMeta** — includes extra fields in notification meta
2. **pushMessage without extraMeta** — backward compatible, no extra fields
3. **pushMessage extraMeta with undefined values** — undefined values filtered out
4. **downloadTelegramFile happy path** — mock getFile + fetch, verify file written
5. **downloadTelegramFile with getFile failure** — returns undefined, no crash
6. **downloadTelegramFile with HTTP error** — returns undefined, no crash
7. **downloadTelegramFile with missing file_path** — returns undefined
8. **downloadTelegramFile filename format** — timestamp-uniqueId.ext
9. **downloadTelegramFile extOverride** — uses override ext when provided

### Integration (manual)

1. Send photo from Telegram → file appears in ~/.claude-bridge/inbox/
2. Photo with caption → content = caption text
3. Photo without caption → content = "(photo)"
4. Photo from non-allowed user → rejected, no download

## Gaps / Risks

- `downloadTelegramFile` uses global `fetch` — test needs mock/spy
- File system writes in tests — use tmpdir for isolation
- Phase 2 will reuse `downloadTelegramFile()` and `extraMeta` pattern
