# 08 — Zod: schema-first validation for TypeScript

Audience: a TS developer who has written `if (typeof x !== 'string') throw ...` by hand, and maybe touched Joi or Yup once. After this chapter you should understand why validation belongs at system boundaries, how to build and compose zod schemas, the difference between `parse` and `safeParse`, and be able to read zod usages in claude-bridge (and its dependencies) without flinching.

This is a learning doc, not a reference. For the API surface go to <https://zod.dev>.

---

## 1. Why schema validation at boundaries

Your TypeScript types are a compile-time fiction. The compiler erases them; at runtime nothing stops a `string` slot from holding a number, `null`, or the literal string `"[object Object]"`. That fiction is fine for data that was born inside your program — variables you assigned, functions you called. It is not fine for anything that crossed a boundary:

- JSON parsed from a file or HTTP body
- `process.env` variables
- CLI args (`process.argv`)
- stdin to a hook callback
- IPC messages from a child process
- rows pulled from a SQLite database whose schema drifted
- anything a user typed

Consider a function written the naive way:

```ts
function greet(user: { name: string; age: number }) {
  return `Hello ${user.name}, age ${user.age + 1}`;
}

// Somewhere at a boundary:
const raw = JSON.parse(stdinText); // typed as `any`
greet(raw);                         // compiler happy, runtime roulette
```

If stdin contained `{"name": 42, "age": "old"}`, the compiler never warned you. `user.name` prints `42`, `user.age + 1` silently becomes the string `"old1"`, and the bug surfaces three functions later. The type annotation `{ name: string; age: number }` was a lie the moment data crossed into your process.

Zod closes that gap. A zod schema is a value you can call `.parse(unknown)` on at runtime, and the *same* value also produces a static TS type via `z.infer`. One source of truth, validated at the boundary, typed everywhere inside.

```ts
import { z } from "zod";

const UserSchema = z.object({
  name: z.string(),
  age: z.number().int().nonnegative(),
});
type User = z.infer<typeof UserSchema>; // { name: string; age: number }

const raw: unknown = JSON.parse(stdinText);
const user = UserSchema.parse(raw); // throws if raw is wrong
// from here on `user` is a real User, both at runtime and to the compiler.
```

The mental model: **validate once at the edge, trust types inside.** Every internal function accepts `User`, not `unknown`. The moment data re-enters from a new boundary (new file, new socket), re-validate.

---

## 2. Zod in one minute

Four things to know before you read any zod code:

1. **A schema is a value.** `z.string()` is an object, not a type. You pass it around, compose it, and call methods on it.
2. **`parse(unknown)` returns the typed value or throws `ZodError`.** Use this when the caller can genuinely not continue on failure (a startup config that must be valid).
3. **`safeParse(unknown)` returns a discriminated union**: `{ success: true; data: T }` or `{ success: false; error: ZodError }`. Use this when you want to produce a friendly error instead of a stack trace — which is almost always.
4. **`z.infer<typeof Schema>` extracts the TS type for free.** No hand-written `interface User { ... }` that can drift.

```ts
const s = z.string();
s.parse("hi");         // "hi"
s.parse(42);           // throws ZodError
s.safeParse(42);       // { success: false, error: ZodError }
type T = z.infer<typeof s>; // string
```

That is 90% of what you need. Everything below is vocabulary for building more precise schemas.

---

## 3. Primitives

Each constructor returns a schema you can chain methods on.

```ts
z.string();                        // any string
z.string().min(1).max(64);         // length bounds
z.string().email();                // format check
z.string().regex(/^[a-z-]+$/);     // custom regex
z.string().uuid();

z.number();                        // any finite number
z.number().int();                  // integer only
z.number().positive();             // > 0
z.number().min(0).max(100);

z.boolean();
z.null();                          // matches exactly null
z.undefined();                     // matches exactly undefined
z.any();                           // escape hatch, avoid
z.unknown();                       // prefer over any

z.literal("pending");              // matches exactly the string "pending"
z.literal(42);
z.literal(true);

z.enum(["pending", "running", "done"]);
// inferred type: "pending" | "running" | "done"

enum Priority { Low, Medium, High }
z.nativeEnum(Priority);            // for TS numeric or string enums
```

A literal schema plus a union is how you build tagged states (section 4). `z.enum(["a","b","c"])` is the shorthand for `z.union([z.literal("a"), z.literal("b"), z.literal("c")])`.

