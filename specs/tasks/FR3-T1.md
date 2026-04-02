# FR3-T1: File Receiving Phase 3 — Voice / Audio / Video / Sticker / Animation Handlers

> **Phase:** File Receiving Phase 3
> **Priority:** Nice-to-have
> **Estimated effort:** 1-2 hours

## Refs

- Plan: plan/file-receiving/phase-3-voice-audio-video.md
- Phase 1: specs/tasks/FR1-T1.md (completed — pushMessage extraMeta, downloadTelegramFile, INBOX_DIR)
- Phase 2: specs/tasks/FR2-T1.md (completed — safeName, download_attachment tool, document handler)
- Modules: channel/server.ts
- Dependencies: FR1-T1, FR2-T1

## What This Task Does

Add 6 Telegram message handlers to cover all remaining file types: voice, audio, video, video_note, sticker, and animation (GIF). All use deferred download pattern (metadata only) except sticker which is text-only (emoji description, no attachment meta). All reuse existing `pushMessage()` with `extraMeta` and existing access control pattern.

## Key Architecture Constraints

- Deferred download: all handlers push metadata only, no eager download
- Sticker is text-only: emoji + set_name description, NO attachment_file_id
- Reuse `safeName()` for audio/video/animation filenames
- Reuse `pushMessage()` with extraMeta for attachment metadata
- Access control gate (`isAllowed`) before processing every message type
- All handlers wrapped in try/catch, errors to stderr
- All handlers use `trackInbound()` for message tracking

## Test Plan

This is a TypeScript channel server — no unit test framework is set up for it. Testing is manual per the plan's test cases. The implementation follows the exact same pattern as the existing `message:document` handler which is already proven in production.

## Gaps in Existing Code

- No `message:voice` handler
- No `message:audio` handler
- No `message:video` handler
- No `message:video_note` handler
- No `message:sticker` handler
- No `message:animation` handler
- All 6 handlers follow the identical pattern from existing `message:document` handler — just different Telegram object fields
