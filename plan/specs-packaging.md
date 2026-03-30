# Claude Bridge — Packaging & Distribution Spec

**Goal:** A developer who has Claude Code installed runs a single command and is ready to dispatch tasks from Telegram in under 5 minutes. No git clone. No PYTHONPATH. No manual venv.

**Last revised:** 2026-03-29 — Adopted Bun as primary runtime; added Claude Code channel/plugin distribution research; added uninstall, doctor, compat matrix, and migration plan; deferred CI/binary releases.

---

## 1. Current State (Baseline)

Today's install is 9 steps:

```
1. git clone ...
2. curl -fsSL https://bun.sh/install | bash   # if no Bun
3. cd channel && bun install
4. Create Telegram bot via BotFather
5. PYTHONPATH=src python3 -m claude_bridge.cli setup-telegram "<token>"
6. PYTHONPATH=src python3 -m claude_bridge.cli setup-bot ~/bridge-bot
7. PYTHONPATH=src python3 -m claude_bridge.cli setup-cron
8. cd ~/bridge-bot && claude --dangerously-load-development-channels server:bridge ...
9. Pair Telegram account
```

**Pain points:**
- Requires `git clone` into a specific location
- `PYTHONPATH=src` in every command (package not installed)
- User must know where the repo lives (`.mcp.json` hardcodes the path)
- Bun installed separately, not tied to the install
- No upgrade path — users `git pull` manually

---

## 2. Runtime Decision: Bun is Primary

**Bun is the chosen runtime for everything TypeScript/JavaScript in this project.**

Anthropic has acquired Bun — it is the direction of the Claude Code ecosystem. Requiring users to install Bun is not a friction point to avoid; it is the correct dependency to declare.

Implications:
- Channel server: runs with `bun run` (not `node`)
- Package scripts: `bun run`, `bun build`, `bun add`
- Distribution: Bun's global install mechanism (`bun install -g`) is the primary path alongside or instead of npm
- `npx` fallback: replaced by `bunx` where needed

**npm / npx are deprecated for this project.** See §3.4 for why npm was considered and rejected.

---

## 3. Packaging Options Analysis

### 3.1 Claude Code Channel / Plugin Distribution ⭐ RECOMMENDED (Research Required)

> **Status: Under active research — this is the highest-priority question before finalising Phase 1.**

Claude Code supports a `--channel` flag (seen in current usage: `claude --dangerously-load-development-channels server:bridge`). The goal is to understand whether claude-bridge can be distributed *as a Claude Code channel* — meaning users would install it natively through the `claude` CLI rather than through a separate package manager.

#### What we need to answer:

| Question | Source to check |
|----------|-----------------|
| How does `--channel` / `--dangerously-load-development-channels` work? | `claude --help`, Claude Code docs |
| Can third-party channels be installed without `--dangerously-load`? | Claude Code channel registry docs |
| Is there a public channel registry or is it always local path? | Claude Code source / docs |
| What's the install UX? (`claude install channel:bridge`? `claude channel add …`?) | Claude Code docs / changelog |
| What format does a channel server need to be in? | Existing channel examples |
| Can a channel ship its own Python backend, or is it TypeScript-only? | Channel SDK docs |
| Is `--dangerously-load-development-channels` a dev-only flag or user-facing? | Claude Code docs |

#### Why this matters:

If Claude Code has a native channel install mechanism, then:

```bash
# Ideal install (if possible):
claude channel install claude-bridge
```

This would be the most native integration path — no separate installer, no pipx, no Bun install step. The `claude` CLI handles distribution, updates, and the user already trusts it.

**If this path is viable, it becomes the Phase 1 primary.** All other distribution methods become fallbacks or secondaries.

#### Potential architecture for channel distribution:

```
claude-bridge (as a Claude Code channel)
  server.ts          ← channel server entry point (Bun)
  package.json       ← channel manifest
  python/            ← bundled Python core
    claude_bridge/   ← the Python package
    run.sh           ← launches Python subprocess
```

