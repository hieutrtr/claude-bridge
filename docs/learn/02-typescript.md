# 02 — TypeScript in strict mode, as used in this project

Welcome. This guide assumes you already know JavaScript well and have written some TypeScript, but mostly the loose kind: `any` sprinkled around, types only where the IDE whined, a `// @ts-ignore` here and there. This project will push back on that style — by design. By the end of this guide you should be comfortable writing new modules that compile cleanly with `tsc --noEmit` on the first try.

We will not tour `src/` file by file. Instead we teach the language features the codebase uses, then point at representative examples.

---

## 1. Why TypeScript, and why strict mode

**Why TypeScript.** TypeScript is JavaScript with a static type system bolted on. At runtime it is just JavaScript — the types are erased by the compiler. What you gain is two things, neither of which is really about "catching bugs": (1) types are documentation that cannot go stale, because the compiler checks it; (2) refactoring is dramatically cheaper, because the compiler will list every caller you have to update. For a project like Claude Bridge, which is a long-lived daemon with a lot of moving parts (CLI, SQLite, subprocesses, MCP, Telegram), that refactor leverage is the main point. You will rename a field on `Task` and tsc will tell you every line that has to change.

**Why strict mode.** TypeScript's defaults are loose because the team wants migrating JS codebases to succeed. That is a reasonable default for adoption but a bad default for new code. Strict mode flips on all the checks that stop TypeScript from silently treating unknowns as `any`. The mental model is: "no escape hatches by default." If you want an escape hatch you have to write `as unknown as Foo` — ugly on purpose, so you notice. This project runs strict mode plus a few additional checks. Once you internalize them, writing code that passes is not much harder than writing code that fails, and the code that passes is dramatically safer.

---

## 2. The strict-mode flags that matter for this project

Open `tsconfig.json` at the repo root. Here is what is in `compilerOptions`, translated into plain language.

```json
{
  "target": "ESNext",
  "module": "ESNext",
  "moduleResolution": "bundler",
  "types": ["bun-types"],
  "strict": true,
  "esModuleInterop": true,
  "skipLibCheck": true,
  "forceConsistentCasingInFileNames": true,
  "noUncheckedIndexedAccess": true,
  "resolveJsonModule": true,
  "isolatedModules": true,
  "verbatimModuleSyntax": true
}
```

### `strict: true`

This is a meta-flag. It turns on a family of child flags. The ones you will feel are:

- **`noImplicitAny`** — if tsc cannot figure out a type, you must write one. No silent `any`.
- **`strictNullChecks`** — `null` and `undefined` are no longer assignable to every type. If a value can be missing, the type must say so (e.g. `string | null`).
- **`strictFunctionTypes`** — function parameter types are checked in the right (contravariant) direction. You will rarely notice this one directly.
- **`strictPropertyInitialization`** — class fields must be initialized in the constructor or declared `?`/`!`.
- **`alwaysStrict`** — emits `"use strict"` and parses in strict mode.
- **`strictBindCallApply`** — `.bind`, `.call`, `.apply` get real type-checking.
- **`noImplicitThis`** — `this` without a declared type is an error.
- **`useUnknownInCatchVariables`** — `catch (e)` gives you `unknown`, not `any`. You must narrow before using it.

The one that bites new contributors most is `strictNullChecks`. If the DB can return `null`, the type is `T | null` and the compiler will make you handle it. Look at `Agent` in `src/types.ts` — `purpose: string | null`, `last_task_at: string | null`. That is not decoration; the code must check both branches.

### `noUncheckedIndexedAccess: true`

This one is not part of `strict` but it matters a lot. Without it, `arr[0]` has type `T` even if the array is empty. With it, `arr[0]` has type `T | undefined`. Same for `record[key]` on a `Record<string, T>`.

```ts
const names: string[] = ["a", "b"];
const first = names[0];
// With noUncheckedIndexedAccess: first is `string | undefined`
// Without:                        first is `string`

if (first !== undefined) {
  first.toUpperCase(); // ok, narrowed to string
}
```

Why it is on: empty arrays and missing keys are real at runtime, and the compiler lying about it leads to the exact kind of "why is this undefined?" bugs TypeScript is supposed to prevent.

### `verbatimModuleSyntax: true`

