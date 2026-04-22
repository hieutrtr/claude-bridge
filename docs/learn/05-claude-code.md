# 05 — Claude Code as a Platform

This chapter is for the developer who has used `claude` interactively — maybe
configured a hook once, maybe edited a `CLAUDE.md` — but has never driven
Claude Code programmatically from another process. After reading, you should
understand the specific Claude Code features that `claude-bridge` is built on
top of, and why the bridge wires them together the way it does.

The goal is not to be a reference (the Anthropic docs already are one — links
at the end). The goal is to build enough of a mental model that when a task
hangs, a session "forgets" itself, or a hook mysteriously doesn't fire, you
can reason about which layer is misbehaving.

A note on honesty: Claude Code ships fast. Where I'm confident about current
behavior I'll say it plainly; where the bridge relies on a contract that may
drift, I'll say "the bridge treats it as if..." and point at the docs.

---

## 1. Claude Code in one minute

Claude Code is Anthropic's official coding product. Concretely, it's:

- A **command-line tool** (`claude`) that talks to the Claude model, reads
  and writes files, runs shell commands, and orchestrates multi-step tasks.
- A set of **IDE integrations** (VS Code, JetBrains) that wrap the same core.
- An **SDK** for embedding Claude-Code-flavored agents inside other apps.
- A growing **plugin and MCP ecosystem** — hooks, subagents, slash commands,
  MCP servers, custom settings.

`claude-bridge` targets exactly one of those surfaces: the CLI. Every time
the bridge "does something smart," what's actually happening is that it
shells out to `claude` with some flags and files staged on disk ahead of
time. Everything else — the SQLite DB, the Telegram relay, the MCP server —
is plumbing around that single subprocess.

If you keep one sentence in your head from this doc, make it:

> The bridge is a conductor. Claude Code is the orchestra.

---

## 2. Why lean on native features?

The bridge deliberately avoids reimplementing things Claude Code already
does. Four reasons, in order of importance:

1. **Reliability.** Sessions, worktrees, hooks, and memory are battle-tested
   inside Claude Code. A homegrown version would re-hit every edge case
   Anthropic already fixed.
2. **Prompt caching.** Claude Code's system prompt and tool definitions are
   set up so the API auto-caches them for up to five minutes. A clean
   subprocess reinvocation with the same agent and session can get a cache
   hit that a custom runner would miss.
3. **Feature parity.** When Claude Code adds a new capability (thinking
   budgets, new tools, subagent improvements), dispatched tasks inherit it
   for free.
4. **Maintenance.** Less surface area to own.

The practical consequence: when you're tempted to add a feature to the
bridge, first check whether Claude Code already has it. Usually it does.

---

## 3. Sessions (`--session-id`)

### What a session is

A Claude Code session is a conversation — a sequence of user messages,
assistant messages, tool calls, and tool results that the model can scroll
back over. It has persistent state: transcript, tool history, any memory
written during the run. Sessions survive across process exits; they're
stored on disk.

### How `--session-id` works

Normally, each `claude -p "..."` invocation starts a fresh conversation.
With `--session-id <uuid>`, you opt into a specific session slot:

- If a session with that id exists, Claude Code **resumes** it — the new
  prompt is appended to the existing transcript.
- If it doesn't exist, Claude Code **creates** it with that id.

This is how the bridge turns a one-shot CLI into a "remembers across
dispatches" agent: dispatch two tasks to the same session id, and the
second one sees the first one's context. Dispatch to two different
session ids and they're fully isolated.

### Session storage

Sessions live on disk under your Claude Code config root (roughly
`~/.claude/`). Treat exact paths as implementation detail; if you need
them, ask `claude` directly. Sessions persist indefinitely by default, but
they're plain files — if you wipe `~/.claude/`, every session goes with
it. There's also a practical context-length ceiling: a session that grows
to tens of thousands of messages will eventually force you to compact or
start over.

### How the bridge uses session ids

The bridge picks one stable session id per (agent, project) pair. For an
agent called `backend` working on the project `my-api`, the logical
identifier is `backend--my-api`. That string is the bridge's **logical**
session id — it's the one you see in `bridge history`, `bridge status`,
file paths under `~/.claude-bridge/workspaces/`, and the agent `.md`
filename.

