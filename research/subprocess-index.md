# Subprocess Architecture Research — Document Index

**Purpose**: Complete research on spawning Claude Code CLI as child processes for the Claude Bridge MVP and scaling phases.

**Research Date**: 2026-03-26
**Status**: Complete research document (ready for implementation planning)

---

## Document Overview

### 1. **subprocess-research.md** (42 KB)
**The comprehensive deep dive** — read this first for full context.

**Contents**:
- Executive summary of the subprocess approach
- All 6 research questions with detailed answers
- Evidence from existing codebase
- Process tree diagrams (ASCII)
- IPC protocol specification (JSON Lines format)
- Spawning & cleanup code outline (pseudocode)
- Limitations & gotchas
- Comparison with alternatives (Agent SDK, Message Queues, HTTP)
- Testing strategy (unit, integration, load tests)
- 8-week implementation roadmap (MVP → Tier 3)
- Key metrics to track
- References to existing codebase documents

**Best for**: Understanding the full architecture, decision-making, reference.

---

### 2. **subprocess-quick-reference.md** (14 KB)
**The TL;DR** — quick answers + working code skeletons.

**Contents**:
- Quick answer table (1 page)
- Code skeleton: MVP Spawn (~50 lines)
- Code skeleton: Daemon Tier 1 + Queue (~150 lines)
- Code skeleton: Daemon Tier 2 + Worker Pool (~120 lines)
- IPC message cheat sheet (all message types)
- File locations reference
- MVP vs Production comparison table
- Common pitfalls & fixes
- Deployment checklist
- Next steps

**Best for**: Developers starting implementation, quick reference during coding.

---

### 3. **subprocess-implementation-notes.md** (23 KB)
**The implementation cookbook** — detailed code patterns, edge cases, debugging.

**Contents**:
- Core implementation details
  - Subprocess spawning (headless vs persistent modes)
  - Async I/O patterns (reading from stdout, timeout handling)
  - Unix socket client/server implementation (full working code)
- Signal collection & reporting
  - Signal types to track
  - Signal collection during task execution
  - Enhancement proposal logic
- Worker health monitoring (heartbeat protocol)
- Error handling & recovery (worker crash recovery, task failure recovery)
- macOS-specific considerations
  - tmux issues
  - Process management quirks
  - Socket cleanup on macOS
- Performance optimization
  - Line buffering for stdout
  - Batch message processing
- Testing strategies (unit, integration tests)
- Debugging tips (logging, socket monitoring, database inspection)
- Scaling considerations (multiple daemons, worker pool sizing)
- Troubleshooting checklist (10 common issues + fixes)

**Best for**: Implementation details, debugging, edge case handling.

---

## Quick Navigation

### For Decision Makers
1. Read: **subprocess-research.md** → Section 6 (Pros/cons)
2. Read: **subprocess-quick-reference.md** → Section 8 (MVP vs Production)
3. Decision: MVP first? Daemon from start? What tier?

### For MVP Developers
1. Read: **subprocess-quick-reference.md** → Full document
2. Copy: Code skeleton for MVP Spawn
3. Reference: **subprocess-implementation-notes.md** → Section 1.1 (Spawn Process)
4. Test against checklist: **subprocess-quick-reference.md** → Section 9

### For Daemon Developers (Phase 1+)
1. Read: **subprocess-research.md** → Sections 2-3 (Architecture & IPC)
2. Copy: Code skeleton for Daemon Tier 1 or 2
3. Deep dive: **subprocess-implementation-notes.md** → Sections 1-2 (IPC details)
4. Implement: Health monitoring, error handling, testing

### For DevOps / Deployment
1. Read: **subprocess-quick-reference.md** → Section 6 (File locations)
2. Reference: **subprocess-implementation-notes.md** → Section 8 (Debugging)
3. Deploy: MVP → Tier 1 → Tier 2 incrementally

---

## Key Questions Answered

