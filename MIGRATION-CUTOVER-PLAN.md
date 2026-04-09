# Migration Cutover Plan: Python → TypeScript

## Status: DRAFT — Review before executing

This plan replaces the old Python/JS codebase with the migrated TypeScript code in `ts-src/`.
The TypeScript migration is feature-complete (Waves 1-7), 90% test coverage, strict mode clean.

**Key decision:** Old source files are moved to `legacy/` (not deleted) for future reference.

---

## 1. Audit: What Goes, What Stays, What Moves

### Files/Directories to MOVE to `legacy/` (old code, reference-only)

Instead of deleting old source files, move them into a `legacy/` folder at the project root.
This preserves them for reference while clearly marking them as deprecated. A `legacy/README.md`
will explain their status.

| Path | Destination in `legacy/` |
|------|--------------------------|
| `src/claude_bridge/` | `legacy/src/claude_bridge/` |
| `channel/` | `legacy/channel/` |
| `tests/` | `legacy/tests/` |
| `pyproject.toml` | `legacy/pyproject.toml` |
| `MANIFEST.in` | `legacy/MANIFEST.in` |
| `build.sh` | `legacy/build.sh` |
| `install.sh` | `legacy/install.sh` |
| `package.json` (root) | `legacy/package.json` |
| `sdd-guideline.md` | `legacy/sdd-guideline.md` |
| `GUIDELINE.md` | `legacy/GUIDELINE.md` |
| `INVESTIGATION.md` | `legacy/INVESTIGATION.md` |

### Files/Directories to DELETE (ephemeral artifacts, not worth preserving)

| Path | Reason |
|------|--------|
| `dist/` | Old PyPI wheels (0.3.8, 0.3.9) — stale build artifacts |
| `.pytest_cache/` | Pytest cache — transient |
| `.venv/` | Python virtualenv — environment-specific, not source |

### Files/Directories to KEEP (at root)

| Path | Notes |
|------|-------|
| `.git/` | Git history |
| `.github/workflows/` | CI — but `publish.yml` needs rewrite (see Section 3) |
| `.claude/` | Claude Code config (agents, rules, settings) |
| `.gitignore` | Needs updating (see Section 3) |
| `CLAUDE.md` | Project instructions — needs major rewrite |
| `CHANGELOG.md` | Release history — keep, continue appending |
| `README.md` / `README_en.md` | Keep, update for TypeScript |
| `plan/` | Architecture docs — keep for reference |
| `specs/` | Task specs — keep for reference |
| `research/` | Research notes — keep for reference |
| `docs/` | Documentation — keep |
| `data/` | Agent memory artifacts — keep |

### What Replaces What

| Old (Python/JS) | New (TypeScript) |
|-----------------|-----------------|
| `src/claude_bridge/cli.py` | `src/cli/index.ts` |
| `src/claude_bridge/db.py` | `src/data/db.ts` |
| `src/claude_bridge/session.py` | `src/data/session.ts` |
| `src/claude_bridge/dispatcher.py` | `src/execution/dispatcher.ts` |
| `src/claude_bridge/on_complete.py` | `src/execution/on-complete.ts` |
| `src/claude_bridge/watcher.py` | `src/execution/watcher.ts` |
| `src/claude_bridge/notify.py` | `src/execution/notify.ts` |
| `src/claude_bridge/daemon.py` | `src/infra/daemon.ts` |
| `src/claude_bridge/bridge_cmd.py` | `src/infra/bridge-cmd.ts` |
| `src/claude_bridge/mcp_server.py` | `src/mcp/server.ts` |
| `src/claude_bridge/mcp_tools.py` | `src/mcp/tools.ts` + `src/mcp/tool-handlers.ts` |
| `src/claude_bridge/agent_md.py` | `src/cli/agent-md.ts` |
| `src/claude_bridge/memory.py` | `src/cli/memory.ts` |
| `src/claude_bridge/loop_orchestrator.py` | `src/orchestration/loop.ts` |
| `src/claude_bridge/loop_evaluator.py` | `src/orchestration/evaluator.ts` |
| `src/claude_bridge/scheduler.py` | `src/orchestration/scheduler.ts` |
| `src/claude_bridge/telegram_poller.py` | `src/channel/telegram/` |
| `channel/server.ts` | `src/mcp/server.ts` |
| `channel/lib.ts` | `src/channel/core.ts` + adapters |
| `channel/format.ts` | `src/channel/telegram/format.ts` etc. |
| `tests/*.py` (33 files) | `tests/` (36 files, bun test) |