Claude Code's `--session-id` wants a UUID-shaped value. So when the bridge
actually spawns `claude`, it hashes the logical id (optionally plus a task
id) into a deterministic UUID and passes *that*. You can see the
conversion in `sessionIdToUuid` in `src/execution/dispatcher.ts`. The
important property is that it's pure: same logical id, same UUID, every
time — which is what gives us the "remembers the previous dispatch"
behavior.

Two knobs worth knowing:

- Passing a task id into the hash means each task can get its own UUID
  under the same logical session — useful when you want isolated
  transcripts per task instead of a running thread.
- Dropping the task id and hashing just the session id gives the long-
  lived "this agent remembers across dispatches" behavior.

Which mode the bridge uses in any given code path is worth checking at the
call site; the default in `Dispatcher.dispatch` is the *per-task* UUID.

---

## 4. Agents (`--agent`)

### What an agent is

In Claude Code, an "agent" is a `.md` file. It's just a Markdown document
with YAML frontmatter at the top. The frontmatter defines:

- `name` — the agent id you pass to `--agent`.
- `description` — short human description (shown in some listings).
- `model` — which model to use (`sonnet`, `opus`, etc).
- `tools` — which built-in tools the agent is allowed to use.
- `allowedTools` — optional extra allow-list, typically for MCP tools
  (e.g. `mcp__claude-bridge__*`).
- Optional extras like `isolation`, `memory`, `hooks`.

The Markdown body below the frontmatter becomes part of the agent's
system prompt. That's where you tell the agent *who it is, what its job
is, and how to behave*.

### Where agent files live

Two locations, checked in order:

- **Project-level**: `<project>/.claude/agents/*.md`. Scoped to one
  project. Can be committed to the repo so teammates share them.
- **User-level**: `~/.claude/agents/*.md`. Available anywhere.

If the same agent name exists in both, project-level wins.

### How the bridge generates agent files

Every time you run `bridge create-agent`, the bridge generates a fresh
agent `.md` file using the template in `src/cli/agent-md.ts`. Key points:

- **Naming**: `bridge--{session_id}.md` — so the `backend` agent on
  `my-api` becomes `bridge--backend--my-api.md`. This guarantees the
  bridge never collides with hand-written agents and makes the mapping
  obvious when you `ls` the agents directory.
- **Location**: when a bot directory is configured (from
  `bridge setup-bot`), the file goes under
  `{bot_dir}/.claude/agents/`. Otherwise it lives in
  `~/.claude/agents/`. The bot-dir path means every instance's agents
  are isolated from other Claude Code usage.
- **Frontmatter it fills in**: `name`, `model`, the built-in tool list,
  MCP tool allow-list (`mcp__claude-bridge__*`), `isolation: { type:
  worktree }`, `memory: { enabled: true }`, and a Stop hook that calls
  back into `bridge on-complete`.

Here's a complete, invented example of what a generated agent file looks
like. Don't copy it into a repo — use `bridge create-agent`. This is for
illustration:

```markdown
---
name: bridge--backend--my-api
model: sonnet
tools:
  - Read
  - Edit
  - Write
  - Bash
  - Grep
  - Glob
  - Agent
allowedTools:
  - mcp__claude-bridge__*
isolation:
  type: worktree
memory:
  enabled: true
hooks:
  stop:
    - command: "CLAUDE_BRIDGE_HOME=/Users/you/.claude-bridge bridge on-complete --session-id backend--my-api"
---

# bridge--backend--my-api

**Purpose:** add pagination to list endpoints

## Behavior

- You are an autonomous agent working on: add pagination to list endpoints
- Project directory: /Users/you/projects/my-api
- Session ID: backend--my-api

## Rules

- Focus on the task at hand
- Write clean, tested code
- Commit your changes when done
- Report progress clearly in your result summary
```

Two things to notice before we move on:

- The `hooks.stop` snippet in the **agent frontmatter** is the bridge's
  template. In parallel, the bridge also writes the hook into the
  project-level `settings.local.json` in the canonical `hooks.Stop[...]`
  shape Claude Code actually consumes. The settings-file form is the one
  that really matters.
- `isolation: { type: worktree }` is declared, and the bridge trusts
  Claude Code to enforce it. See the worktree section.

---

## 5. Hooks, with a deep dive on `Stop`

### What hooks are

A hook is a shell command Claude Code runs for you when a specific
lifecycle event fires. They're plain commands; Claude Code passes
context to them as JSON on stdin and reads a JSON response (or just an
exit code) back.

### The set of events (current, as of this writing)

You don't need to memorize these — just know the shape. The common ones:

- `SessionStart` — at the beginning of a session.
- `UserPromptSubmit` — when the user submits a prompt.
- `PreToolUse` — before a tool call (you can veto).
- `PostToolUse` — after a tool call completes.
- `Stop` — when the agent's turn ends (the model decides it's done).
- `SubagentStop` — a subagent turn ends.
- `Notification` — when Claude wants to notify the user.

Consult
[the hooks docs](https://docs.anthropic.com/en/docs/claude-code/hooks)
for the current full list and exact payload shapes — they evolve.

### Stop, in detail

Stop fires when the model says "I'm done" — no more tool calls, no more
output, the turn is over. For a `-p "..."` one-shot invocation, Stop is
effectively the "task finished" signal.

What Claude Code passes to your Stop command:

- A JSON object on **stdin** with context about the session: session id,
  transcript path, working directory, etc. Exact field names are
  documented upstream; the bridge's handler reads what it needs and
  ignores the rest.
- A normal Unix environment. Env vars you set on the parent process (the
  one that launched `claude`) are inherited — that's how the bridge
  passes `CLAUDE_BRIDGE_HOME` through.

How your Stop command signals back:

- **Exit code 0** — OK, continue normally.
- **Non-zero** — generally treated as a failure signal. Claude Code may
  surface the error, and some upstream docs describe "blocking" vs
  "non-blocking" exits depending on the event. For Stop specifically,
  the bridge treats a successful call as "DB updated, notify sent," and
  doesn't try to interfere with Claude's own lifecycle.

### How the bridge wires Stop

When `bridge create-agent` runs, it does two things in the hook space:

1. Generates the agent `.md` with a `hooks.stop` stanza in the
   frontmatter (see the template in `agent-md.ts`). Whether Claude
   Code reads hooks from agent frontmatter depends on version — the
   bridge treats this as a belt.
2. Writes `{project_dir}/.claude/settings.local.json` containing the
   canonical Claude Code hooks shape (the suspenders):

   ```json
   {
     "hooks": {
       "Stop": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "CLAUDE_BRIDGE_HOME=/Users/you/.claude-bridge bridge on-complete --session-id backend--my-api"
             }
           ]
         }
       ]
     }
   }
   ```

Two things about that JSON matter, and both bit a previous version of
the bridge:

- The event key is **capitalized `Stop`**, not `stop`.
- Each entry is `{ hooks: [{ type: "command", command: "..." }] }`, not
  a flat `{ command: "..." }`.

Earlier versions emitted the flat lowercase form; Claude Code silently
ignored it, tasks never produced a Stop callback, and the
`ProcessWatcher` eventually marked them failed when the PID exited.
`installStopHook` in `agent-md.ts` now also migrates legacy entries
into the canonical shape when it re-runs.

When the Stop hook fires, the command is:

```
CLAUDE_BRIDGE_HOME=... bridge on-complete --session-id backend--my-api
```

**Subtle but important:** Claude Code runs the Stop hook *inside* the
`claude` process (blocking it from exiting) before claude's stdout is
flushed to the result file. That means `bridge on-complete` usually
cannot read the result JSON — the file is empty or partial at that
moment. In practice the Stop hook is an optimistic fast-path and
normally no-ops; the real completion processing happens in
`ProcessWatcher` (`src/execution/watcher.ts`), which polls every 5s
and parses the result *after* claude exits and stdout flushes.

The `on-complete` handler (`src/execution/on-complete.ts`) and the
watcher both funnel into `CompletionHandler.handleCompletion`, which
updates SQLite with success/failure, records cost/tokens, advances any
associated goal loop, and enqueues a notification. The startup
orchestrator's 5s notify loop picks it up and relays to Telegram. See
`docs/specs/02-execution-pipeline.md` §3.3 for the full reasoning and
`docs/specs/03-orchestration.md` §1.3 for the loop-completion seam.

One recurring confusion: if you edit the hook command *after* creating
the agent, you need to update `settings.local.json` — re-running
`bridge create-agent` does that idempotently.

---

## 6. Worktree isolation

### What a git worktree is

`git worktree` lets you check out more than one branch from the same
repo, in different directories, all sharing the same `.git` history.
You do this with:

```
git worktree add ../my-feature feature/my-feature
```

That creates a new directory `../my-feature` on branch
`feature/my-feature`, with its own working tree, while still pointing
at the same `.git`. You can edit, commit, and push from either
directory without them clobbering each other's working files.

Cleanup:

```
git worktree remove ../my-feature
```

(or `git worktree prune` to clean up metadata for directories that
were deleted manually.)

### Why the bridge needs this

The bridge dispatches tasks *concurrently*. If two tasks for the same
project ran in the project's primary checkout, they'd step on each
other's working tree — file writes, branch switches, in-flight edits.
Worktrees turn that into a non-problem: each task gets its own
directory.

### What Claude Code's `isolation: worktree` does

The agent frontmatter declares `isolation: { type: worktree }`. The
bridge treats this as "Claude Code, please run this task in its own
worktree." Concretely, Claude Code is responsible for creating,
reusing, and cleaning up the worktree per its current implementation.

Be honest about two things:

1. The exact lifecycle (one worktree per task? per session? when does
   it clean up?) is a Claude Code implementation detail that has
   evolved and may evolve further. If you need to know at runtime,
   inspect `.git/worktrees/` in the project dir during a dispatch.
2. If Claude Code can't create a worktree (e.g. the project isn't a
   git repo, or the repo is in a bad state), the bridge won't save
   you — tasks will try to run in the main checkout, and concurrent
   dispatches will conflict. `bridge doctor` is the place to add
   checks for this.