### Q1: Can you spawn Claude Code CLI as subprocess?
✅ **YES** → See subprocess-research.md, Q1 + subprocess-quick-reference.md, Section 2

### Q2: Best IPC method?
**Unix sockets** → See subprocess-research.md, Q2 + subprocess-implementation-notes.md, Section 1.3

### Q3: Know when child finishes?
✅ **Multiple methods** → See subprocess-research.md, Q3 + subprocess-implementation-notes.md, Section 1.2

### Q4: Manage multiple children?
✅ **Yes, async/await** → See subprocess-research.md, Q4 + subprocess-quick-reference.md, Section 3

### Q5: Spawn programmatically?
✅ **Full CLI support** → See subprocess-research.md, Q5

### Q6: Complexity vs latency vs reliability?
**Detailed comparison** → See subprocess-research.md, Q6 + subprocess-quick-reference.md, Section 8

---

## Architecture Tiers

### MVP Phase (Weeks 1-2)
Direct spawn per task. No daemon. ~200 lines Python.

**Read**: subprocess-quick-reference.md, Section 2

**Key file**: subprocess-implementation-notes.md, Section 1.1

**Checklist**: subprocess-quick-reference.md, Section 9 (MVP Phase)

---

### Phase 1: Daemon Tier 1 (Week 3)
Add queue + basic IPC. ~400 lines Python.

**Read**: subprocess-quick-reference.md, Section 3

**Key files**: subprocess-implementation-notes.md, Sections 1.3 (Sockets) + 2 (Health)

**Checklist**: subprocess-quick-reference.md, Section 9 (Phase 1)

---

### Phase 1.5: Daemon Tier 2 (Week 4)
Worker pool + auto-respawn. ~600 lines Python.

**Read**: subprocess-quick-reference.md, Section 4

**Key files**: subprocess-implementation-notes.md, Sections 1.2 (Async) + 4 (Recovery)

**Checklist**: subprocess-quick-reference.md, Section 9 (Phase 1.5)

---

### Phase 2: Daemon Tier 3 (Weeks 5-6)
Full async + production hardening. ~1000 lines Python.

**Read**: subprocess-research.md, Section 6 (Approach: Daemon Tier 3)

**Key files**: subprocess-implementation-notes.md, Sections 5-7 (macOS, Performance, Debugging)

**Checklist**: subprocess-quick-reference.md, Section 9 (Phase 2)

---

## File Locations (Reference)

All paths referenced in research:

```
/tmp/claude-bridge/
├── daemon.sock              # Main daemon socket
└── worker-*.sock           # Worker sockets (optional)

~/.claude-bridge/
├── task_queue.db            # SQLite task queue
├── daemon.log               # Daemon logs
├── agents/
│   └── {agent-name}/
│       ├── profile.yaml
│       ├── enhancement-accumulator.yaml
│       └── session.log
└── sessions.yaml            # Worker registry
```

See: subprocess-implementation-notes.md, Section 3

---

## IPC Protocol

All message types: subprocess-quick-reference.md, Section 5

Detailed spec: subprocess-research.md, Section 3

Implementation details: subprocess-implementation-notes.md, Section 1.3

---

## Code Skeletons

| What | Where | Lines |
|------|-------|-------|
| **Spawn subprocess** | subprocess-implementation-notes.md, 1.1 | 30 |
| **Async read output** | subprocess-implementation-notes.md, 1.2 | 25 |
| **Timeout handling** | subprocess-implementation-notes.md, 1.2 | 20 |
| **IPC Server** | subprocess-implementation-notes.md, 1.3 | 80 |
| **IPC Client** | subprocess-implementation-notes.md, 1.3 | 70 |
| **Signal collection** | subprocess-implementation-notes.md, 2.2 | 50 |
| **Heartbeat monitor** | subprocess-implementation-notes.md, 3 | 40 |
| **Worker crash recovery** | subprocess-implementation-notes.md, 4.1 | 35 |

