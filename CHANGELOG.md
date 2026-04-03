# Changelog

All notable changes to Claude Bridge are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
