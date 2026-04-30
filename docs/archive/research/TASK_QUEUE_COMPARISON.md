# Task Queue: Decision Matrix & Recommendations

Quick reference for choosing between SQLite polling, daemon IPC, and other approaches.

---

## Executive Decision Matrix

### For Claude Bridge MVP (Recommended)

| Criterion | Rating | Winner |
|-----------|--------|--------|
| **Implementation speed** | 🔴 Critical | SQLite Polling |
| **External dependencies** | 🔴 Critical | SQLite Polling (none) |
| **Concurrent safety** | 🔴 Critical | SQLite Polling (ACID) |
| **Responsiveness (5-10s OK?)** | 🟡 Nice-to-have | SQLite Polling |
| **Debugging ease** | 🟡 Nice-to-have | SQLite Polling (SQL queries) |
| **Crash recovery** | 🟡 Nice-to-have | SQLite Polling (WAL) |
| **Real-time (sub-second)** | 🟢 Not needed | Daemon (if needed later) |

**Verdict: ✅ SQLite Polling is the clear winner for MVP.**

---

## Three Approaches Compared

### 1. SQLite Polling (Recommended for MVP)

```
Telegram Channel                   Claude Code Session A
    ↓                              ↙
    → [SQLite Database]            Claude Code Session B ← Polls every 5s
                                   ↙
                              Claude Code Session C
    ↑
    ← [Cron Watchers] (recovery, reporting)
```

**Architecture:**
- Single SQLite file at `~/.claude-bridge/tasks.db`
- Each session runs TaskPoller in background thread
- Cron jobs every 1-5 minutes for maintenance
- Telegram writes tasks, sessions claim them

**Locking Mechanism:**
```sql
BEGIN IMMEDIATE;  -- Exclusive lock
UPDATE tasks SET status='running' WHERE id=? AND status='pending';
-- Only one session succeeds
COMMIT;
```

**Pros:**
- ✅ No external dependencies (SQLite is stdlib)
- ✅ Zero setup/configuration
- ✅ ACID guarantees prevent duplicates
- ✅ Graceful recovery from crashes (WAL mode)
- ✅ Easy to debug (just query the DB)
- ✅ Scales to 1000s of tasks
- ✅ Minimal code (100-200 lines core logic)

**Cons:**
- ❌ 5-30s latency (polling delay)
- ⚠️ Constant CPU wakeups (mitigated with backoff)
- ⚠️ Database size grows (needs cleanup)

**When to use:**
- MVP phase (now)
- <100 concurrent sessions
- Latency-tolerant workloads
- Simple, reliable operation priority

**Code footprint:** ~500 lines (database + poller + watchers)

---

### 2. Daemon + IPC (Real-time Alternative)

```
Bridge Daemon (single process)
    ↓ spawns/manages
[Session A] [Session B] [Session C]
    ↓         ↓         ↓
Telegram → Daemon routes → Sessions
    ↑         ↓
    ← Reports back
```

**Architecture:**
- Bridge daemon runs continuously
- Spawns/monitors Claude Code sessions
- Sessions connected via pipes or sockets
- Immediate task dispatch (event-driven)

**Task Dispatch:**
```python
Telegram writes task
    ↓
Daemon receives (via MCP channel)
    ↓
Daemon finds idle session for agent
    ↓
Daemon pipes task to session stdin
    ↓
Session processes (instant)
```

**Pros:**
- ✅ Real-time dispatch (sub-second)
- ✅ Single source of truth (daemon)
- ✅ Lower CPU usage (event-driven vs polling)
- ✅ Easier session lifecycle management
- ✅ Better observability (daemon logs)

