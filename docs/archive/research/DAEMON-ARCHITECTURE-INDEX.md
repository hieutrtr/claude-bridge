# Claude Bridge Daemon Architecture — Complete Documentation Index

**Published**: 2026-03-26
**Status**: Design proposal for Phase 1.5+ implementation
**Scope**: Persistent background daemon orchestration for multi-agent coordination

---

## Document Overview

This is a **complete architectural proposal** for replacing the ad-hoc task spawning model (current MVP) with a **persistent daemon-based orchestration layer** that coordinates multiple Claude Code sessions.

### Three-Document Structure

| Document | Purpose | Audience | Length |
|----------|---------|----------|--------|
| **daemon-architecture.md** | Vision, design, trade-offs | Architects, tech leads | 1,366 lines |
| **daemon-implementation-guide.md** | Code patterns, IPC protocols, testing | Engineers, reviewers | 966 lines |
| **daemon-decision-guide.md** | When to build, phasing, go/no-go | PMs, teams, decision-makers | 481 lines |

---

## Quick Navigation

### For Architects/Tech Leads
Start here: **daemon-architecture.md**
- Understand the vision (§1 Executive Summary)
- See high-level diagrams (§1 Architecture Diagrams)
- Answer the 5 core questions (§2 Core Questions & Answers):
  - Q1: How does the daemon maintain connections to multiple Claude Code processes?
  - Q2: Can each Claude Code session connect back to daemon as a tool/client?
  - Q3: What's the minimal viable implementation?
  - Q4: How do you handle session failure/recovery?
  - Q5: What are the pros/cons vs other approaches?

**Key insight**: The daemon is an **orchestration layer**, not a replacement for Claude Code. It coordinates process spawning, task routing, permission relay, and signal accumulation.

---

### For Engineers (Writing Code)
Start here: **daemon-implementation-guide.md**
- Understand IPC protocol (§1, §2)
- Get socket code samples (Unix sockets, async I/O)
- Copy task queue SQLite schema (§3)
- Use worker spawner patterns (§4)
- Implement permission relay (§5)
- Apply testing strategies (§6)

**Ready-to-use patterns:**
- `IPCServer` class (asyncio-based Unix socket server)
- `WorkerIPCClient` class (inside Claude Code)
- `TaskQueueDB` class (SQLite wrapper)
- `WorkerSpawner` class (tmux integration)
- `PermissionRouter` class (Telegram relay)

---

### For Decision-Makers (PMs, Teams)
Start here: **daemon-decision-guide.md**
- Quick decision tree (§1): Should we build daemon?
- Phased roadmap (§2): MVP → Daemon Tier 1 → Tier 2 → Tier 3
- Risk assessment (§4): What can go wrong at each phase?
- Performance expectations (§5): Throughput, latency, memory
- Go/No-Go checklists (§7): When to proceed to next phase
- FAQ (§9): Common questions answered

**Bottom line**: Implement daemon incrementally (Tier 1 in Week 3, Tier 2 in Week 4) only after MVP is validated. Don't over-engineer early.

---

## Key Concepts

### The Daemon
A **persistent background process** (like `redis-server`) that:
- Runs continuously (survives task failures)
- Maintains a task queue (SQLite)
- Manages worker pool (Claude Code processes in tmux)
- Routes tasks to available workers via IPC
- Relays permission requests to Telegram
- Accumulates signals for profile enhancement

### IPC (Inter-Process Communication)
Uses **Unix sockets** for daemon ↔ worker communication:
- JSON Lines protocol (one JSON message per line)
- Message types: task, progress, permission_request, task_complete, heartbeat
- Async I/O (daemon talks to many workers simultaneously)
- No network exposure (local-only, secure)

### Three Implementation Tiers

**Tier 1 (MVP)**: Single task at a time, synchronous dispatch
- Simple, easy to validate
- No concurrency

**Tier 2 (Phase 1.5)**: Worker pool, async dispatch, healthchecks
- Multiple concurrent tasks
- Auto-recovery on crash
- Still blocking permission relay

**Tier 3 (Phase 2)**: Full async I/O, non-blocking permission relay, session recovery
- Production-ready
- Handles edge cases
- High performance

### Backwards Compatibility
Daemon is **additive**, not destructive:
- MVP spawn still works (redirects through daemon wrapper)
- No rewrite of existing code
- Gradual migration path

---

## Answer Summary: The 5 Core Questions

### Q1: How does daemon maintain connections to multiple Claude Code processes?

**Answer**: Multi-channel IPC using async event loops:
```
Daemon
  ├─ Async Event Loop (select/epoll/kqueue)
  ├─ Unix socket: /tmp/bridge/worker-1.sock
  ├─ Unix socket: /tmp/bridge/worker-2.sock
  └─ Unix socket: /tmp/bridge/worker-n.sock

Each socket:
  - Worker connects on startup
  - Daemon listens asynchronously
  - Non-blocking I/O (daemon doesn't wait for one worker)
  - Heartbeat every 10 seconds (detect dead workers)
```