---

## 2. Directory Restructuring

### Target structure (after cutover)

```
claude-bridge/                  # Project root
├── .claude/                    # Claude Code config (unchanged)
├── .claude-plugin/             # Plugin metadata (from ts-src)
│   └── plugin.json
├── .github/workflows/          # CI (updated)
├── .gitignore                  # Updated for TS
├── bun.lock                    # Dependency lock (from ts-src)
├── CHANGELOG.md
├── CLAUDE.md                   # Rewritten for TS
├── legacy/                     # ⚠️ DEPRECATED — old Python/JS code (reference-only)
│   ├── README.md               # Explains deprecation status
│   ├── src/claude_bridge/      # Old Python package
│   ├── channel/                # Old TS channel server
│   ├── tests/                  # Old pytest suite
│   ├── pyproject.toml
│   ├── MANIFEST.in
│   ├── build.sh
│   ├── install.sh
│   ├── package.json
│   ├── sdd-guideline.md
│   ├── GUIDELINE.md
│   └── INVESTIGATION.md
├── mcp.json                    # MCP config (from ts-src)
├── package.json                # From ts-src/package.json
├── README.md
├── README_en.md
├── skills/                     # Claude Code skills (from ts-src)
│   ├── dispatch.md
│   └── status.md
├── src/                        # Main source (from ts-src/src/)
│   ├── channel/
│   ├── cli/
│   ├── config.ts
│   ├── data/
│   ├── execution/
│   ├── index.ts
│   ├── infra/
│   ├── mcp/
│   ├── orchestration/
│   └── types.ts
├── tests/                      # Test suite (from ts-src/tests/)
│   ├── wave1/ ... wave7/
│   └── coverage/
├── tsconfig.json               # From ts-src
├── docs/                       # Merged: root docs/ + ts-src/docs/
├── plan/
├── specs/
├── research/
└── data/
```

### Key moves

1. **`ts-src/src/` → `src/`** — Promote TS source to root `src/`
2. **`ts-src/tests/` → `tests/`** — Replace old pytest tests
3. **`ts-src/package.json` → `package.json`** — Replace root package.json
4. **`ts-src/tsconfig.json` → `tsconfig.json`** — Move to root
5. **`ts-src/mcp.json` → `mcp.json`** — Move to root
6. **`ts-src/bun.lock` → `bun.lock`** — Move to root
7. **`ts-src/.claude-plugin/` → `.claude-plugin/`** — Merge with root (currently empty)
8. **`ts-src/skills/` → `skills/`** — Merge with root (currently empty)
9. **`ts-src/docs/` → `docs/`** — Merge with existing docs/
10. **`ts-src/` directory removed** — Everything promoted out

---

## 3. Config Updates

### package.json

The `ts-src/package.json` becomes the root `package.json`. Path updates needed:

```jsonc
{
  "bin": {
    "bridge-cli": "./src/cli/index.ts"  // Already correct after src/ promotion
  },
  "scripts": {
    "start": "bun run src/index.ts",     // Already correct
    "build": "bun build src/index.ts --outdir dist --target node",  // Already correct
    "test": "bun test",                   // Already correct
    "typecheck": "tsc --noEmit"           // Already correct
  }
}
```

No path changes needed — `ts-src/package.json` already uses `src/` relative paths.

### tsconfig.json

