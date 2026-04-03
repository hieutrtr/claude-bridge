---
name: improvement_plan_status
description: 15-issue improvement plan from installation experience analysis — 3 P0 blocking, 7 P1 important, 5 P2 polish + 2 new features. Full plan in data/output/latest.txt
type: project
---

Installation experience analysis (2026-04-03) found 15 issues. Full plan: `data/output/latest.txt`

Status: ⚠️ NOT READY to share publicly — 3 P0 blockers unfixed.

**Phase 1 — P0 BLOCKING (do first):**
- IMP-01: channel_server/dist/server.js missing → add auto-build in setup wizard
- IMP-02: `mcp` dependency missing from pyproject.toml → add `mcp>=1.0`
- IMP-03: install.sh doesn't exist → write per PACKAGING_SPEC.md §11

**Phase 2 — P1 IMPORTANT:**
- IMP-04: Version inconsistency (3 files different) + package name mismatch
- IMP-05: Stop hook uses `python3` not `sys.executable` (breaks pipx installs)
- IMP-06: `bridge start` missing config validation
- IMP-07: No bun.lock committed
- IMP-08: No .env.example for channel server env vars
- IMP-09: README pairing Step 6 missing context about where code comes from

**Phase 3 — P2 + NEW:**
- IMP-10: CHANGELOG.md missing
- IMP-11: bridge-cli doctor missing key checks
- IMP-12: Architecture diagram (mermaid) missing from README
- IMP-13: Troubleshooting section sparse + test_mcp_server.py skip unexplained
- IMP-14 (NEW): CLAUDE_BRIDGE_HOME env var (learned from OpenClaw OPENCLAW_HOME)
- IMP-15 (NEW): systemd/launchd daemon install (learned from openclaw onboard --install-daemon)

**Why:** Installation analysis showed a new user cannot successfully install without hitting P0 issues. OpenClaw patterns (single-command install, doctor checks, CHANGELOG, daemon install) are worth adopting.

**How to apply:** When dispatching tasks, start with IMP-01+IMP-02 (can be parallel), then IMP-03. Commit format: `IMP-XX: description`.
