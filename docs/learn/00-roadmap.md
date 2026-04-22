# Learning Roadmap

This roadmap is for a developer who wants to work on claude-bridge and wants to
*understand the stack* rather than just copy patterns from the codebase.

The eight chapters in this directory are stack-focused: they teach each
technology (Bun, TypeScript, SQLite+WAL, MCP, Claude Code, Grammy/Telegram,
daemons/tmux, Zod) with tiny abstract examples, then show how the bridge uses
them. They are deliberately **not** a code tour of `src/`. For that, see
[`../specs/`](../specs/).

## Who this is for

- You can write JavaScript. You know TypeScript exists.
- You have shipped at least one HTTP API or CLI tool.
- You've used a Postgres or MySQL server. You may have never opened SQLite.
- You've used `systemd` to check a service status but never written a unit file.
- You use Claude Code interactively and have configured one or two things in
  `~/.claude/settings.json`, but you've never written an MCP server or a Stop
  hook.

If you check most of the above boxes, this roadmap is sized for you. Plan for
8–15 hours to work through the whole set with the exercises. You can skip
chapters you already know — each is standalone.

## Prerequisites to install

Before chapter 1, make sure you have:

- **Bun** (`curl -fsSL https://bun.sh/install | bash`) — verify with `bun --version`.
- **git** (2.5+ for worktree support).
- **A terminal multiplexer** — `tmux` on your PATH.
- **The `sqlite3` CLI** — ships with macOS; `apt install sqlite3` on Debian/Ubuntu.
- **Claude Code CLI** — `npm i -g @anthropic-ai/claude-code`, then `claude --version`.
- **A Telegram account** — free to create a bot via [@BotFather](https://t.me/BotFather).

You do **not** need to clone claude-bridge to follow the chapters; the
exercises are self-contained scratch-dir work. You will understand the bridge
better if you have it cloned to refer to, though.

## Chapter order

The chapters are numbered but not strictly linear. The foundational four
(Bun, TypeScript, SQLite, MCP) are prerequisites for the rest. The remaining
four stand alone.

```
         01-bun ─────┐
                     │
 02-typescript ──────┤
                     ├──► 05-claude-code ──► (then the repo makes sense)
03-sqlite-wal ──────┤                ▲
                     │                │
      04-mcp ────────┘                │
                                      │
06-telegram-grammy  ──────────────────┤
                                      │
07-daemons-and-tmux ──────────────────┤
                                      │
       08-zod ────────────────────────┘
```

## Chapter index

| # | Chapter | What you'll learn | Lines | Est. time |
| --- | --- | --- | --- | --- |
| 01 | [Bun](01-bun.md) | The runtime, package manager, test runner, `Bun.spawn`, `bun:sqlite`, the `.js`-import-for-`.ts` convention | 343 | 45 min |
| 02 | [TypeScript](02-typescript.md) | Strict mode flags that matter, discriminated unions, narrowing, exhaustiveness, the project's TS conventions | 498 | 60 min |
| 03 | [SQLite + WAL](03-sqlite-wal.md) | Embedded-DB mental model, WAL mode, the "daemon + stop-hook subprocess" concurrent-writer pattern, schema design choices | 690 | 90 min |
| 04 | [Model Context Protocol](04-mcp.md) | What MCP is, stdio JSON-RPC wire, tools/resources/prompts, how to build a minimal MCP server, Inspector | 596 | 90 min |
| 05 | [Claude Code as a platform](05-claude-code.md) | `--agent`, `--session-id`, hooks (esp. Stop), worktree isolation, Auto Memory, MCP client integration, prompt caching | 718 | 90 min |
| 06 | [Telegram + Grammy](06-telegram-grammy.md) | Telegram Bot API, BotFather, long polling vs webhooks, Grammy context/middleware/filters, escaping pitfalls | 577 | 60 min |
| 07 | [Daemons and tmux](07-daemons-and-tmux.md) | Unix process model, launchd, systemd user units, tmux as a supervisor-adjacent tool, debugging won't-start daemons | 706 | 90 min |
| 08 | [Zod](08-zod.md) | Schema-first validation at boundaries, `parse` vs `safeParse`, discriminated unions, `z.infer`, error formatting | 461 | 45 min |

## Suggested paths

**"I just want to fix a bug in dispatch"** — skim 01 (Bun) and 02 (TS), then
read 03 (SQLite WAL) carefully, then 05 (Claude Code). You can skip the rest
for now.

**"I want to add a new MCP tool"** — skim 01 and 02, then read 04 (MCP)
carefully, then look at [`../specs/04-mcp-and-channels.md`](../specs/04-mcp-and-channels.md).
08 (Zod) is useful for validating tool inputs.

**"I want to add a Slack/Discord adapter"** — skim the whole foundational four,
then 06 (Grammy/Telegram — for the existing reference adapter), then
[`../specs/04-mcp-and-channels.md`](../specs/04-mcp-and-channels.md).

**"I want to understand why bridge won't start on my box"** — read 07
(daemons/tmux) and 01 (Bun basics), then
[`../specs/06-infrastructure.md`](../specs/06-infrastructure.md).

**"I want the full mental model"** — read all eight in order. Budget a weekend.

## How to use each chapter

Each chapter follows the same pattern:

1. **Concept** — what the technology is, without reference to this project.
2. **Tiny abstract examples** — code you can paste into a scratch file and run.
3. **How claude-bridge uses it** — a short tour, with pointers to the reference
   doc in [`../specs/`](../specs/) for code-level details.
4. **Pitfalls** — the specific footguns maintainers have tripped over.
5. **Exercises** — three short hands-on tasks. Do these. They're the whole point.
6. **Further reading** — canonical links only (official docs), not blog posts.

The exercises are small (5–15 minutes each). Do them in a scratch directory —
`mkdir ~/scratch && cd ~/scratch` — not in the claude-bridge repo.

## After you finish

Pick a real task from the repo and implement it:

1. Read [`../specs/00-overview.md`](../specs/00-overview.md) for the big picture.
2. Read the relevant spec chapter for whatever you're changing.
3. Make a branch, write tests, run `bun test` and `bun run typecheck` green, and
   push a PR.

The spec docs are for maintainers who already know the stack. The learn docs
(this directory) are to get you to that point. Don't skip them if you're not
sure — they're faster than trying to reverse-engineer the intent from code.
