# 04 — The Model Context Protocol (MCP)

This is a **learning** guide. By the end you should be able to:

1. Explain what MCP is and why it exists.
2. Read a JSON-RPC exchange between an MCP client and server and follow what is happening.
3. Name the three primitives MCP defines (tools, resources, prompts) and give an example of each.
4. Write a minimal working MCP server in TypeScript from a blank folder.
5. Look at `src/mcp/server.ts` in claude-bridge and understand every line of it.

If you are only looking for a map of the bridge's MCP surface — which tools it exposes and where their handlers live — that is the job of the spec doc at `docs/specs/04-mcp-and-channels.md`. This guide teaches the protocol itself.

---

## 1. What MCP is

The **Model Context Protocol** is an open specification, originally published by Anthropic in late 2024, that standardises how a large language model (LLM) application talks to external **tools**, **data sources**, and **prompt templates**.

The pitch is "USB for LLM context." Before MCP, every LLM product invented its own function-calling plumbing: OpenAI had one JSON shape, Anthropic had another, custom agent frameworks each rolled their own glue. If you wanted Claude Desktop to talk to GitHub, and ChatGPT to also talk to GitHub, you wrote the integration twice, in two languages, against two different runtimes.

MCP flips that around. You write **one** server that exposes tools in a protocol-defined shape, and **any** MCP-aware client can connect to it. Today that list includes Claude Desktop, Claude Code, Cursor, Zed, and a growing handful of IDE plugins and agent frameworks.

A few facts about the spec that matter for this guide:

- **It is JSON-RPC 2.0**, extended with a small set of MCP-specific method names (`initialize`, `tools/list`, `tools/call`, etc.) and notifications.
- **It is transport-agnostic.** The spec defines how messages are framed once you have a stream; it does not mandate a particular stream. In practice three transports exist:
  - **stdio** — the server is a child process; you write JSON-RPC over its stdin and read from its stdout.
  - **HTTP + SSE** — long-running HTTP connection with Server-Sent Events for the server → client direction.
  - **Streamable HTTP** — a newer single-endpoint HTTP transport.
- **stdio is the common case**, especially for local developer tooling like Claude Code. That is the only transport claude-bridge uses, and the only one this guide will teach in depth.
- **It is stateful.** A client opens a session, performs an `initialize` handshake, and then freely calls methods until the process exits. There is no request-per-HTTP-request fiction.

The spec lives at <https://modelcontextprotocol.io>. The reference TypeScript SDK lives at <https://github.com/modelcontextprotocol/typescript-sdk>. Those are the two URLs to keep open while you read this.

---

## 2. Why it matters for claude-bridge

Everything the bridge does, Claude Code triggers by calling a tool. Let's be precise about who is who:

- The **bot agent** (a long-running `claude` session inside a tmux pane) is the **MCP client**. It initiates connections.
- `bridge` — specifically the process started by `bridge start`, which runs `src/mcp/server.ts` — is the **MCP server**. It exposes tools.
- Telegram is *not* part of MCP. It is a separate transport for humans. Telegram messages become MCP notifications, and Claude's replies become outgoing Telegram HTTP calls, but the protocol connecting Claude Code to `bridge` is MCP.

So when a user types `@bot dispatch backend "add pagination"` in Telegram, the chain is:

1. Telegram → grammy → `bridge` server, which queues the message.
2. `bridge` sends a **JSON-RPC notification** to Claude Code saying "a message is waiting."
3. Claude Code wakes up and calls the **`bridge_dispatch` tool** via a JSON-RPC request.
4. The `bridge` server runs its tool handler, spawns a `claude --agent ...` child process, and returns a JSON-RPC response.

Every interesting interaction with the bridge is some variation on that loop. If you cannot read the JSON-RPC on the wire, you cannot debug the bridge.

---

## 3. The three primitives

MCP defines exactly three kinds of thing a server can expose. You will mostly use tools.

### Tools

**Functions the model can decide to call.** A tool has a name, a description (read by the model to decide when to call it), and a **JSON Schema** for its input. The return value is a list of content blocks — usually text, but images and embedded resources are also legal.