Move `ts-src/tsconfig.json` to root. No changes needed — already references `./src` and `./dist`.

### mcp.json

Currently references `${CLAUDE_PLUGIN_ROOT}/src/mcp/server.ts`. This should work as-is if `CLAUDE_PLUGIN_ROOT` points to the project root.

### .gitignore — Rewrite

```gitignore
# Claude Code
.claude/worktrees/

# Dependencies
node_modules/

# Build output
dist/

# IDE
.vscode/
.idea/
*.swp

# Bridge runtime
*.db
*.log

# Environment secrets
.env
channel/.env

# OS
.DS_Store

# Claude
.mcp.json
```

Remove: Python-specific entries (`__pycache__`, `*.py[cod]`, `*.egg*`, `build/`, `!src/claude_bridge/channel_server/dist/`, `.pytest_cache/`)

### .github/workflows/publish.yml

**Option A: Remove entirely** — If distribution is now via Claude Code plugin ecosystem only.

**Option B: Rewrite for npm/bun** — If publishing to npm:
- Replace Python build steps with `bun install && bun run build`
- Replace PyPI publish with npm publish
- Update environment URLs

**Recommendation:** Keep the file but disable it (rename to `publish.yml.disabled`) until the npm/plugin distribution strategy is decided. The old PyPI package can remain as-is for existing users.

### CLAUDE.md — Major Rewrite

The entire CLAUDE.md needs rewriting to reflect:
- TypeScript/Bun stack (not Python)
- New project structure (`src/` not `src/claude_bridge/`)
- New build/test commands (`bun test` not `pytest`)
- New entry points (`bun run src/cli/index.ts` not `python -m claude_bridge.cli`)
- Remove all Python-specific conventions
- Remove the "Development & Deploy Flow" section about dual Python+TS layers
- Update the "Build & Test" section

---

## 4. Entry Points

### CLI: `bridge-cli`

| Before | After |
|--------|-------|
| `pip install -e .` → `bridge-cli` (Python) | `bun run src/cli/index.ts` or `bunx bridge-cli` |
| Defined in `pyproject.toml [project.scripts]` | Defined in `package.json "bin"` |

For local dev: `bun run src/cli/index.ts` works directly.
For installed use: `bun link` or add to PATH.

### CLI: `bridge` (dispatch shortcut)

| Before | After |
|--------|-------|
| `bridge` → `src/claude_bridge/bridge_cmd:main` | `bun run src/infra/bridge-cmd.ts` |

Add to `package.json` bin:
```json
"bin": {
  "bridge-cli": "./src/cli/index.ts",
  "bridge": "./src/infra/bridge-cmd.ts"
}
```

### MCP Server

| Before | After |
|--------|-------|
| `python3 -m claude_bridge.mcp_server` | `bun run src/mcp/server.ts` |
| FastMCP (Python) | @modelcontextprotocol/sdk (TypeScript) |

Configured via `mcp.json` — already points to `src/mcp/server.ts`.

### Daemon

| Before | After |
|--------|-------|
| `bridge-cli daemon start` (Python subprocess) | `bridge-cli daemon start` (Bun subprocess) |

The daemon module at `src/infra/daemon.ts` handles lifecycle. The daemon process itself
runs `claude --agent ...` which is unchanged.

### Stop Hook (on-complete)

| Before | After |
|--------|-------|
| `python3 -m claude_bridge.on_complete` | `bun run src/execution/on-complete.ts` |

Agent `.md` files generated by `bridge-cli create-agent` include the stop hook path.
The `src/cli/agent-md.ts` module must generate the correct `bun run ...` command.

**Action required:** Verify that `agent-md.ts` generates stop hooks pointing to
`bun run <project-root>/src/execution/on-complete.ts` (not the old Python path).

---

## 5. Backwards Compatibility

### Python scripts referencing old paths

