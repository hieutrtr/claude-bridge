# W3.2: Dispatcher

## Description
Implement Dispatcher with Bun.spawn({detached: true}), PID tracking, result/stderr paths,
session-id-to-uuid conversion, graceful kill (SIGTERM→wait→SIGKILL).

## Python Source: `src/claude_bridge/dispatcher.py` (114 LOC, 6 functions)
## TS Target: `src/execution/dispatcher.ts`