---

## 4. Composites

This is where schemas stop being toys and start modelling real data.

### `z.object`

```ts
const Task = z.object({
  id: z.string().uuid(),
  title: z.string().min(1),
  durationMs: z.number().int().nonnegative(),
});
// inferred: { id: string; title: string; durationMs: number }
```

By default zod objects **ignore unknown keys** — they pass validation but are stripped from the output. Use `.strict()` to reject them, `.passthrough()` to keep them. More in section 10.

### `z.array`

```ts
const Tasks = z.array(Task);              // Task[]
z.array(z.string()).min(1).max(10);       // 1–10 strings
```

### `z.tuple`

Fixed-length, heterogeneous. Use when order matters and length is known.

```ts
const Point = z.tuple([z.number(), z.number()]);  // [number, number]
```

### `z.record`

Objects used as maps with unknown keys.

```ts
z.record(z.string());                  // { [k: string]: string }
z.record(z.string(), z.number());      // { [k: string]: number }, explicit key
```

Use `z.object` when keys are known in advance; `z.record` when the keys are data (e.g., a map from user id to user).

### `z.union`

```ts
const StrOrNum = z.union([z.string(), z.number()]);
// equivalent shorthand:
const StrOrNum2 = z.string().or(z.number());
```

### `z.intersection`

Both at once. Rarely needed with objects (prefer `.extend`), occasionally useful for cross-type constraints.

```ts
const HasId = z.object({ id: z.string() });
const HasName = z.object({ name: z.string() });
const Both = z.intersection(HasId, HasName);  // { id: string; name: string }
```

### `z.discriminatedUnion` — the important one

When your data is a tagged state machine — a field like `type`, `status`, or `kind` decides the shape of the rest — use `discriminatedUnion`. It is faster than `z.union` (zod reads the tag and jumps straight to the right branch) and produces much better error messages (it blames the failing branch, not "none of the union members matched").

```ts
const Event = z.discriminatedUnion("type", [
  z.object({ type: z.literal("click"), x: z.number(), y: z.number() }),
  z.object({ type: z.literal("key"),   key: z.string() }),
  z.object({ type: z.literal("scroll"), delta: z.number() }),
]);

type Event = z.infer<typeof Event>;
// { type: "click"; x: number; y: number }
// | { type: "key"; key: string }
// | { type: "scroll"; delta: number }

Event.parse({ type: "click", x: 10, y: 20 }); // ok
Event.parse({ type: "key", key: "Enter" });   // ok
Event.parse({ type: "boom" });                 // clear error on the tag
```

If your dispatcher stores task state as `{ status: "pending" | "running" | "done", ... }` and each status has different fields, this is the schema you want. It mirrors the `switch (event.type)` narrowing you already write by hand.

**Picking which composite**: object for records with known fields; array/tuple for ordered collections; record for maps with dynamic keys; discriminatedUnion for tagged variants; union only when there's no tag to discriminate on; intersection almost never.

---

## 5. Modifiers

Chainable methods that refine or transform a schema.

```ts
z.string().optional();   // string | undefined
z.string().nullable();   // string | null
z.string().nullish();    // string | null | undefined

z.string().default("anon");
// input may be undefined, output is always string

z.number().catch(0);
// on any parse failure, yield 0 instead of throwing
```

### `.refine` — custom predicates

```ts
const Password = z.string().refine(
  (s) => s.length >= 8 && /[0-9]/.test(s),
  { message: "password must be 8+ chars and contain a digit" },
);
```

Multiple `.refine` calls stack. For cross-field validation on objects use `.superRefine` which gets a `ctx` to attach issues to specific paths.

### `.transform` — reshape the output

Schemas have two sides: input (what you feed `.parse`) and output (what you get back). `.transform` changes the output.

```ts
const Trimmed = z.string().transform((s) => s.trim());
Trimmed.parse("  hi  ");  // "hi"
```

### `.pipe` — transform then validate again

```ts
const NumericString = z.string()
  .transform((s) => Number(s))
  .pipe(z.number().int().nonnegative());

NumericString.parse("42");  // 42 (number)
NumericString.parse("abc"); // fails the second validation
```

`.pipe` is how you validate the *output* of a transform. The combination `z.string().transform(JSON.parse).pipe(MySchema)` is the canonical "parse JSON and validate" trick (section 8).

---

## 6. Type inference: `z.infer`, `z.input`, `z.output`

