# FR2-T1: File Receiving Phase 2 — Document Deferred Download + download_attachment Tool

> **Phase:** File Receiving Phase 2
> **Priority:** High
> **Estimated effort:** 2-3 hours

## Refs

- Plan: plan/file-receiving/phase-2-document.md
- Phase 1: specs/tasks/FR1-T1.md (completed)
- Modules: channel/lib.ts, channel/server.ts
- Dependencies: FR1-T1 (pushMessage extraMeta, downloadTelegramFile, INBOX_DIR)

## What This Task Does

Add deferred document file handling: when a user sends a document from Telegram, only metadata is pushed (no download). A new `download_attachment` MCP tool lets Claude fetch the file on-demand. Also adds `safeName()` utility for filename sanitization.

## Key Architecture Constraints

- Deferred download: metadata only in notification, no eager download
- Reuse `downloadTelegramFile()` from Phase 1 inside `download_attachment` tool handler
- `safeName()` strips dangerous characters from Telegram filenames
- Access control gate before processing document
- Error handling: expired file_id, download failure → clear error message

## Test Plan

Happy path:
- safeName strips dangerous characters (< > / \ : * ? " | etc.)
- safeName returns safe filenames unchanged
- pushMessage with document attachment meta fields
- download_attachment tool handler calls downloadTelegramFile and returns path

Edge cases:
- safeName with undefined → returns undefined
- safeName with empty string → returns undefined
- safeName with only dangerous chars → returns undefined
- pushMessage attachment meta with undefined values filtered out

Errors:
- download_attachment with missing file_id → error response
- download_attachment when download fails → error with expiry hint

## Gaps in Existing Code

- No `safeName()` function — need to add to lib.ts
- No `message:document` handler in server.ts
- No `download_attachment` tool definition or handler
- MCP instructions don't mention `attachment_file_id`
