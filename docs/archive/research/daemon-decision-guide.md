# Claude Bridge Daemon — Decision & Recommendation Guide

**Quick reference** for choosing when, how, and if to implement daemon architecture.

---

## 1. Quick Decision Tree

### Should you implement the daemon?

```
Q: Are you in MVP phase (validating core concept)?
├─ YES: Skip daemon for now, use direct spawn (DESIGN.md approach)
│       → Simpler code, faster validation
│       → Can migrate to daemon later
└─ NO: Proceed to next question

Q: Do you need concurrent task execution (multiple tasks at once)?
├─ YES: Daemon is strongly recommended
│       → Single task at a time (direct spawn) will bottleneck
└─ NO: Proceed to next question

Q: Is permission relay latency critical for UX?
├─ YES: Daemon + async permission handling improves responsiveness
└─ NO: Can defer daemon to later phase

Q: Do you need session persistence across crashes?
├─ YES: Daemon + tmux solves this elegantly
└─ NO: Can work around with direct spawn

RECOMMENDATION:
├─ If answers: MVP (YES), concurrency (NO), relay (NO), persistence (NO)
│  → Stay with MVP, revisit in Phase 2
│
├─ If answers: MVP (NO), concurrency (YES), relay (ANY), persistence (ANY)
│  → Implement daemon (Phase 1.5+)
│
└─ If answers: MVP (NO), concurrency (YES), relay (YES), persistence (YES)
   → Implement daemon + async (Phase 2)
```

---

## 2. Phased Implementation Roadmap

### Timeline Estimates (full-time)

```
┌─ MVP (Weeks 1-2): Direct spawn ─────────────────────────┐
│                                                          │
│  • Load profile.yaml                                    │
│  • Generate CLAUDE.md                                   │
│  • Spawn single Claude Code process                     │
│  • Route task via stdin                                 │
│  • Collect output                                       │
│  • Log signals to accumulator                           │
│                                                          │
│  VALIDATION: Does core agent lifecycle work?            │
└──────────────────────────────────────────────────────────┘
                         ↓
┌─ Phase 1 (Week 3): Daemon Tier 1 ──────────────────────┐
│                                                          │
│  • SQLite task queue                                    │
│  • Daemon skeleton (main loop)                          │
│  • Spawn one worker per task                            │
│  • Basic IPC (Unix socket)                              │
│  • Task → Worker dispatch                               │
│                                                          │
│  VALIDATION: Can daemon queue & execute tasks?          │
└──────────────────────────────────────────────────────────┘
                         ↓
┌─ Phase 1.5 (Week 4): Daemon Tier 2 ─────────────────────┐
│                                                          │
│  • Worker pool (spawn N idle workers)                   │
│  • Async dispatcher (non-blocking assignment)           │
│  • Worker health monitoring (heartbeat)                 │
│  • Auto-respawn on crash                                │
│                                                          │
│  VALIDATION: Can daemon handle multiple concurrent      │
│              tasks? Do workers recover on crash?        │
└──────────────────────────────────────────────────────────┘
                         ↓
┌─ Phase 2 (Weeks 5-6): Daemon Tier 3 ────────────────────┐
│                                                          │
│  • Async I/O (kqueue/epoll)                             │
│  • Permission relay (async, non-blocking)               │
│  • Signal accumulation (in-flight)                      │
│  • Session recovery (daemon restart)                    │
│                                                          │
│  VALIDATION: Production readiness. Can handle edge      │
│              cases & high load?                         │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Architecture Decision Matrix

### When to use each approach

| Scenario | MVP Spawn | Daemon Tier 1 | Daemon Tier 2 | Daemon Tier 3 |
|----------|-----------|---------------|---------------|---------------|
| **Single user, validate concept** | ✅ | ❌ | ❌ | ❌ |
| **Multiple tasks in sequence** | ✅ | ✅ | ✅ | ✅ |
| **2-3 concurrent tasks** | ❌ | ✅ | ✅ | ✅ |
| **5+ concurrent tasks** | ❌ | ⚠️ | ✅ | ✅ |
| **Permission relay < 5 sec** | ❌ | ❌ | ✅ | ✅ |
| **Survive daemon crash** | ❌ | ⚠️ | ⚠️ | ✅ |
| **Simple codebase** | ✅ | ✅ | ⚠️ | ❌ |
| **Production-ready** | ❌ | ❌ | ⚠️ | ✅ |

**Legend:**
- ✅ Recommended for this use case
- ⚠️ Possible but with trade-offs
- ❌ Not recommended

---

## 4. Risk Assessment

### MVP Spawn Approach
**Risks:**
- ❌ Single-threaded (can't handle rapid task bursts)
- ❌ Tmux session leaks if process crashes
- ❌ No queue (tasks fail if spawn timing bad)
- ❌ No session recovery on daemon exit

**Mitigations:**
- Small user base (single developer)
- Document manual cleanup for tmux sessions
- Accept first version is "best effort"

**Go/No-Go:** ✅ Proceed for MVP validation

---

### Daemon Tier 1
**Risks:**
- ⚠️ Still blocking dispatch (one worker at a time)
- ⚠️ IPC sockets might leak if not cleaned
- ⚠️ SQLite contention (one write at a time)

**Mitigations:**
- Add socket cleanup on startup
- Pragmatic DB timeouts
- Monitor /tmp/claude-bridge/ for leaks

**Go/No-Go:** ✅ Proceed once MVP validated (Week 3)

---

### Daemon Tier 2
**Risks:**
- ⚠️ Async code introduces complexity
- ⚠️ Worker pool sizing is non-obvious
- ⚠️ Thundering herd if all workers spawn at once

**Mitigations:**
- Comprehensive unit tests for async paths
- Start with small pool (3-5 workers)
- Gradually increase with monitoring

**Go/No-Go:** ✅ Proceed once Tier 1 stable (Week 4)

---

### Daemon Tier 3
**Risks:**
- ❌ OS-specific code (kqueue vs epoll)
- ❌ Edge cases in async signal handling
- ❌ Hard to debug distributed failures

**Mitigations:**
- Extensive integration tests
- Staging environment validation
- Gradual rollout (10% users first)

**Go/No-Go:** ⚠️ Proceed with caution (Week 5+)

---

## 5. Performance Expectations

### Task Throughput

```
MVP Spawn (direct):
  • 1 task at a time
  • No parallelism
  • Each task: spawn + execute + cleanup
  • Throughput: 1-2 tasks/minute (depending on task length)