```ts
const WithDefault = z.object({
  name: z.string(),
  retries: z.number().default(3),
});

type In  = z.input<typeof WithDefault>;
//  { name: string; retries?: number }   — retries may be omitted
type Out = z.output<typeof WithDefault>;
//  { name: string; retries: number }    — retries always present
type T   = z.infer<typeof WithDefault>;  // alias for z.output
```

When a schema has `.default`, `.transform`, or `.pipe`, input and output differ. Most callers want `z.infer` (= output). If you are writing code that *constructs* values before parsing (e.g., a factory) you want `z.input`.

---

## 7. Error handling

A `ZodError` has an `issues` array. Each issue has `path` (array of keys/indices pointing at the bad field), `message`, and `code` (machine-readable).

```ts
const User = z.object({
  name: z.string(),
  age: z.number().int().nonnegative(),
});

const result = User.safeParse({ name: 42, age: -1 });
if (!result.success) {
  for (const issue of result.error.issues) {
    console.error(issue.path.join("."), issue.code, issue.message);
  }
  // name  invalid_type    Expected string, received number
  // age   too_small       Number must be greater than or equal to 0
}
```

Two formatting helpers:

- `error.flatten()` — returns `{ formErrors: string[]; fieldErrors: Record<string, string[]> }`. Great for flat forms and one-liner error messages.
- `error.format()` — returns a nested object mirroring the schema. Great for deep data.

**Prefer `safeParse` at boundaries.** A thrown `ZodError` inside a CLI handler turns into an unhelpful stack trace. Catch it, format it, and return exit code 1 with a readable message. Use `parse` only when you are ready to let the program crash (e.g., an invalid config file at startup is fatal, by design).

```ts
const r = ConfigSchema.safeParse(readJson(path));
if (!r.success) {
  console.error("invalid config:", r.error.flatten().fieldErrors);
  process.exit(1);
}
const config = r.data;
```

---

## 8. Practical patterns

### Validating `process.env` at startup

Environment variables arrive as strings or `undefined`. Validate and coerce at boot so downstream code sees typed values.

```ts
const EnvSchema = z.object({
  DATABASE_URL: z.string().url(),
  LOG_LEVEL:    z.enum(["debug", "info", "warn", "error"]).default("info"),
  PORT:         z.string().regex(/^\d+$/).transform(Number).default("3000"),
});
export const env = EnvSchema.parse(process.env);
// env.PORT is number, env.LOG_LEVEL is a union literal, DATABASE_URL is validated.
```

Crash early. An invalid env is never a warning; it is a configuration bug.

### Parse JSON and validate in one step

```ts
const StopHookPayload = z.object({
  session_id: z.string(),
  stop_hook_active: z.boolean(),
  transcript_path: z.string(),
});

const Parsed = z.string()
  .transform((s, ctx) => {
    try { return JSON.parse(s); }
    catch (e) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "invalid JSON" });
      return z.NEVER;
    }
  })
  .pipe(StopHookPayload);

const payload = Parsed.parse(stdinText);
```

Using `ctx.addIssue` inside the transform keeps JSON-parse failures inside the normal zod error pipeline.

### Zod as a JSON Schema source

MCP tool definitions want raw JSON Schema (`{ type: "object", properties: { ... } }`), not zod schemas. If you already have a zod schema you can convert it with `zod-to-json-schema` — or, for a handful of tools, just hand-write both. In claude-bridge the MCP tool inputs are hand-written JSON Schema (see `src/mcp/tools.ts`), which is fine at this scale.

### A `Result<T, ZodError>` helper

If you dislike the union shape, wrap it:

```ts
type Result<T> = { ok: true; value: T } | { ok: false; error: z.ZodError };

export function decode<T>(schema: z.ZodType<T>, input: unknown): Result<T> {
  const r = schema.safeParse(input);
  return r.success ? { ok: true, value: r.data } : { ok: false, error: r.error };
}
```

---

## 9. How claude-bridge uses zod

Zod is declared as a direct dependency (`zod ^3.23.0` in `package.json`). Most current usage is transitive through the MCP SDK (`@modelcontextprotocol/sdk` uses zod internally for request/response schemas). The places you will likely reach for zod as a maintainer:

