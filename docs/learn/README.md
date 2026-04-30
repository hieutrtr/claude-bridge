# Claude Bridge — Learn the Stack

Teaching-oriented docs for developers who want to build a mental model of the
technologies used by claude-bridge. Read these *before* diving into the code.

Start with [`00-roadmap.md`](00-roadmap.md) — it explains who these docs are
for, what to install first, and which chapter to read when.

## Chapters

| # | Chapter | Topic |
| --- | --- | --- |
| 00 | [Roadmap](00-roadmap.md) | Prerequisites, reading order, suggested paths |
| 01 | [Bun](01-bun.md) | Runtime, package manager, test runner, key APIs |
| 02 | [TypeScript](02-typescript.md) | Strict mode and project conventions |
| 03 | [SQLite + WAL](03-sqlite-wal.md) | Embedded DB + concurrent-writer pattern |
| 04 | [Model Context Protocol](04-mcp.md) | Tools, stdio JSON-RPC, SDK, building a minimal server |
| 05 | [Claude Code as a platform](05-claude-code.md) | Agents, sessions, hooks, worktrees, memory |
| 06 | [Telegram + Grammy](06-telegram-grammy.md) | Bot API, long polling, middleware, context |
| 07 | [Daemons + tmux](07-daemons-and-tmux.md) | launchd, systemd user units, tmux supervision |
| 08 | [Zod](08-zod.md) | Schema-first validation at boundaries |

## This directory vs `../specs/`

- **`docs/learn/`** (this directory) — teaches you the stack. Vendor-agnostic
  where possible; focused on concepts, with short project examples.
- **[`../specs/`](../specs/)** — code reference for the bridge itself. Assumes
  you already know the stack. Heavy use of `src/path:line` pointers.

Use `learn/` to build knowledge. Use `specs/` to find where something lives in
the code.

## Conventions

- Every chapter has exercises. Do them in a scratch directory.
- Every chapter ends with canonical further-reading links (official docs).
- No emojis. No marketing prose. Teaching tone throughout.
- Chapters are standalone — you can skip any you already know.