This flag makes TypeScript preserve imports exactly as you wrote them, instead of rewriting them. The practical consequence: if you import something that is only a type (an `interface`, a `type` alias, a type-only re-export), you must write `import type`:

```ts
import type { Agent, Task } from "../types.js";
import { AgentDB } from "../data/db.js";   // a class, used at runtime
```

You will see this pattern everywhere in `src/`. Mixing the two is fine as long as the types are prefixed:

```ts
import { AgentDB, type Agent } from "../data/db.js";
```

Why it is on: it keeps compiled output predictable, and it makes dead type-only imports impossible to miss at review time.

### `moduleResolution: "bundler"`

This tells TypeScript to resolve imports the way a bundler (or Bun) would, rather than emulating Node's historical CommonJS rules. Consequences worth knowing:

- You can import from `"zod"` without `/index.js` nonsense.
- You do not need `.js` extensions for Node's sake — but this project uses them anyway (see next section).
- `package.json` `"exports"` fields are honored.

### The `.js` import suffix convention

This is the single weirdest thing about modern TypeScript + ESM, and this project uses it everywhere:

```ts
import type { Agent } from "../types.js";          // file is types.ts!
import { AgentDB } from "../data/db.js";           // file is db.ts!
```

You are importing `.ts` files but writing `.js` in the import specifier. Why:

1. This project is ESM (`"type": "module"` in `package.json`, `module: "ESNext"` in tsconfig).
2. The Node/ESM spec requires file extensions in import paths.
3. When TypeScript compiles `.ts` to `.js`, the import specifier is **not rewritten**. What you wrote is what ships.
4. So: to make the compiled output correct, the source must say `.js` even though the file on disk is `.ts`.

Bun can run the source directly and it resolves `./foo.js` to `./foo.ts` transparently. The rule is: **always write `.js` in relative imports of project files.** Omit the extension for `node_modules` packages (`"zod"`, not `"zod/index.js"`).

### `isolatedModules: true`

Every file must be compilable on its own, without looking at other files. This rules out some cross-file type shenanigans and makes the codebase friendly to fast transpilers (Bun, esbuild, swc). You will rarely bump into this; when you do, the fix is usually to `export type` instead of `export`.

### `esModuleInterop` and `skipLibCheck`

Quality-of-life flags. `esModuleInterop` lets you write `import fs from "fs"` even when the module doesn't have a real default export. `skipLibCheck` tells tsc not to type-check `.d.ts` files from your dependencies, which makes compilation much faster at the cost of trusting that `@types/*` packages are internally consistent.

### `forceConsistentCasingInFileNames`

`./Foo.ts` and `./foo.ts` are the same file on macOS (case-insensitive filesystem) but different on Linux (CI). This flag makes tsc treat them as different, so you don't ship something that breaks on CI. Just match the case of the file on disk.

---

## 3. TypeScript features this codebase uses heavily

Short tutorials. Each one teaches the concept, shows a tiny abstract example, and points at where you will find it in `src/`.

### `interface` vs `type`

Both declare a named shape. The rules-of-thumb this project follows:

- **`interface`** for object shapes that might be implemented by classes or extended by other shapes. See `IDatabase`, `ISessionManager`, `IScheduler` in `src/data/interfaces.ts` and `src/orchestration/interfaces.ts` — the `I`-prefix convention marks them as "implementable."
- **`type`** for unions, primitives-with-meaning, tuples, and anything that isn't a plain object. See `TaskStatus`, `LoopStatus`, `AgentState` in `src/types.ts`.
- **`interface`** for plain data records that describe rows (`Agent`, `Task`, `Loop`). You could use `type` — it is a stylistic choice.

```ts
interface User {
  id: number;
  name: string;
}

type Status = "idle" | "running" | "done";
type Pair<A, B> = [A, B];
```

A property of interfaces: they can be re-declared to add fields (declaration merging). `type` aliases cannot. This is mostly only useful for augmenting library types; don't do it by accident.

### Discriminated unions (tagged unions)

This is the single most important TypeScript pattern you don't already know from JavaScript. A discriminated union is a union of object types that share a field (the "tag" or "discriminant") with a literal type. The compiler uses that field to figure out which variant you have.