The channel server (TypeScript/Bun) becomes the outer shell; it spawns the Python core as a subprocess. Claude Code manages the channel lifecycle; Python handles bridge logic.

**Open questions before adopting this path:**
- Does Claude Code allow channels to spawn arbitrary subprocesses?
- Can a channel bundle Python files and invoke them?
- Is there version management for channels (channel update)?

---

### 3.2 Bun Global Install (Primary CLI distribution)

```bash
bun install -g claude-bridge
# or
bunx claude-bridge setup
```

| Dimension | Assessment |
|-----------|------------|
| Install UX | ★★★★★ One command. Bun is already required for the channel server. |
| Auto-updates | `bun update -g claude-bridge` |
| Dependency mgmt | Bun handles JS isolation. Python still needs to be on system (3.11+). |
| Cross-platform | macOS, Linux, Windows |
| Claude Code ecosystem fit | High — Bun is where the ecosystem is going |
| Versioning | npm registry semver (Bun uses npm registry) |
| Publishing | `bun publish` — publishes to npm registry |

**How it works:** A thin Bun package (`bin/claude-bridge.js`) that locates and invokes the Python core. Python is installed separately (system Python or via Homebrew).

**Bun registry note:** Bun currently publishes to the npm registry (`bun publish` = `npm publish` equivalent). There is no separate Bun-specific registry yet. The `bun add` flag is `bun add -g` for global installs. So `bun install -g claude-bridge` is the correct idiom.

**Verdict:** Primary distribution path alongside Claude Code channel (§3.1). Zero additional friction since users already need Bun.

---

### 3.3 pipx (PyPI) — Retained as Secondary

```bash
pipx install claude-bridge
```

| Dimension | Assessment |
|-----------|------------|
| Install UX | ★★★★☆ One command. Auto-creates isolated venv. |
| Auto-updates | `pipx upgrade claude-bridge` |
| Dependency mgmt | Pipx handles Python isolation. Bun/Node must exist separately. |
| Cross-platform | macOS, Linux, Windows (WSL) |
| Claude Code ecosystem fit | Medium — Claude Code users may or may not have pipx |
| Versioning | PyPI semver |
| Maturity | Standard Python CLI tool distribution |

**Verdict:** Retained as the explicit Python-first install path. Best for users who want to manage the Python package directly. Also serves as the fallback if Claude Code channel distribution is not viable.

---

### 3.4 npm — ❌ Rejected

> **npm is not the distribution path for this project. Bun supersedes it.**

The analysis below is retained for context on why npm was considered and rejected.

An npm package would be a thin wrapper that either:
- (a) Runs `pip install claude-bridge` as a postinstall script — blocked by pnpm v10 default, ignored by `--ignore-scripts`
- (b) Ships Python binaries inside the npm package — complex, ~6–10 MB per platform
- (c) Is a pure JS rewrite — out of scope

Since Bun uses the npm registry, publishing to npm is still needed to reach `bun install -g`. The package exists on npm, but the *install instruction* we tell users is `bun install -g`, not `npm install -g`.

---

### 3.5 Homebrew Tap — Secondary (macOS)

```bash
brew tap hieutrtr/claude-bridge
brew install claude-bridge
```

| Dimension | Assessment |
|-----------|------------|
| Install UX | ★★★★☆ Familiar for macOS devs. |
| Auto-updates | `brew upgrade claude-bridge` |
| Dependency mgmt | `depends_on "bun"` handles Bun automatically. Python 3.11 managed. |
| Cross-platform | macOS + Linux only |
| Claude Code ecosystem fit | Medium — Claude Code also has a Homebrew cask |
| Maintenance | Requires separate `homebrew-claude-bridge` repo |

**Verdict:** Excellent secondary for macOS discoverability. Deferred to Phase 2 — do Phase 1 (Bun / Claude channel) first.

---

### 3.6 Shell One-liner (`curl | sh`) — Hero Install Command

```bash
curl -fsSL https://raw.githubusercontent.com/hieutrtr/claude-bridge/main/install.sh | sh
```

