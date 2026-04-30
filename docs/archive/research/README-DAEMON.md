# Daemon Architecture — Quick Start Guide

**Start here** if you're new to the daemon proposal.

---

## What is the Daemon?

A **persistent background process** that orchestrates multiple Claude Code agents:

```
Telegram/Discord/Slack
    ↓
[Daemon] ← persistent, always running
    ├─ Task queue (SQLite)
    ├─ Worker pool (Claude Code processes)
    ├─ Permission relay (→ Telegram)
    ├─ Signal accumulator (enhancement signals)
    └─ IPC router (Unix sockets)
```

**Without daemon**: Task → spawn Claude Code → done → cleanup
**With daemon**: Task → queue → idle worker → execute → done (worker stays alive for next task)

---

## Why Do We Need It?

### Current MVP Problems
- ❌ Single task at a time (no parallelism)
- ❌ Tmux sessions leak on crash
- ❌ Permission relay blocks session (bad for UX)
- ❌ No graceful recovery from failures

### Daemon Solutions
- ✅ Multiple concurrent tasks (worker pool)
- ✅ Sessions persist in tmux (survive daemon crash)
- ✅ Async permission relay (non-blocking)
- ✅ Auto-respawn on failure (self-healing)

---

## Four-Step Timeline

```
Weeks 1-2: MVP ─────────→ Direct spawn, validate concept

Week 3:  Daemon Tier 1 ─→ Task queue (serial execution)
         [start here]

Week 4:  Daemon Tier 2 ─→ Worker pool (parallel execution)

Week 5+: Daemon Tier 3 ─→ Async I/O (production-ready)
```

**Each tier is independently useful.** Don't skip steps.

---

## Key Insight: Three Separate Things

1. **Daemon** (orchestration layer)
   - Manages task queue
   - Spawns workers
   - Monitors health
   - Routes messages

2. **Claude Code** (execution engine)
   - Reads task from socket
   - Executes agent logic
   - Sends back results
   - Same code as before

3. **Telegram MCP Channel** (I/O layer)
   - Receives messages
   - Sends to daemon/workers
   - Handles permission requests
   - No daemon-specific code

**The daemon is NOT a replacement for Claude Code. It's a coordinator.**

---

## Document Map