### Cleanup semantics

The bridge doesn't hand-manage worktrees. If stale ones accumulate in
`.git/worktrees/`, you can clean them with:

```
git worktree list
git worktree prune
```

from inside the project dir.

---

## 7. Auto Memory

### What it is

Claude Code's Auto Memory is a file-based memory system: as sessions
progress, Claude can write persistent notes — "facts the user told me,"
"conventions in this project," "things I learned the hard way" — to a
memory file. On subsequent sessions, that memory is loaded into context,
so the agent doesn't relearn everything from scratch.

The canonical reference is the
[memory docs](https://docs.anthropic.com/en/docs/claude-code/memory).
Exact file locations and format have changed over time, so treat what
follows as shape-of-the-thing rather than a byte-for-byte contract.

### Where it's stored

Memory lives on disk under Claude Code's config root, scoped per
project (and optionally per agent). The bridge doesn't pretend to know
the internal layout; it asks Claude Code itself.

### How the bridge surfaces it

`bridge memory <agent>` reads the memory associated with the agent's
session and prints it. Inside the bridge, this typically shells out to
`claude`'s `/memory` slash command (or its SDK equivalent) and returns
the resulting text. Reading is safe — the bridge never writes memory;
it only lets Claude Code update it as part of normal operation.

Rule of thumb: **don't hand-edit memory files.** If you need to change
what the agent "remembers," say it to the agent in a session; let
Claude Code update the file. Hand-edits risk corrupting whatever format
the current version expects.

---

## 8. MCP integration

Claude Code is an MCP (Model Context Protocol) **client**. It speaks
MCP to external servers, which each expose tools, resources, and
prompts. You configure servers in three places, in precedence order:

- `claude mcp add <name> -- <command>` — manages user/project config
  via the CLI.
- A project's `.mcp.json` — committed to the repo, applies to anyone
  running Claude Code in that project.
- User-level config under `~/.claude/`.

The bridge participates on the other side of the wire: it **exposes
itself as an MCP server**. When you configure the bot project's
`.mcp.json` to launch `claude-bridge` as a server, the Bridge Bot
(which is itself a Claude Code session) gets tools like:

- `bridge_dispatch` — dispatch a task to an agent.
- `bridge_list_agents`, `bridge_status`, `bridge_history`, etc.

These are the `mcp__claude-bridge__*` tools you see in the generated
agent's `allowedTools`.

Why this matters: the bot is not special code. It's a Claude Code
session that happens to have the Telegram MCP server and the
claude-bridge MCP server wired up. Every user message in Telegram
becomes a prompt; every time the bot calls `bridge_dispatch`, it's
just one MCP tool call away from spawning a new `claude` subprocess on
the user's behalf.

For the protocol-level details of MCP — transports, message shape,
tool/prompt/resource semantics — see
[`04-mcp.md`](./04-mcp.md) in this series.

---

## 9. Subagents

Claude Code supports **subagents**: an agent can spawn another agent
to handle a sub-task and return a result. The child runs in its own
context window, which is how Claude Code keeps long, multi-phase
projects from blowing out a single conversation's token budget.

The bridge doesn't try to own this feature. If a dispatched task
decides to delegate to a subagent, that's happening entirely inside
Claude Code's process. The bridge's Stop hook fires only when the
*top-level* agent turn ends, not on each subagent's internal
completion. (`SubagentStop` is a separate event; the bridge currently
ignores it.)

For a maintainer, this mostly shows up as "why does a task's
transcript mention tools I didn't expect?" — the answer is usually
"a subagent was spawned." See the
[sub-agents docs](https://docs.anthropic.com/en/docs/claude-code/sub-agents).

---

## 10. Prompt caching

Anthropic's API supports prompt caching: if you send a prompt where a
large chunk of the prefix (system prompt, tool definitions, long
documents) is identical to a recent call, that chunk can be served
from a cache for up to ~5 minutes, at a significantly reduced cost and
latency.

Claude Code sets its prompts up so this caching "just works" for
repeated invocations of the same agent: the system prompt, tool
definitions, and MCP tool schemas are stable across calls and cache
well. For `claude-bridge`, this means two dispatches to the same
agent, within a few minutes, share the cache — the second one is
cheaper and faster than the first. This is a big part of why
*reusing* the bridge's agents (rather than creating new ones for each
task) is a noticeable win.

You don't need to configure anything for this; just be aware that a
long idle period between dispatches loses the cache, and the next
call pays full price again.

---

## 11. Putting it together — one dispatched task's lifecycle

Here's the Claude-Code-side story of a single `bridge dispatch`:

1. **Spawn.** The dispatcher builds a `claude` command roughly like:

   ```
   claude \
     --agent bridge--backend--my-api \
     --session-id 3f2a...-...-... \
     --output-format json \
     --dangerously-skip-permissions \
     --model sonnet \
     -p "add pagination to /users"
   ```

   It runs it detached with `Bun.spawn`, cwd set to the project dir,
   stdout redirected to a result file, stderr to a stderr file.

   `--dangerously-skip-permissions` is required because the subprocess
   has no TTY — there's no human to answer permission prompts, so the
   task would hang forever on the first tool call otherwise.

2. **Load agent.** Claude Code reads
   `<bot_dir>/.claude/agents/bridge--backend--my-api.md` (or the
   user-level fallback), parses the YAML frontmatter, and configures
   itself: model, allowed tools, isolation, memory, hooks.

3. **Resolve session.** The UUID passed via `--session-id` either
   resumes an existing conversation or creates a fresh one keyed to
   that UUID. Memory for the project/agent is loaded.

4. **Isolate.** Because of `isolation: worktree`, Claude Code sets up
   (or reuses) a git worktree and makes that the effective cwd for
   the task's file edits.

5. **Run.** The model does its thing — reading files, editing, running
   tests, talking to MCP servers including the bridge's own tools.

6. **Stop hook.** When the model decides it's done, Claude Code fires
   the `Stop` hook from `settings.local.json`, which runs:

   ```
   CLAUDE_BRIDGE_HOME=... bridge on-complete --session-id backend--my-api
   ```

   That process reads the task's result JSON, updates SQLite, and
   enqueues a notification.

7. **Exit.** The `claude` subprocess exits. The bridge's
   `ProcessWatcher` (fallback) would have caught the exit even if
   Stop had failed; the hook is the fast path.

8. **Notify.** The notify loop picks up the pending notification and
   relays it via the channel adapter (Telegram).

If any of those steps misbehaves, knowing the sequence is how you
localize the fault. A missing Stop hook? Step 6 didn't run; check
`settings.local.json`. A task that "finishes instantly"? Step 5 never
really started — check the stderr file. A task that hangs forever?
Almost always step 1 without `--dangerously-skip-permissions`.

---

## 12. Exercises

These are hands-on. Do them in a scratch directory, not in a repo you
care about.

### Exercise A — Write a Stop hook from scratch

Goal: feel the hooks contract without the bridge in the way.

1. Create a directory `~/tmp/hook-demo/` and inside it:

   ```
   mkdir -p ~/tmp/hook-demo/.claude/agents
   ```

2. Create `~/tmp/hook-demo/.claude/agents/logger.md`:

   ```markdown
   ---
   name: logger
   model: sonnet
   tools:
     - Read
   ---

   # logger

   You are a minimal test agent. Answer tersely.
   ```

3. Create `~/tmp/hook-demo/.claude/settings.local.json`:

   ```json
   {
     "hooks": {
       "Stop": [
         {
           "hooks": [
             { "type": "command", "command": "date >> /tmp/claude-test.log" }
           ]
         }
       ]
     }
   }
   ```

4. Run:

   ```
   cd ~/tmp/hook-demo
   claude --agent logger -p "say hi"
   ```

5. Verify:

   ```
   cat /tmp/claude-test.log
   ```

   You should see a fresh timestamp. Run the command again; you should
   see a second one. Now you know exactly how the bridge's Stop hook
   plumbing works — it's the same thing, just with a heavier command.

### Exercise B — Session continuity with `--session-id`

Goal: see for yourself that `--session-id` resumes state.

1. Run:

   ```
   claude --session-id my-test -p "remember the number 42 for me"
   ```

2. Then, in a separate invocation:

   ```
   claude --session-id my-test -p "what number did I ask you to remember?"
   ```

3. It should answer 42. Now try the second command with a different
   `--session-id` and confirm it doesn't know the number.

This is the exact mechanism the bridge uses to give each (agent,
project) pair persistent memory across dispatches.

### Exercise C — Worktree isolation by hand

Goal: feel what "concurrent tasks can't corrupt each other" means.

1. In a throwaway git repo with a clean working tree:

   ```
   git worktree add ../scratch -b scratch
   cd ../scratch
   claude -p "create a file called HELLO.md with the word hi"
   ```

2. Check `git status` in `../scratch` — you'll see `HELLO.md`.
3. Check `git status` in the original checkout — clean. The edit
   didn't touch it.
4. Clean up:

   ```
   cd -
   git worktree remove ../scratch
   git branch -D scratch
   ```

Now replay the bridge's intuition in your head: it spawns `claude`
with `isolation: worktree`, each task lands somewhere like `../scratch`
automatically, and concurrent dispatches can't stomp on each other.

---

## 13. Further reading

Canonical upstream docs only:

- Overview — https://docs.anthropic.com/en/docs/claude-code/overview
- Settings — https://docs.anthropic.com/en/docs/claude-code/settings
- Hooks — https://docs.anthropic.com/en/docs/claude-code/hooks
- Slash commands — https://docs.anthropic.com/en/docs/claude-code/slash-commands
- Sub-agents — https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Memory — https://docs.anthropic.com/en/docs/claude-code/memory
- MCP in Claude Code — https://docs.anthropic.com/en/docs/claude-code/mcp
- `git worktree` — https://git-scm.com/docs/git-worktree

When you hit something surprising, those pages are the source of truth.
This document is just the map that tells you which page to open.
