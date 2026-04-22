# Claude Bridge — Technical Specs

Per-subsystem technical references for maintainers. Each doc is a deep dive into
one area of the code, with file:line pointers so you can jump straight into the
source while reading.

For the high-level architecture narrative, see
[`../ARCHITECTURE.md`](../ARCHITECTURE.md). For the wave-by-wave build plan, see
[`../IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md).

## Reading order

Start with `00-overview.md` to orient, then jump to whichever subsystem you are
about to touch. The subsystem docs cross-reference each other where seams cross.

| Doc | Scope | Good for |
| --- | --- | --- |
| [00-overview.md](00-overview.md) | Module map, end-to-end request lifecycle, boot sequence, glossary | Orienting a new maintainer; finding which doc to read next |
| [01-data-layer.md](01-data-layer.md) | `src/data/` — `bridge.db` + `messages.db` schemas, WAL, sessions, interfaces, migrations | Adding a column or table; debugging schema drift; writing a new query |
| [02-execution-pipeline.md](02-execution-pipeline.md) | `src/execution/` + agent `.md` Stop-hook wiring — dispatch → spawn → watcher → on-complete → notify | Debugging "task spawned but never completed" or "notification never fired" |
| [03-orchestration.md](03-orchestration.md) | `src/orchestration/` — loop lifecycle, evaluator contract, scheduler | Touching loops/schedules; understanding iterative task execution |
| [04-mcp-and-channels.md](04-mcp-and-channels.md) | `src/mcp/` + `src/channel/` — MCP server, tools, Telegram inbound, channel adapter pattern | Adding an MCP tool or a new channel adapter (Slack, Discord) |
| [05-cli.md](05-cli.md) | `src/cli/` — command dispatcher, `setup-bot`, agent `.md` / `CLAUDE.md` generation, `memory`, `doctor` | Adding a subcommand; debugging scaffolding; understanding `doctor` checks |
| [06-infrastructure.md](06-infrastructure.md) | `src/infra/` + `src/config.ts` — daemon, startup orchestrator, permissions, tmux, multi-instance | Debugging daemon start/stop; `CLAUDE_BRIDGE_HOME` isolation; launchd/systemd |
| [07-testing-and-conventions.md](07-testing-and-conventions.md) | `tests/` layout, Bun runtime conventions, build/typecheck/test loop | Writing a new test; running the pre-push checklist; contributing a PR |

## Conventions used in these docs

- **File references** are written as `src/path/file.ts:123` so they resolve in
  any editor that supports GitHub-style linking (VS Code, JetBrains, etc.).
- **Sizes:** each doc is 300–460 lines — readable in one sitting.
- **No code dumps:** function bodies are referenced by line range, not pasted.
  Read the source alongside the doc.
- **Honest gaps flagged:** where a feature is stubbed, partial, or unwired, the
  doc says so rather than implying it works. Look for "gotcha" / "known gap"
  sections.

## Keeping these docs current

These are reference docs, not tutorials — they claim things about the current
code. When you change code that the doc describes, update the doc in the same
commit. The doc that lies is worse than the doc that doesn't exist.