| Dimension | Assessment |
|-----------|------------|
| Install UX | ★★★★★ Most accessible entry point |
| Auto-updates | Delegates to whichever package manager it installs |
| Dependency mgmt | Detects and installs missing deps (Bun, Python) |
| Cross-platform | macOS + Linux |
| Security | HTTPS only; can verify SHA256 of downloaded artifacts |

**Verdict:** Retained as the README hero command. Now delegates to Bun (`bun install -g`) instead of pipx.

---

### 3.7 Binary Releases (PyInstaller) — ❌ Deferred

> **Deferred indefinitely.** Build complexity is high; the value over Bun global install is low given our user base is developers who already have Bun. Revisit for v1.0 if user research shows demand.

---

### 3.8 Docker — ❌ Not Suitable

Claude Bridge needs to launch local `claude` subprocesses and access `~/.claude/` — Docker isolation breaks this entirely.

---

## 4. Recommendation: Distribution Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│   HERO COMMAND (README, docs, tweets)                           │
│                                                                 │
│   curl -fsSL https://claude-bridge.sh | sh                     │
│   └─ installs Bun if needed → bun install -g claude-bridge     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
         ┌─────────────┼──────────────────────────────┐
         ▼             ▼                               ▼
  claude channel   bun install -g               brew install
  install bridge   claude-bridge                claude-bridge
  [PRIMARY if      [PRIMARY CLI]                [macOS secondary,
   viable]                                       Phase 2]
```

### Phase 1 (MVP)
1. **Research** Claude Code channel distribution (§3.1) — 2–3 days
2. If viable: package as a Claude Code channel (TypeScript outer shell + Python core)
3. If not viable: `bun install -g claude-bridge` as primary, publish to npm registry via `bun publish`
4. `curl | sh` installer as the hero README command (delegates to `bun install -g`)
5. Interactive setup wizard (`claude-bridge setup`)

### Phase 2
- Homebrew tap (`brew install hieutrtr/claude-bridge/claude-bridge`)
- `pipx install claude-bridge` as explicit Python-first alternative
- Version update notifications in `claude-bridge doctor`

### Phase 3 (deferred)
- Binary releases if user research demands it
- CI/GitHub Actions release automation (on hold per §10)

---

## 5. Package Structure

### 5.1 Python Package (PyPI / Bun-distributed core)

```
src/
  claude_bridge/
    __init__.py          (version = "0.1.0")
    cli.py               (includes: setup, uninstall, doctor subcommands)
    db.py
    session.py
    agent_md.py
    claude_md_init.py
    bridge_bot_claude_md.py
    dispatcher.py
    memory.py
    on_complete.py
    notify.py
    channel.py
    watcher.py
    permission_relay.py
    mcp_server.py
    mcp_tools.py
    message_db.py
    telegram_poller.py
    channel_server/         ← bundled TypeScript server
      server.ts
      lib.ts
      package.json
      bun.lock
      dist/
        server.js           ← bun build output (pre-built, no bun install needed)
```

**Channel server bundling:** Bundle the TypeScript channel server files inside the Python package. When the user runs `claude-bridge setup`, it:
1. Copies `channel_server/` to `~/.claude-bridge/channel/`
2. Runs `bun run ~/.claude-bridge/channel/dist/server.js` (pre-built — `bun install` not required at setup time)

### 5.2 Bun Package (`package.json` at repo root)

```json
{
  "name": "claude-bridge",
  "version": "0.1.0",
  "description": "Multi-session Claude Code dispatch from Telegram",
  "bin": {
    "claude-bridge": "./bin/claude-bridge.js"
  },
  "scripts": {
    "build": "bun build channel/server.ts --outfile src/claude_bridge/channel_server/dist/server.js --target bun --bundle --minify",
    "postinstall": "node ./bin/check-python.js"
  },
  "engines": {
    "bun": ">=1.0.0"
  }
}
```

```javascript
// bin/claude-bridge.js — thin Bun wrapper that invokes Python core
#!/usr/bin/env node
const { execFileSync } = require('child_process');