| Script | Status | Action |
|--------|--------|--------|
| `build.sh` | References `channel/server.ts → src/claude_bridge/channel_server/dist/` | Moved to `legacy/` |
| `install.sh` | Clones repo, runs pip install | Moved to `legacy/` — write new bun-based installer if needed |
| `.github/workflows/publish.yml` | Builds Python wheel, publishes to PyPI | Disable or rewrite |

### Existing deployed instances

If there are running instances using the Python version:
1. Stop all instances: `bridge stop` / `bridge-cli daemon stop`
2. The SQLite database at `~/.claude-bridge/bridge.db` is **compatible** — same schema
3. Agent `.md` files in `~/.claude-bridge/` may reference old Python stop hooks — regenerate with `bridge-cli create-agent`
4. `.mcp.json` in bot directories references old Python MCP — re-run `bridge-cli setup-bot`

### PyPI package (`claude-agent-bridge`)

The existing PyPI package remains as-is. Users who installed via pip can continue using
the Python version. The TypeScript version is a separate distribution channel.

Consider publishing a final Python version (0.5.9) that prints a deprecation notice
pointing users to the TypeScript version.

---

## 6. Testing: Verification Checklist

### Pre-cutover (on ts-migration branch, before restructure)

```bash
# Ensure all TS tests pass
cd ts-src && bun test

# Ensure typecheck passes
cd ts-src && bun run typecheck
```

### Post-cutover (after restructure)

```bash
# 1. Install dependencies
bun install

# 2. Run all tests
bun test
# Expected: 36 test files, 90%+ line coverage

# 3. Typecheck
bun run typecheck
# Expected: 0 errors

# 4. CLI smoke test
bun run src/cli/index.ts --help
bun run src/cli/index.ts list-agents
bun run src/cli/index.ts status

# 5. MCP server starts
bun run src/mcp/server.ts &
# Should start without error, kill after test

# 6. Build succeeds
bun run build
# Should produce dist/index.js

# 7. Import resolution
# Verify no imports reference ts-src/ or old Python paths (exclude legacy/)
grep -r "ts-src" src/ tests/ package.json tsconfig.json mcp.json || echo "OK: no ts-src references"
grep -r "claude_bridge" src/ tests/ || echo "OK: no Python references"
# Note: legacy/ will have old references — that's expected, it's reference-only

# 8. Plugin metadata
cat .claude-plugin/plugin.json  # Should exist and be valid JSON

# 9. Integration test (manual)
# - Create agent: bun run src/cli/index.ts create-agent test-agent /tmp/test-project --purpose "test"
# - Dispatch task: bun run src/cli/index.ts dispatch test-agent "echo hello"
# - Check status: bun run src/cli/index.ts status
```

---

## 7. Git Strategy

### Recommended: Staged commits on `ts-migration` branch

Do NOT do this as one giant commit. Use 4-5 focused commits for reviewability and safe rollback:

```
Commit 1: "chore: move old Python/JS source to legacy/ for reference"
  - Create: legacy/ directory with README.md (deprecated/reference-only notice)
  - Move: src/claude_bridge/ → legacy/src/claude_bridge/
  - Move: channel/ → legacy/channel/
  - Move: tests/ → legacy/tests/
  - Move: pyproject.toml, MANIFEST.in, build.sh, install.sh → legacy/
  - Move: package.json (root), sdd-guideline.md, GUIDELINE.md, INVESTIGATION.md → legacy/
  - Delete: dist/ (stale build artifacts), .pytest_cache/, .venv/ (ephemeral, not worth keeping)
  - Remove: src/ directory (now empty after moving claude_bridge/)

Commit 2: "chore: promote ts-src/ contents to project root"
  - Move: ts-src/src/ → src/
  - Move: ts-src/tests/ → tests/
  - Move: ts-src/package.json → package.json
  - Move: ts-src/tsconfig.json → tsconfig.json
  - Move: ts-src/mcp.json → mcp.json
  - Move: ts-src/bun.lock → bun.lock
  - Move: ts-src/.claude-plugin/ → .claude-plugin/
  - Move: ts-src/skills/ → skills/
  - Move: ts-src/docs/ → docs/ (merge)
  - Remove: ts-src/ (now empty)

Commit 3: "chore: update configs for new structure"
  - Rewrite: .gitignore (remove Python entries, add node_modules)
  - Update: CLAUDE.md (rewrite for TypeScript)
  - Disable: .github/workflows/publish.yml → publish.yml.disabled
  - Verify: package.json paths still correct
  - Verify: tsconfig.json paths still correct

Commit 4: "chore: verify build and tests pass"
  - Run: bun install (generates/updates bun.lock)
  - Run: bun test (all 36 files pass)
  - Run: bun run typecheck (0 errors)
  - Fix: any import path issues discovered
  - Update: README.md with new setup instructions

Commit 5: "chore: update README and changelog for v1.0.0-beta"
  - Update: README.md — installation via bun, new commands
  - Update: CHANGELOG.md — migration notes
  - Bump: package.json version if needed
```

