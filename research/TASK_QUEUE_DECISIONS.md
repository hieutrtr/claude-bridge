# Task Queue Decisions — Final Choices

Document date: 2026-03-26  
Status: Ready for implementation  
Audience: Claude Bridge development team

---

## 1. Storage Backend: SQLite (DECIDED ✅)

**Decision:** Use SQLite with WAL mode for task queue storage.

**Rationale:**
- No external dependencies (single file, stdlib)
- ACID transactions guarantee correctness
- Automatic crash recovery (WAL mode)
- Excellent for 1000+ tasks
- Easy to debug (query directly)
- Production-proven (used in browsers, mobile OS)

**Configuration:**
```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA cache_size=-64000;
```

**Alternatives rejected:**
- YAML: Race conditions, manual locking complexity
- Redis: External dependency, overkill for MVP
- RabbitMQ: Overkill, complex setup
- PostgreSQL: Overkill, requires server

**Migration path:** If needed in Phase 3+, easy to migrate to Daemon or Message Queue.

---

## 2. Concurrency Model: Polling with Atomic Claiming (DECIDED ✅)

**Decision:** Multiple sessions poll SQLite database independently. Each session claims one task atomically using `BEGIN IMMEDIATE` + rowcount verification.

**Mechanism:**
```python
# In TaskPoller._claim_pending_task()
cursor.execute("BEGIN IMMEDIATE")
cursor.execute("""
    UPDATE tasks
    SET status='running', assigned_to=?
    WHERE id=? AND status='pending'
""", (session_id, task_id))

if cursor.rowcount == 0:
    # Lost the race, another session claimed it
    conn.rollback()
    return None

conn.commit()
```

**Why this works:**
- `BEGIN IMMEDIATE` acquires exclusive lock
- Only one UPDATE succeeds (others get rowcount==0)
- No possibility of duplicate execution
- Scales to multiple sessions without synchronization overhead

**Alternatives rejected:**
- Daemon routes tasks: Requires IPC, single point of failure
- File locks: Manual, error-prone
- Redis BLPOP: Requires external server

---

## 3. Polling Interval: 5 Seconds (DECIDED ✅)

**Decision:** Default poll interval 5 seconds. Back off to 30 seconds if queue empty.

**Rationale:**
- 5s: Good balance between latency (5-10s) and CPU usage
- 1-2s: Too aggressive, wastes CPU on empty queue
- 30s: Acceptable, but less responsive
- Backoff: If no tasks for 30s, wait longer (save CPU)

**Configuration:**
```yaml
polling:
  interval_seconds: 5
  empty_queue_backoff_seconds: 30
```

**Latency expectations:**
- Task appears in queue: 0-0.5s (Telegram → DB)
- Next poll window: 0-5s
- Task execution starts: 0.5-5.5s (acceptable)

---

## 4. Task Timeout: 600 Seconds (DECIDED ✅)

**Decision:** Default task timeout 10 minutes (600 seconds), configurable per agent.

**Rationale:**
- Most tasks complete in seconds to minutes
- Complex tasks (e.g., code review) might take 5-10 min
- 10 min is reasonable upper bound
- Beyond that, task should be broken into smaller pieces

**Configuration:**
```yaml
task_limits:
  task_timeout_seconds: 600  # 10 minutes
```

**Per-agent override** (future):
```yaml
agents:
  researcher-my-app:
    task_timeout_seconds: 1800  # 30 min for long research tasks
```

---

## 5. Retry Strategy: 3 Retries Max (DECIDED ✅)

**Decision:** Failed tasks retry automatically up to 3 times total.

**Rationale:**
- Transient failures (network, temp resource issue) often succeed on retry
- 3 retries catches most transients
- After 3, likely a real problem
- User can manually retry if needed

**Retry logic:**
```python
if result.failed:
    if task.retry_count < task.max_retries:
        # Reset to pending for auto-retry
        cursor.execute("""
            UPDATE tasks SET status='pending', retry_count=retry_count+1
            WHERE id=?
        """)
    else:
        # Mark as failed, don't retry
        cursor.execute("""
            UPDATE tasks SET status='failed'
            WHERE id=?
        """)
```

**Configuration:**
```yaml
task_limits:
  max_retries: 3
```

---

## 6. Stale Task Recovery: 1-Minute Checks (DECIDED ✅)

**Decision:** Cron watcher checks for stale (crashed) tasks every 1 minute.