A tool definition as it appears on the wire looks like:

```json
{
  "name": "bridge_dispatch",
  "description": "Dispatch a task to a Claude Bridge agent",
  "inputSchema": {
    "type": "object",
    "properties": {
      "agent":  { "type": "string", "description": "Agent name" },
      "prompt": { "type": "string", "description": "Task prompt" }
    },
    "required": ["agent", "prompt"]
  }
}
```

That is word-for-word what the bridge sends — see `src/mcp/tools.ts`. The model reads the description and the schema and decides whether to call the tool. If the user says "ask backend to add pagination," Claude will produce a tool call with `{"agent": "backend", "prompt": "add pagination"}`.

### Resources

**Read-only, addressable content the client can load into context.** A resource has a URI (`file:///etc/hosts`, `postgres://.../schema`, `git://HEAD/README.md` — any URI scheme you like), a MIME type, and a body. The client may list resources, fetch one, or subscribe to changes.

A resource listing looks like:

```json
{
  "uri": "file:///Users/alice/project/README.md",
  "name": "README.md",
  "mimeType": "text/markdown"
}
```

Where tools are verbs, resources are nouns. If you have static docs, database schemas, or config files you want the model to be able to pull in, expose them as resources. claude-bridge does **not** use resources — everything it does is an action.

### Prompts

**Named prompt templates the user (not the model) triggers.** A prompt has a name, arguments, and when invoked returns a list of message blocks that become the next user turn. In Claude Desktop, prompts appear as slash commands.

A prompt listing looks like:

```json
{
  "name": "summarise_pr",
  "description": "Summarise a pull request",
  "arguments": [
    { "name": "pr_url", "required": true }
  ]
}
```

Again, claude-bridge does not use prompts. The bridge's "commands" live in the model's CLAUDE.md, not in MCP.

So for the rest of this guide: **tools, tools, tools.** Resources and prompts exist and you should recognise them, but you will not implement them for the bridge.

---

## 4. The wire protocol

MCP is JSON-RPC 2.0. If you have never seen JSON-RPC before, here is the whole thing in one paragraph: each message is a JSON object with `jsonrpc: "2.0"`. A **request** has `id`, `method`, and `params`. A **response** has `id` and either `result` or `error`. A **notification** has `method` and `params` but **no** `id` — and therefore gets no response. That is it.

Over stdio, messages are framed as **newline-delimited JSON**: one complete JSON object per line, separated by `\n`. The SDK handles framing for you; you never write `\n` yourself.

Let's walk through a real session. A client connects to a server and wants to call one tool. Here is the full exchange, with who-sends-what annotated.

### 4.1 `initialize`

The client opens the conversation by announcing who it is and what protocol version it speaks:

```json
→ {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": { "name": "my-client", "version": "0.1.0" }
    }
  }
```

The server replies with its own identity and capabilities — which primitives it supports:

```json
← {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
      "protocolVersion": "2024-11-05",
      "capabilities": {
        "tools": {}
      },
      "serverInfo": { "name": "claude-bridge", "version": "1.0.0-beta" }
    }
  }
```

An empty `tools: {}` object means "I support the tools primitive." Capabilities are objects-not-booleans so they can carry sub-features later (`tools: { listChanged: true }` says the server will send a notification when its tool list changes).

After the server responds, the client sends an `initialized` **notification** (no id, no response) to signal the handshake is done:

```json
→ {
    "jsonrpc": "2.0",
    "method": "notifications/initialized"
  }
```

### 4.2 `tools/list`

Now the client asks what tools exist:

```json
→ {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
  }

← {
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
      "tools": [
        {
          "name": "bridge_dispatch",
          "description": "Dispatch a task to a Claude Bridge agent",
          "inputSchema": { "type": "object", "properties": { ... }, "required": ["agent", "prompt"] }
        },
        {
          "name": "bridge_status",
          "description": "Get status of running tasks. Optionally filter by agent name",
          "inputSchema": { "type": "object", "properties": { ... } }
        }
      ]
    }
  }
```

Whatever the client (say, Claude Code) decides to show the model is then fed into the system prompt.

