# Changelog

All notable changes to Claude Bridge are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