See **daemon-architecture.md §2.1** for full implementation.

---

### Q2: Can each Claude Code session connect back to daemon?

**Answer**: Yes, via **hooks + environment variables**:
```
Claude Code session gets env vars:
  - BRIDGE_WORKER_ID = worker-abc123
  - BRIDGE_CALLBACK_SOCKET = /tmp/bridge/daemon.sock
  - BRIDGE_DAEMON_PID = 1234

Hook fires (e.g., PreToolUse[Bash]):
  - Detects blocked pattern (e.g., "git push --force")
  - Opens connection to BRIDGE_CALLBACK_SOCKET
  - Sends PermissionRequest (JSON)
  - Waits for response (blocking)
  - Continues/halts based on approval

Claude Code **cannot** directly call daemon (no RPC), but can:
  - Send messages via socket
  - Wait for responses (with timeout)
  - Doesn't need to know about daemon internals
```

See **daemon-architecture.md §2.2** for code samples.

---

### Q3: What's minimal viable implementation?

**Answer**: Three-tier progression:

**Tier 1 (Week 1)**: Direct spawn through daemon wrapper
```python
class Daemon:
    def start(self):
        while True:
            task = db.pop_pending_task()
            if task:
                self.spawn_worker(task)
                self.wait_for_completion()
```
- One task at a time
- Simple, testable
- No concurrency

**Tier 2 (Week 2)**: Worker pool
```python
class Daemon:
    async def start(self):
        for i in range(pool_size):
            self.spawn_idle_worker()

        while True:
            free_worker = self.get_free_worker()
            task = db.pop_pending_task()
            if free_worker and task:
                await self.send_task_to_worker(free_worker, task)
```
- N workers
- Async dispatch
- Multiple concurrent tasks

**Tier 3 (Week 3+)**: Full async, permission relay, recovery
- Async event loop
- Non-blocking permission relay
- Crash recovery

See **daemon-implementation-guide.md §1-5** for code.

---

### Q4: How do you handle session failure/recovery?

**Answer**: Multi-layered fault tolerance:

**Detection**:
- Heartbeat monitoring (worker silent > 30s = dead)
- Process monitoring (check if PID exists)
- Socket errors (worker disconnects)

**Recovery**:
- Worker crash → respawn immediately (max 3 retries)
- Task was running → mark as failed, replay
- Tmux session survives (can reconnect to it)
- Daemon crash → restore from session registry YAML

**Task replay logic**:
- Worker crash → auto-replay (always)
- Timeout → replay with longer timeout (once)
- Permission timeout → wait for re-approval
- Agent error → don't replay (was task error, not crash)

See **daemon-architecture.md §2.4** for detailed recovery strategies.

---

### Q5: Pros/cons vs other approaches?

**Comparison matrix** in **daemon-architecture.md §7**:

| Approach | MVP Simplicity | Production-Ready | Concurrency | Dependencies |
|----------|---|---|---|---|
| Daemon (Proposed) | 3/5 | 5/5 | 5/5 | 3/5 |
| Direct Spawn (MVP) | 5/5 | 2/5 | 1/5 | 5/5 |
| Redis/Celery | 2/5 | 5/5 | 5/5 | 2/5 |
| Multiprocessing | 4/5 | 3/5 | 4/5 | 5/5 |

**Recommendation**: Start with Direct Spawn (MVP), migrate to Daemon Tier 1 (Week 3).

---

## Phased Implementation Timeline

### Phase: MVP (Weeks 1-2)
**Goal**: Validate core agent lifecycle
**Approach**: Direct spawn, no daemon
**Deliverables**:
- Profile.yaml load/save working
- CLAUDE.md generation multi-layer
- Single Claude Code spawn working
- Signal accumulation working
- Enhancement proposal logic working

**Success**: Agent completes tasks end-to-end

---

### Phase 1: Daemon Tier 1 (Week 3)
**Goal**: Add task queueing
**Approach**: Daemon, but serial (one task at a time)
**Deliverables**:
- SQLite task queue
- Daemon main loop
- IPC Unix socket (basic)
- Task → worker dispatch

**Success**: 10 tasks queued and executed without loss

---

### Phase 1.5: Daemon Tier 2 (Week 4)
**Goal**: Enable concurrency
**Approach**: Worker pool, async dispatch
**Deliverables**:
- N idle workers (configurable, default 5)
- Async task dispatcher
- Worker heartbeat monitoring
- Auto-respawn on crash

**Success**: 5 tasks execute in parallel

---