Daemon Tier 1:
  • Still 1 task at a time (but queued)
  • Queue hides latency
  • Throughput: 1-2 tasks/minute (same as MVP)
  • ✅ Benefit: No dropped tasks on burst

Daemon Tier 2:
  • N workers (configurable, default 5)
  • Parallel execution
  • Throughput: 5-10 tasks/minute (5x improvement)
  • ✅ Benefit: Can handle concurrent dispatches

Daemon Tier 3:
  • N workers + true async I/O
  • No kernel thread blocking
  • Throughput: 10-50 tasks/minute (depending on task size)
  • ✅ Benefit: Efficient resource usage
```

### Permission Relay Latency

```
MVP Spawn:
  • Blocking: agent waits for Telegram response
  • Latency: 0-5 seconds (typical user response time)
  • ❌ Block: Agent stalls entire session

Daemon Tier 1:
  • Still blocking (same as MVP)
  • Latency: 0-5 seconds
  • ✅ Improvement: Other tasks can proceed in queue

Daemon Tier 2+:
  • Async permission handling
  • Latency: 0-5 seconds (but non-blocking to agent)
  • ✅ Benefit: Agent continues (if possible)
  • ⚠️ Trade-off: More complex error handling
```

### Memory Usage

```
MVP Spawn:
  • Single Claude Code process
  • Memory: ~500 MB (one process)

Daemon Tier 1:
  • Daemon + 1 Claude Code process at a time
  • Memory: ~100 MB (daemon) + 500 MB (worker) = 600 MB total

Daemon Tier 2:
  • Daemon + N idle workers (e.g., 5)
  • Memory: ~100 MB (daemon) + (500 MB × 5) (workers) = 2.5 GB
  • ⚠️ Trade-off: Higher baseline, faster spawn

Daemon Tier 3:
  • Same as Tier 2
  • Memory: ~2.5 GB (configurable pool size)
```

---

## 6. Migration Path

### From MVP → Daemon (Backwards Compatibility)

**Option A: Wrapper Layer (Recommended)**
```
Phase 1 (Week 3):
  ├─ Daemon starts running
  ├─ `claude-bridge task spawn` still works (routes through daemon)
  ├─ Old direct spawn deprecated but not removed
  └─ Users see no change

Phase 2 (Week 5):
  ├─ Deprecation warning in CLI
  ├─ Documentation updated
  ├─ Direct spawn removed from code
  └─ All tasks use daemon

Risk: LOW (wrapper ensures compatibility)
```

**Option B: Flag-Based Migration**
```
Phase 1:
  ├─ New flag: `--use-daemon` (opt-in)
  ├─ Default: direct spawn
  └─ Users can test daemon voluntarily

Phase 2:
  ├─ Default: daemon
  ├─ Flag `--no-daemon` for fallback
  └─ Most users transparent

Risk: MEDIUM (flag explosion)
```

**Recommendation:** Use **Option A** (wrapper layer).

```python
# claude_bridge/task_runner.py
class TaskRunner:
    """Abstraction over spawn method."""

    def __init__(self, use_daemon: bool = True):
        self.use_daemon = use_daemon

        if use_daemon:
            self.backend = DaemonTaskRunner()
        else:
            self.backend = DirectSpawnTaskRunner()  # MVP

    async def run(self, task: Task) -> TaskResult:
        """Route through appropriate backend."""
        return await self.backend.run(task)
