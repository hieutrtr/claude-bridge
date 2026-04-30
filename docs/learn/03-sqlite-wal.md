# SQLite and WAL mode: a guide for maintaining claude-bridge

A learning guide for developers who know Postgres or MySQL well but have never
treated SQLite as a real database. claude-bridge stores all its state — agents,
tasks, loops, schedules, permissions, message queues — in SQLite, and the whole
architecture only works because SQLite's WAL journal mode lets a long-lived
daemon, short-lived CLI invocations, and Stop-hook subprocesses all read and
write the same file concurrently without corruption.

By the end of this doc you should be able to answer:

- Why SQLite fits this project at all, given you could have used Postgres.
- What WAL is, why `-wal` and `-shm` files appear next to `bridge.db`, and what
  rules the WAL contract imposes on your code.
- Why the `bridge on-complete` stop-hook subprocess can write to the DB
  simultaneously with the daemon without stepping on it.
- How to safely add a column, an index, or a query.
- How to poke at `bridge.db` with the `sqlite3` CLI when things look wrong.

---

## 1. What SQLite actually is

The single most important sentence in this guide: **SQLite is not a database
server. It is a C library that reads and writes a database file.**

When your code does `new Database("bridge.db")`, you are not connecting to a
daemon over a socket. There is no `sqlited` process. You are loading object
code into your own process, which opens a regular file on disk and manipulates
B-trees inside it using POSIX syscalls — `read`, `write`, `fcntl` for locking,
`fsync` for durability. Processes that open the same file coordinate via file
locks, not a server.

Consequences:

- **Opening a DB is cheap.** No round-trip, no TLS, no auth. For a CLI that runs
  briefly and exits, this matters a lot.
- **Queries run in-process.** `db.query("SELECT * FROM tasks").all()` fills a
  JavaScript array directly from the page cache in your process's memory. No
  wire serialization.
- **"The server" is whoever currently holds the write lock.** There is no
  central coordinator.
- **Schema management is your job.** No roles, no `pg_dump`, no extensions.
  The database is one file.
- **There is exactly one writer at a time.** True in the default journal mode,
  and — surprisingly — still true in WAL mode. What WAL changes is whether
  *readers* have to wait. Not whether two writers can run at once.

### Where SQLite shines

Desktop apps (Firefox, Chrome, every iOS/Android app), CLIs that need local
state (npm, apt, homebrew), local caches, tests with an in-memory DB, and
anything where "the data lives next to the program" is the natural shape.

### Where SQLite does not shine

Multi-node deployments (no built-in replication), high-concurrency write
workloads (one writer at a time becomes a wall at tens of thousands of writes
per second), cross-machine clients over NFS (locking semantics differ and you
*will* corrupt the file), or any scenario where you want a DBA between the app
and the data.

claude-bridge sits squarely in the "shines" column: one machine, a handful of
processes, write volumes measured in dozens per minute at peak.

---

## 2. Why claude-bridge uses SQLite

Concretely, the architecture dictates the storage choice:

1. **Zero ops.** The project ships as a Bun binary (`bridge`). No "install
   Postgres, create a role, run migrations, configure `pg_hba.conf`." A fresh
   `bun install` + `bridge start` works; the DB file is created on first open
   at `~/.claude-bridge/bridge.db`.

2. **It ships inside the CLI.** `bun:sqlite` is built into Bun, so the binary
   that dispatches tasks and the binary the Stop hook invokes are the *same*
   binary, and both open the same file directly. No client library versioning,
   no connection pool to tune.

3. **No network hop for the stop-hook subprocess.** When a Claude Code run
   finishes, Claude invokes `bridge on-complete <task-id>` as a subprocess.
   That subprocess has to write "task X done, cost Y, duration Z" and exit.
   With Postgres you'd pay: spawn + TCP connect + TLS + auth + query + close.
   With SQLite: spawn + `open()` + `write()` + `close()`. The difference is
   ~40ms vs ~2ms.

4. **WAL gives us enough concurrency.** The daemon holds a long-lived handle.
   CLI invocations open short-lived ones. Stop-hook subprocesses do the same.
   WAL mode (next section) lets readers never block, and lets the one current
   writer not block readers.

5. **The data naturally lives next to the program.** Agent `.md` files, the
   worktree root, config JSON, and the SQLite file all live under
   `~/.claude-bridge/` (or whatever `CLAUDE_BRIDGE_HOME` points at). Multi-
   instance setups get their own directory, DB, and daemon.