**Cons:**
- ❌ Complex IPC setup (sockets/pipes)
- ❌ Daemon is single point of failure
- ❌ Harder to recover from daemon crash
- ❌ Sessions depend on daemon (can't poll independently)
- ❌ More code (~1000+ lines)
- ❌ Requires careful process management
- ⚠️ Distributed state harder to debug

**When to use:**
- Phase 2+ when real-time is needed
- 100+ concurrent sessions
- Production stability required
- You want a proper orchestration layer

**Code footprint:** ~1000+ lines (daemon + session mgmt + IPC)

---

### 3. Message Queue (Redis/RabbitMQ)

```
Telegram → [Redis Queue] ← Sessions poll/subscribe
                            ↓
                        [Task Execution]
```

**Architecture:**
- Dedicated queue server (Redis, RabbitMQ, Kafka)
- Telegram pushes to queue
- Sessions pop/subscribe from queue
- Separate database for task results

**Pros:**
- ✅ Built for this purpose
- ✅ Proven, battle-tested
- ✅ Scales to millions of tasks
- ✅ Advanced features (priorities, delays, DLQ)
- ✅ Language-agnostic

**Cons:**
- ❌ External dependency (must run Redis/RabbitMQ)
- ❌ Additional complexity (deployment, monitoring)
- ❌ Overkill for MVP (too much power)
- ❌ More code (~500 lines adapters)
- ⚠️ New failure mode (queue server down)

**When to use:**
- Phase 3+ for distributed systems
- 1000s of tasks, 100s of sessions
- Need advanced queue features
- You have ops experience

**Code footprint:** ~500 lines (adapters only, queue managed externally)

---

## Decision Tree

```
                   ┌─ What phase are you in?
                   │
     ┌─────────────┼─────────────┐
     │             │             │
    MVP       Phase 2+        Production
     │             │             │
     ↓             ↓             ↓
[SQLite]      [Daemon]     [Message Queue]
 Polling        IPC         (Redis/RabbitMQ)
     │             │             │
  5-30s         <1s            <1s
  latency       latency         latency
```

---

## Implementation Timeline

### SQLite Polling (Weeks 1-2)

```
Day 1:  Database schema + init
Day 2:  TaskPoller class
Day 3:  Telegram integration
Day 4:  Cron watchers
Day 5:  Testing + debugging
```

**Total: 1 week**

### Daemon + IPC (Weeks 2-4)

```
Day 1:  Design IPC protocol
Day 2:  Implement daemon core
Day 3:  Session lifecycle
Day 4:  Error handling
Day 5:  Testing + edge cases
```

**Total: 1+ weeks (after SQLite baseline)**

### Message Queue (Weeks 3-5)

```
Day 1:  Deploy Redis/RabbitMQ
Day 2:  Queue adapters
Day 3:  Error handling + recovery
Day 4:  Monitoring
Day 5:  Testing
```

**Total: 1+ weeks (after SQLite baseline)**

---

## Failure Scenario Responses

### Session Crashes (Mid-Task)

| Approach | Detection | Recovery | Time |
|----------|-----------|----------|------|
| **SQLite Polling** | Cron watches heartbeat | Reset task to pending | 1 min |
| **Daemon** | Daemon socket detects | Reassign to another session | <1 sec |
| **Message Queue** | Task lease expires | Queue auto-requeue | <1 sec |

### Database/Queue Corruption

| Approach | Prevention | Recovery | Downtime |
|----------|-----------|----------|----------|
| **SQLite Polling** | WAL mode | Automatic | 0 min |
| **Daemon** | Manual checkpointing | Likely manual | 5+ min |
| **Message Queue** | Persistence config | Depends on queue | Varies |

### Multiple Sessions Race (Claiming Same Task)

| Approach | Prevention |
|----------|-----------|
| **SQLite Polling** | IMMEDIATE transaction + rowcount check |
| **Daemon** | Daemon serializes with lock |
| **Message Queue** | Queue atomically pops |

**All three are safe** — different mechanisms.

---

## Performance Characteristics

### Throughput

```
SQLite Polling:       1000 tasks/sec (with proper indexes)
Daemon IPC:           5000 tasks/sec (CPU limited)
Message Queue:        10000+ tasks/sec
```

**For MVP:** SQLite easily handles 10-100 tasks/min.

### Latency (Task Dispatch → Execution Start)

```
SQLite Polling:       5-30s (polling interval)
Daemon IPC:           10-100ms
Message Queue:        10-100ms
```

**For MVP:** 5-30s is acceptable for task queue.

### Resource Usage

```
SQLite Polling:       1-2 threads per session, minimal memory
Daemon IPC:           1 central daemon + pipes
Message Queue:        Separate server (1GB+ RAM)
```

**For MVP:** SQLite is most lightweight.

---

## Data Durability

### Task Loss Risk

| Scenario | SQLite | Daemon | Queue |
|----------|--------|--------|-------|
| Process crash | ✅ Safe (WAL) | ⚠️ Loss if daemon crashes | ✅ Safe |
| Disk full | ❌ Risky | ❌ Risky | ✅ Depends |
| Power loss | ✅ Safe | ⚠️ Loss | ✅ Safe |
| Corrupted DB | ✅ Auto-recover (WAL) | ❌ Manual | ✅ Depends |

**SQLite is excellent for durability** (better than daemon IPC).

---

## Recommended Path Forward

### MVP (Now) → Phase 2 → Production

**Phase 1: MVP (Weeks 1-3)**
- ✅ SQLite Polling
- ✅ Basic Telegram integration
- ✅ Single agent per session
- Success criteria: Task queued → executed → reported

**Phase 2: Scaling (Weeks 4-6)**
- ✅ Keep SQLite (working fine)
- ✅ Multi-session support per agent
- ✅ Profile enhancements
- ✅ Advanced Telegram commands

**Phase 3: Production (Weeks 7-10)**
- 🤔 **Decide then** whether to:
  - Keep SQLite (if load is light, <100 tasks/day)
  - Migrate to Daemon (if need real-time, <1000 tasks/day)
  - Migrate to Message Queue (if need 1000+ tasks/day)

**Why this path?**
1. SQLite gets you shipping in 1 week
2. You can measure real-world load before making expensive changes
3. If SQLite is "good enough" (it usually is), avoid unnecessary complexity
4. You learn the domain before choosing infrastructure

---

## Quick Recommendation Summary

### Use SQLite Polling If:
- ✅ Building MVP (now) ← **YOU ARE HERE**
- ✅ <100 tasks/day
- ✅ 5-30s latency acceptable
- ✅ Want simple, reliable operation
- ✅ Single machine (not distributed)

### Use Daemon If:
- ✅ Real-time dispatch critical
- ✅ 100-1000 tasks/day
- ✅ Want centralized control
- ✅ Expert in process management

### Use Message Queue If:
- ✅ 1000+ tasks/day
- ✅ Distributed systems (multiple machines)
- ✅ Advanced features needed (priorities, scheduling)
- ✅ Production SLA requirements

---

## Configuration Recommendation

For Phase 1 MVP with SQLite:

```yaml
task_queue:
  backend: sqlite
  db_path: ~/.claude-bridge/tasks.db

  polling:
    interval_seconds: 5          # Check every 5 seconds
    empty_queue_backoff: 30      # If idle, back off to 30s
    max_concurrent_per_agent: 1  # One task at a time (MVP)

  task_limits:
    max_retries: 3               # Retry failed tasks 3x
    stale_timeout_seconds: 300   # 5 min = session crashed
    task_timeout_seconds: 600    # 10 min max per task

  watchers:
    stale_task_recovery:
      enabled: true
      interval_seconds: 60       # Check every minute

    completion_reporter:
      enabled: true
      interval_seconds: 300      # Report every 5 min
      report_to_telegram: true
```

**This is production-safe for MVP scale.**

---

## Appendix: Queue Comparison Table

| | SQLite | Daemon | Redis | RabbitMQ |
|---|---|---|---|---|
| **Setup time** | 1 hour | 3 hours | 2 hours | 4 hours |
| **Code complexity** | Low | Medium | Low-Medium | Medium |
| **Dependencies** | None | IPC knowledge | Redis | Erlang+Broker |
| **Latency** | 5-30s | <1s | <1s | <1s |
| **Throughput** | 1K/s | 5K/s | 10K+/s | 10K+/s |
| **Durability** | Excellent | Good | Good | Excellent |
| **Scaling** | Single machine | Single machine | Multi-machine | Multi-machine |
| **Debugging** | Easy (SQL) | Medium | Medium | Hard |
| **MVP fit** | ✅ Perfect | ⚠️ Overkill | ❌ Overkill | ❌ Overkill |
| **Production** | ✅ OK | ✅ Good | ✅ Good | ✅ Excellent |

---

## Final Answer

**For Claude Bridge MVP: Use SQLite Polling.**

Reasons:
1. **Speed to MVP**: 1 week vs 3-4 weeks
2. **No dependencies**: SQLite is built-in
3. **Reliable**: ACID transactions, WAL recovery
4. **Simple**: <500 lines of code
5. **Easy to debug**: Just query the database
6. **Sufficient**: Handles 100+ tasks/day easily

When you hit limits (which you likely won't in Phase 1), migrate to daemon or message queue. But don't over-engineer for a problem you don't have yet.