```ts
type Result<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

function double(n: number): Result<number> {
  if (Number.isNaN(n)) return { ok: false, error: "NaN" };
  return { ok: true, value: n * 2 };
}

const r = double(4);
if (r.ok) {
  // r is { ok: true; value: number } here
  console.log(r.value * 10);
} else {
  // r is { ok: false; error: string } here
  console.error(r.error);
}
```

The magic is in the `if (r.ok)`. TypeScript looks at the literal type `true` and narrows `r` to the matching variant. You get `r.value` without casts.

In this codebase, look at `DoneCondition` in `src/orchestration/interfaces.ts` — its `type` field is a literal union (`"command" | "file_exists" | ...`) that callers switch on. Look at `atomicCheckAndCreateTask` in `src/data/interfaces.ts`, whose return includes an `isBusy: boolean` discriminant.

### Generics (light)

Generics are type parameters. You have seen them used — `Array<T>`, `Promise<T>` — now you can write them.

```ts
function first<T>(items: T[]): T | undefined {
  return items[0];
}

const n = first([1, 2, 3]);       // number | undefined
const s = first(["a", "b"]);      // string | undefined
```

The `<T>` is a placeholder that the compiler fills in at each call site. Constrain it when you need to:

```ts
function byId<T extends { id: number }>(xs: T[], id: number): T | undefined {
  return xs.find((x) => x.id === id);
}
```

You will see generics most often in database / collection-shaped helpers. You rarely need to reach for advanced generic tricks (conditional types, mapped types) in day-to-day work here.

### `readonly` and `as const`

`readonly` marks a property as not reassignable. Useful on interfaces that represent "frozen-ish" config:

```ts
interface IConfigProvider {
  readonly homeDir: string;
  readonly dbPath: string;
  load(): BridgeConfig;
}
```

You can see this exact shape at the bottom of `src/data/interfaces.ts`.

`as const` is the runtime equivalent: it tells TypeScript that a literal is, well, literal. Without it, the compiler widens types.

```ts
const DEFAULT = { model: "sonnet", retries: 3 };
// type: { model: string; retries: number }

const DEFAULT2 = { model: "sonnet", retries: 3 } as const;
// type: { readonly model: "sonnet"; readonly retries: 3 }
```

Use `as const` for lookup tables, fixed option lists, and anywhere you want the literal values preserved in the type.

### Utility types: `Partial`, `Pick`, `Omit`, `Record`

Four you will use all the time:

```ts
interface Task {
  id: number;
  status: "pending" | "running" | "done";
  prompt: string;
  model: string | null;
}

type TaskUpdate = Partial<Task>;
// { id?: number; status?: ...; prompt?: string; model?: string | null }

type TaskSummary = Pick<Task, "id" | "status">;
// { id: number; status: ... }

type TaskDraft = Omit<Task, "id">;
// everything except id

type StatusLabels = Record<Task["status"], string>;
// { pending: string; running: string; done: string }
```

`Partial<Task>` is used directly in `IDatabase.updateTask(id: number, updates: Partial<Task>): void` — the caller passes only the fields they want to change. `Record<K, V>` is the right type for "a dict-like object from K to V."

### Narrowing: `in`, `typeof`, `instanceof`, and user-defined type guards

Narrowing is how you tell the compiler "inside this branch the type is more specific than you thought."

```ts
function greet(x: string | string[]) {
  if (typeof x === "string") {
    // x is string
    return x.toUpperCase();
  }
  // x is string[]
  return x.join(", ");
}

function area(s: { kind: "circle"; r: number } | { kind: "square"; side: number }) {
  if ("r" in s) return Math.PI * s.r ** 2;   // narrowed by `in`
  return s.side ** 2;
}

function fromError(e: unknown) {
  if (e instanceof Error) return e.message;  // narrowed by `instanceof`
  return String(e);
}
```

When the built-in narrowings aren't expressive enough, write a **user-defined type guard**. The return type `x is Foo` is a special predicate signature:

```ts
interface Agent { name: string; kind: "agent"; }
interface Team  { name: string; kind: "team"; members: string[]; }

function isTeam(x: Agent | Team): x is Team {
  return x.kind === "team";
}

function describe(x: Agent | Team) {
  if (isTeam(x)) {
    return `team of ${x.members.length}`; // x narrowed to Team
  }
  return `agent ${x.name}`;               // x narrowed to Agent
}
```

Type guards are the clean way to factor narrowing out of the call site. You'll see them used to validate data coming back from SQLite rows and from `JSON.parse`.