---

## Testing

**Unit tests**: subprocess-research.md, Section 7.1 + subprocess-implementation-notes.md, Section 7.1

**Integration tests**: subprocess-research.md, Section 7.2 + subprocess-implementation-notes.md, Section 7.2

**Load tests**: subprocess-research.md, Section 7 + subprocess-implementation-notes.md, Section 6.2

---

## Common Issues

**All common issues with fixes**: subprocess-quick-reference.md, Section 7 + subprocess-implementation-notes.md, Section 10

Top issues:
1. Socket "Address already in use" → `unlink(missing_ok=True)`
2. Worker crashes silently → Implement heartbeat timeout
3. Lost messages → Use JSON Lines format
4. Permission relay timeout → 5 minute max with fail-safe (deny)
5. tmux session leaks → Daemon startup cleanup

---

## Related Documents in Codebase

These research docs complement existing codebase:

- **DESIGN.md** — High-level vision, profile system, enhancement flow
- **daemon-architecture.md** — Daemon design (this research expands on it)
- **daemon-decision-guide.md** — When to implement daemon (this research validates it)
- **daemon-implementation-guide.md** — Code samples (some code from this research)
- **specs/04-agent-lifecycle.md** — Agent state machine
- **specs/07-channels.md** — Telegram MCP channel

---

## Recommendation

### Start with MVP (Weeks 1-2)
- Simple, validates core concept
- ~200 lines Python
- Direct spawn per task
- Easy to debug

See: subprocess-quick-reference.md, Section 2

### Graduate to Tier 1 (Week 3)
- Add queue to prevent task loss
- Add IPC for distributed communication
- ~400 lines Python total

See: subprocess-quick-reference.md, Section 3

### Upgrade to Tier 2 (Week 4)
- Worker pool for 2-5 concurrent tasks
- Auto-respawn on crash
- ~600 lines Python total

See: subprocess-quick-reference.md, Section 4

### Polish to Tier 3 (Weeks 5-6, if needed)
- Full async, production-ready
- ~1000 lines Python total
- Only if scaling required

See: subprocess-research.md, Section 6 (Approach: Tier 3)

---

## Success Criteria

**MVP validation**:
- Can spawn Claude Code via subprocess
- Can pipe task via stdin, capture output
- Can detect when process finishes
- Telegram integration works

**Phase 1 validation**:
- Daemon starts cleanly
- SQLite queue works
- IPC socket communication works
- Tasks queue and execute correctly

**Phase 1.5 validation**:
- Multiple workers run concurrently
- Dead workers auto-respawn
- Handle 2-5 concurrent tasks

**Phase 2 validation**:
- Production metrics met
- Graceful shutdown works
- Comprehensive test coverage

---

## Next Steps

1. **Read** subprocess-quick-reference.md end-to-end (15 min)
2. **Review** subprocess-research.md Section 6 for approach decision (20 min)
3. **Plan** MVP implementation (30 min)
4. **Implement** MVP (Weeks 1-2)
5. **Reference** subprocess-implementation-notes.md as needed

---

## Document Statistics

| Document | Size | Sections | Code Examples |
|----------|------|----------|----------------|
| subprocess-research.md | 42 KB | 10 | 15+ |
| subprocess-quick-reference.md | 14 KB | 10 | 5+ |
| subprocess-implementation-notes.md | 23 KB | 10 | 25+ |
| **Total** | **79 KB** | **30** | **45+** |

---

## Questions?

Refer to the specific document based on your question type:

- **Architecture**: subprocess-research.md
- **Quick answers**: subprocess-quick-reference.md
- **Implementation details**: subprocess-implementation-notes.md
- **Existing codebase**: DESIGN.md, daemon-*.md, specs/

---

**End of Index**

*Last updated: 2026-03-26*
*Research status: Complete*
*Ready for implementation planning*
