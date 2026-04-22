# 07 — Testing Strategy & Development Conventions

Contributor quick reference for the repo's runtime, test layout, mocking rules,
and the required pre-push loop. Pair this with
[`CLAUDE.md`](../../CLAUDE.md) and [`docs/IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md)
(wave definitions).

---

## 1. Runtime: Bun

The project is Bun-first by design, not by convenience.

| Feature used | Why |
|---|---|
| `bun:sqlite` | Native SQLite with WAL; no `better-sqlite3` / `node-sqlite3` build step |
| `bun:test` | Test runner baked in; no jest/vitest config |
| `Bun.spawn` | Detached child processes with `unref()` — see `src/execution/dispatcher.ts:107` |
| TypeScript direct-run | `bin: "./src/cli/index.ts"` in `package.json:7` — no compile step for `bridge` |
| `Bun.sleep`, `Bun.file` | Used across tests for small waits and scratch files |

**Versions.** `package.json` pins only the npm deps (`grammy ^1.21`, `zod ^3.23`,
`@modelcontextprotocol/sdk ^1.0`, `typescript ^5.4`, `@types/bun` latest). The
Bun runtime itself is not pinned in-repo — use a recent stable Bun
(>=1.1 recommended for the WAL + spawn behaviours relied on). `claude` CLI must
be on `PATH` for real use; tests must never invoke it (see §5).

---

## 2. Build / test / typecheck / lint

| Command | What it does | When to run |
|---|---|---|
| `bun install` | Install deps, create `node_modules`, `bun.lock` | First clone, after dep bump |
| `bun link` | Put `bridge` binary on `PATH` (symlinks `./src/cli/index.ts`) | Once per clone, if you want to invoke `bridge` directly |
| `bun test` | Run every `tests/**/*.test.ts` (root fixed by `bunfig.toml`) | After every edit |
| `bun test tests/wave3` | Run one wave | While iterating on a single subsystem |
| `bun test tests/wave3/dispatcher.test.ts` | Single file | Debugging one failure |
| `bun test -t "atomic dispatch"` | Filter by describe/test name | Narrow a failure |
| `bun run typecheck` (alias for `tsc --noEmit`) | Strict TS check | Before commit |
| `bun run build` | Emit `dist/` via `bun build` | Release only; runtime uses `src/` directly |
| `bun run src/cli/index.ts <cmd>` | Dev invocation without `bun link` | Local scratch |

No lint step is configured. `tsc --noEmit` with `strict: true` is the gate.

---

## 3. TypeScript config

From [`tsconfig.json`](../../tsconfig.json):

| Key | Value | Note |
|---|---|---|
| `target` / `module` | `ESNext` | Bun handles ESM directly |
| `moduleResolution` | `bundler` | Matches Bun's resolver; allows `.js` suffix on `.ts` imports |
| `types` | `["bun-types"]` | No `@types/node`; Bun globals only |
| `strict` | `true` | Non-negotiable |
| `noUncheckedIndexedAccess` | `true` | Every array access is `T \| undefined`; tests use `arr[0]!` |
| `verbatimModuleSyntax` | `true` | Use `import type` for type-only imports |
| `isolatedModules` | `true` | Each file must stand alone (enables fast transforms) |
| `declaration` + `declarationMap` + `sourceMap` | `true` | Emitted on `bun run build` only |
| `include` | `src/**/*.ts` | Tests are excluded from the emit set |
| `exclude` | `node_modules`, `dist`, `**/*.test.ts` | Tests are typechecked separately via `bun test` |

Imports inside `src/` use the `.js` extension (TypeScript + bundler resolution
idiom), e.g. `from "../../src/data/db.js"` — keep this consistent.

---

## 4. Test layout: waves

Tests live in `tests/waveN/` mirroring the implementation waves in
[`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md) §1.2, plus a `coverage/`
bucket for targeted extra coverage. There are currently 36 files.

| Directory | Scope (one line) |
|---|---|
| `tests/wave1/` | Plugin shell: `plugin.json`, skills, MCP module imports |
| `tests/wave2/` | Data layer: `BridgeDatabase`, `MessageDatabase`, `SessionManager`, cross-compat |
| `tests/wave3/` | Execution: `Dispatcher`, `CompletionHandler`, `Notifier`, `Watcher` |
| `tests/wave4/` | Orchestration: `LoopOrchestrator`, `LoopEvaluator`, `Scheduler` |
| `tests/wave5/` | CLI + integration: `bridge` commands, agent `.md` generator, memory reader |
| `tests/wave6/` | Infrastructure: daemon, permissions, tmux/bridge-cmd, "no-python" audit |
| `tests/wave7/` | Final merge: native MCP handlers, bridge-md, E2E smoke |
| `tests/coverage/` | Extra tests filling coverage gaps (`*-extra.test.ts`) |

Do not reorganise across waves for new features — add to the wave that owns the
subsystem you touched, or to `coverage/` for an isolated edge case.

---

## 5. Test conventions

### 5.1 Never call real `claude`

Tests must not spawn the real `claude` binary. Two patterns are in use:

1. **PATH shim** — write an executable `claude` script into the temp dir and
   prepend it to `PATH`. Used when you want `Dispatcher.dispatch` to actually
   spawn a subprocess without doing work. See
   [`tests/wave5/cli.test.ts:40-44`](../../tests/wave5/cli.test.ts) and
   [`tests/wave7/tool-handlers.test.ts:22-28`](../../tests/wave7/tool-handlers.test.ts):
   ```ts
   const shim = join(tmpDir, "claude");
   writeFileSync(shim, "#!/bin/sh\nexit 0\n");
   chmodSync(shim, 0o755);
   process.env["PATH"] = `${tmpDir}:${originalPath ?? ""}`;
   ```
   Restore `PATH` in `afterEach`.

2. **Fake `IDispatcher`** — when the test exercises orchestration logic, not
   spawning, inject a hand-rolled object that implements `IDispatcher`. See
   [`tests/wave4/loop.test.ts:16-27`](../../tests/wave4/loop.test.ts) and
   [`tests/wave7/e2e.test.ts:84-92`](../../tests/wave7/e2e.test.ts). Tracks
   `calls` so the test can assert how many iterations fired.

3. **`Bun.spawn` against real harmless commands** — `Dispatcher.cancel` is
   tested by spawning `sleep 60` directly
   ([`tests/wave3/dispatcher.test.ts:82`](../../tests/wave3/dispatcher.test.ts))
   because signal delivery is the behaviour under test.

### 5.2 Temp directories + ephemeral `CLAUDE_BRIDGE_HOME`

Every test that touches disk uses `fs.mkdtempSync(join(tmpdir(), "bridge-..."))`
in `beforeEach` and `rmSync(..., { recursive: true, force: true })` in
`afterEach`. This is the **only** form of isolation — there is no shared
fixture dir.

When code under test reads `CLAUDE_BRIDGE_HOME`, save/restore the env var:

```ts
// tests/wave7/tool-handlers.test.ts:19
originalEnv = process.env["CLAUDE_BRIDGE_HOME"];
process.env["CLAUDE_BRIDGE_HOME"] = tmpDir;
// afterEach:
if (originalEnv) process.env["CLAUDE_BRIDGE_HOME"] = originalEnv;
else delete process.env["CLAUDE_BRIDGE_HOME"];
```

Never write to `~/.claude-bridge` from tests. Any test that does is a bug.

### 5.3 Database setup/teardown

No in-memory SQLite. Every DB test uses a file inside `tmpDir`:

```ts
// tests/wave2/db-core.test.ts:13-21
tmpDir = mkdtempSync(join(tmpdir(), "bridge-test-"));
db = new BridgeDatabase(join(tmpDir, "test.db"));
// afterEach:
db.close();
rmSync(tmpDir, { recursive: true, force: true });
```

Rationale: `BridgeDatabase` sets WAL mode in its constructor and creates
`-wal`/`-shm` sidecar files. Testing on disk exercises that path; in-memory
SQLite would bypass it.

Always call `db.close()` before `rmSync` to flush WAL and release the file
handle — Bun on macOS tolerates leaks, but Linux CI does not.

### 5.4 MCP server testing

MCP tools are tested by **direct handler call**, not stdio round-trip. See
[`tests/wave7/tool-handlers.test.ts`](../../tests/wave7/tool-handlers.test.ts):

```ts
import { executeToolNative } from "../../src/mcp/tool-handlers.js";
const result = await executeToolNative("bridge_agents", {});
expect(result.content[0]!.text).toContain("No agents");
```

The stdio transport is only exercised at import-smoke level in
[`tests/wave1/smoke.test.ts:62`](../../tests/wave1/smoke.test.ts) (verifies
`startServer`, `TOOL_NAMES`, `TOOL_DEFINITIONS` import). Full round-trip tests
would require spawning the MCP server as a subprocess — not worth the flake
budget.

### 5.5 Telegram / grammy

Grammy itself is not mocked. Tests exercise:

- **Formatting** — pure functions like `Notifier.formatMessage` are called
  directly against synthetic `Task` objects. See
  [`tests/wave3/notify.test.ts:54-87`](../../tests/wave3/notify.test.ts).
- **Config parsing** — `Notifier.getBotToken` reads `config.json` from
  `CLAUDE_BRIDGE_HOME`; test writes the file into `tmpDir`
  ([`tests/wave3/notify.test.ts:102`](../../tests/wave3/notify.test.ts)).
- **Inbound handlers** — not currently tested at the grammy layer. New
  handlers should be factored so the pure part (parse → DB write) is callable
  without a `Bot` instance.

No HTTP-level Telegram API mocking exists. If you need it, add a
`makeFakeBot()` helper in the test file; do not import nock/msw.

---

## 6. Running tests

```bash
# everything
bun test

# one wave
bun test tests/wave4

# one file
bun test tests/wave4/loop.test.ts

# filter by test name (matches describe and test strings)
bun test -t "atomic dispatch"

# with coverage (bun's built-in)
bun test --coverage

# a single test, verbose — add console.log, re-run
bun test tests/wave4/loop.test.ts -t "startLoop"

# if a test leaks (hangs at exit), check for unclosed DBs / unreffed procs
bun test --timeout 5000 tests/waveN/foo.test.ts
```

Debugging: prefer narrowing to a single `-t` match, adding `console.error` (not
`console.log` — CLI tests capture stdout, see §7), and inspecting `tmpDir` by
dropping a `process.exit(0)` before teardown.

---

## 7. Code conventions

From [`CLAUDE.md`](../../CLAUDE.md) "Conventions" + observation:

- **TypeScript strict mode.** No `any` in new code. Use `!` for
  noUncheckedIndexedAccess in tests only.
- **Single responsibility per module.** `src/data/db.ts` does DB only,
  `src/execution/dispatcher.ts` does spawning only, etc.
- **All state in SQLite.** `~/.claude-bridge/bridge.db` + `messages.db`. No
  process-local caches that could desync with the DB.
- **stderr for errors, stdout for data.** CLI tests hook both
  ([`tests/wave5/cli.test.ts:36-37`](../../tests/wave5/cli.test.ts)). If a
  command prints an error to stdout, the test will fail.
- **Exit code 0 = success, non-zero = error.** CLI handlers return a numeric
  `code` (see `COMMAND_HANDLERS` in `src/cli/index.ts`).
- **Imports use `.js` suffix** for local `.ts` files (bundler resolution).
- **Agent `.md` files** use native Claude Code format: YAML frontmatter +
  markdown body. Keep the Stop hook wired to `bridge on-complete`.
- **One commit per logical change.** Use conventional-commit style (`fix:`,
  `feat:`, `refactor:`) per the existing history in `git log`.

---

## 8. Pre-push loop

The full loop from [`CLAUDE.md`](../../CLAUDE.md) "Development Flow". Run all
of these before pushing anything non-trivial:

```bash
# 1. edit in src/
# 2. unit tests
bun test

# 3. typecheck
bun run typecheck              # or: tsc --noEmit

# 4. re-scaffold a test bot dir (interactive prompts for Telegram token)
bridge setup-bot ~/projects/bridge-bot
# non-interactive:
bridge setup-bot ~/projects/bridge-bot --telegram-token "$TELEGRAM_TOKEN" --no-prompt

# 5. verify wiring
bridge doctor

# 6. restart running instances so they pick up the new src/
bridge restart
# (or, per-instance:)
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge restart

# 7. smoke test on Telegram with a real dispatch
# 8. commit, tag, push
```

`bridge doctor` is the integration gate — it checks PATH, config, DB schema,
daemon status. If it fails and `bun test` passes, you have an environment bug
(see §10 and `CLAUDE.md` "Debugging Critical Bugs").

---

## 9. Multi-instance dev testing

Do not test against your real `~/.claude-bridge` — use a throwaway home:

```bash
export CLAUDE_BRIDGE_HOME=~/.claude-bridge-dev
bridge setup-bot ~/projects/bridge-bot-dev --telegram-token "$DEV_BOT_TOKEN" --no-prompt
bridge start
bridge create-agent test /tmp/scratch --purpose "smoke"
bridge dispatch test "print hello"
bridge daemon-status
bridge stop
rm -rf ~/.claude-bridge-dev
```

Every `bridge` subcommand honours `CLAUDE_BRIDGE_HOME`. The daemon service name
is derived from it, so main and dev instances coexist cleanly (see
[`CLAUDE.md`](../../CLAUDE.md) "Multi-Instance Setup").

For tests, `tool-handlers.test.ts` demonstrates the pattern programmatically:
set `process.env.CLAUDE_BRIDGE_HOME = tmpDir` in `beforeEach`, restore in
`afterEach` (§5.2).

---

## 10. Pitfalls

| Pitfall | Symptom | Fix |
|---|---|---|
| Writing to real `~/.claude-bridge` | Tests mutate your actual bridge DB | Always set `CLAUDE_BRIDGE_HOME=tmpDir`; grep for hard-coded `~` in new tests |
| Not closing `BridgeDatabase` | WAL files left behind, flaky `rmSync` on Linux | `db.close()` before `rmSync` in `afterEach` |
| Leaking `Bun.spawn` children | Test hangs at exit | Always `await dispatcher.cancel(pid)` in the test, or `proc.unref()` + explicit `kill` |
| Calling real `claude` | Test makes network calls, costs money, flakes | Use PATH shim (§5.1.1) or fake dispatcher (§5.1.2); audit new tests for `spawn(["claude"` |
| Forgetting to restore `process.env` | Later tests see stale `CLAUDE_BRIDGE_HOME` / `PATH` | Save in `beforeEach`, restore in `afterEach` unconditionally |
| Forgetting to restore `console.log` in CLI tests | Other tests lose output | Save `originalLog = console.log` before overriding; restore in `afterEach` (see `tests/wave5/cli.test.ts:34-49`) |
| Tests that depend on wall-clock timing | Flakes under load | Prefer state assertions (`db.getTask(id)!.status === "done"`) over sleep-and-check |
| Using `any` to silence `noUncheckedIndexedAccess` | Masks real bugs | Use `!` only when you just inserted the row; otherwise handle `undefined` |
| Importing `.ts` without `.js` suffix | Works in Bun, breaks `tsc --noEmit` under `moduleResolution: bundler` in edge cases | Always `from "../../src/foo.js"` |
| Real Telegram calls in tests | 429s, flakes, leaked tokens | Grammy is not mocked; test pure functions only (§5.5) |

When a bug only reproduces in CI or against the real daemon, follow the
"Debugging Critical Bugs" protocol in [`CLAUDE.md`](../../CLAUDE.md) —
reproduce, challenge the first theory, check the environment before the code.
