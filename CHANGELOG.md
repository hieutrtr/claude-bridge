# Changelog

All notable changes to Claude Bridge are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.1] — 2026-04-30

### Fixed

- **Plugin install path was broken in 1.0.0** — the published tarball was missing
  `mcp.json` (the Claude Code plugin's MCP server manifest), `skills/` (the four
  bundled slash commands `/dispatch`, `/status`, `/loop-review`,
  `/loop-code-review`), and `assets/` (the README hero image). Users installing
  via `bun install -g` were unaffected (CLI runtime only needs `src/`), but
  `/plugin install hieutrtr/claude-bridge` could not start the MCP server.
  Extend the `files` allowlist in `package.json` to include all three.

---

## [1.0.0] — 2026-04-30

### Removed

- **`legacy/` directory** — the frozen Python source kept as reference during the
  beta is dropped. The final Python release remains recoverable at the
  `v0.5.10-python-final` git tag.
- **`MIGRATION-CUTOVER-PLAN.md`** — transitional migration scaffolding.
- **`README_en.md`** — stale English README; the primary `README.md` is now in
  English and is the single source.
- **Pre-migration design docs** — `plan/` and `research/` moved under
  `docs/archive/` for historical reference; they no longer describe the running
  system.

### Notes

`1.0.0` is the stable cutover from the `1.0.0-beta` line. No functional changes
versus the beta — this release marks the deprecation of the Python implementation
and the cleanup of migration-era artifacts on `main`.

---

## [1.0.0-beta] — 2026-04-10

### Changed — Full TypeScript Migration

Claude Bridge has been completely rewritten from Python to TypeScript (Bun runtime).
This is a breaking change from the Python version (0.5.x).

- **Runtime**: Python 3.11+ → Bun (TypeScript)
- **Test suite**: pytest (405 tests) → bun test (541 tests across 36 files, 90%+ coverage)
- **Dependencies**: pip/pipx → `bun install` (`@modelcontextprotocol/sdk`, `grammy`, `zod`)
- **CLI**: `python -m claude_bridge.cli` → `bun run src/cli/index.ts`
- **MCP server**: FastMCP (Python) → `@modelcontextprotocol/sdk` (TypeScript)
- **Stop hook**: `on_complete.py` → `on-complete.ts`
- **Project structure**: `src/claude_bridge/` → modular `src/` (cli/, data/, execution/, orchestration/, infra/, mcp/, channel/)
- **Old code**: Moved to `legacy/` for reference (not deleted)

### Migration from Python

1. Stop all running instances: `bridge stop`
2. `git pull` and `bun install`
3. Regenerate agent files: `bun run src/cli/index.ts create-agent <name> <path>`
4. Re-run setup for bot dirs: `bun run src/cli/index.ts setup-bot <bot-dir>`
5. SQLite database is compatible — no data migration needed

---

## [0.5.8] — 2026-04-09

### Fixed

- **Notification channel resolution for loop tasks** — `on_complete.py` now correctly
  resolves the notification channel when dispatching loop task completions, ensuring
  Telegram notifications reach the right chat.
- **`allowFrom` array handling in channel server** — `loadAllowlist()` in
  `channel/server.ts` now correctly handles `allowFrom` as an array, fixing
  multi-user setups where multiple chat IDs are allowed.
- **Loop notifications on task completion** — added proactive loop notification path
  in `loop_orchestrator.py` via `_send_loop_notification()` helper that queues
  loop-formatted Telegram messages at every completion point (cost exceeded, done
  condition met, max iterations, max consecutive failures, and progress updates).
  Watcher fallback also gains loop-aware formatting via `_format_loop_task_notification()`.
  Anti-duplicate guard prevents double-sending between proactive and watcher paths.
- **`get_loop_by_task_id()` status filter** — removed `AND status='running'` constraint
  so watcher fallback can find loops in any status (was missing terminal loops).

---

## [0.5.7] — 2026-04-08

### Fixed

- **Telegram rate limit handling** — `telegram_send_message()` now returns `retry_after`
  on HTTP 429 instead of `False`, allowing the poller to back off for the correct duration.
- **Outbound message batch throttling** — poller sends max 5 outbound messages per cycle
  to avoid burst rate limits from Telegram API.
- **Stale notification cleanup** — added `cleanup_old_outbound()` to purge stale
  sent/failed messages from the outbound queue. Watcher now skips notifications for
  tasks completed more than 1 hour ago.

---

## [0.5.6] — 2026-04-08

