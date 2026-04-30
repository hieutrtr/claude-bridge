# Claude Bridge — Packaging Implementation Plan

Based on `plan/specs-packaging.md` (last revised 2026-03-29).

**Goal:** A developer who has Claude Code installed runs `pip install claude-bridge` and `bridge-cli setup` to be ready in under 5 minutes. No git clone. No PYTHONPATH.

**Primary distribution:** `pip install claude-bridge` (PyPI) or `pipx install claude-bridge`
**Secondary distribution:** `bun install -g claude-bridge` (npm, thin wrapper)
**Hero install command:** `curl -fsSL https://claude-bridge.sh | sh`
**Claude Code channel:** DONE — `channel/server.ts` with `experimental['claude/channel']`
**Homebrew:** Phase 6 (deferred)

---

## Version Compatibility Matrix

| Python | Bun | macOS | Linux (Ubuntu) | Notes |
|--------|-----|-------|----------------|-------|
| 3.11 | ≥1.0.0 | 13+ (arm64 + x86_64) | 22.04, 24.04 | Minimum supported |
| 3.12 | ≥1.0.0 | 14+ | 22.04, 24.04 | **Recommended** |
| 3.13 | ≥1.0.0 | 15+ | 24.04 | Tested, supported |

- **Windows:** Bun ≥1.1 supported. `install.sh` PowerShell equivalent deferred to v0.2. WSL2 should work as Linux path — untested.
- **Python <3.11:** Not supported (uses `match`, `tomllib`, type union `str | None`).
- **Bun <1.0:** Not supported.
- **Claude Code:** Minimum version TBD. Requires `--dangerously-load-development-channels` support. Track `claude --version`.

---

## Phase 1 — Package Structure

**Goal:** The repo can be built and installed. `bun install -g claude-bridge` and `pipx install claude-bridge` both work. Channel server is bundled in the Python package. Pre-built JS eliminates the `bun install` step for end users.

**Status:** Not started. Estimated effort: 3–4 days.

---

### P1-T1: Bundle channel server into Python package

**What:** Copy the TypeScript channel server into `src/claude_bridge/channel_server/` and add a Bun build step that pre-compiles `server.ts` → `dist/server.js`.

**Files changed:**
- `src/claude_bridge/channel_server/` (new directory — tracked in git)
- `channel/server.ts`, `channel/lib.ts`, `channel/package.json` (symlinked or copied)
- `pyproject.toml` — add `package-data` for `channel_server/**/*`
- Root `package.json` (new) — add `build` script

**Build script (root `package.json`):**
```json
{
  "name": "claude-bridge",
  "scripts": {
    "build": "bun build channel/server.ts --outfile src/claude_bridge/channel_server/dist/server.js --target bun --bundle --minify"
  }
}
```

**Acceptance criteria:**
- `bun run build` produces `src/claude_bridge/channel_server/dist/server.js`
- `dist/server.js` runs standalone: `bun run src/claude_bridge/channel_server/dist/server.js` (exits with missing token error, not import error)
- `src/claude_bridge/channel_server/dist/server.js` is committed to git (pre-built artifact)
- `python -m build` includes `channel_server/**/*` in the wheel

**Dependencies:** None (first task)

---

### P1-T2: Update `pyproject.toml` to match spec

**What:** Bring `pyproject.toml` up to the spec (§5.3): add metadata, classifiers, URLs, dynamic version, `claude-bridge` entry point, `bridge-cli` deprecated alias, package-data for channel_server.

**Current state:**
```toml
[project.scripts]
bridge-cli = "claude_bridge.cli:main"   # only entry point
```

**Target state:**
```toml
[project]
name = "claude-bridge"
dynamic = ["version"]
description = "Multi-session Claude Code dispatch from Telegram"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
keywords = ["claude", "claude-code", "telegram", "ai", "cli"]
classifiers = [...]

[project.scripts]
claude-bridge = "claude_bridge.cli:main"
bridge-cli = "claude_bridge.cli:main"   # deprecated alias

[tool.setuptools.dynamic]
version = {attr = "claude_bridge.__version__"}

[tool.setuptools.package-data]
claude_bridge = ["channel_server/**/*"]
```