- **MCP tool argument validation** — `src/mcp/tool-handlers.ts` receives `arguments` as `unknown` from the SDK. The handlers currently do ad-hoc checks; adding zod schemas per tool is a natural cleanup. Tool descriptions live in `src/mcp/tools.ts` as hand-written JSON Schema.
- **Stop hook payload parsing** — `src/execution/on-complete.ts` reads JSON from stdin. Anything that calls `JSON.parse` on input Claude Code sent you is a boundary worth validating.
- **Config files on disk** — the setup-bot flow writes a `config.json` under `~/.claude-bridge` (see `src/infra/bridge-cmd.ts` and `src/config.ts`). Reading it back should validate the shape, because users will hand-edit it and typos will happen.

For the architectural "what crosses which boundary" view, see `docs/specs/`.

---

## 10. Pitfalls

- **Parse throws.** Wrap `parse` in try/catch or use `safeParse`. A missed throw becomes a 500.
- **Objects are lax by default.** `z.object({ a: z.string() }).parse({ a: "x", b: 1 })` succeeds and strips `b`. If you need to reject unknown keys (e.g., config files where typos should surface), call `.strict()`. If you need to *keep* them (e.g., pass-through metadata), call `.passthrough()`.
- **Recursive schemas need `z.lazy`.** You cannot reference a schema before it is defined, so wrap it:
  ```ts
  type Tree = { value: number; children: Tree[] };
  const Tree: z.ZodType<Tree> = z.lazy(() =>
    z.object({ value: z.number(), children: z.array(Tree) }),
  );
  ```
  The explicit type annotation is required because TypeScript cannot infer through `z.lazy`.
- **Parsing is not free.** For hot paths with data you produced yourself, skip validation. The rule stays: **validate at boundaries, trust inside.** Do not sprinkle `.parse` on every function call — that is defensive programming, not safety.
- **Error messages default to English, technical.** For user-facing errors provide `{ message: "..." }` on constraints, or pass a custom `errorMap`.
- **Zod 3 vs 4.** Claude-bridge is on zod 3 (see `package.json`). Zod 4 is newer, faster, and has a slightly different API in places (e.g., error formatting). Pin and check the docs matching your version. <https://zod.dev> currently covers zod 3; zod 4 docs are on the same site but flagged.

---

## 11. Exercises

Do these in a scratch file (`bun run scratch.ts`). Each is self-contained.

### Exercise 1 — Task payload with safeParse

Write a schema for:

```ts
type Task = {
  id: string;
  status: "pending" | "running" | "done";
  durationMs?: number;
};
```

Then parse one valid and one invalid payload, and handle both outcomes with `safeParse`. Do not use `parse`. Print the `path` and `message` for each issue in the failing case.

Hint: `z.enum` for `status`, `.optional()` for `durationMs`, `.min(0)` and `.int()` to keep it sane.

### Exercise 2 — envSchema

Write an `envSchema` that:

- requires `DATABASE_URL` to be a valid URL
- requires `PORT` which arrives as a string but must coerce to an integer in `[1, 65535]`
- allows optional `LOG_LEVEL` from `{"debug", "info", "warn", "error"}`, defaulting to `"info"`

Call it at startup against `process.env`. On failure, print `error.flatten().fieldErrors` and call `process.exit(1)`. Verify the exported `env` object has `env.PORT: number`, not string.

### Exercise 3 — Discriminated union for an event stream

Model:

```ts
type Event =
  | { type: "click"; x: number; y: number }
  | { type: "key";   key: string };
```

Build it with `z.discriminatedUnion("type", [...])`. Then parse this input and log each event with a `switch (event.type)` — notice how TypeScript narrows inside each `case`:

```ts
const input: unknown[] = [
  { type: "click", x: 10, y: 20 },
  { type: "key", key: "Enter" },
  { type: "key" },             // invalid: missing key
  { type: "scroll", delta: 5 },// invalid: unknown tag
];
```

Count how many parsed and how many failed. Bonus: try the same with `z.union` instead and compare the error messages.

---

## 12. Further reading

- <https://zod.dev> — canonical docs, API reference, examples.
- <https://github.com/colinhacks/zod> — source, issues, changelog. Read the README once end-to-end; it is short.
- <https://zod.dev/ERROR_HANDLING> — deeper dive on `ZodError`, custom error maps, and formatting.

That is the full mental model. Validate at the edges, compose small schemas into bigger ones, reach for `discriminatedUnion` when your data has a tag, use `safeParse` unless you are happy to crash. Everything else is vocabulary.