### Fixed

- **Watcher result summary truncation** — increased `result_summary` limit from 500 to
  2000 characters in watcher's repair and missed-hook paths, preventing loss of important
  information in completion notifications.

---

## [0.5.5] — 2026-04-07

### Fixed

- **Unique tmux session name per `CLAUDE_BRIDGE_HOME`** — `tmux_session.py` now hashes
  `CLAUDE_BRIDGE_HOME` (md5[:8]) to generate a unique session name per instance.
  Default home (`~/.claude-bridge`) keeps the backward-compatible name `claude-bridge`;
  all other homes get `claude-bridge-{hash}` (e.g. `claude-bridge-a2dbe0cf`).
  This allows multiple bridge instances to run simultaneously without tmux session
  name collisions.

---

## [0.5.4] — 2026-04-07

*(version bump only — no code changes beyond 0.5.3)*

---

## [0.5.3] — 2026-04-07

### Added

- **Markdown table support in Telegram messages** — `channel/format.ts` now converts
  Markdown tables to plain `cell1 | cell2` text lines before HTML conversion, since
  Telegram's HTML parse mode does not support `<table>` tags. Separator rows (`|---|`)
  are dropped automatically.
- **Residual markdown cleanup in plain-text fallback** — `stripHtmlTags()` in
  `channel/format.ts` now also strips unconverted Markdown symbols (`**bold**`,
  `## headings`, `*italic*`, `~~strike~~`, `` `code` ``) so the fallback plain-text
  message is clean even when conversion is incomplete.
- **Python port of Markdown formatter** — `telegram_poller.py` gains
  `markdown_to_telegram_html()` (a Python mirror of the TypeScript formatter) and
  `_strip_html()`. `telegram_send_message()` now sends with `parse_mode=HTML` and
  falls back to plain text automatically when Telegram rejects the HTML.

---

## [0.5.2] — 2026-04-07

### Fixed

- **`channel_server/dist/server.js`** — pre-built file was missing from PyPI package after
  `pip install claude-agent-bridge` because `channel_server/dist/` was gitignored.
  Fixed by adding `.gitignore` negation (`!src/claude_bridge/channel_server/dist/`) and
  `MANIFEST.in` to explicitly include the file in wheel/sdist.

---

## [0.5.1] — 2026-04-07

### Fixed

- **`channel/package.json`** — added `build` script so `bun run build` works from the
  `channel/` directory (was missing, causing `install.sh` to fail silently).
- **`install.sh`** — `bun run build` now runs from `$INSTALL_DIR/channel/` (the correct
  working directory) instead of `$INSTALL_DIR/`.
- **`install.sh`** — `~/.bun/bin` is now added to `PATH` immediately after bun install,
  before any subsequent `bun` invocations, preventing fallback-to-python errors on fresh
  installs where the shell `PATH` has not yet been updated.
- **`channel/server.ts`** — `bridge_dispatch` MCP tool now accepts `chat_id` and `user_id`
  parameters and forwards them to `bridge-cli dispatch` via `--chat-id` / `--user-id`.
- **`cli.py`** — `dispatch` command gains `--user-id` flag; when `--chat-id` is provided
  without an explicit channel, the channel is auto-set to `telegram`.

---

## [0.4.0] — 2026-04-05

### Added

**Multi-user routing infrastructure — `chat_id` / `user_id` propagation**

Groundwork for future single-bot multi-user support. All dispatch paths now carry
the originating Telegram `chat_id` and `user_id` so that task completions and
notifications can be routed back to the correct user.

- **`chat_id` / `user_id` through dispatch chain** — `dispatcher.py`, `on_complete.py`,
  and the MCP `bridge_dispatch` tool now accept and propagate `chat_id` / `user_id`
  as first-class fields stored in the `tasks` table.
- **DB schema** — `tasks` table gains `chat_id` and `user_id` columns (additive
  migration; existing databases upgrade automatically on first run).
- **Multi-user documentation** — `README.md` and `README_en.md` now document the
  safe multi-user setup pattern (separate `CLAUDE_BRIDGE_HOME` + separate bot token
  per user) with setup examples and known limitations.

### Notes

- Single-bot multi-user support (shared bot token, per-user routing and access
  control) is not yet implemented. Use separate instances as documented in the
  new Multi-User Setup section.
- This release does not change the single-user UX; existing setups continue to
  work without changes.

---

## [0.3.0] — 2026-04-03

### Added