### For Quick Overview
**Start**: `DAEMON-ARCHITECTURE-INDEX.md` (this section's parent)
- 5-minute read
- High-level concepts
- Navigation to other docs

### For Deep Dive (Architects)
**Read**: `daemon-architecture.md`
- Complete vision (§1)
- 5 core questions + answers (§2)
- Implementation outline (§3)
- Trade-offs vs alternatives (§7)
- ~1,400 lines, comprehensive

### For Implementation (Engineers)
**Read**: `daemon-implementation-guide.md`
- IPC protocol spec (§1)
- Code samples (§2-5):
  - IPCServer (asyncio Unix socket)
  - TaskQueueDB (SQLite)
  - WorkerSpawner (tmux)
  - PermissionRouter (Telegram relay)
- Testing strategies (§6)
- ~1,000 lines, practical

### For Decision-Making (PMs/Teams)
**Read**: `daemon-decision-guide.md`
- Decision tree (§1)
- Phased roadmap (§2)
- Risk assessment (§4)
- Go/No-Go checklists (§7)
- FAQ (§9)
- ~500 lines, actionable

---

## Quick Decision: Should You Build It?

### Do you need...

**Multiple concurrent tasks?**
- MVP (direct spawn): ❌ Can't do it
- Daemon Tier 1: ❌ Still serial
- Daemon Tier 2: ✅ Yes, up to 5 concurrent
- Daemon Tier 3: ✅ Yes, 50+ concurrent

**Task queueing (burst handling)?**
- MVP: ❌ No queue, tasks fail if spawn timing bad
- Daemon Tier 1+: ✅ Yes, SQLite queue

**Fast permission relay (<2 sec)?**
- MVP: ❌ Blocking (5-10 seconds typical)
- Daemon Tier 1-2: ❌ Still blocking
- Daemon Tier 3: ✅ Async (< 1 second)

**Recovery from worker crash?**
- MVP: ❌ No auto-respawn
- Daemon Tier 1: ⚠️ Manual intervention
- Daemon Tier 2+: ✅ Auto-respawn (max 3 retries)

**Production-grade resilience?**
- MVP: ❌ Not designed for it
- Daemon Tier 1-2: ⚠️ Getting there
- Daemon Tier 3: ✅ Production-ready

---

## Core Architecture (Visual)

### Flow: Task Execution

```
User (Telegram)
   ↓ "Fix login bug"

Daemon TaskRouter
   ├─ Parse message
   ├─ INSERT task_queue (status='pending')
   └─ Notify dispatcher

Daemon SessionDispatcher
   ├─ Pop from queue
   ├─ Find free worker (or spawn new)
   ├─ Send via IPC socket:
   │  {type: 'task', id: 'task-001', payload: '...'}
   └─ Track assignment

Worker (Claude Code in tmux)
   ├─ Read from socket
   ├─ Load profile.yaml + CLAUDE.md
   ├─ Execute task
   ├─ Send progress updates
   ├─ On permission needed:
   │  └─ Send PermissionRequest to daemon
   └─ Send task_complete when done

Daemon PermissionRouter
   ├─ Receive permission request
   ├─ INSERT permissions (status='pending')
   ├─ Send to Telegram with [✅ Approve] [❌ Deny]
   ├─ Wait for user response
   ├─ Send approval/denial back to worker
   └─ Worker continues/halts

Daemon SignalCollector
   ├─ Receive task_complete
   ├─ Log signals to enhancement-accumulator.yaml
   ├─ UPDATE task_queue (status='completed')
   ├─ Send summary to Telegram
   └─ Check if enhancement threshold hit
```

### IPC Protocol (JSON Lines)

```
# Daemon → Worker: Task assignment
{"type": "task", "id": "task-001", "payload": "...", "timeout": 300}

# Worker → Daemon: Ack
{"type": "task_ack", "task_id": "task-001", "status": "started"}

# Worker → Daemon: Permission request (blocks worker)
{"type": "permission_request", "id": "perm-xyz", "action": "bash", "pattern": "git push"}

# Daemon → Worker: Permission response (unblocks worker)
{"type": "permission_response", "id": "perm-xyz", "approved": true}

# Worker → Daemon: Task complete
{"type": "task_complete", "task_id": "task-001", "status": "success", "signals": [...]}
```

---

## Key Data Models

### Task Queue (SQLite)
```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    agent_name TEXT,
    payload TEXT,
    status TEXT,  -- pending|assigned|running|completed|failed
    assigned_worker_id TEXT,
    created_at TIMESTAMP,
    retry_count INTEGER
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

---

## Implementation Roadmap

### Week 1-2: MVP
- [ ] Profile.yaml load/save
- [ ] CLAUDE.md generation
- [ ] Single Claude Code spawn
- [ ] Signal collection
- [ ] Basic enhancement logic

### Week 3: Daemon Tier 1
- [ ] SQLite task queue
- [ ] Daemon main loop
- [ ] Unix socket IPC
- [ ] Task → worker dispatch (serial)

### Week 4: Daemon Tier 2
- [ ] Worker pool (N idle workers)
- [ ] Async dispatcher
- [ ] Heartbeat monitoring
- [ ] Auto-respawn on crash

### Week 5+: Daemon Tier 3
- [ ] Event loop (kqueue/epoll)
- [ ] Async permission relay
- [ ] Session recovery (daemon restart)
- [ ] Comprehensive error handling

---

## Success Criteria

### MVP Phase
- Single task execution end-to-end
- Output in Telegram within 30 seconds
- Signals logged correctly

### Daemon Phase 1
- 10 tasks queued without loss
- Task queue persists across daemon restart

### Daemon Phase 2
- 5 tasks execute in parallel
- Worker auto-respawns on crash
- Permission relay < 5 seconds

### Daemon Phase 3
- 50+ tasks queued
- Daemon restart recovers in-flight tasks
- Async permission relay < 1 second

---

## FAQ

**Q: Is this required for MVP?**
A: No. MVP works with direct spawn. Daemon is Phase 1.5+ (after MVP validation).

**Q: Can we use daemon from day 1?**
A: Possible but not recommended. MVP is simpler, validates core concept first. Then add daemon.

**Q: What if we don't implement daemon?**
A: MVP still works fine. You just can't handle concurrent tasks or have advanced recovery.

**Q: How does this integrate with existing code?**
A: Daemon replaces spawn logic. Everything else (profile, CLAUDE.md, hooks, enhancement) stays the same.

**Q: What if the daemon crashes?**
A: Tier 3 includes recovery. Earlier tiers: manual restart acceptable (or keep MVP model as fallback).

---

## Next Steps

1. **Understand the concept**
   - Read DAEMON-ARCHITECTURE-INDEX.md (5 min)
   - Skim daemon-architecture.md (20 min)

2. **For architects/tech leads**
   - Read daemon-architecture.md §2 (5 core questions)
   - Review §7 (trade-offs)
   - Discuss with team

3. **For engineers**
   - Read daemon-implementation-guide.md §1-3
   - Copy code patterns
   - Build Tier 1 prototype (Week 3)

4. **For PMs/teams**
   - Read daemon-decision-guide.md §1-2
   - Plan MVP + daemon phases
   - Add to sprint planning

---

## Related Documentation

- **DESIGN.md** — Current system design (MVP, no daemon)
- **SPECS.md** — Technical specifications (profile, enhancement, etc.)
- **docs/architecture.md** — Current architecture deep-dive

---

## TL;DR

- **What**: Persistent daemon orchestrates Claude Code agents
- **Why**: Enable concurrency, fault tolerance, better UX
- **When**: Start after MVP validation (Week 3+)
- **How**: Three tiers (serial → concurrent → production)
- **Cost**: Moderate complexity, high payoff

**Start**: Read DAEMON-ARCHITECTURE-INDEX.md, then follow links above.
