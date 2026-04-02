# File Receiving — Implementation Plan

> Nhan file tu Telegram qua Bridge Channel Server

## Overview

```
                    +-- Phase 1: Photo --> eager download --> image_path in meta
Telegram message ---+-- Phase 2: Document --> deferred --> attachment_file_id + download_attachment tool
                    +-- Phase 3: Voice/Audio/Video --> deferred --> attachment meta
                    +-- Phase 4: Cleanup, size limits, error handling
```

## Phases

| Phase | File | Effort | Priority |
|---|---|---|---|
| 1 | [phase-1-photo.md](phase-1-photo.md) | ~2-3h | MVP |
| 2 | [phase-2-document.md](phase-2-document.md) | ~2-3h | Cao |
| 3 | [phase-3-voice-audio-video.md](phase-3-voice-audio-video.md) | ~1-2h | Nice-to-have |
| 4 | [phase-4-cleanup.md](phase-4-cleanup.md) | ~1-2h | Production |

**Tong:** ~6-10h

## Dependency Graph

```
Phase 1 (Photo) ---> Phase 2 (Document) ---> Phase 3 (Voice/Audio/Video)
       \                    \                          |
        \                    \                         v
         +----- Phase 4 co the bat dau sau Phase 2 ----+
```

## Research

Xem [research/telegram-file-handling.md](../../research/telegram-file-handling.md) cho phan tich chi tiet.

## Files thay doi

| File | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|---|---|---|---|---|
| `channel/server.ts` | INBOX_DIR, photo handler | document handler, download_attachment tool | voice/audio/video/sticker handlers | cleanup interval, size check |
| `channel/lib.ts` | pushMessage extraMeta, downloadTelegramFile | safeName() | — | cleanupInbox(), FILE_SIZE_LIMIT, download timeout |