### 4.3 `tools/call`

When the model picks a tool, the client sends:

```json
→ {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "bridge_dispatch",
      "arguments": {
        "agent": "backend",
        "prompt": "add pagination"
      }
    }
  }
```

The server runs its handler and returns content blocks:

```json
← {
    "jsonrpc": "2.0",
    "id": 3,
    "result": {
      "content": [
        { "type": "text", "text": "Task #42 dispatched to backend" }
      ],
      "isError": false
    }
  }
```

If the handler throws, the SDK either serialises a protocol-level `error` object or returns a `result` with `isError: true`. Both are legal, but **`isError: true` is preferred for handler-level failures** — the model sees the text and can react, whereas a protocol `error` typically halts the call.

### 4.4 Notifications

Anything without an `id` is a one-way message. Servers can send notifications to clients — the spec defines `notifications/tools/list_changed`, `notifications/resources/updated`, `notifications/message` (log line), and clients may accept custom experimental notifications.

Example: claude-bridge sends a custom notification when a Telegram message arrives, so the bot agent wakes up:

```json
← {
    "jsonrpc": "2.0",
    "method": "notifications/claude/channel",
    "params": {
      "source": "bridge",
      "chat_id": "12345",
      "user": "alice",
      "text": "dispatch backend: add pagination"
    }
  }
```

That `notifications/claude/channel` method is a Claude Code extension, declared at connect time under `capabilities.experimental`. Standard clients would ignore it; Claude Code routes it into the agent's inbox.

### 4.5 Other transports — just so you know they exist

- **SSE transport**: two endpoints, one for POST'ed client-to-server requests, one for an SSE stream carrying server-to-client messages. Useful when you want your MCP server to live on a remote machine.
- **Streamable HTTP**: a single POST endpoint per request, with the response either a single JSON body or an SSE stream depending on the `Accept` header. Newer, recommended for new remote servers.

You will not touch either unless you write a hosted MCP server. For the bridge, it is stdio all the way down.

---

## 5. The TypeScript SDK

Install:

```bash
npm install @modelcontextprotocol/sdk
# or
bun add @modelcontextprotocol/sdk
```

### What's in the package

The package is split into submodules, each exported via subpath:

- `@modelcontextprotocol/sdk/server/index.js` — `Server`, the low-level server class.
- `@modelcontextprotocol/sdk/server/stdio.js` — `StdioServerTransport`, which pipes the server to `process.stdin` / `process.stdout`.
- `@modelcontextprotocol/sdk/server/sse.js` and `streamableHttp.js` — other transports.
- `@modelcontextprotocol/sdk/client/index.js` — `Client` class, for writing MCP clients. (You normally don't need it — you are the server.)
- `@modelcontextprotocol/sdk/types.js` — request/response **Zod schemas** for every method the protocol defines. `InitializeRequestSchema`, `ListToolsRequestSchema`, `CallToolRequestSchema`, `ListResourcesRequestSchema`, etc.

There is also a higher-level helper called `McpServer` (in `@modelcontextprotocol/sdk/server/mcp.js`) that gives you a nicer API — `.tool(name, schema, handler)` and done. It is a thin wrapper around `Server`. The bridge uses the lower-level `Server` because its tool list is generated from a config file; either is fine.

### The shape of a handler

With the low-level API, the pattern is always the same: register a handler for a request schema.

```ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

const server = new Server(
  { name: "my-server", version: "0.1.0" },
  { capabilities: { tools: {} } },
);

// Respond to tools/list
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "echo",
        description: "Echo back the input",
        inputSchema: {
          type: "object",
          properties: { message: { type: "string" } },
          required: ["message"],
        },
      },
    ],
  };
});

// Respond to tools/call
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  if (name !== "echo") {
    throw new Error(`Unknown tool: ${name}`);
  }
  return {
    content: [{ type: "text", text: `echo: ${args?.message}` }],
  };
});
```

That is exactly the pattern `src/mcp/server.ts` uses — one handler for each of the two schemas. When a JSON-RPC request comes in, the SDK validates it against the Zod schema you registered and, if it matches, calls your handler. If it does not match, the SDK sends a JSON-RPC error back and your handler never runs.

### Error handling conventions

Two layers:

1. **Protocol errors** — invalid JSON, unknown method, malformed params. The SDK handles these by emitting a proper JSON-RPC `error` object. You do not write this code.
2. **Tool errors** — your handler ran but something went wrong. Prefer returning `{ content: [...], isError: true }` over throwing. The message in the content block ends up in the model's context and the model can retry or escalate. Throwing in a handler still works (the SDK will translate it), but you lose nuance.

The bridge uses a little helper to make this obvious:

```ts
function error(s: string): ToolResult {
  return { content: [{ type: "text", text: s }], isError: true };
}
```

and returns `error("Agent not found")` anywhere a tool cannot be serviced.

---

## 6. Build a minimal MCP server

Time to actually write one. We will build a server that exposes a single `echo` tool, run it, and poke at it with the MCP Inspector.

### 6.1 Scaffold the project

```bash
mkdir mcp-echo
cd mcp-echo
npm init -y
npm install @modelcontextprotocol/sdk
npm install --save-dev typescript @types/node
npx tsc --init --target es2022 --module nodenext --moduleResolution nodenext --outDir dist
```

Edit `package.json` so the `type` field is `"module"` (so Node treats your `.js` output as ESM) and add a `start` script:

```json
{
  "name": "mcp-echo",
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "build": "tsc",
    "start": "node dist/server.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0"
  },
  "devDependencies": {
    "typescript": "^5.0.0",
    "@types/node": "^20.0.0"
  }
}
```

### 6.2 Write the server

Create `src/server.ts`:

```ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

// Construct the server. The first arg is identity, the second is capabilities.
const server = new Server(
  { name: "mcp-echo", version: "0.0.1" },
  { capabilities: { tools: {} } },
);

// Register the list-tools handler. Called when the client asks "what do you have?"
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "echo",
      description: "Echo back the provided message.",
      inputSchema: {
        type: "object",
        properties: {
          message: { type: "string", description: "Text to echo back" },
        },
        required: ["message"],
      },
    },
  ],
}));

// Register the call-tool handler. This is where the actual work happens.
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name !== "echo") {
    // isError: true flags a handler-level failure. The model sees the text.
    return {
      content: [{ type: "text", text: `Unknown tool: ${name}` }],
      isError: true,
    };
  }

  const message = String(args?.message ?? "");
  return {
    content: [{ type: "text", text: `echo: ${message}` }],
  };
});

// Connect to stdio. This takes over stdin/stdout until the process exits.
const transport = new StdioServerTransport();
await server.connect(transport);

// Log to stderr — NEVER stdout, because stdout is the JSON-RPC transport.
process.stderr.write("mcp-echo started\n");
```

That is the whole server. Thirty-odd lines.

Build it:

```bash
npm run build
```

### 6.3 Test it with the MCP Inspector

The Inspector is an official tool that spawns your server and gives you a web UI to call its methods. No setup — it ships as an npx package:

```bash
npx @modelcontextprotocol/inspector node dist/server.js
```

You will see output like:

```
MCP Inspector is up and running at http://127.0.0.1:6274
```

Open it in a browser. You will see:

- The **initialize** handshake happen automatically.
- A **Tools** tab that shows `echo` with its schema.
- A form that lets you fill in `message` and hit "Call" — the response appears below.

This is the single best tool for debugging an MCP server. When something does not work with Claude Code, get it working with the Inspector first, then worry about why the client is different.

### 6.4 What just happened, in JSON-RPC terms

The Inspector spawned `node dist/server.js` as a child process. It wrote to that process's stdin and read from its stdout:

```
→ { "jsonrpc": "2.0", "id": 1, "method": "initialize", ... }
← { "jsonrpc": "2.0", "id": 1, "result": { ... } }
→ { "jsonrpc": "2.0",       "method": "notifications/initialized" }
→ { "jsonrpc": "2.0", "id": 2, "method": "tools/list" }
← { "jsonrpc": "2.0", "id": 2, "result": { "tools": [ { "name": "echo", ... } ] } }
→ { "jsonrpc": "2.0", "id": 3, "method": "tools/call",
    "params": { "name": "echo", "arguments": { "message": "hello" } } }
← { "jsonrpc": "2.0", "id": 3, "result": {
    "content": [ { "type": "text", "text": "echo: hello" } ] } }
```

That is the protocol. Everything else is detail.

---

## 7. How claude-bridge composes these primitives

Now you can open `src/mcp/server.ts` and read it like English. Some observations:

**It uses only tools.** No resources, no prompts. Everything the bot agent does is an action: dispatch a task, kill a task, send a reply. Nothing the bridge owns is "content" the model should load.

**Tool definitions are a static array.** `src/mcp/tools.ts` exports `TOOL_DEFINITIONS`. The server's `ListToolsRequestSchema` handler just returns it. No dynamic tool registration — simplicity.

**Tool handlers are a big switch statement.** `src/mcp/tool-handlers.ts` has one `switch (toolName)` that dispatches each tool name to a block of code that calls into `data/`, `execution/`, or `orchestration/` modules. Look at the `bridge_dispatch` case: it resolves the agent, creates a task row, starts a subprocess, and returns a text result. That is the archetype for every bridge tool.

**Server-to-client notifications are queued.** Read the comment around `queuedNotification` in `server.ts`. stdio multiplexes tool responses and notifications on a single stream. If you emit a notification while a tool handler is mid-flight, the JSON frames can interleave and corrupt the client's parser. The bridge tracks `toolCallInFlight` and buffers notifications until the handler returns, then flushes. If you ever need to emit notifications from your own MCP server, copy this pattern.

**A custom capability is declared.** Look at the `Server` constructor in `server.ts` — it declares `capabilities.experimental["claude/channel"]`. That opts in to Claude Code's channel extension: a way for the server to push "a human sent a message" notifications that Claude Code knows to surface as user turns. Standard MCP clients would ignore the capability.

For the full map of every tool and what layer it touches, read `docs/specs/04-mcp-and-channels.md`. That doc is maintained as reference; this one is not.

---

## 8. Pitfalls

**Do not write to stdout.** Ever. Your server's stdout is the JSON-RPC transport. A stray `console.log` will produce a non-JSON line and the client will either drop the session or misparse a tool response. Use `process.stderr.write(...)`, or a logger configured to write to stderr. Note in `src/mcp/server.ts` how the bridge logs `[server] ...` to stderr exclusively.

**JSON-RPC ids must be unique per session.** The SDK generates them for you on the client side and matches responses on the server side, so you mostly do not think about this. But if you embed another JSON-RPC implementation — say, calling a sub-process that also speaks JSON-RPC — do not share id namespaces or interleave frames on the same stream.

**Tool input schemas are plain JSON Schema, not Zod.** The SDK validates method *envelopes* with Zod internally, but the schema you put in `inputSchema` is JSON Schema (Draft-07 shape) that the client forwards to its model. If you want to author with Zod, convert at build time (`zod-to-json-schema` is the common tool). The bridge skips Zod entirely and hand-writes JSON Schemas — see `TOOL_DEFINITIONS`.

**Long-running tools have no progress primitive** in the base protocol (a `progress` notification exists but is rarely used). If your tool needs minutes, do not block the handler — return immediately with "started task #42" and deliver the result later, either via a separate notification channel, a polling tool (`bridge_status`), or a callback like the bridge's Stop-hook → SQLite → `notifications/claude/channel` pipeline. Never make your `tools/call` handler wait five minutes.

**Stdio servers are children; their lifecycle is the client's.** If Claude Code exits without cleanly closing stdin, your server process may keep running. Handle SIGTERM/SIGINT (see bottom of `server.ts`) and exit on stdin EOF. The SDK's `StdioServerTransport` handles EOF for you, but cleanup of your own resources (DBs, timers, child processes) is your problem.

**Tool descriptions are a prompt.** The model reads your `description` strings to decide when to call the tool. "Dispatch a task" is vague; "Dispatch a task to a Claude Bridge agent — only use when the user has asked for work to be started" is actionable. Tune them like prompts, not like Swagger docs.

---

## 9. Testing and debugging MCP servers

Three tools in decreasing order of usefulness:

**MCP Inspector.** `npx @modelcontextprotocol/inspector <your server command>`. Always start here. It will show you the initialize handshake, the tool list, and let you call tools interactively. If your server works in Inspector but not in Claude Code, the bug is in the client config or the model's prompt, not your server.

**`claude mcp` CLI.** Claude Code has its own MCP management commands:

```bash
claude mcp list                         # show configured MCP servers
claude mcp add my-echo node ./dist/server.js   # register a new one
claude mcp remove my-echo
```

Useful to confirm Claude Code actually sees your server. If `claude mcp list` doesn't show it, the problem is registration, not protocol.

**Log to stderr, inspect it.** Claude Code captures stderr from stdio MCP servers and dumps it on failures. When things break mid-session, `~/Library/Logs/Claude Code/` (macOS) or the equivalent on your platform is where the MCP stderr ends up. The bridge's `process.stderr.write` calls land there.

For **unit testing** a handler, skip the transport entirely. Construct a `Server`, register handlers, and call them directly — or better, extract the handler body into a plain function (like `executeToolNative` in `src/mcp/tool-handlers.ts`) and test that. No MCP involved. The bridge's `tests/wave7/tool-handlers.test.ts` does exactly this.

---

## 10. Exercises

**Exercise 1 — "now" tool.**
Copy your `mcp-echo` server. Replace `echo` with a `now` tool that takes no arguments (`inputSchema: { type: "object", properties: {} }`) and returns the current timestamp as an ISO-8601 string. Run it with the MCP Inspector and call it a few times to confirm the timestamp updates.

**Exercise 2 — "add" tool with input validation.**
Add a second tool, `add`, with schema `{ type: "object", properties: { a: { type: "number" }, b: { type: "number" } }, required: ["a", "b"] }`. Implement the handler. Then try calling it with a string for `a` — what happens? The SDK does **not** validate `inputSchema` against incoming arguments; validation is the handler's job (or the model's). Add explicit `typeof args.a !== "number"` checks in your handler and return `isError: true` with a helpful message. This is why the bridge's handlers start with `String(args["agent"])` — defensive coercion.