### `never` and exhaustiveness checks

`never` is the type with zero values. You rarely write it as an annotation — instead you use it to prove to the compiler that you have handled every case of a union. This catches bugs when someone adds a new variant and forgets to update a switch.

```ts
type TaskStatus = "pending" | "running" | "done" | "failed";

function label(s: TaskStatus): string {
  switch (s) {
    case "pending": return "...";
    case "running": return "...";
    case "done":    return "ok";
    case "failed":  return "err";
    default: {
      const _exhaustive: never = s;
      throw new Error(`unhandled: ${_exhaustive}`);
    }
  }
}
```

If you later add `"cancelled"` to `TaskStatus`, the `default` branch stops compiling because `s` is no longer `never` there. That is the compiler protecting you. Use this pattern whenever you switch on one of the string-literal unions in `src/types.ts` (`TaskStatus`, `LoopStatus`, `AgentState`, `MessageStatus`, `PermissionStatus`, `NotificationStatus`).

---

## 4. Common strict-mode pain points and how to fix them properly

Strict mode occasionally flags code that "looks fine." The right answer is almost never `as any` or `// @ts-ignore`. Here are the usual suspects.

### "Object is possibly 'undefined'" from `noUncheckedIndexedAccess`

```ts
const rows = db.query("...").all() as Task[];
const first = rows[0];
console.log(first.prompt); // error: first is Task | undefined
```

Fixes, in order of preference:

1. **Check explicitly.** `if (first === undefined) return null;`
2. **Destructure with a default.** `const [first = null] = rows;`
3. **Use `.at()` with an explicit narrow.** `const first = rows.at(0); if (!first) ...`
4. **Assert non-null with `!` only when you have just proven it.** `if (rows.length === 0) throw ...; const first = rows[0]!;`

Never reach for `as Task` — you are lying to the compiler about something the compiler is right about.

### "This expression is not callable" from union types

```ts
type Reader = (() => string) | string;

function read(r: Reader) {
  return r(); // error: r might be a string
}
```

Narrow first:

```ts
function read(r: Reader) {
  return typeof r === "function" ? r() : r;
}
```

The same thing happens with unions of objects that have same-named methods with different signatures. Narrow by a discriminant.

### Async return type inference

`async function` always returns a `Promise<T>`. If your function has multiple return paths, TS infers the union.

```ts
async function find(id: number) {
  const row = await db.get(id);
  if (!row) return null;
  return row;
}
// return type: Promise<Row | null>
```

When the inferred union gets weird, write the return type explicitly. All the `I*` interfaces in `src/data/interfaces.ts` and `src/orchestration/interfaces.ts` spell out async return types — follow that style in implementations.

### Narrowing lost after a method call

```ts
interface Box { item?: string }
function take(b: Box) {
  if (b.item !== undefined) {
    doSomethingAsync().then(() => {
      b.item.toUpperCase(); // error: narrowing lost across callback
    });
  }
}
```

The compiler is correct: another function could have mutated `b.item` to `undefined` before the callback runs. Fix it by capturing the narrowed value:

```ts
if (b.item !== undefined) {
  const item = b.item;
  doSomethingAsync().then(() => item.toUpperCase());
}
```

### The `catch` variable is `unknown`

With `useUnknownInCatchVariables` (on via `strict`), this fails:

```ts
try { ... } catch (e) { console.error(e.message); }
// error: e is unknown
```

Narrow it:

```ts
try { ... } catch (e) {
  const msg = e instanceof Error ? e.message : String(e);
  console.error(msg);
}
```

---

## 5. Project conventions

A short checklist beyond the language features.