If the project ever became a hosted multi-tenant service, you would swap
SQLite out for Postgres behind `src/data/interfaces.ts` — the interface was
designed with that in mind. Today, SQLite is the right tool.

---

## 3. Core concepts refresher (for Postgres people)

SQLite looks like every other SQL database on the surface. There are half a
dozen places where defaults will surprise you. These are the ones that matter
for maintaining claude-bridge.

### Type affinity, not strict types

In Postgres, an `INTEGER` column rejects `'hello'`. In classic SQLite, columns
have *affinities*: the column prefers an integer, but will store a string if
you give it one. This is why you'll see `TIMESTAMP` columns in `db.ts` that
actually contain ISO-8601 text — there is no true `TIMESTAMP` type, just an
affinity that prefers text-like storage. Practically: timestamps are ISO-8601
strings (`"2026-04-22 10:15:00"`), booleans are `0`/`1`, and you validate in
TypeScript rather than relying on SQLite to reject bad input.

### Transactions

SQLite transactions behave like Postgres transactions, except: if you don't
open one, every statement auto-commits. Multi-statement work must be grouped
explicitly. The idiomatic `bun:sqlite` form is `db.transaction(fn)`, which
returns a callable that runs `fn` inside `BEGIN`/`COMMIT`. See
`atomicCheckAndCreateTask` in `db.ts` — it checks for a running task and
inserts atomically, using `.exclusive()` to serialize against other writers.
Wrapping 100 inserts in one transaction is ~100× faster than 100 autocommits,
because each autocommit forces an fsync.

### Prepared statements and parameter binding

Every query in this codebase uses `?` placeholders:

```ts
this.db.query("SELECT * FROM tasks WHERE id = ?").get(id);
```

That is not stylistic — it is the only way to avoid SQL injection. Building a
query with string concatenation and user input is a bug. The one exception is
dynamic column names in the generic updaters (`updateTask`, `updateLoop`),
which use a whitelist (`TASK_UPDATABLE`, `LOOP_UPDATABLE`) so only known
column names can reach the SQL. Preserve that pattern when you add new
updatable columns.

### Foreign keys are off by default

This is the most surprising SQLite default. `FOREIGN KEY (...) REFERENCES ...`
is parsed and stored, but *not enforced* unless you turn it on per-connection:

```ts
this.db.exec("PRAGMA foreign_keys=ON");
```

Every `BridgeDatabase` and `MessageDatabase` constructor runs this. If you
open a connection elsewhere (a script, a test, the `sqlite3` CLI), you have
to run it too. Per-connection, not per-database.

### Indexes

Same tradeoff as Postgres: indexes speed up matching reads and slow down
writes on indexed columns. The `CREATE INDEX IF NOT EXISTS` block at the
bottom of `initSchema()` is driven by specific hot queries (`status =
'running'`, `session_id = ?`, `next_run_at <= ?`). Don't add an index without
a query that justifies it, and use `EXPLAIN QUERY PLAN` (section 8) to
confirm it's used.

---

## 4. Journal modes: the heart of the matter

SQLite's durability story is built around a *journal*: a side file that holds
enough information to either undo a partial transaction (rollback journal) or
redo a committed transaction (write-ahead log). Which, and how, is controlled
by `PRAGMA journal_mode`. This is the single pragma you most need to
understand.

Here is the default mode, `DELETE`, and the one we use, `WAL`, side by side.

### DELETE mode (the default)

```
   Main DB file            Rollback journal
   ----------------         -------------------
   [ pages A, B, C ]        <journal of old pages>
                ^                     ^
                |                     |
                +--- writer copies --+
                     old pages here
                     before overwriting
```

When a writer commits:

1. Acquire an exclusive lock on the main DB. **All readers must wait.**
2. Copy the original contents of every page about to be modified into
   `bridge.db-journal`.
3. `fsync()` the journal.
4. Write the new page contents into the main DB file.
5. `fsync()` the main DB.
6. Delete the journal file.
7. Release the lock.

If the process crashes after step 3 but before step 6, the next opener sees
the leftover journal and rolls the old pages back in. Durable and correct. But
the crucial property is step 1: **writers hold an exclusive lock, so readers
block for the entire duration of every write.** On a workload with many
readers this serializes everything.