**Also:** Add `__version__ = "0.1.0"` to `src/claude_bridge/__init__.py` (single source of truth).

**Acceptance criteria:**
- `pip install -e .` installs both `claude-bridge` and `bridge-cli` commands
- `claude-bridge --version` prints version string
- `python -m build` produces `dist/claude_bridge-0.1.0-py3-none-any.whl` and `.tar.gz`
- Wheel contains `claude_bridge/channel_server/dist/server.js`

**Dependencies:** P1-T1 (dist/server.js must exist before build)

---

### P1-T3: Add Bun wrapper (`bin/claude-bridge.js`)

**What:** Create the thin Bun wrapper that locates and delegates to the Python core. This is what gets installed when users run `bun install -g claude-bridge`.

**Files:**
- `bin/claude-bridge.js` (new)
- `bin/check-python.js` (new — postinstall check)
- Root `package.json` — add `bin`, `engines`, `postinstall`, full package metadata

**`bin/claude-bridge.js`:** Searches candidate Python install paths; runs the Python `claude-bridge` command passing through `process.argv`. Falls back with a helpful install message if not found.

**Candidate paths to check:**
- `$HOME/.local/bin/claude-bridge` (pipx)
- `/usr/local/bin/claude-bridge`
- `$HOME/Library/Python/3.11/bin/claude-bridge` (macOS pip --user 3.11)
- `$HOME/Library/Python/3.12/bin/claude-bridge` (macOS pip --user 3.12)
- `python3 -m claude_bridge.cli` (fallback if package installed but not in PATH)

**Acceptance criteria:**
- `bun install -g .` (from repo root) installs `claude-bridge` command
- `claude-bridge list-agents` delegates to Python CLI correctly
- When Python core not found: prints helpful error with install instructions, exits 1
- `bun publish --dry-run` succeeds (package.json valid for npm registry)

**Dependencies:** P1-T2

---

### P1-T4: Create `install.sh`

**What:** The hero curl install script. Checks prerequisites (claude CLI, Python 3.11+), installs Bun if missing, installs `claude-bridge` via `bun install -g`, falls back to `pipx`.

**File:** `install.sh` (new at repo root)

**Logic (per spec §11):**
1. Check `claude` CLI present; exit with instructions if not
2. Check Python 3.11+; exit with instructions if not
3. Check Bun; if missing: `curl -fsSL https://bun.sh/install | bash`
4. `bun install -g claude-bridge` (primary)
5. If Bun fails: `pipx install claude-bridge` (fallback)
6. Verify `claude-bridge` in PATH; print PATH fix hint if not
7. Print "next steps" with `claude-bridge setup`

**Acceptance criteria:**
- `sh install.sh` succeeds on macOS arm64 (integration test)
- When `claude` not found: clear error, exit 1
- When Python 3.10: clear error, exit 1
- Idempotent: safe to run on already-installed system
- `shellcheck install.sh` passes (POSIX sh compatible)

**Dependencies:** P1-T3 (package must be publishable)

---

### P1-T5: `claude-bridge setup` command (setup-telegram + setup-bot + setup-cron in one)

**What:** Add a `setup` subcommand to `cli.py` that wraps the existing `setup-telegram`, `setup-bot`, and `setup-cron` calls into a single interactive wizard. Also add `--no-prompt` flag for scripted installs.

> **Note:** The existing separate setup commands stay; `setup` orchestrates them.

**Steps in wizard:**
1. **Token** — prompt for Telegram bot token; save to `~/.claude-bridge/config.json`; skip if already set
2. **Bot directory** — prompt for bot project dir (default `~/projects/bridge-bot`); create dir, write CLAUDE.md, write .mcp.json pointing to channel_server dist
3. **Cron** — install watcher cron job; skip if already installed
4. **Start instructions** — print the `claude --dangerously-load-development-channels ...` command to run

**`.mcp.json` must use installed path** (`~/.claude-bridge/channel/dist/server.js`) not the repo path:
```json
{
  "mcpServers": {
    "bridge": {
      "command": "bun",
      "args": ["run", "~/.claude-bridge/channel/dist/server.js"],
      "env": { "TELEGRAM_BOT_TOKEN": "..." }
    }
  }
}
```

