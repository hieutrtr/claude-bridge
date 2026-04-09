# Legacy Code (Deprecated)

This directory contains the original Python/JavaScript implementation of Claude Bridge.
It has been replaced by the TypeScript implementation in the project root (`src/`).

**Status:** Deprecated — reference only. Do not modify or use for new development.

**Preserved for:** Historical reference, rollback scenarios, and understanding design decisions.

## Contents

- `src/claude_bridge/` — Original Python package
- `channel/` — Original TypeScript channel server
- `tests/` — Original pytest test suite (33 files)
- `pyproject.toml` — Python package config
- `MANIFEST.in` — Python distribution manifest
- `build.sh` / `install.sh` — Old build/install scripts
- `package.json` — Old root package.json (for channel builds)
- `sdd-guideline.md`, `GUIDELINE.md`, `INVESTIGATION.md` — Design docs

## Migration

The TypeScript migration was completed in April 2026 (Waves 1-7).
See `CHANGELOG.md` in the project root for migration details.