**Exercise 3 — register with Claude Code.**
Register your server as an MCP server that Claude Code can use:

```bash
claude mcp add mcp-echo node /absolute/path/to/mcp-echo/dist/server.js
claude mcp list   # confirm it shows up
```

Start a Claude Code session and ask: "Use the mcp-echo server to add 17 and 25." Watch Claude pick the `add` tool, call it, and incorporate the result into its answer. If it does not call the tool, check your description — the model needs to understand what the tool is for. Fix, reload (`claude mcp remove mcp-echo && claude mcp add ...`), retry.

Once all three work, you have written, tested, and shipped an MCP server. Rereading `src/mcp/server.ts` now should feel like reading a slightly fancier version of the same file.

---

## 11. Further reading

Canonical sources only — do not go looking for a "top 10 MCP tutorials" post on Medium before exhausting these:

- <https://modelcontextprotocol.io> — spec landing page.
- <https://modelcontextprotocol.io/docs/concepts/architecture> — client/server/transport model, in more depth than this guide.
- <https://modelcontextprotocol.io/docs/concepts/tools> — tool semantics, including content block types.
- <https://modelcontextprotocol.io/docs/tools/inspector> — how to use the Inspector, including advanced features like saved sessions.
- <https://github.com/modelcontextprotocol/typescript-sdk> — SDK source and examples. Read the `examples/` directory once — it is the best shortcut to fluency.
- <https://docs.anthropic.com/en/docs/claude-code/mcp> — Claude Code's MCP integration: how to register servers, what transports are supported, and what Claude Code's experimental capabilities (like `claude/channel`) do.

Once those feel familiar, move on to `docs/learn/05-stdio-ipc.md` to go one level deeper into the stdio framing itself, or to `docs/specs/04-mcp-and-channels.md` for the full bridge-specific reference.