**Channel server deployment:** `setup` copies `channel_server/dist/server.js` (bundled in package) to `~/.claude-bridge/channel/dist/server.js`.

**Non-interactive mode:**
```bash
claude-bridge setup --token <tok> --bot-dir ~/bridge-bot --no-prompt
```

**Acceptance criteria:**
- Interactive wizard runs, all 4 steps complete
- Re-running `setup` skips already-done steps (idempotent)
- `--no-prompt` with all flags skips all prompts
- `.mcp.json` uses `~/.claude-bridge/channel/dist/server.js` (not repo path)
- `~/.claude-bridge/channel/dist/server.js` exists after setup
- `claude-bridge doctor` (Phase 3) passes after setup

**Dependencies:** P1-T2, P1-T1

---

## Phase 2 — CLI Wizard Polish

**Goal:** The setup wizard is production-quality: clear UX, good error messages, pairing flow, and re-runnable.

**Status:** Not started. Estimated effort: 2 days.

---

### P2-T1: Wizard step — Pair Telegram account

**What:** After bot is running, add a pairing step that guides the user to DM the bot and confirms their user_id gets added to `access.json`.

**Flow:**
1. Print: "DM your bot @{username} anything to pair your account."
2. Poll `~/.claude/channels/telegram/access.json` until a user_id appears
3. Confirm: "Paired! Your user ID: {id}"
4. Timeout after 2 minutes with skip option

**Acceptance criteria:**
- Pairing step detects access.json population within 5s of DM
- Timeout with clear instructions to pair manually later
- Skippable: `--skip-pair` flag or press Enter to skip

**Dependencies:** P1-T5

---

### P2-T2: Wizard — detect and handle existing installations

**What:** When `setup` detects an already-configured bridge (config.json exists, bot-dir exists), offer to re-configure, update, or skip each step.

**Behaviour:**
- Token: show masked existing token, offer to replace
- Bot directory: show existing path, offer to reconfigure
- Cron: show "already installed", offer to reinstall
- Channel server: always redeploy (update)

**Acceptance criteria:**
- Running `setup` twice shows existing config and prompts to update/skip
- `setup --update` updates channel_server without re-prompting for token

**Dependencies:** P1-T5

---

## Phase 3 — Doctor & Uninstall

**Goal:** Users can verify their installation and cleanly remove it.

**Status:** Not started. Estimated effort: 2 days.

---

### P3-T1: `claude-bridge doctor` command

**What:** Add a `doctor` subcommand to `cli.py` that runs a diagnostic report.

**Checks (per spec §8):**

| Category | What to check |
|----------|--------------|
| Runtime | Python version ≥3.11, Bun version ≥1.0, claude CLI present |
| Installation | claude-bridge version + install path |
| Data directory | `~/.claude-bridge/` exists |
| Config file | `~/.claude-bridge/config.json` exists |
| Telegram token | token present (masked), not shown |
| Bot project dir | exists, CLAUDE.md present, .mcp.json present |
| Channel server | `~/.claude-bridge/channel/dist/server.js` exists |
| Cron job | installed, last run time |
| Database | `bridge.db` exists, agent count, task stats |
| Telegram connectivity | `getMe` API call succeeds |
| Agent .md files | list all `bridge--*.md` files |

**Output format:** Human-readable with `✓` / `✗` / `⚠` per check, grouped by category.

**Exit codes:** `0` = all pass, `1` = warnings, `2` = critical failures.

**`--fix` flag:** Attempt auto-repair: redeploy channel server if missing, reinstall cron if missing, recreate data dir if missing.

**Acceptance criteria:**
- `doctor` exits 0 after successful `setup`
- Missing config.json → exits 2 (critical)
- Missing cron but DB and token OK → exits 1 (warning)
- Telegram API down → warning (not critical) with clear message
- `--fix` redeploys missing channel server

**Dependencies:** P1-T5

---

### P3-T2: `claude-bridge uninstall` command

**What:** Clean removal of everything claude-bridge installs (per spec §7).

**What gets removed:**

| Item | How |
|------|-----|
| Cron job | `crontab -l | grep -v claude-bridge | crontab -` |
| `~/.claude-bridge/` | `rm -rf ~/.claude-bridge` |
| `~/.claude/agents/bridge--*.md` | glob + rm |
| `.mcp.json` entry in bot-dir | remove `mcpServers.bridge` key |