**Mechanism:**
- Check for tasks in `running` state with old `started_at`
- If session not alive (no heartbeat in 5 min): reset to pending
- Retries follow retry logic above

**Configuration:**
```yaml
watchers:
  stale_task_recovery:
    enabled: true
    interval_seconds: 60  # Check every minute
    
task_limits:
  stale_timeout_seconds: 300  # 5 minutes = session crashed
```

**Recovery example:**
- Task starts: 10:00:00
- Session crashes at 10:01:30
- Cron checks at 10:01:00 (no action, too soon)
- Cron checks at 10:02:00 (still within 5 min, no action)
- Cron checks at 10:06:00 (5 min passed, session not alive)
- Task reset to pending, retry_count incremented

---

## 7. Completion Reporting: Every 5 Minutes (DECIDED ✅)

**Decision:** Cron watcher reports completed tasks to Telegram every 5 minutes.

**Mechanism:**
- Query for tasks with `status IN ('completed', 'failed')` and `reported_at IS NULL`
- Send summary to Telegram
- Mark with `reported_at = NOW()`

**Configuration:**
```yaml
watchers:
  completion_reporter:
    enabled: true
    interval_seconds: 300  # Every 5 minutes
    report_to_telegram: true
```

**Example report:**
```
✅ Task task_abc123 completed
Agent: coder-my-app
Output: Fixed login bug in src/auth/session.ts
Files changed: 1
Duration: 2m 34s
```

---

## 8. Heartbeat Mechanism: Update on Every Poll (DECIDED ✅)

**Decision:** Each session updates its `last_heartbeat` timestamp on every poll cycle, even if no task claimed.

**Mechanism:**
```python
# In TaskPoller._poll_loop()
while running:
    task = self._claim_pending_task()
    if task:
        result = self._execute_task(task)
        self._update_task_status(task.id, result)
    
    # ALWAYS update heartbeat
    self._update_heartbeat()
    
    time.sleep(self.poll_interval)
```

**Cleanup:**
- Sessions with `last_heartbeat < NOW() - 5 minutes`: considered dead
- Dead sessions removed from database
- Their tasks reset to pending (for retry)

**Configuration:**
```yaml
task_limits:
  stale_timeout_seconds: 300  # Session considered dead after 5 min
```

---

## 9. Database Constraints: Foreign Keys Enforced (DECIDED ✅)

**Decision:** Use SQL constraints to prevent orphaned records.

**Constraints:**
```sql
-- Tasks require valid agent
FOREIGN KEY (agent_name) REFERENCES agents(name) ON DELETE CASCADE

-- Valid status values
CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'))

-- Unique agents per project+role
UNIQUE(project_path, role)
```

**Rationale:**
- Database maintains invariants
- Can't create task for non-existent agent
- Can't set invalid status
- DB is source of truth

---

## 10. Session State Model (DECIDED ✅)

**Decision:** Session state is simple: `idle | working | stopped`

**Transitions:**
```
idle → working (when claiming task)
working → idle (when task completes)
any → stopped (when session exits)
```

**Current task tracking:**
- Session.current_task_id points to task being executed
- Used for debugging and audit trail
- Cleared when task completes

**Note:** State is informational only. Real state comes from task status.

---

## 11. Agent Registration: Manual via Profile (DECIDED ✅)

**Decision:** Agents registered when profile is created. Bridge auto-registers in agents table.

**Process:**
```python
# When ProfileManager.create() called
profile = ProfileManager.create("coder-my-app", "~/my-app")

# Bridge auto-registers in DB
cursor.execute("""
    INSERT INTO agents (name, project_path, role)
    VALUES (?, ?, ?)
""", ("coder-my-app", "~/my-app", "coder"))
```

**Agent lifecycle:**
- Created: When user runs `/spawn coder --project ~/my-app`
- Active: While profile exists and sessions reference it
- Deleted: When user runs `/delete-agent` (cascades to tasks)

---

## 12. Telegram Integration: Task Creation Only (DECIDED ✅)

**Decision:** Telegram channel writes tasks to DB. Doesn't spawn Claude Code directly.

**Flow:**
```
Telegram: /spawn coder-my-app "Fix login bug"
   ↓
TelegramTaskCreator.create_task()
   ↓
INSERT INTO tasks (agent_name, description, ...)
   ↓
TaskPoller (in session) polls and claims task
   ↓
TaskPoller executes via subprocess.run(['claude', ...])
   ↓
Result saved to database
   ↓
Cron reporter sends completion back to Telegram
```