### WAL mode

WAL inverts the durability story. Instead of copying *old* pages into a
journal and overwriting the DB in place, the writer appends *new* pages to a
write-ahead log file and leaves the main DB untouched until a checkpoint.

```
   Main DB file        WAL file                SHM file
   [ pages ... ]       [ new page 1 ]          [ index into WAL ]
   (unchanged by       [ new page 2 ]          [ reader marks ]
    live writes until  [ new page 3 ]
    checkpoint)         ^
                        writer appends here
```

You will see three files next to each other when WAL is on:

- `bridge.db` — the main database. Untouched by live writers between
  checkpoints.
- `bridge.db-wal` — the write-ahead log. Grows as writes happen. Pruned at
  checkpoints.
- `bridge.db-shm` — shared memory: a memory-mapped index that tells every
  connection which WAL frames correspond to which page numbers, plus reader
  positions.

When a writer commits in WAL mode:

1. Acquire the *write* lock (only writers contend; readers do not).
2. Append the new page images to the WAL file.
3. `fsync()` the WAL.
4. Update the shared-memory index so future readers see the new frames.
5. Release the write lock.

Readers follow a different protocol. At start, a reader notes the current
end-of-WAL position ("my snapshot ends here"). It then reads pages in this
order: check the WAL up to my snapshot point; if the page is there, use it;
otherwise read the page from the main DB. Readers *never* block writers, and
writers *never* block readers. That is the whole game.

Invariants you must keep in mind:

- **Still one writer at a time.** WAL does not enable concurrent writers. Two
  `INSERT`s at the same microsecond will still serialize.
- **Readers see a consistent snapshot.** A reader that started at WAL position
  100 sees the DB as of that moment, even if the WAL has since grown to 500.
- **Checkpoints move WAL pages into the main DB.** SQLite does this
  automatically at ~1000 WAL pages (~4 MB). Force one with
  `PRAGMA wal_checkpoint(TRUNCATE)`.
- **All three files travel together.** Copying `bridge.db` alone can produce
  a stale/partial DB. Either stop all writers first, or checkpoint to
  `TRUNCATE` before copying, or use SQLite's backup API.

### TRUNCATE, MEMORY, OFF (for completeness)

You will almost never touch these:

- `TRUNCATE` — like DELETE, but truncates the journal file to zero length
  instead of deleting it. Marginally faster on some filesystems.
- `MEMORY` — rollback journal in RAM. Fast, but a crash mid-write corrupts
  the DB.
- `OFF` — no journal at all. A crash mid-write corrupts the DB. Useful only
  for one-shot bulk loads you can re-run from scratch.

For claude-bridge, `WAL` is the only correct answer. Both `BridgeDatabase` and
`MessageDatabase` set it in their constructor. Do not remove those lines.

---

## 5. The concurrent-writer pattern in claude-bridge

This is the most important section, because the whole Stop-hook architecture
depends on understanding it.

### The cast of processes

```
  +-------------------+          +------------------------+
  |  bridge daemon    |          |  bridge CLI (dispatch) |
  |  (long-lived)     |          |  (short-lived)         |
  |  holds DB handle  |          |  opens, writes, exits  |
  +---------+---------+          +-----------+------------+
            |                                 |
            v                                 v
         +------------------ bridge.db -------------------+
         |  +--------+      WAL mode       +--------+    |
         |  | main   |                     | wal    |    |
         |  | pages  |                     | frames |    |
         |  +--------+                     +--------+    |
         +---+--------+---------------------+--------+---+
                ^                                ^
                |                                |
      +---------+---------+         +------------+------------+
      |  claude subprocess |         |  bridge on-complete    |
      |  (running a task)  |-------->|  (Stop hook)           |
      |                    |  spawn  |  opens, writes, exits  |
      +--------------------+         +------------------------+
```

Four categories of processes touch `bridge.db`:

1. **The daemon.** Kept alive by launchd/systemd. Holds one `Database` handle
   for its lifetime. Reads tasks, enqueues notifications, polls running tasks.
2. **CLI commands** like `bridge dispatch`, `bridge list-agents`,
   `bridge history`. Open a handle, do their work, `close()`, exit.