const candidates = [
  process.env.HOME + '/.local/bin/claude-bridge',
  '/usr/local/bin/claude-bridge',
  // pipx-installed location on macOS
  process.env.HOME + '/Library/Python/3.11/bin/claude-bridge',
];

for (const p of candidates) {
  try {
    execFileSync(p, process.argv.slice(2), { stdio: 'inherit' });
    process.exit(0);
  } catch (e) {
    if (e.code !== 'ENOENT') process.exit(e.status || 1);
  }
}

// Python core not found — guide user
console.error('claude-bridge Python core not found.');
console.error('Run: pipx install claude-bridge');
console.error('Or:  pip install --user claude-bridge');
process.exit(1);
```

### 5.3 Updated `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "claude-bridge"
version = "0.1.0"
description = "Multi-session Claude Code dispatch from Telegram"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
keywords = ["claude", "claude-code", "telegram", "ai", "cli"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Environment :: Console",
  "Intended Audience :: Developers",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development :: Libraries :: Application Frameworks",
]

[project.urls]
Homepage = "https://github.com/hieutrtr/claude-bridge"
Repository = "https://github.com/hieutrtr/claude-bridge"
"Bug Tracker" = "https://github.com/hieutrtr/claude-bridge/issues"

[project.scripts]
claude-bridge = "claude_bridge.cli:main"
bridge-cli = "claude_bridge.cli:main"   # deprecated alias — kept for backward compat

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
claude_bridge = [
  "channel_server/**/*",   # bundle the TypeScript channel server + pre-built JS
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

---

## 6. Setup Wizard (`claude-bridge setup`)

The `setup` command wraps all 9 current steps into a single interactive wizard. Each step is **idempotent** — re-running `setup` is safe. Steps check existing state and skip or update as needed.

```
$ claude-bridge setup

╔═══════════════════════════════╗
║   Claude Bridge Setup Wizard  ║
╚═══════════════════════════════╝

Step 1/4: Telegram Bot Token
  Enter your bot token from @BotFather:
  > 7123456789:AAH1bGcK9...
  ✓ Token saved to ~/.claude-bridge/config.json

Step 2/4: Bot Project Directory
  Where should the Bridge Bot project be created?
  > ~/projects/bridge-bot (press Enter for default)
  ✓ Directory created: ~/projects/bridge-bot
  ✓ CLAUDE.md generated
  ✓ .mcp.json generated
  ✓ Channel server deployed to ~/.claude-bridge/channel/

Step 3/4: Cron Watcher
  ✓ Cron job installed (checks every 5 minutes)
  (Already installed — skipped)

Step 4/4: Start Bridge Bot
  Run this command to start your bridge:

    cd ~/projects/bridge-bot
    claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions

  Then DM your bot on Telegram to pair your account.

Setup complete! 🎉
Run `claude-bridge doctor` to verify your configuration at any time.
```

**Non-interactive mode** (for dotfiles / scripted installs):
```bash
claude-bridge setup --token 7123456789:AAH --bot-dir ~/bridge-bot --no-prompt
```

---

## 7. Uninstall (`claude-bridge uninstall`)

Complete, clean removal of everything claude-bridge installs. Idempotent — safe to run even if partially installed.

### What it removes:

| Component | Location | Action |
|-----------|----------|--------|
| Cron job | `crontab` | `crontab -l \| grep -v claude-bridge \| crontab -` |
| Bridge data dir | `~/.claude-bridge/` | `rm -rf ~/.claude-bridge` |
| MCP config entry | `~/projects/bridge-bot/.mcp.json` | Remove `server:bridge` entry |
| Channel server | `~/.claude-bridge/channel/` | Removed as part of data dir |
| Agent .md files | `~/.claude/agents/bridge--*.md` | `rm -f ~/.claude/agents/bridge--*.md` |
| Python package | pipx or pip | `pipx uninstall claude-bridge` (or `pip uninstall`) |
| Bun global package | `~/.bun/bin/claude-bridge` | `bun remove -g claude-bridge` |

### CLI flow:

```
$ claude-bridge uninstall

This will remove:
  ✓ Cron job (claude-bridge watcher)
  ✓ ~/.claude-bridge/ (database, config, channel server)
  ✓ ~/.claude/agents/bridge--*.md (agent definition files)
  ✓ .mcp.json entry in ~/projects/bridge-bot

The following will NOT be removed (run manually if desired):
  - ~/projects/bridge-bot/ (your bot project directory)
  - Bun itself
  - Python itself

Continue? [y/N] y

  Removing cron job... ✓
  Removing ~/.claude-bridge/... ✓
  Removing agent .md files... ✓
  Removing .mcp.json entry... ✓

Claude Bridge has been uninstalled.
To remove the Python package: pipx uninstall claude-bridge
To remove the Bun package:    bun remove -g claude-bridge
```

---

## 8. Doctor (`claude-bridge doctor`)

Diagnostic report: checks all dependencies, configuration, and connectivity. Designed to be the first thing users run when something is broken.

```
$ claude-bridge doctor

Claude Bridge Diagnostics
─────────────────────────────────────────────────────

Runtime
  Python version:     3.12.2  ✓  (required: >=3.11)
  Bun version:        1.1.38  ✓  (required: >=1.0.0)
  claude CLI:         1.0.17  ✓
  OS:                 macOS 15.2 (arm64)

Installation
  claude-bridge:      0.1.0   ✓  (installed via pipx)
  Install path:       ~/.local/bin/claude-bridge
  Data directory:     ~/.claude-bridge/  ✓  (exists)
  Config file:        ~/.claude-bridge/config.json  ✓

Configuration
  Telegram token:     ✓  (set, not shown)
  Bot project dir:    ~/projects/bridge-bot  ✓  (exists)
  CLAUDE.md:          ~/projects/bridge-bot/CLAUDE.md  ✓
  .mcp.json:          ~/projects/bridge-bot/.mcp.json  ✓

Channel Server
  Deployed:           ~/.claude-bridge/channel/dist/server.js  ✓
  Runtime check:      bun run --smol ~/.claude-bridge/channel/dist/server.js --check  ✓

Cron Watcher
  Installed:          ✓  (every 5 minutes)
  Last run:           2026-03-29 14:22:01  ✓  (2 minutes ago)

Database
  Path:               ~/.claude-bridge/bridge.db  ✓
  Agents:             3 registered
  Tasks (24h):        12 completed, 0 failed

Telegram Connectivity
  API reachable:      ✓  (getMe: @my_bridge_bot)
  Bot username:       @my_bridge_bot
  Webhook/polling:    polling active  ✓

Agent .md Files
  ~/.claude/agents/bridge--backend--my-api.md  ✓
  ~/.claude/agents/bridge--frontend--my-app.md  ✓

─────────────────────────────────────────────────────
Status: All checks passed ✓

Run `claude-bridge doctor --fix` to attempt auto-repair of detected issues.
```

**Exit codes:** `0` = all pass, `1` = warnings, `2` = critical failures.

---

## 9. Version Compatibility Matrix

| Python | Bun | macOS | Linux (Ubuntu) | Notes |
|--------|-----|-------|----------------|-------|
| 3.11 | ≥1.0.0 | 13+ (arm64 + x86_64) | 22.04, 24.04 | Minimum supported |
| 3.12 | ≥1.0.0 | 14+ | 22.04, 24.04 | Recommended |
| 3.13 | ≥1.0.0 | 15+ | 24.04 | Tested, supported |

**Claude Code compatibility:**
- Minimum Claude Code version: TBD (needs `--dangerously-load-development-channels` support)
- Channel API stability: follows Claude Code releases; track `claude --version`

**macOS architecture:**
- Apple Silicon (arm64): primary dev target
- Intel (x86_64): supported, not primary test target

**Windows:**
- Python 3.11+: available
- Bun: Windows support added in Bun 1.1
- `install.sh`: PowerShell equivalent needed — **deferred to v0.2**
- WSL2: should work as Linux path — untested

**Known incompatibilities:**
- Python 3.10 and below: not supported (uses `match` statements, `tomllib`, type union syntax)
- Bun <1.0: not supported (pre-1.0 APIs changed significantly)

---

## 10. CI / GitHub Actions — On Hold

> **GitHub Actions CI and release automation are deferred.** No `.github/workflows/` files will be added in Phase 1.

Rationale: The packaging strategy (especially §3.1 Claude Code channel) is still being researched. Setting up a release pipeline before the distribution model is finalised wastes effort. Add CI after Phase 1 delivery is validated manually.

**Manual release process (Phase 1):**
```bash
# 1. Bump version in src/claude_bridge/__init__.py
# 2. Build
bun run build           # pre-build TypeScript → dist/server.js
pip install build
python -m build         # produces dist/*.whl and dist/*.tar.gz
# 3. Publish to PyPI
pip install twine
twine upload dist/*
# 4. Publish to npm/Bun registry
bun publish
# 5. Tag
git tag v0.X.0 && git push origin main --tags
```

---

## 11. Install Script (`install.sh`)

Updated to use Bun as primary, pipx as fallback.

```bash
#!/usr/bin/env sh
# Claude Bridge installer
# https://github.com/hieutrtr/claude-bridge
#
# Usage: curl -fsSL https://raw.githubusercontent.com/hieutrtr/claude-bridge/main/install.sh | sh
#
set -e

PACKAGE_NAME="claude-bridge"
BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

info()    { printf "${BLUE}[claude-bridge]${NC} %s\n" "$1"; }
success() { printf "${GREEN}[claude-bridge]${NC} %s\n" "$1"; }
warn()    { printf "${YELLOW}[claude-bridge]${NC} %s\n" "$1"; }
error()   { printf "${RED}[claude-bridge]${NC} ERROR: %s\n" "$1" >&2; }

check_python() {
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
    PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
    [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ]
  else
    return 1
  fi
}

check_bun()    { command -v bun    >/dev/null 2>&1; }
check_pipx()   { command -v pipx   >/dev/null 2>&1; }
check_claude() { command -v claude >/dev/null 2>&1; }

# ── Check claude CLI ──────────────────────────────────────────────────────────

if ! check_claude; then
  error "claude CLI not found."
  error "Install Claude Code first: npm install -g @anthropic-ai/claude-code"
  exit 1
fi
info "✓ claude CLI found"

# ── Check Python 3.11+ ────────────────────────────────────────────────────────

if ! check_python; then
  error "Python 3.11+ required but not found."
  command -v brew >/dev/null 2>&1 && warn "Install with: brew install python@3.12"
  warn "Or download from: https://www.python.org/downloads/"
  exit 1
fi
info "✓ Python $(python3 --version | cut -d' ' -f2) found"

# ── Install / verify Bun ──────────────────────────────────────────────────────

if ! check_bun; then
  info "Installing Bun (required for channel server)..."
  curl -fsSL https://bun.sh/install | bash >/dev/null 2>&1
  export PATH="$HOME/.bun/bin:$PATH"
  if check_bun; then
    success "Bun $(bun --version) installed"
  else
    warn "Bun install may need a shell restart."
    warn "After restarting, run: bun install -g claude-bridge"
  fi
else
  info "✓ Bun $(bun --version) found"
fi

# ── Install claude-bridge ─────────────────────────────────────────────────────

# Primary: Bun global install (uses npm registry)
if check_bun; then
  info "Installing claude-bridge via Bun..."
  bun install -g "$PACKAGE_NAME"
  INSTALLED_BY="bun"
  success "Installed via bun install -g"
else
  # Fallback: pipx
  if ! check_pipx; then
    info "Installing pipx..."
    python3 -m pip install --user pipx --quiet
    export PATH="$HOME/.local/bin:$PATH"
  fi
  info "Installing claude-bridge via pipx (Bun not available)..."
  pipx install "$PACKAGE_NAME" --quiet
  INSTALLED_BY="pipx"
  success "Installed via pipx"
fi

# ── Verify ────────────────────────────────────────────────────────────────────

if ! command -v claude-bridge >/dev/null 2>&1; then
  warn "claude-bridge not in PATH yet."
  [ "$INSTALLED_BY" = "bun" ] && warn "Run: export PATH=\"\$HOME/.bun/bin:\$PATH\""
  [ "$INSTALLED_BY" = "pipx" ] && warn "Run: export PATH=\"\$HOME/.local/bin:\$PATH\""
  warn "Or restart your terminal."
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
success "Claude Bridge installed! 🎉"
echo ""
echo "  Next steps:"
echo ""
echo "  1. Create a Telegram bot: https://t.me/BotFather"
echo "  2. Run the setup wizard:"
echo ""
echo "       claude-bridge setup"
echo ""
echo "  (This guides you through token setup, bot project creation, and cron.)"
echo ""
[ "$INSTALLED_BY" = "bun"  ] && echo "  To update later:  bun update -g claude-bridge"
[ "$INSTALLED_BY" = "pipx" ] && echo "  To update later:  pipx upgrade claude-bridge"
echo "  To verify setup:  claude-bridge doctor"
echo ""
```

---

## 12. Install Experience — Before vs After

### Before (current git-clone)

```bash
# 9 steps, ~5-10 minutes, error-prone
git clone https://github.com/hieutrtr/claude-bridge.git ~/projects/claude-bridge
cd ~/projects/claude-bridge/channel && bun install
PYTHONPATH=src python3 -m claude_bridge.cli setup-telegram "<token>"
PYTHONPATH=src python3 -m claude_bridge.cli setup-bot ~/projects/bridge-bot
PYTHONPATH=src python3 -m claude_bridge.cli setup-cron
cd ~/projects/bridge-bot
claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions
```

### After (Phase 1 — Bun global + curl)

```bash
# 2 steps, ~2 minutes, guided
curl -fsSL https://raw.githubusercontent.com/hieutrtr/claude-bridge/main/install.sh | sh
claude-bridge setup
# (interactive wizard: enter bot token → done)
```

### After (Phase 1 — if Claude Code channel viable)

```bash
# 1 step
claude channel install claude-bridge
claude-bridge setup
```

### After (Phase 2 — Homebrew)

```bash
# macOS, 1 step
brew install hieutrtr/claude-bridge/claude-bridge
claude-bridge setup
```

---

## 13. Migration Plan (for existing git-clone users)

Users who currently run claude-bridge via `git clone` need a clear upgrade path.

### Detection

`claude-bridge setup` should detect an existing git-clone installation:
```
Detected existing git-clone installation at ~/projects/claude-bridge.
Would you like to migrate to the installed package? [Y/n]
```

### Migration Steps

```
$ claude-bridge migrate

Migrating from git-clone to installed package...

Step 1: Export existing configuration
  Reading token from PYTHONPATH=src python3 -m claude_bridge.cli ... ✓
  Reading agent definitions from ~/.claude/agents/bridge--*.md ... ✓ (3 found)
  Reading database from ~/.claude-bridge/bridge.db ... ✓

Step 2: Update .mcp.json
  Old server path: /Users/you/projects/claude-bridge/channel/server.ts
  New server path: ~/.claude-bridge/channel/dist/server.js
  Updating ~/projects/bridge-bot/.mcp.json ... ✓

Step 3: Update cron job
  Old command: PYTHONPATH=/Users/you/projects/claude-bridge/src ...
  New command: claude-bridge cron-watch
  Updating crontab ... ✓

Step 4: Verify
  Running claude-bridge doctor ... ✓

Migration complete!

Your git-clone at ~/projects/claude-bridge is no longer needed by the bridge.
You may delete it or keep it for development purposes.
```

### Backward Compatibility Guarantees

- `bridge-cli` command: kept as deprecated alias through v0.2
- Agent .md files in `~/.claude/agents/bridge--*.md`: format unchanged
- SQLite schema: backward compatible (additive migrations only, no drops)
- `.mcp.json` format: unchanged; only the server path changes

### Communication to Existing Users

- CHANGELOG.md entry under the first packaged release
- README banner: "Upgrading from git-clone? See [Migration Guide](docs/migration.md)"

---

## 14. Build Pipeline (Manual, Phase 1)

### Pre-build: Bundle Channel Server

```bash
# Pre-build TypeScript → single JS file (no bun install needed at runtime)
cd channel
bun build server.ts \
  --outfile ../src/claude_bridge/channel_server/dist/server.js \
  --target bun --bundle --minify
cp package.json ../src/claude_bridge/channel_server/
```

### Build Python Package

```bash
pip install build
python -m build
# Output:
#   dist/claude_bridge-0.1.0.tar.gz
#   dist/claude_bridge-0.1.0-py3-none-any.whl
```

### Version Management

Single source of truth in `src/claude_bridge/__init__.py`:

```python
__version__ = "0.1.0"
```

`pyproject.toml` reads it dynamically:

```toml
[project]
dynamic = ["version"]

[tool.setuptools.dynamic]
version = {attr = "claude_bridge.__version__"}
```

---

## 15. Homebrew Formula (Phase 2)

### Repository: `github.com/hieutrtr/homebrew-claude-bridge`

```ruby
# Formula/claude-bridge.rb
class ClaudeBridge < Formula
  desc "Multi-session Claude Code dispatch from Telegram"
  homepage "https://github.com/hieutrtr/claude-bridge"
  url "https://files.pythonhosted.org/packages/source/c/claude-bridge/claude_bridge-0.1.0.tar.gz"
  sha256 "PLACEHOLDER_UPDATED_BY_CI"
  license "MIT"
  head "https://github.com/hieutrtr/claude-bridge.git", branch: "main"

  depends_on "python@3.12"
  depends_on "bun"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/claude-bridge --version")
  end
end
```

Because claude-bridge has no pip dependencies, there are **no `resource` blocks**. `depends_on "bun"` means `brew install claude-bridge` also installs Bun automatically.

---

## 16. PyPI Setup (when ready)

### One-time setup:

```bash
# 1. Register at https://pypi.org/
# 2. Configure Trusted Publishing (OIDC — no API keys):
#    Owner: hieutrtr | Repo: claude-bridge | Workflow: release.yml | Env: pypi
# 3. First manual publish to claim the package name:
pip install twine build
python -m build
twine upload dist/*
```

After the first publish, subsequent releases use `twine upload` (manual Phase 1) or GitHub Actions (Phase 3).

---

## 17. Open Questions

1. **Claude Code channel distribution (§3.1):** This is the highest-priority research item. Is `--dangerously-load-development-channels` dev-only, or a user-facing install mechanism? Can we publish a channel to a registry?

2. **Bun package registry:** `bun publish` currently publishes to the npm registry. Is there a separate Bun registry planned, and should we target it when it launches?

3. **Package name on PyPI:** Is `claude-bridge` available? Check https://pypi.org/project/claude-bridge/ — if taken, use `claude-bridge-bot` or `clbridge`.

4. **`claude-bridge` vs `bridge-cli`:** `claude-bridge` is the canonical command going forward. `bridge-cli` is a deprecated alias kept through v0.2.

5. **Windows / PowerShell installer:** `install.sh` is sh-only. A PowerShell equivalent is needed for native Windows support — deferred to v0.2.

6. **Auto-update notifications:** Neither pipx nor Bun global installs auto-update. A startup check (`claude-bridge` pings PyPI/npm weekly, prints a notice) would improve upgrade discoverability. Add to `doctor` in Phase 2.

7. **`setup` wizard TTY requirement:** Interactive prompts require a TTY. Non-interactive mode: `claude-bridge setup --token <tok> --bot-dir ~/bridge-bot --no-prompt`.