```

---

## 7. Go/No-Go Checklist

### Before starting MVP

- [ ] Project structure created (daemon/, channels/, models/)
- [ ] DESIGN.md reviewed with team
- [ ] Telegram MCP channel understanding clear
- [ ] Claude Code process spawn tested manually
- [ ] SQLite schema designed
- [ ] IPC protocol designed (JSON Lines)

### Before starting Daemon Tier 1

- [ ] MVP working end-to-end (agent completes task)
- [ ] Signal accumulation working
- [ ] Enhancement proposal logic validated
- [ ] Telegram relay tested

### Before starting Daemon Tier 2

- [ ] Daemon Tier 1 handles 10+ queued tasks
- [ ] IPC reliable (no socket leaks)
- [ ] Worker spawn/kill tested
- [ ] Heartbeat monitoring implemented

### Before starting Daemon Tier 3

- [ ] Daemon Tier 2 handles 5 concurrent tasks
- [ ] Performance profiling done (CPU, memory, latency)
- [ ] Crash scenarios tested (daemon crash, worker crash)
- [ ] Integration tests passing

---

## 8. Success Metrics

### MVP Phase
- Can spawn agent and execute single task
- Output returned to Telegram within 30 seconds
- Signals logged to accumulator correctly
- No crashes for 10 consecutive tasks

### Daemon Phase 1
- Task queue persists across daemon restart
- 10 tasks can be queued and executed sequentially
- IPC sockets cleaned up on shutdown
- Error handling prevents daemon crash on task failure

### Daemon Phase 2
- 5 tasks execute in parallel (within 2x time of sequential)
- Worker auto-respawns on crash (max 3 retries)
- Permission relay completes within 5 seconds
- Memory stable at 2.5 GB with 5-worker pool

### Daemon Phase 3
- 50+ tasks queued without latency degradation
- Async permission relay < 1 second (non-blocking)
- Daemon restart recovers all in-flight tasks
- CPU usage < 50% during moderate load (10 tasks/min)

---

## 9. FAQ

**Q: Should we implement daemon from day 1?**
A: No. Start with MVP (direct spawn), validate core concept, then introduce daemon incrementally. This reduces risk and complexity.

**Q: What if users want to run multiple agents in parallel?**
A: Daemon Tier 2 solves this. Tier 1 would still be sequential.

**Q: How does daemon handle Claude Code updates/crashes?**
A: Tmux persists the session. If Claude Code updates, next spawn uses new version. If it crashes, heartbeat detects it → auto-respawn.

**Q: Can daemon run on a separate machine?**
A: Not in current design (uses Unix sockets). Future phase could use network sockets (TCP) for distributed deployment.

**Q: What if the daemon itself crashes?**
A: Tier 3 includes recovery logic. In-flight tasks are re-queued, sessions recover from tmux snapshots. Less critical in MVP (manual restart acceptable).

**Q: How do we avoid spawning too many tmux sessions?**
A: Pool sizing. Tier 2 maintains N idle workers. Tier 1 spawns per-task (acceptable for MVP).

**Q: Can permission relay be fully async?**
A: Only in Tier 3. Tier 1-2 still block worker. Trade-off: blocking is simpler, async is more scalable.

---

## 10. Communication & Sign-Off

### Recommended Discussion Points

**With team:**
- "MVP is direct spawn. Daemon is Phase 1.5+ when we need concurrency."
- "This document is the migration plan. No surprises."
- "Estimated timeline: MVP (2 weeks) → Daemon (4 weeks total)."

**With stakeholders:**
- "MVP validates the concept with single-task execution."
- "Daemon (Phase 1.5+) enables multi-task workflows."
- "No architectural debt. Daemon is an add-on, not a rewrite."

**In documentation:**
- Link daemon-architecture.md in README
- Make clear MVP doesn't include daemon
- Document when to upgrade to daemon

---

## 11. Appendix: Variant Architectures

### What if we used gRPC instead of Unix sockets?

**Pros:**
- Type-safe serialization (protobuf)
- Language-agnostic (could spawn workers in other languages)
- Built-in streaming

**Cons:**
- Extra dependency (gRPC, protobuf)
- Overkill for single-machine communication
- Requires service discovery (if multi-machine)

**Verdict:** Unix sockets simpler for MVP. gRPC if multi-machine later.

---

### What if we used message brokers (RabbitMQ, Kafka)?

**Pros:**
- Distributed queuing
- Persistence out-of-box
- Pub/sub patterns

**Cons:**
- Heavy infrastructure (RabbitMQ server)
- Overkill for MVP (add 20+ MB deps)
- Harder to debug (another service to run)

**Verdict:** SQLite simpler for MVP. Message broker if scaling to 100+ agents.

---

### What if we used Actor Model (Erlang/Akka)?

**Pros:**
- Designed for concurrent systems
- Hot-reload capability
- Supervisors handle recovery

**Cons:**
- Language lock-in (Erlang/Scala)
- Learning curve steep
- Overkill for Claude Code (already manages its own lifecycle)

**Verdict:** Python asyncio sufficient. Actors if we need hot-reload (Phase 3+).

---

## Conclusion

This decision guide provides **clear criteria** for when to implement daemon, which tier, and how to transition.

**TL;DR:**
- **MVP**: Direct spawn, no daemon
- **Week 3**: Daemon Tier 1 (queue only)
- **Week 4**: Daemon Tier 2 (concurrency)
- **Week 5+**: Daemon Tier 3 (production-ready)

Start simple. Add complexity only when validated.