### Branch strategy

1. Continue on `ts-migration` branch (current)
2. Execute the 4-5 commits above
3. Run full test suite, verify everything works
4. Open PR: `ts-migration` → `main`
5. Squash-merge or regular merge (prefer regular merge to preserve history)
6. Tag: `v1.0.0-beta.1` (or `v0.7.0` to continue semver)

---

## 8. Rollback Plan

### During cutover (before merging to main)

The cutover happens entirely on `ts-migration` branch. If anything goes wrong:

```bash
# Option A: Reset to before cutover commits
git log --oneline  # Find the commit before cutover started
git reset --hard <pre-cutover-commit>

# Option B: Revert specific commits
git revert <commit-hash>  # Revert in reverse order
```

### After merging to main

```bash
# Revert the merge commit
git revert -m 1 <merge-commit-hash>
```

This restores `main` to the Python version. The `ts-migration` branch still has
the TypeScript code for retry.

### Restore from legacy/

Because the old code lives in `legacy/` rather than being deleted, you can also
restore individual files without reverting commits:
```bash
# Restore a specific file
cp legacy/src/claude_bridge/dispatcher.py src/claude_bridge/dispatcher.py

# Restore everything (full rollback to Python)
cp -r legacy/src/claude_bridge/ src/claude_bridge/
cp -r legacy/tests/ tests/
cp legacy/pyproject.toml .
```

### Nuclear option

The Python version is published on PyPI (v0.3.9). Users can always:
```bash
pip install claude-agent-bridge==0.3.9
```

### Data safety

The SQLite database (`~/.claude-bridge/bridge.db`) is never modified by the cutover.
Both Python and TypeScript versions use the same schema. No data migration needed.

---

## 9. Open Questions

1. **npm publish?** — Should we publish to npm as `claude-bridge`? Or is Claude Code plugin the only distribution channel?
2. **install.sh replacement?** — Do we need a new installer script for bun-based install?
3. **PyPI deprecation?** — Should we publish a final Python version with deprecation notice?
4. **Version number?** — `v1.0.0` (breaking change, new stack) or `v0.7.0` (continuation)?
5. **Root-level `.claude-plugin/` and `skills/`** — These directories already exist at root but are empty. Were they created manually? Should we check for conflicts?
6. **`ts-src/.gitignore`** — Has TS-specific ignores. Merge into root `.gitignore` or use as-is?

---

## Execution Checklist

- [ ] Review and approve this plan
- [ ] Answer open questions above
- [ ] Pre-cutover: run `cd ts-src && bun test && bun run typecheck`
- [ ] Commit 1: Move old code to legacy/
- [ ] Commit 2: Promote ts-src/
- [ ] Commit 3: Update configs
- [ ] Commit 4: Verify build/tests
- [ ] Commit 5: Update docs
- [ ] Open PR to main
- [ ] Manual smoke test on a real instance
- [ ] Merge to main
- [ ] Tag release