3. **Stop-hook subprocesses** — `bridge on-complete <task-id>` — spawned by
   Claude Code itself when an agent run finishes. They open a fresh handle,
   update the row for that task (`status='done'`, `cost_usd`, `duration`,
   `exit_code`), then exit.
4. **The `claude` subprocess** running the actual work. This one doesn't
   touch `bridge.db` directly; it writes a result file, and the Stop hook
   records it.

All of these hit the *same file on disk*. WAL mode is what makes that safe.

### Why this works without a server

Because there is no server, "coordination" means "file locks plus the rules
both processes follow." The rules are:

- Every opener runs `PRAGMA journal_mode=WAL` (set in the constructor, so all
  openers agree).
- Every opener runs `PRAGMA foreign_keys=ON`.
- Writers acquire the WAL write lock briefly. If it's held, they get
  `SQLITE_BUSY` back.
- Readers never have to wait.

A typical sequence:

```
  t=0.00s  daemon inserts "task 42 running" (write lock for ~1ms)
  t=0.01s  daemon releases lock
  t=5.00s  claude finishes the task
  t=5.01s  claude runs `bridge on-complete 42`
  t=5.02s  on-complete opens bridge.db, acquires write lock,
           UPDATEs row 42 with cost/duration/status, releases lock
  t=5.03s  on-complete exits
  t=5.05s  daemon's next read loop sees reported=0, status=done,
           builds notification, enqueues outbound message
```

The daemon reading at t=5.00s sees a consistent pre-update snapshot. The
subprocess writing at t=5.02s sees a consistent pre-write state and commits
atomically. Neither process blocks the other for more than the microsecond
cost of appending a few WAL frames.

### The SQLITE_BUSY failure mode

The interesting case is when two writers arrive simultaneously. Say a daemon
housekeeping update collides with a stop-hook subprocess. Only one can hold
the write lock. The loser gets:

```
Error: database is locked   (SQLITE_BUSY)
```

In plain SQLite, that error is immediate — no waiting. If unhandled, the
subprocess exits with an error, the task never gets marked done, and the
daemon must recover via the fallback PID watcher.

The fix is a single pragma:

```sql
PRAGMA busy_timeout = 5000;  -- milliseconds
```

With `busy_timeout`, when a writer hits a locked DB, SQLite polls the lock for
up to that duration before returning `SQLITE_BUSY`. For a workload like this,
5 seconds is plenty: write locks are held for milliseconds, so collisions
resolve in the first few retries. If you start seeing "database is locked" in
practice, setting an explicit `busy_timeout` in the constructor is the first
fix to try.

### Minimal demonstration

Imagine three tiny Bun scripts pointed at `/tmp/demo.db`:

```ts
import { Database } from "bun:sqlite";
const db = new Database("/tmp/demo.db", { create: true });
db.exec("PRAGMA journal_mode=WAL");
db.exec("PRAGMA busy_timeout=5000");
db.exec("CREATE TABLE IF NOT EXISTS hits (id INTEGER PRIMARY KEY, who TEXT, at TEXT)");
db.run("INSERT INTO hits (who, at) VALUES (?, ?)",
       [process.argv[2] ?? "anon", new Date().toISOString()]);
console.log("rows:", db.query("SELECT COUNT(*) as n FROM hits").get());
db.close();
```

Run three in parallel (`bun run hit.ts a & bun run hit.ts b & bun run hit.ts c
&`). All three succeed. The table has three rows. WAL handles the interleaving,
`busy_timeout` absorbs any brief contention, and no `SQLITE_BUSY` surfaces.
That is the exact pattern claude-bridge uses, at a different scale.

---

## 6. Bun and `bun:sqlite` basics

The Node default is `better-sqlite3`. Bun ships `bun:sqlite` — same underlying
SQLite, similar synchronous API, no native compile step. Most of your
`better-sqlite3` intuitions carry over.

```ts
import { Database } from "bun:sqlite";

const db = new Database("bridge.db", { create: true });
db.exec("PRAGMA journal_mode=WAL");
db.exec("PRAGMA foreign_keys=ON");
db.exec("PRAGMA busy_timeout=5000");

// Queries
const task  = db.query("SELECT * FROM tasks WHERE id = ?").get(42); // row | null
const all   = db.query("SELECT * FROM tasks").all();                 // row[]
const meta  = db.run("DELETE FROM tasks WHERE id = ?", [42]);
meta.changes;          // rows affected
meta.lastInsertRowid;  // for INSERTs

// Transactions
const insertMany = db.transaction((items) => {
  for (const x of items) db.run("INSERT INTO widgets (name) VALUES (?)", [x]);
});
insertMany(["a", "b", "c"]);   // one fsync total

db.close();
```