**What is NOT removed:**
- Bot project directory (user's project files)
- Bun itself
- Python itself
- The Python or Bun package (instructions provided to uninstall manually)

**Flow:**
1. Print summary of what will be removed
2. Print what will NOT be removed
3. `Continue? [y/N]`
4. Remove items, print `✓` per item
5. Print manual uninstall commands for Python/Bun packages

**`--force` flag:** Skip confirmation prompt.

**Acceptance criteria:**
- After uninstall: no cron entry, `~/.claude-bridge/` gone, no `bridge--*.md` files
- `.mcp.json` updated (bridge entry removed, other entries preserved)
- Idempotent: safe to run if already uninstalled
- `--force` skips confirmation

**Dependencies:** P3-T1

---

## Phase 4 — Claude Code Channel/Plugin Research

**Goal:** Determine whether claude-bridge can be distributed as a native Claude Code channel, and what that distribution path would look like.

**Status:** DONE. Channel server built (`channel/server.ts`). Uses `--dangerously-load-development-channels server:bridge`. Third-party channel registry does not exist yet — dev flag is the only path for custom channels.

**Estimated effort:** ~~2–3 days research + 3–5 days implementation~~ Completed.

---

### P4-T1: Research `--dangerously-load-development-channels` mechanism

**What:** Understand how Claude Code channel loading works and whether third-party channels can be published.

**Questions to answer:**

| Question | Where to look |
|----------|--------------|
| How does `--channel` / `--dangerously-load-development-channels` work? | `claude --help`, Claude Code docs |
| Can third-party channels be installed without `--dangerously-load`? | Claude Code channel registry |
| Is there a public channel registry? | Claude Code source / docs / changelog |
| What's the install UX? (`claude channel install …`?) | Claude Code docs |
| What format does a channel need to be? | Existing channel examples |
| Can a channel ship Python? Or TypeScript-only? | Channel SDK docs |
| Is `--dangerously-load-development-channels` dev-only or user-facing? | Claude Code docs |
| Can channels spawn arbitrary subprocesses? | Channel examples / sandboxing docs |

**Output:** `research/claude-code-channel-distribution.md` — findings + recommendation

**Decision criteria:**
- If native channel install exists: Phase 4 is the primary distribution path
- If dev-only flag: document and move on; Bun global install remains primary

**Dependencies:** None (parallel to other phases)

---

### P4-T2: Package as Claude Code channel (if P4-T1 determines viable)

**What:** Restructure for channel distribution if the research in P4-T1 shows a viable path.

**Proposed channel structure (per spec §3.1):**
```
claude-bridge (as Claude Code channel)
  server.ts           ← channel server entry point (current channel/server.ts)
  package.json        ← channel manifest
  python/
    claude_bridge/    ← Python package
    run.sh            ← launches Python subprocess
```

**If viable — install UX would become:**
```bash
claude channel install claude-bridge
claude-bridge setup
```

**Questions to resolve:**
- Does Claude Code manage channel lifecycle and updates?
- Can the channel bundle and invoke Python files?
- How is the channel registered / discovered?

**Acceptance criteria (if pursued):**
- `claude channel install claude-bridge` installs the channel
- Bridge bot can be started without `--dangerously-load-development-channels`
- Channel update mechanism works (`claude channel update claude-bridge`)

**Dependencies:** P4-T1 (research must conclude viable before starting)

---

## Phase 5 — Migration (git-clone users)

**Goal:** Existing users who installed via `git clone` can migrate to the packaged version with a single command.

**Status:** Not started. Estimated effort: 2 days.

---

### P5-T1: Detect git-clone installation

**What:** Add detection logic in `setup` (and optionally `doctor`) that identifies when the current install is a git-clone install.

**Detection signals:**
- `~/.claude-bridge/config.json` exists but `claude-bridge` command was run from a git repo path
- `.mcp.json` references a hardcoded `/path/to/claude-bridge/channel/server.ts` (not `~/.claude-bridge/channel/dist/server.js`)
- `PYTHONPATH` set to a repo `src/` directory in crontab

**Acceptance criteria:**
- `setup` prints detection notice when git-clone install found
- Prompts: "Detected git-clone installation. Migrate to installed package? [Y/n]"
- Graceful: if detection fails, falls through to normal setup

**Dependencies:** P1-T5

---

### P5-T2: `claude-bridge migrate` command

**What:** Automate migration from git-clone install to packaged install.

**Migration steps (per spec §13):**
1. **Export config** — read token from old location (PYTHONPATH=src python3 -m ...) or config.json
2. **Update `.mcp.json`** — change server path from repo path to `~/.claude-bridge/channel/dist/server.js`
3. **Update cron** — replace `PYTHONPATH=... python3 -m claude_bridge.watcher` with `claude-bridge cron-watch`
4. **Verify** — run `claude-bridge doctor`
5. **Print** — old git-clone path no longer needed, user can delete

**Backward compatibility preserved:**
- `bridge-cli` alias: kept through v0.2
- Agent .md files: format unchanged (no migration needed)
- SQLite schema: additive migrations only, no drops
- `.mcp.json`: only server path changes

**`--dry-run` flag:** Show what would change without applying it.

**Acceptance criteria:**
- `migrate` succeeds on a real git-clone install
- `.mcp.json` updated to packaged path
- Crontab updated to `claude-bridge cron-watch`
- `doctor` passes after migration
- `--dry-run` shows changes without applying

**Dependencies:** P5-T1

---

## Phase 6 — Homebrew Tap (Deferred)

**Status:** Deferred. Do Phase 1–3 first.

**Why deferred:** Packaging strategy (especially Claude Code channel, Phase 4) must be resolved first. Setting up a Homebrew release pipeline before the distribution model is stable wastes effort.

**When to resume:** After Phase 1 is manually validated and the package is published to PyPI and npm registry.

---

### P6-T1: Create `homebrew-claude-bridge` tap

**What:** Create a separate repo `github.com/hieutrtr/homebrew-claude-bridge` with a Homebrew formula.

**Formula highlights (per spec §15):**
```ruby
class ClaudeBridge < Formula
  depends_on "python@3.12"
  depends_on "bun"
  # No resource blocks — no pip dependencies
end
```

`depends_on "bun"` means `brew install claude-bridge` installs Bun automatically.

**Install UX (after this phase):**
```bash
brew tap hieutrtr/claude-bridge
brew install claude-bridge
```

**Acceptance criteria:**
- `brew install hieutrtr/claude-bridge/claude-bridge` works on macOS
- `brew upgrade claude-bridge` works
- `brew test claude-bridge` passes (`--version` check)

**Dependencies:** Phase 1 complete, package published to PyPI

---

## Build Pipeline (Manual, Phase 1)

**Manual release process (until CI is set up in a future phase):**

```bash
# 1. Bump version
#    Edit src/claude_bridge/__init__.py → __version__ = "X.Y.Z"

# 2. Pre-build TypeScript
bun run build
# Produces: src/claude_bridge/channel_server/dist/server.js

# 3. Build Python package
pip install build
python -m build
# Produces: dist/claude_bridge-X.Y.Z.tar.gz, dist/claude_bridge-X.Y.Z-py3-none-any.whl

# 4. Publish to PyPI
pip install twine
twine upload dist/*

# 5. Publish to npm/Bun registry (bun uses npm registry)
bun publish

# 6. Tag
git tag vX.Y.Z && git push origin main --tags
```

---

## Summary Table

| Phase | Goal | Effort | Status |
|-------|------|--------|--------|
| P1 | Package structure + pip install + install.sh + setup wizard | 3–4 days | Not started |
| P2 | Wizard polish (pairing, re-run UX) | 2 days | Not started |
| P3 | Doctor + Uninstall | 2 days | Not started |
| P4 | Claude Code channel research + implementation | ~~2–8 days~~ | **DONE** |
| P5 | Migration from git-clone | 2 days | Not started |
| P6 | Homebrew tap | 1–2 days | Deferred |

**Critical path:** P1-T1 → P1-T2 → P1-T5 → P2 → P3
**Note:** P1-T3 (Bun wrapper) is secondary — pip is primary distribution. P4 is done.
