# Learning Bun for claude-bridge

Welcome. This guide is for you if you know JavaScript or TypeScript, you have shipped something with Node.js before, and now you need to maintain claude-bridge — which runs on Bun, not Node. After reading this and skimming the linked Bun docs, you should be able to open any file in `src/` and know what is happening, even the parts that look unfamiliar.

This is a learning doc. It teaches concepts, then shows where the project uses them, then sends you to the official Bun docs for depth. It is not a reference — for the specific wiring of dispatch, orchestration, or the database, read the matching file in `docs/specs/`.

## 1. What is Bun?

Bun is a single binary that does four things that used to need four tools:

- A **JavaScript/TypeScript runtime**, the way `node` is a runtime. You run `bun some-file.ts` and it executes.
- A **package manager**, the way `npm` or `pnpm` is. `bun install` reads `package.json` and populates `node_modules`.
- A **test runner**, the way `jest` or `vitest` is. `bun test` finds files matching `*.test.ts` and runs them.
- A **bundler**, the way `esbuild` or `webpack` is. `bun build` turns source into a deployable artifact.

Under the hood Bun is written in Zig and uses JavaScriptCore (the engine from Safari) instead of V8 (the engine in Node and Chrome). The engine swap rarely matters to you as an application developer — standard JavaScript works the same way — but it does mean that native addons built for Node (`.node` files compiled against V8's ABI) often cannot load in Bun. We will come back to that pitfall.

Bun is mostly Node-compatible: `process`, `Buffer`, `fs`, `path`, `crypto`, most of `child_process`, and `npm` packages generally just work. On top of compatibility, Bun adds its own APIs (the `Bun.*` namespace, plus `bun:*` built-in modules like `bun:sqlite` and `bun:test`) that are faster or more ergonomic than the Node equivalents.

## 2. Why claude-bridge uses Bun

Every language choice should survive the question "what does this buy us in practice?" For claude-bridge the answers are concrete:

**TypeScript runs directly, no build step.** The `bin` entry in `package.json` points at `./src/cli/index.ts`. When you type `bridge dispatch backend "add pagination"`, Bun reads the `.ts` source, type-strips it in memory, and runs it. There is no `tsc` build in the dev loop, no `dist/` directory to keep in sync with source. Iteration is: edit a file, run the CLI, see the behavior change.

**Native SQLite via `bun:sqlite`.** All state — agents, tasks, loops, schedules, permissions, notifications, teams — lives in one SQLite file. In Node you reach for `better-sqlite3`, which is a native module compiled per-platform, and that compilation breaks in ways that are painful to debug (wrong Python version, wrong Xcode tools, mismatched Node ABI). Bun ships SQLite as a built-in: `import { Database } from "bun:sqlite"` and you are done. Zero native build steps for contributors. On a fresh machine `bun install && bun test` just works.

**Fast, TypeScript-native test runner.** `bun test` discovers tests, runs them in parallel-capable workers, reads `.ts` directly, and uses a Jest-compatible API (`describe`, `test`, `expect`, `beforeEach`). The suite in `tests/` is 36 files and runs in seconds. No `ts-jest`, no Babel config, no `jest.config.js`.

**`Bun.spawn` with sensible ergonomics.** The core job of claude-bridge is spawning `claude` subprocesses — one per task — and collecting their exit codes, stdout, and PID. `Bun.spawn` accepts file descriptors directly for stdout/stderr (so output streams straight to disk without a Node-land copy), returns a `proc` object with a `pid` and a `proc.exited` promise, and has `proc.unref()` for detaching — all the primitives the dispatcher needs.

**Shipping a CLI is trivial.** `package.json`'s `"bin": { "bridge": "./src/cli/index.ts" }` plus `bun link` installs a `bridge` command on the user's `PATH` that executes the TypeScript entry point directly. No wrapper shell script, no compiled binary to publish per OS.

You will notice a theme: Bun removes steps. Each step removed is one less thing a contributor has to get right before they can make changes.

## 3. Getting started

Install Bun:

```bash
curl -fsSL https://bun.sh/install | bash
```

That gives you the `bun` binary. Verify with `bun --version`.

In this repo, after cloning:

```bash
bun install       # reads package.json, populates node_modules + bun.lockb
bun link          # makes the 'bridge' bin entry available on PATH
bun test          # runs the test suite
bun run typecheck # runs tsc --noEmit (type-check without emitting JS)
```

For quick exploration outside the repo:

```bash
mkdir scratch && cd scratch
bun init -y       # drops package.json, tsconfig, a README, an index.ts
bun run index.ts  # run it
```

A few commands worth knowing:

- `bun add <pkg>` — add a dependency (like `npm install`).
- `bun add -d <pkg>` — add a dev dependency.
- `bun run <script>` — run an npm script from `package.json`.
- `bun <file.ts>` — run a TypeScript file directly.
- `bun repl` — interactive REPL with top-level `await`.

## 4. Core APIs used in claude-bridge

### 4.1 `Bun.spawn` — launching subprocesses

**What it is.** The Bun replacement for Node's `child_process.spawn`. It starts a process and returns a handle you can read from, write to, wait on, and signal.

**Tiny example.**

```ts
// Run `echo hello`, capture stdout as text.
const proc = Bun.spawn(["echo", "hello"], { stdout: "pipe" });
const out = await new Response(proc.stdout).text();
await proc.exited;
console.log(out.trim()); // "hello"
```

Note three Bun idioms in that snippet. First, the command is an array — no shell interpretation, no quoting bugs. Second, `proc.stdout` is a `ReadableStream` that you can feed to any `Response`-shaped API (Bun leans hard on web standards). Third, `proc.exited` is a `Promise<number>` that resolves with the exit code.

The `stdout` and `stderr` options accept several shapes:
- `"pipe"` — readable stream, capture in the parent.
- `"inherit"` — forward to parent's stdout/stderr (what you want for a TTY child).
- `"ignore"` — discard.
- A numeric file descriptor — Bun writes directly to that fd.

**Where the repo uses it.** `src/execution/dispatcher.ts` spawns `claude` subprocesses. It opens real file descriptors with `openSync` and passes them as `stdout` and `stderr`, so the result JSON streams straight from the child to `{home}/workspaces/{session}/tasks/{id}.result.json`. Then it calls `proc.unref()` so exiting the dispatcher does not kill the child. For how the pieces fit together — session IDs, result file layout, stop hooks — see `docs/specs/`.

**Gotchas.**
- `proc.stdout` does not exist unless you asked for `stdout: "pipe"`. Forgetting this gives you `undefined`.
- `proc.exited` is a `Promise`, not a property. Always `await` it if you care about the exit code.
- `proc.unref()` detaches the child from the parent's event loop — the parent can exit while the child keeps running. This is what you want for a task dispatcher and what you absolutely do not want for a child you expect to read from.
- Environment is not inherited automatically when you pass `env`. If you want the parent's env plus your own additions, spread it: `env: { ...process.env, MY_VAR: "x" }`.

### 4.2 `bun:sqlite` — built-in SQLite

**What it is.** A synchronous SQLite binding built into the Bun runtime. Node has nothing equivalent out of the box; the usual Node choice is `better-sqlite3`, which has the same synchronous-style API but is a separate native module.

**Tiny example.**

```ts
import { Database } from "bun:sqlite";

const db = new Database(":memory:"); // or a file path
db.exec("CREATE TABLE cats (name TEXT, age INTEGER)");
db.run("INSERT INTO cats VALUES (?, ?)", ["Miso", 4]);

const row = db.query("SELECT * FROM cats WHERE name = ?").get("Miso");
// { name: "Miso", age: 4 }
```

Three API shapes to remember:
- `db.exec(sql)` — run one or more statements, no parameters, no result.
- `db.run(sql, params)` — execute with parameters, returns `{ changes, lastInsertRowid }`.
- `db.query(sql)` — returns a prepared statement object with `.get(...params)` (one row) and `.all(...params)` (many rows).

Transactions are first-class:

```ts
const move = db.transaction((from: string, to: string) => {
  db.run("UPDATE accounts SET bal = bal - 1 WHERE id = ?", [from]);
  db.run("UPDATE accounts SET bal = bal + 1 WHERE id = ?", [to]);
});
move("alice", "bob"); // runs both UPDATEs atomically
```

**Where the repo uses it.** `src/data/db.ts` wraps `bun:sqlite` in a `BridgeDatabase` class that enables WAL mode, runs idempotent migrations, and exposes typed methods for every table (agents, tasks, loops, schedules, permissions, notifications, teams). The interesting patterns there — a whitelist of updatable columns, atomic check-and-insert via `db.transaction(...)`, `PRAGMA table_info` for conditional schema migrations — are general SQLite techniques, not Bun-specific.

**Gotchas.**
- The API is synchronous. `db.query(...).all()` blocks. For a CLI or a small daemon that is fine and actually simpler to reason about. Do not wrap it in `Promise.resolve()` to "make it async"; that adds a microtask without adding concurrency.
- WAL mode (`PRAGMA journal_mode=WAL`) is not on by default. claude-bridge turns it on so reads and writes from the daemon and the CLI do not block each other.
- Parameter binding types are `number | string | bigint | Uint8Array | null`. If you have `undefined` in your args it will throw; coerce to `null` first.
- The return type of `.get()` and `.all()` is `unknown` in strict TypeScript. The repo uses `as SomeType` assertions because the types are enforced by the schema, not the compiler.

### 4.3 `Bun.file` — reading and writing files

**What it is.** A thin wrapper over a file path that behaves like a lazy `Blob`. You do not read the file until you ask for its contents; then you can pull bytes, text, JSON, or a stream.

**Tiny example.**

```ts
const config = await Bun.file("/etc/bridge/config.json").json();
// Write text:
await Bun.write("/tmp/out.txt", "hello\n");
// Copy a file by piping Bun.file to Bun.write:
await Bun.write("/tmp/copy.txt", Bun.file("/tmp/out.txt"));
```

In Node you would mix `fs.readFileSync`, `fs.promises.readFile`, and `JSON.parse`. In Bun the `Bun.file(path).json()` one-liner replaces all of that.

**Where the repo uses it.** Various places that need to read result JSON, config files, or agent `.md` files. The repo also uses `node:fs` directly (`mkdirSync`, `openSync`) where a lower-level operation is clearer — the Node `fs` module is fully available, so pick the tool that reads best.

**Gotchas.**
- `Bun.file(path)` never throws for a missing file at construction time. The error shows up when you actually read it. Use `await file.exists()` to test up front.
- `Bun.write` creates the file if it does not exist but does not create parent directories. If you are writing to a nested path, `mkdirSync(dir, { recursive: true })` first.

### 4.4 `bun test` — the test runner

**What it is.** A Jest-compatible test runner built into Bun. It discovers files matching `*.test.ts`, `*.spec.ts`, and a few more patterns, runs them, and reports.

**Tiny example.**

```ts
import { describe, test, expect, beforeEach } from "bun:test";

describe("addition", () => {
  let a: number;
  beforeEach(() => { a = 1; });

  test("1 + 1 is 2", () => {
    expect(a + 1).toBe(2);
  });
});
```

Run the whole suite with `bun test`. Run a subset with:
- `bun test path/to/file.test.ts` — one file.
- `bun test -t "addition"` — only tests whose name (including nested `describe`s) matches `"addition"`.
- `bun test --watch` — rerun on file changes.

**Where the repo uses it.** All of `tests/`. The layout matches the feature waves the project was built in — `wave1/` through `wave7/` plus `coverage/` for extra cases. A `bunfig.toml` at the repo root contains `[test] root = "./tests"` so you do not have to point at the tests directory.

**Gotchas.**
- The API looks like Jest but there is no `jest` global. Always import `describe`, `test`, `expect`, etc. from `"bun:test"`.
- Mocks are done with `import { mock } from "bun:test"` — similar to `jest.fn()` but not identical. Check the docs when you need one.
- `expect().toMatchInlineSnapshot` and related snapshot matchers exist and mostly work like Jest's.
- Tests run in the same process by default. If you set module-level state in one test file it can leak into another; scope state with `beforeEach` / `afterEach`.

### 4.5 TypeScript, directly

**What it is.** Not an API — a capability. Bun's loader type-strips TypeScript at runtime. You write `.ts`, you run `bun file.ts`, you are done.

**Tiny example.** In a fresh directory:

```bash
bun init -y
# Edit index.ts:
#   const greeting: string = "hi";
#   console.log(greeting);
bun run index.ts  # prints: hi
```

No `tsc`, no build output, no separate "dev" vs "prod" flow.

**Where the repo uses it.** Everywhere. The `bin` entry in `package.json` points at a `.ts` file, not a compiled `.js`. Every `import` resolves to the source file.

**Gotchas.**
- Bun type-strips but does not type-check at runtime. A `.ts` file with a type error still runs if the generated JavaScript is valid. That is why `bun run typecheck` (which is `tsc --noEmit`) is in the scripts — CI and contributors should run it.
- Imports inside the repo use `.js` suffixes even though the files are `.ts`. Example: `import { Dispatcher } from "../../src/execution/dispatcher.js"`. This is the Node ESM convention; TypeScript and Bun both resolve it to the `.ts` file. It looks wrong the first time you see it. It is correct.
- `tsconfig.json` matters for `tsc`, but Bun uses it mostly for `paths` and `baseUrl`. Most of its behavior is baked in.

### 4.6 `package.json` `bin` + `bun link`

**What it is.** The Node convention for shipping a CLI: `"bin": { "name": "path/to/entry" }` in `package.json`. `npm` and `bun` both honor it.

In claude-bridge:

```json
"bin": {
  "bridge": "./src/cli/index.ts"
}
```

When you run `bun link` inside the repo, Bun registers this package globally and creates a `bridge` shim on your `PATH` that runs `bun ./src/cli/index.ts` with whatever arguments you pass. The shim lives wherever your Bun global install puts binaries (often `~/.bun/bin`).

**Tiny example.** A two-file CLI:

```ts
// greet.ts
const name = process.argv[2] ?? "world";
console.log(`hello, ${name}`);
```

```json
// package.json
{
  "name": "greet",
  "bin": { "greet": "./greet.ts" }
}
```

After `bun link`, `greet Alice` prints `hello, Alice`.

**Gotchas.**
- Bun's `bin` entries can be `.ts` files directly — `npm` would need a `.js` file or a `#!/usr/bin/env node` shebang. If you use Bun's style, consumers running under `npm install -g` (not `bun install -g`) will not get a working binary.
- To publish a CLI that works under both Node and Bun, you ship a built JavaScript entry. claude-bridge currently targets Bun users via the `bun link` flow and ships source-only.

## 5. Bun vs Node: differences that matter here

| Topic | Node | Bun |
|---|---|---|
| Run a `.ts` file | Needs `ts-node` or a build step | `bun file.ts` just works |
| SQLite | `better-sqlite3` (native addon) | `import { Database } from "bun:sqlite"` |
| Test runner | Jest, Vitest, etc., plus config | `bun test` with zero config |
| `fetch` | Global since Node 18 | Global always |
| Spawn a child | `child_process.spawn`, `exec`, ... | `Bun.spawn(["cmd", "arg"])` |
| Import inside repo | `from "./foo.js"` (if ESM) | Same — `.js` suffix even for `.ts` source |
| `require("pkg")` | Works in CJS, not in ESM | Works in both (CJS interop is strong) |
| Native addons | Wide ecosystem | Hit or miss — N-API support is growing |
| Startup time | ~50–150 ms typical | Often sub-20 ms |
| Bundled utilities | Separate tools (`npm`, `jest`, `esbuild`, ...) | One binary |

A detail worth internalizing: `.js` import suffixes on `.ts` source files. ESM requires file extensions in relative imports. TypeScript's convention, which Bun follows, is that your source imports `./foo.js` and the resolver finds `./foo.ts`. Do not try to "fix" this by writing `./foo.ts` in imports — `tsc` will then reject the extension, and downstream bundlers get confused. The correct, ugly-looking, universal form is `./foo.js`.

`process` works. `Buffer` works. `fetch` is global. `crypto.randomUUID()` is global. Most of `fs` and `path` and `os` works unchanged. The mental model is: "assume Node, check the docs for differences when something breaks."

## 6. Common pitfalls for Node devs

**Some npm packages do not test on Bun.** Most pure-JavaScript packages work. The ones that ship native addons (`sharp`, older `sqlite3`, `bcrypt`, some crypto libraries) are the risk. The symptom is usually a confusing `Symbol not found` or `.node file` error at import time. When you add a dependency, run the test suite and watch for it.

**`proc.stdout` only exists if you asked for it.** If you wrote `Bun.spawn([...])` without `stdout: "pipe"`, then `proc.stdout` is undefined. This catches people who assume Node's default-piping behavior.

**`proc.exited` is a promise, not a number.** Always `await proc.exited` to get the exit code. Reading it synchronously returns a Promise every time.

**Output can be buffered.** When a child prints to `stdout` that is piped back to the parent, the child's libc may buffer until it hits a newline or EOF. If you are watching for a specific line to appear before killing the child, add explicit flushing or force line-buffering in the child.

**Bun's `fetch` is a real fetch.** That includes surprising defaults — no automatic cookie jar, strict redirect policy, streaming response bodies. It is closer to browser fetch than to `axios`.

**`__dirname` and `__filename` work.** Unlike native ESM in Node (where you have to derive them from `import.meta.url`), Bun exposes them globally even in ESM mode. This is convenient but non-portable; if you care about running the same code in Node's ESM, use `import.meta.url` and `fileURLToPath`.

**`tsc --noEmit` catches what Bun does not.** Bun type-strips. It will run code that has type errors as long as the JS is valid. The `typecheck` script exists for a reason. If your CI does not run it, broken types leak into main.

**Module caching per process.** Tests in the same file share module state. If module-level mutable state bleeds between tests, you get flaky behavior. Prefer constructor-injected state (the `BridgeDatabase` and `Dispatcher` classes follow this pattern — each test makes its own instance in a temp dir).

## 7. Exercises

Do these in a scratch directory, not in the repo. They take five minutes each.

**Exercise 1: spawn and capture.** Write `spawn-ls.ts` that runs `ls -la /tmp` via `Bun.spawn`, captures stdout, and prints the first three lines.

```ts
// scratch/spawn-ls.ts
const proc = Bun.spawn(["ls", "-la", "/tmp"], { stdout: "pipe" });
const text = await new Response(proc.stdout).text();
await proc.exited;
// TODO: print the first 3 lines
```

Fill in the TODO. Run with `bun run spawn-ls.ts`. If it prints six lines, you forgot to slice.

**Exercise 2: in-memory SQLite.** Write a script that opens `":memory:"`, creates a `notes(id, body)` table, inserts two rows, and prints them.

```ts
import { Database } from "bun:sqlite";
const db = new Database(":memory:");
// TODO: create the table, insert 2 rows, select all, console.log
```

When it works, change the connection string from `":memory:"` to `"./notes.db"`, rerun, and observe that the second run prints four rows. That is persistence.

**Exercise 3: test filter.** Create `math.test.ts`:

```ts
import { test, expect } from "bun:test";

test("adds", () => expect(1 + 1).toBe(2));
test("subtracts", () => expect(2 - 1).toBe(1));
test("multiplies", () => expect(2 * 2).toBe(5)); // intentionally wrong
```

Run `bun test math.test.ts` — three tests, one fails. Now run `bun test -t "adds"` and confirm only the passing test runs. Fix the failing test (change `5` to `4`), run the full file again, watch all three pass. You have just used the `-t` filter and the red-green flow.

## 8. Further reading

Canonical Bun docs. Bookmark these.

- https://bun.sh/docs — top-level documentation index.
- https://bun.sh/docs/api/spawn — `Bun.spawn`, stdio options, signals.
- https://bun.sh/docs/api/sqlite — `bun:sqlite`, prepared statements, transactions.
- https://bun.sh/docs/cli/test — test runner, matchers, filters, watch mode.
- https://bun.sh/docs/runtime/typescript — how Bun handles TypeScript at runtime.

For the specifics of how claude-bridge uses these APIs — the exact subprocess layout for dispatch, the database schema and migrations, the daemon lifecycle — look in `docs/specs/`. This doc is about understanding the tool. The specs are about understanding the system.

Once you are comfortable here, the next layer up is the project's architecture: read `docs/ARCHITECTURE.md`, then pick a feature wave in `tests/` and trace one test through the code it exercises. That is the fastest way to get maintainer-fluent.