`query` and `prepare` are near-synonyms. `.get()` returns the first row (or
`null`), `.all()` returns an array, `.run()` executes a write. `exec` runs
statements that don't take parameters or return rows. `":memory:"` as the
path gives you an ephemeral in-memory DB — often the right choice for tests.
The Bun docs (section 10) are the reference.

---

## 7. Schema design patterns in this project

Non-obvious choices you'll see in `db.ts` and `message-db.ts`:

### ISO-8601 strings for timestamps

`TIMESTAMP DEFAULT CURRENT_TIMESTAMP` columns hold strings like `"2026-04-22
10:15:00"` (space separator, no `T`, no timezone — UTC by convention). The
`utcnow()` helper generates these. Strings over epoch ints because readability
in `sqlite3 bridge.db "SELECT created_at FROM tasks"` beats `1745316000000`.
SQLite's date functions (`datetime()`, `date()`, `'+5 minutes'` modifiers)
work on these strings.

### Integer booleans (0/1)

SQLite has no native boolean. `reported INTEGER DEFAULT 0`, `enabled INTEGER
DEFAULT 1`, `pending_approval INTEGER NOT NULL DEFAULT 0` are booleans in
disguise. Bind `1`/`0` from TypeScript, not `true`/`false`. Compare with
`=== 1` on read.

### UNIQUE as identity anchor

`agents.session_id TEXT NOT NULL UNIQUE` and `schedules UNIQUE(name,
agent_name)` are not just constraints — they are the stable identifier the
rest of the code uses for lookup. The numeric `id` autoincrement is for
internal joins; the UNIQUE key is what external callers reference. When you
add a new table, ask whether there's a natural identity besides the
autoincrement, and if so, make it UNIQUE.

### IF NOT EXISTS bootstrap

`initSchema()` is one `exec` block of `CREATE TABLE IF NOT EXISTS` and
`CREATE INDEX IF NOT EXISTS`. It runs on every open. Fresh DB: creates
everything. Existing DB: no-ops. That is the entire "schema deployment"
story — no migration runner, no versioning table. It works because every
change to an existing table is additive.

### addColumnIfMissing for additive migrations

`CREATE TABLE IF NOT EXISTS` won't alter an existing table. For new columns,
the project uses `addColumnIfMissing`, which consults `PRAGMA table_info` and
runs `ALTER TABLE ... ADD COLUMN` only if the column is missing. Idempotent,
safe to run on every start. When you add a column, add it to both
`initSchema()` (for fresh installs) *and* `runMigrations()` (for upgrades).

Harder changes — renaming a column, dropping one, adding `NOT NULL` without a
default — require a real migration: create a new table, copy data, drop old,
rename. The project hasn't needed that yet. If you're the first to add one,
introduce a version counter at the same time.

---

## 8. Debugging SQLite

When something looks off, the `sqlite3` CLI is the fastest way in. Ships with
macOS and every Linux distro.

```bash
sqlite3 ~/.claude-bridge/bridge.db
```

Meta-commands (start with a dot):

```
.tables               -- list tables
.schema               -- dump every CREATE TABLE / INDEX
.schema tasks         -- just one table
.headers on           -- show column names
.mode column          -- pretty-print results
.timer on             -- time each query
.quit                 -- exit
```

With `.headers on` and `.mode column`, normal SELECTs are readable:

```sql
SELECT id, session_id, status, cost_usd, created_at
FROM tasks
ORDER BY id DESC
LIMIT 10;
```

### EXPLAIN QUERY PLAN

When a query feels slow or you're unsure it uses an index:

```sql
EXPLAIN QUERY PLAN
SELECT * FROM tasks WHERE status = 'running';
```

`SEARCH tasks USING INDEX idx_tasks_status (status=?)` = good (index hit).
`SCAN tasks` = bad (full table scan). Add an index or reshape the query.

### Finding the WAL and SHM files

Next to `bridge.db` you'll see:

```
bridge.db
bridge.db-wal
bridge.db-shm
```