### Phase 2: Daemon Tier 3 (Weeks 5+)
**Goal**: Production-ready
**Approach**: Full async I/O, permission relay, recovery
**Deliverables**:
- Event loop (kqueue/epoll)
- Async permission relay
- Session recovery (daemon restart)
- Comprehensive error handling

**Success**: Pass production validation (load test, edge cases)

---

## Data Models

### Task Queue (SQLite)
```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    agent_name TEXT,
    payload TEXT,
    status TEXT,  -- pending|assigned|running|completed|failed
    assigned_worker_id TEXT,
    retry_count INTEGER,
    ...
);
```

### Session Registry (YAML)
```yaml
workers:
  worker-abc123:
    agent_name: coder-my-app
    pid: 1234
    tmux_session: bridge-abc123
    state: running
    last_heartbeat: 2026-03-26T10:15:00Z
```

### IPC Protocol (JSON Lines)
```json
{"type": "task", "id": "task-001", "payload": "..."}
{"type": "task_ack", "task_id": "task-001", "status": "started"}
{"type": "permission_request", "id": "perm-xyz", "action": "bash", "pattern": "git push"}
{"type": "permission_response", "id": "perm-xyz", "approved": true}
{"type": "task_complete", "task_id": "task-001", "status": "success"}
```

See **daemon-implementation-guide.md §1-3** for complete schemas.

---

## Success Criteria

### MVP Phase
- [ ] Single task execution works end-to-end
- [ ] Output returned to Telegram within 30 seconds
- [ ] Signals logged correctly
- [ ] No crashes for 10 consecutive tasks

### Daemon Phase 1
- [ ] Task queue persists across daemon restart
- [ ] 10 tasks queued and executed sequentially
- [ ] IPC sockets clean up on shutdown
- [ ] Error handling prevents daemon crash

### Daemon Phase 2
- [ ] 5 tasks execute in parallel
- [ ] Worker auto-respawns on crash
- [ ] Permission relay < 5 seconds
- [ ] Memory stable at 2.5 GB

### Daemon Phase 3
- [ ] 50+ tasks queued without latency degradation
- [ ] Async permission relay < 1 second
- [ ] Daemon restart recovers in-flight tasks
- [ ] CPU < 50% at 10 tasks/min

See **daemon-decision-guide.md §8** for detailed checklist.

---

## Next Steps

### For Architects
1. Read **daemon-architecture.md** (entire document)
2. Review the high-level diagrams (§1)
3. Evaluate the 5 core questions (§2)
4. Assess trade-offs (§7)
5. Discuss with team

### For Engineers
1. Read **daemon-implementation-guide.md** (§1-3)
2. Review IPC protocol specification
3. Copy code patterns (IPCServer, WorkerSpawner, TaskQueueDB)
4. Set up SQLite schema
5. Start with Tier 1 implementation

### For Teams/PMs
1. Read **daemon-decision-guide.md** (§1, §2, §7)
2. Follow the decision tree (§1)
3. Review the phased roadmap (§2)
4. Check success criteria (§8)
5. Plan sprints accordingly

---

## References & Related Docs

### Existing Claude Bridge Documents
- **DESIGN.md**: Current system design (MVP, no daemon)
- **SPECS.md**: Technical specifications (profile system, enhancement, etc.)
- **docs/architecture.md**: Current architecture deep-dive
- **docs/profile-system.md**: Profile management details

### New Daemon Documents (This Index)
- **docs/daemon-architecture.md**: Architectural vision & design
- **docs/daemon-implementation-guide.md**: Code patterns & IPC
- **docs/daemon-decision-guide.md**: When/how/if to implement

---

## Key Assumptions

1. **Telegram MCP Channel works**: Claude Code can send/receive via Telegram reliably
2. **Tmux available on target OS**: Darwin (macOS), Linux
3. **Python async (asyncio)**: Suitable for I/O-bound daemon
4. **Unix sockets available**: macOS, Linux (not Windows without WSL)
5. **Single machine deployment**: Daemon + workers on same machine (for MVP)

---

## Known Limitations

### Tier 1-2
- ❌ No distributed deployment (all on one machine)
- ❌ Permission relay is blocking (worker waits)
- ❌ SQLite single-writer (contention under very high load)

### Workarounds
- Increase pool size for concurrency (not distributed)
- Accept blocking permission (typically < 5 seconds)
- Use WAL mode (SQLite write-ahead logging)

### Future (Phase 3+)
- TCP sockets for multi-machine deployment
- Message broker (Redis, RabbitMQ) for distributed queue
- Async permission relay (non-blocking worker)

---

## Questions?

See **daemon-decision-guide.md §9 (FAQ)** for common questions.

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-03-26 | 1.0 | Initial design proposal (3 documents) |

---

**End of Index**

For deep dives, refer to the three main documents above.