**Goal Loop — complete hybrid orchestration for autonomous agent loops**

The Goal Loop feature lets Bridge automatically dispatch tasks in a loop until
a done condition is met, with full observability, cost tracking, and Telegram
integration.

- **`bridge-cli loop <AGENT> <GOAL> --done-when <COND>`** — start a goal loop.
  Done conditions: `command:CMD`, `file_exists:PATH`, `file_contains:PATH:PAT`,
  `llm_judge:RUBRIC`, `manual:MSG`. Options: `--max N`, `--max-cost N.NN`,
  `--type bridge|agent|auto`.

- **`bridge-cli loop-list [AGENT] [--limit N] [--active]`** — list all active
  and recent loops with status, progress, and cost.

- **`bridge-cli loop-history <LOOP_ID>`** — show full iteration history with
  result summaries, done check results, cost, and duration per iteration.

- **`bridge-cli loop-status [--loop-id ID] [AGENT]`** — show current loop
  status with recent iterations.

- **`bridge-cli loop-cancel <LOOP_ID>`** — cancel a running loop (current task
  completes but no further iterations are dispatched).

- **`bridge-cli loop-approve <LOOP_ID>`** — approve a loop waiting for manual
  done condition — marks it as done.

- **`bridge-cli loop-reject <LOOP_ID> [--feedback TEXT]`** — reject a manual
  approval and continue to the next iteration.

- **Hybrid orchestrator** — `decide_loop_type(goal, done_when, user_preference,
  max_iterations)` selects bridge vs agent loop automatically:
  - `command`/`file_exists`/`file_contains` + `max_iterations <= 5` → agent loop
    (agent retries internally, no Bridge overhead between attempts)
  - `manual`/`llm_judge` or `max_iterations > 5` → bridge loop (observable,
    cost-tracked, notification-supported)
  - Explicit `--type bridge|agent` always overrides the heuristic.

- **Telegram loop notifications** (`telegram_loop.py`):
  - `format_loop_progress()` — batched iteration update messages
  - `format_loop_done()` — completion/failure notifications with cost + duration
  - `format_loop_approval_request()` — manual condition approval prompts
  - `format_loop_started()` — loop start confirmations
  - `parse_approval_reply()` — parse "approve" / "reject: feedback" / "/approve-loop 42"
  - `parse_loop_command()` — NLP parser: "loop backend fix tests until pytest passes"

- **MCP tools** for Bridge Bot:
  - `bridge_loop_list` — list loops with status dashboard
  - `bridge_loop_history` — full iteration history for a loop
  - `bridge_loop_notify(loop_id, chat_id)` — send formatted Telegram notification
    about current loop state
  - `bridge_parse_loop_command(text)` — parse natural language loop commands
    and approval replies from Telegram

- **LLM judge done condition** (`llm_judge:RUBRIC`) — calls `claude --print`
  to evaluate whether the goal is met against a rubric. Falls back gracefully
  if claude CLI is unavailable.

- **Manual done condition** (`manual:MSG`) — loop pauses after each iteration
  and waits for `loop-approve` or `loop-reject` before continuing.

- **Enhanced feedback generation** — parses test failures, stack traces from
  iteration results and injects structured context into the next iteration prompt.

- **Agent loop branching** — for simple conditions, Bridge injects internal loop
  instructions into a single task prompt; the agent retries internally and
  reports via `AGENT_LOOP_RESULT` JSON marker.

- **Cost limit enforcement** (`--max-cost N.NN`) — stops loop when total cost
  exceeds the limit; warns at 80% of limit.

### Changed

- **DB schema** — `loops` and `loop_iterations` tables added via additive migration
  (`CREATE IF NOT EXISTS` + `ALTER TABLE` for new columns); v0.2 databases upgrade
  automatically on first run without data loss.

- **`on_complete.py`** — Stop hook now checks whether the completed task belongs to
  a loop; if so, it delegates to the loop orchestrator (evaluate done condition,
  dispatch next iteration or terminate) instead of the normal queue path.

- **Version** — bumped from `0.2.0` to `0.3.0` across `pyproject.toml`,
  `src/claude_bridge/__init__.py`, and `channel/package.json`.

---

## [0.2.0] — 2026-04-03

### Added
- **`install.sh` hero install script** — `curl -fsSL <url> | sh` end-to-end installer;
  detects OS, checks prerequisites, clones repo, builds channel server, runs setup wizard