**Rationale:**
- Decouples Telegram from Claude Code
- Session can run independently
- Telegram doesn't need to stay connected
- Reliable async execution

---

## 13. Error Handling: Fail-Open, Report-Back (DECIDED ✅)

**Decision:** If anything fails (execution, DB, network), log and report back. Don't crash.

**Principle:** "Fail gracefully"

**Examples:**
- Task execution fails → marked as failed, reported to user
- DB locked → back off, retry next poll
- Telegram send fails → logged, task still recorded
- Permission timeout → default to DENY (safe)

**Logging:**
- All errors logged to `~/.claude-bridge/logs/bridge.log`
- Audit trail in `audit_log` table
- User notified via Telegram of important events

---

## 14. Configuration: Single YAML File (DECIDED ✅)

**Decision:** All configuration in `~/.claude-bridge/config.yaml`

**Structure:**
```yaml
task_queue:
  backend: sqlite
  db_path: ~/.claude-bridge/tasks.db

  polling:
    interval_seconds: 5
    empty_queue_backoff_seconds: 30
    heartbeat_timeout_seconds: 300

  task_limits:
    max_retries: 3
    stale_timeout_seconds: 300
    task_timeout_seconds: 600

  watchers:
    stale_task_recovery:
      enabled: true
      interval_seconds: 60

    completion_reporter:
      enabled: true
      interval_seconds: 300
```

**Rationale:**
- Single source of truth for configuration
- Easy to manage, version control, backup
- No hardcoded values in code

---

## 15. Debugging: Query the Database (DECIDED ✅)

**Decision:** No special debugging tools. Just query SQLite directly.

**Commands:**
```sql
-- Current work
SELECT * FROM tasks WHERE status IN ('pending', 'running');

-- Failed tasks
SELECT * FROM tasks WHERE status='failed' ORDER BY completed_at DESC;

-- Active sessions
SELECT * FROM sessions;

-- Full audit trail
SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 100;

-- Task history for one agent
SELECT id, status, created_at, completed_at FROM tasks
WHERE agent_name='coder-my-app' ORDER BY created_at DESC;
```

**Rationale:**
- SQL is universal language
- No special logging format to parse
- Can answer arbitrary questions
- Database is always in consistent state

---

## Implementation Order

1. **Database schema** (1 day)
   - Create SQLite, all tables, indexes

2. **TaskPoller** (1 day)
   - Atomic claiming logic
   - Task execution via subprocess
   - Status updates

3. **Telegram adapter** (1 day)
   - Write tasks from Telegram
   - Input validation

4. **Cron watchers** (1 day)
   - Stale recovery
   - Completion reporter
   - Session health

5. **Integration & testing** (1-2 days)
   - Integrate into Bridge daemon
   - Test concurrent sessions
   - Test failure scenarios

**Total: 1 week**

---

## Acceptance Criteria

- ✅ Multiple sessions claim tasks without duplication
- ✅ Crashed sessions auto-recover within 1 minute
- ✅ Tasks appear in queue within 5 seconds
- ✅ Completion reported within 5 minutes
- ✅ Database survives process crash with no manual recovery
- ✅ Configuration is simple (one YAML)
- ✅ Debugging is easy (just query SQL)
- ✅ No external dependencies
- ✅ Production-ready code

---

## Open Questions / Future Decisions

These decisions are **deferred** to Phase 2:

1. **Priority queue?**
   - Not needed for MVP
   - Can add `priority` column, sort by it
   - Decision: Phase 2

2. **Task dependencies?**
   - Task B must wait for Task A
   - Not needed for MVP
   - Decision: Phase 3

3. **Scheduled tasks?**
   - "Run at 3pm", "every day"
   - Not needed for MVP
   - Decision: Phase 3

4. **Multi-machine?**
   - SQLite works only on single machine
   - Upgrade to Daemon/Message Queue if needed
   - Decision: Phase 2-3

5. **Real-time dispatch?**
   - Current polling is 5-30s latency
   - If faster needed, upgrade to Daemon IPC
   - Decision: Phase 2 (if needed)

---

## Summary

**Selected approach:** SQLite + Polling

**Why:** Simplest, most reliable, fastest to implement, zero dependencies.

**When to reconsider:** When you hit limits (unlikely in MVP).

**Effort:** 1 week implementation, 1 week integration.

**Status:** Ready to start. All decisions finalized.

---

*Research completed and decisions finalized on 2026-03-26*  
*Next: Begin implementation*
