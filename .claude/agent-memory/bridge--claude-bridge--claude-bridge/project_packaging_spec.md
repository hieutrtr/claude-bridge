---
name: packaging_spec
description: Packaging & distribution strategy for claude-bridge — Bun primary, Claude Code channel research ongoing, curl installer as hero command, Homebrew secondary, CI deferred
type: project
---

Packaging spec at `plan/PACKAGING_SPEC.md` — revised 2026-03-29.

**Runtime decision:** Bun is primary (Anthropic acquired Bun — it's the ecosystem direction). npm is deprecated for this project. Python core stays — no rewrite.

**Recommended distribution strategy:**
1. Research Claude Code channel/plugin distribution first (highest priority — if viable, becomes primary install path: `claude channel install claude-bridge`)
2. `bun install -g claude-bridge` (primary CLI install, uses npm registry via `bun publish`)
3. `curl | sh` installer as hero README command (now delegates to `bun install -g`)
4. pipx/PyPI as Python-first fallback

**Why:** Bun is already required for the channel server; no extra friction to use it for global install too. Claude Code channel distribution would be the most native integration. npm postinstall anti-patterns avoided by using Bun.

**Phase plan:**
1. Phase 1 (MVP): Research Claude Code channel distribution → Bun global install + curl installer + `claude-bridge setup` wizard + `uninstall` + `doctor`
2. Phase 2: Homebrew tap, pipx/PyPI explicit path, update notifications
3. Phase 3 (deferred): Binary releases, GitHub Actions CI/release automation

**New commands added to spec:**
- `claude-bridge uninstall` — removes cron, ~/.claude-bridge, .mcp.json entries, agent .md files
- `claude-bridge doctor` — diagnostic report (deps, config, connectivity, cron status)
- `claude-bridge migrate` — migration path for existing git-clone users

**Compat matrix:** Python 3.11/3.12/3.13 × Bun ≥1.0 × macOS 13+ / Ubuntu 22.04+. Windows deferred to v0.2.

**How to apply:** CI/GitHub Actions on hold until distribution model is finalised. Manual release process in spec §10.