- **Import `.js`, not `.ts`, for project files.** Explained in section 2. Scan `src/data/interfaces.ts` to see the pattern.
- **`import type` for type-only imports.** Required by `verbatimModuleSyntax`. If you see `import type { Agent, Task } from "../types.js";` — match that style.
- **Interfaces for services, named `IThing`.** `IDatabase`, `IMessageDatabase`, `ISessionManager`, `ILoopOrchestrator`, `IScheduler`. Implementations drop the `I`: `Database`, `SessionManager`, etc.
- **All shared data types live in `src/types.ts`.** Row shapes, status unions, config. If you are adding a new concept, add its type here and import from here. Do not redefine it ad-hoc in a module.
- **stderr vs stdout.** Error messages go to `process.stderr` (or `console.error`). Normal output goes to `stdout` (`console.log`). CLI commands exit 0 on success, non-zero on error. This is a `CLAUDE.md` rule; the type system won't enforce it but reviewers will.
- **Errors as classes when they matter.** For flow-control errors (not found, validation), throw a typed `Error` subclass and narrow with `instanceof`. For "expected absence," return `null` or a `Result<T>`-shaped discriminated union — look at `atomicCheckAndCreateTask`'s return shape for an example.
- **Validate at the boundary with zod.** Anything coming from outside the process — JSON files, HTTP/MCP payloads, subprocess stdout — should pass through a zod schema before it becomes a typed object. That converts runtime uncertainty into compile-time certainty. See `08-zod.md` in this series for the full treatment; for now, the rule is: do not `as Foo` external data.
- **No `any`, no `@ts-ignore`.** If you need an escape hatch, use `unknown` and narrow, or use `as unknown as Foo` so the ugliness is visible in review. `@ts-expect-error` with a comment explaining why is acceptable in tests.

---

## 6. The typecheck loop

```bash
bun run typecheck    # runs tsc --noEmit
# or equivalently
tsc --noEmit
```

`--noEmit` means "check the types but don't produce output files." Bun runs the actual code; tsc is only there as the checker.

**When to run it.**

- Before every commit. The project's convention is "typecheck, then test, then commit." A failing typecheck blocks the pipeline.
- After renaming a type or changing an interface — that is where tsc pays off most. It will list every caller that needs to change.
- Any time you pull `main`.

**Editor integration.**

- VS Code and Cursor both ship a TypeScript language service. It runs tsc incrementally in the background and shows errors inline. Prefer the workspace version of TypeScript (the one in `node_modules`), not the bundled one — otherwise a TS version bump in `package.json` won't show up in the editor. In VS Code: Command Palette → "TypeScript: Select TypeScript Version" → "Use Workspace Version."
- If the editor shows an error that `bun run typecheck` does not (or vice versa), restart the TS server: Command Palette → "TypeScript: Restart TS Server."

**Speed.** `skipLibCheck` is on, so full typecheck of the project should finish in a second or two. If it ever gets slow, the likely cause is that someone introduced a deep conditional type somewhere; look at recent changes.

---

## 7. Exercises

Create a scratch file (e.g. `/tmp/scratch.ts`) and run `bun run /tmp/scratch.ts` to execute. Or paste into the TypeScript playground at <https://www.typescriptlang.org/play>.

### Exercise 1 — Result type

Write a `Result<T, E = string>` discriminated union. Then write `parseIntSafe(s: string): Result<number>` that returns `{ ok: true, value: n }` on success and `{ ok: false, error: "..." }` on failure. Call it and handle both branches with narrowing (no casts).

### Exercise 2 — Task state machine with exhaustive switch

Write `type TaskState = "pending" | "running" | "done" | "failed"`. Write `function nextLabel(s: TaskState): string` that returns a user-facing label via a `switch`. Add a `default` branch that assigns to a `const _: never = s;`. Now add `"cancelled"` to `TaskState` and watch the compiler point at your switch. Fix the switch.

### Exercise 3 — Fix a `noUncheckedIndexedAccess` failure properly

Start with this broken function:

```ts
function firstWord(line: string): string {
  const parts = line.split(" ");
  return parts[0].toLowerCase(); // error under noUncheckedIndexedAccess
}
```

Fix it three different ways: (a) explicit `if` check that returns a default, (b) destructure with a default, (c) a guard that throws. Do not use `!` or `as string`.

---

## 8. Further reading

Canonical docs only; everything else is second-hand.

- <https://www.typescriptlang.org/docs/handbook/intro.html> — the Handbook, start here.
- <https://www.typescriptlang.org/tsconfig> — every compiler option, with examples. Bookmark this.
- <https://www.typescriptlang.org/docs/handbook/2/everyday-types.html> — a tour of the types you will use daily.
- <https://www.typescriptlang.org/docs/handbook/2/narrowing.html> — narrowing, type guards, and exhaustiveness, in depth.
- <https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-0.html> — TS 5.0 release notes; useful for understanding recent features like `const` type parameters and the modern module resolution story.