If the daemon is running, `bridge.db-wal` may be nonempty while `bridge.db`
looks stale. Normal. The WAL holds recent writes not yet checkpointed. To
inspect the canonical main DB — e.g. for backup — force a checkpoint:

```sql
PRAGMA wal_checkpoint(TRUNCATE);
```

This writes everything from WAL into the main DB and truncates the WAL. If
another process is writing, the checkpoint may complete only partially; stop
the daemon first if it matters.

### "Database is locked" and integrity check

Long-running transactions in the CLI (e.g. a forgotten interactive `BEGIN;`)
stall other writers. `.quit` releases the lock. Don't leave interactive
sessions open against a live DB.

```sql
PRAGMA integrity_check;
```

Should return `ok`. Anything else: preserve a copy immediately and investigate
from the copy.

---

## 9. Exercises

Work through these in a scratch directory — don't point them at
`~/.claude-bridge/bridge.db`. They should all take seconds.

### Exercise 1: Create a WAL database and watch the side files

Goal: see the `-wal` and `-shm` files appear, then watch them shrink after a
checkpoint.

```bash
cd /tmp
rm -f foo.db foo.db-wal foo.db-shm
bun repl
```

In the REPL:

```ts
const { Database } = await import("bun:sqlite");
const db = new Database("foo.db", { create: true });
db.exec("PRAGMA journal_mode=WAL");
db.exec("CREATE TABLE t (id INTEGER PRIMARY KEY, s TEXT)");
for (let i = 0; i < 3; i++) db.run("INSERT INTO t (s) VALUES (?)", [`row ${i}`]);
```

In another terminal: `ls -la /tmp/foo.db*`. All three files exist; `foo.db-wal`
is nonzero. Back in the REPL:

```ts
db.exec("PRAGMA wal_checkpoint(TRUNCATE)");
```

Re-run `ls -la`. `foo.db-wal` is now zero bytes (or very small), and `foo.db`
grew to absorb the writes.

### Exercise 2: Induce SQLITE_BUSY, then fix it

Goal: feel lock contention, then see the fix. Create `writer.ts`:

```ts
import { Database } from "bun:sqlite";
const db = new Database("/tmp/bar.db", { create: true });
// NOTE: no busy_timeout yet
db.exec("PRAGMA journal_mode=WAL");
db.exec("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, s TEXT)");

db.transaction(() => {
  for (let i = 0; i < 10000; i++) {
    db.run("INSERT INTO t (s) VALUES (?)", [`${process.pid}-${i}`]);
  }
})();
console.log(process.pid, "done");
```

Run two copies in parallel:

```bash
bun run writer.ts & bun run writer.ts & wait
```

One may throw `Error: database is locked`. Now add after `journal_mode`:

```ts
db.exec("PRAGMA busy_timeout=5000");
```

Delete `bar.db*`, re-run. Both succeed. The loser waits up to 5 seconds,
acquires the lock, and continues.

### Exercise 3: Explore a real claude-bridge DB

Goal: get comfortable reading the schema you'll be modifying.

```bash
sqlite3 ~/.claude-bridge/bridge.db
```

```
.headers on
.mode column
.schema tasks

SELECT id, session_id, status, cost_usd, created_at, completed_at
FROM tasks ORDER BY created_at DESC LIMIT 10;

EXPLAIN QUERY PLAN
SELECT * FROM tasks WHERE status = 'running';
```

Interpret each column: `session_id` is the `agent--project` composite built by
`src/data/session.ts`; `status` cycles through `pending → running →
done|failed|timeout`; `cost_usd`/`completed_at` come from the Stop hook;
`reported` (0/1) tracks whether the daemon has already built a notification
for that task. The EXPLAIN should show an index hit on `idx_tasks_status`.

If you're feeling exploratory:

```sql
SELECT status, COUNT(*) FROM tasks GROUP BY status;
SELECT session_id, SUM(cost_usd) AS total FROM tasks
  GROUP BY session_id ORDER BY total DESC;
```

---

## 10. Further reading

Canonical sources. Prefer these over blog posts — SQLite's own docs are
unusually good.

- When to use SQLite: https://www.sqlite.org/whentouse.html
- Write-Ahead Logging: https://www.sqlite.org/wal.html
- Transactions: https://www.sqlite.org/lang_transaction.html
- All pragmas: https://www.sqlite.org/pragma.html
- Bun's SQLite API: https://bun.sh/docs/api/sqlite