- **`bridge-cli setup` auto-build** — if `channel/dist/server.js` is missing and `bun` is
  available, setup wizard now runs `bun run build` automatically instead of silently failing
- **`mcp` Python package dependency** — added `mcp>=1.0` to `pyproject.toml`; MCP mode
  no longer crashes with `ModuleNotFoundError` on first run
- **Version unification** — single source of truth in `src/claude_bridge/__init__.py`;
  all `package.json` files and `pyproject.toml` now share version `0.2.0`
- **`bun.lock` lockfile** — committed to repo for reproducible channel server builds
  (`bun install --frozen-lockfile` guaranteed to produce same result)
- **`channel/.env.example`** — documents all environment variables for manual channel
  server testing (required/optional, default values, usage notes)
- **`CLAUDE_BRIDGE_HOME` env var** — override the default `~/.claude-bridge` home
  directory; useful for CI, multiple users, NixOS, and non-standard `HOME`
  (e.g. `CLAUDE_BRIDGE_HOME=/tmp/test-bridge bridge-cli setup`)
- **Architecture mermaid diagram** — end-to-end flow diagram in README (renders on GitHub)
- **Daemon install wizard** — `bridge-cli setup` now offers to install as a system
  service; Linux: `~/.config/systemd/user/claude-bridge.service`;
  macOS: `~/Library/LaunchAgents/ai.claude-bridge.plist`
- **`bridge-cli daemon` subcommand** — `start | stop | status | logs | install | uninstall`
  for managing the system service

### Fixed
- **Stop hook Python path** — `agent_md.py` now uses `sys.executable` instead of the
  hard-coded `python3` binary; fixes agents created inside a `pipx`-managed venv where
  `python3` on `PATH` cannot find `claude_bridge`
- **`bridge start` config validation** — fails fast with an actionable error message when
  `bot_dir` is missing or not a directory, rather than silently misbehaving
- **`bridge-cli doctor` suggestions** — missing channel server now prints the exact
  `bun run build` command with the correct path instead of a generic error

### Changed
- **README Quick Start** — replaced 4-step manual install with the `curl | sh` one-liner
  as the primary install path; manual steps moved to "Installation" section
- **README Step 6 (pairing)** — fully rewritten with an ASCII flow diagram and a
  step-by-step walkthrough that clearly distinguishes the Claude Code session from
  `bridge-cli` commands; includes a troubleshooting table for common pairing failures
- **`bridge-cli doctor`** — expanded checks: bun version, Claude CLI version, Telegram
  `getMe` connectivity test, bridge tool permissions in `settings.local.json`, shows
  `CLAUDE_BRIDGE_HOME` path in use

---

## [0.1.0] — 2026-03-01

### Added
- Initial release of Claude Bridge
- **Multi-session dispatch** — register agents per project (`bridge-cli create-agent`),
  dispatch tasks from Telegram or CLI (`bridge-cli dispatch`)
- **Worktree isolation** — each task runs in a fresh `git worktree`; no concurrent
  filesystem corruption between parallel tasks
- **Stop hook integration** — `on_complete.py` called by Claude Code Stop hook; updates
  SQLite task status and queues Telegram notification
- **Task queue** — when an agent is busy, new tasks are automatically queued and
  dispatched in order on completion
- **Agent teams** — `bridge-cli create-team`, `team-dispatch`: fan out a single prompt
  to a lead + member agents with automatic sub-task tracking
- **Cost tracking** — `bridge-cli cost` shows total / average spend per agent or globally
- **Permission relay** — dangerous Bash commands (`git push`, `rm -rf`) pause and ask
  for approval via Telegram before executing
- **Memory reader** — `bridge-cli memory <agent>` surfaces Claude Code Auto Memory files
  so you can see what the agent has learned about the project
- **Watcher cron** — fallback cron job catches tasks whose Stop hook never fired (e.g.
  process killed, machine rebooted)
- **`bridge` command** — `bridge start / stop / attach / logs / restart / status` for
  tmux-based Bridge Bot lifecycle management
- **`bridge-cli doctor`** — basic health check: Python version, bun, claude CLI,
  channel server, config, database, cron, tmux
- **`bridge-cli uninstall`** — removes `~/.claude-bridge/`, agent `.md` files, and
  watcher cron
- **TypeScript channel server** — Telegram poller via `grammy`; push delivery with 30s
  retry (5 attempts); per-message acknowledgement to prevent duplicate delivery
- **Python MCP mode** — fallback for environments without `bun`; exposes bridge tools
  over the MCP stdio protocol
