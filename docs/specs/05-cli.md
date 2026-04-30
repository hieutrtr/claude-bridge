# CLI Layer

Reference for the `bridge` command-line tool. A maintainer adding a new
subcommand, debugging `bridge setup-bot`, inspecting the generated agent `.md`,
or chasing why `bridge doctor` flags a warning should start here. The CLI is
the only user-visible entry point to the system: every other layer (data,
execution, orchestration, MCP) is reached either through a `bridge`
subcommand or through the MCP server that a `bridge start`-ed session spawns.

The implementation is deliberately framework-free — one dispatcher module with
a manual arg parser and a flat handler registry. There is no Commander/Yargs,
no middleware, no plugin system.

## 1. Files in scope

| File | Role |
| --- | --- |
| `src/cli/index.ts` | Main dispatcher, arg parsing, handler registry, all lifecycle/execution/loop/schedule/daemon/logs/attach commands. |
| `src/cli/setup-bot.ts` | `bridge setup-bot` scaffolder — writes `CLAUDE.md`, `.mcp.json`, `.claude/agents/`, `.claude/settings.local.json`, and persists `bot_dir` into `config.json`. |
| `src/cli/agent-md.ts` | Generates per-agent `.md` files (YAML frontmatter + body) and installs the Stop hook into the project's `.claude/settings.local.json`. |
| `src/cli/claude-md.ts` | `initClaudeMd` helper — spawns `claude -p` to author a project `CLAUDE.md`. Not wired to a subcommand; exposed for future use. |
| `src/cli/memory.ts` | Reads Claude Code's Auto Memory directory for the `bridge memory` command. |
| `src/cli/doctor.ts` | `bridge doctor` self-diagnostic: eleven ordered checks returning `[ok] / [warn] / [fail]`. |
| `src/mcp/bridge-md.ts` | `generateBridgeBotMd()` — produces the `CLAUDE.md` that `setup-bot` writes into the bot directory. Cross-reference only. |

## 2. Binary wiring

`package.json` declares a single bin entry:

```json
"bin": { "bridge": "./src/cli/index.ts" }
```

`src/cli/index.ts` opens with `#!/usr/bin/env bun`, so it is executed directly
by Bun without a build step. After `bun install`, running `bun link` in the
repo (or `bun link claude-bridge` in a consumer) places a `bridge` shim on
PATH. There is no separate build artefact — the TypeScript source is the
distributable.

Equivalent invocations:

| Form | When to use |
| --- | --- |
| `bridge <cmd>` | User-facing and daemon-spawned (via the shim installed by `bun link`). |
| `bun run src/cli/index.ts <cmd>` | Dev-mode — no link required; picks up unstaged edits immediately. Used by tests and by contributors iterating locally. |

The self-reference is important: the Stop hook command embedded into each
agent's `settings.local.json` is literally the string
`CLAUDE_BRIDGE_HOME=... bridge on-complete --session-id ...`
(`src/cli/agent-md.ts:152`). If `bridge` is not on PATH inside the shell that
`claude` uses to run hooks, the on-complete callback silently fails and
`ProcessWatcher` becomes the sole completion path.

## 3. Dispatcher mechanics

All entry through `main(argv?)` at `src/cli/index.ts:999`. The top-level
handler switch is the `COMMAND_HANDLERS` record at
`src/cli/index.ts:865`, and the string `main()` at `src/cli/index.ts:1008`
is the point where a looked-up handler is invoked.

### Argument parsing

No framework. Three helpers at `src/cli/index.ts:68`-`89`:

| Helper | Syntax | Semantics |
| --- | --- | --- |
| `getArg(args, "foo")` | `--foo <value>` | Returns the string after `--foo`, or `undefined`. |
| `getFlag(args, "foo")` | `--foo` | Boolean presence check. |
| `getPositional(args, n)` | Bare tokens | Returns the n-th non-`--` token; each flag **always** consumes the next token as its value. |

The positional walker's assumption — every `--flag` is paired with a value —
is why `setup-bot` maintains its own variant of `getPositional` at
`src/cli/setup-bot.ts:53` that knows `--no-prompt` and `--force` are
value-less flags. Adding a new value-less flag elsewhere requires the same
awareness or a parsing bug ensues (see section 11).

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Command succeeded. |
| `1` | User-visible failure — bad args, agent not found, dispatch failed, daemon install error, doctor check failed, etc. |

Non-zero codes propagate via `main().then(process.exit)` at
`src/cli/index.ts:1027`. There are no other documented exit codes; anything
non-zero is "failure, see stderr".

### Streams

Strict convention enforced throughout:

- **Success output, machine-readable summaries, table rows** go to stdout via
  `console.log`.
- **Errors, usage lines, warnings** go to stderr via
  `process.stderr.write(...)`. Always with a trailing `\n` since writes are
  unbuffered.

This is load-bearing for `bridge on-complete` (spawned by Claude Code's Stop
hook) — anything on stdout is fine; anything on stderr surfaces in the hook's
error log.

### Help and unknown commands

`printUsage()` at `src/cli/index.ts:975` formats the `COMMAND_GROUPS` list
at `src/cli/index.ts:938` into seven sections. `--help` / `-h` / no command
exits 0; an unknown command writes to stderr, prints usage, exits 1
(`src/cli/index.ts:1009`).

## 4. Command catalog

Every handler receives a `CommandContext` ( `src/cli/index.ts:93`) with
`{ db, bridgeHome, config, args }`. Handlers are `async` and return a number
(the exit code). The `db` is opened in `main()` and closed in a `finally` —
handlers must not close it themselves.

### Agent lifecycle

| Command | Handler | One-liner |
| --- | --- | --- |
| `create-agent <name> <path> [--purpose ...] [--model ...]` | `cmdCreateAgent` at `src/cli/index.ts:104` | Validates name, derives `session_id`, writes agent `.md`, installs Stop hook, inserts `agents` row. |
| `delete-agent <name>` | `cmdDeleteAgent` at `src/cli/index.ts:157` | Removes agent `.md` and deletes the DB row. Does **not** purge the Stop hook. |
| `list-agents` | `cmdListAgents` at `src/cli/index.ts:177` | Prints each agent with BUSY flag and model. |
| `set-model <name> <model>` | `cmdSetModel` at `src/cli/index.ts:366` | Validates against `["sonnet","opus","haiku"]`, updates DB. |
| `memory <name>` | `cmdMemory` at `src/cli/index.ts:392` | Formats the Claude Code Auto Memory for the agent's project (section 8). |
| `status [name]` | `cmdStatus` at `src/cli/index.ts:192` | Per-agent state or global agent-count/running-task summary. |

### Task execution

| Command | Handler | One-liner |
| --- | --- | --- |
| `dispatch <agent> <prompt> [--channel ...] [--chat-id ...] [--user-id ...] [--message-id ...]` | `cmdDispatch` at `src/cli/index.ts:225` | Atomically claims or queues the task; on claim, spawns via `Dispatcher.startTask`. |
| `kill <agent>` | `cmdKill` at `src/cli/index.ts:288` | Kills the running task's PID and marks it failed. |
| `history <agent> [--limit N]` | `cmdHistory` at `src/cli/index.ts:323` | Lists recent tasks with status and cost. |
| `cost [agent] [--period ...]` | `cmdCost` at `src/cli/index.ts:352` | Aggregate cost summary. |
| `on-complete --session-id <id>` | `cmdOnComplete` at `src/cli/index.ts:621` | Optimistic Stop-hook callback. See `02-execution-pipeline.md` for the buffering rationale. |

### Loops

| Command | Handler | One-liner |
| --- | --- | --- |
| `loop <agent> <goal> --done-when <cond> [--max ...] [--max-failures ...] [--type ...] [--max-cost ...] [--channel ...] [--chat-id ...] [--user-id ...] [--no-plan] [--pass-threshold N]` | `cmdLoop` at `src/cli/index.ts:411` | Starts a `LoopOrchestrator` run; prints the new `loop_id`. Plan-first is on by default — pass `--no-plan` to skip the planning iter. `--pass-threshold N` requires N consecutive PASS verdicts before terminating (default 1; raise to 2–3 for `llm_judge` / flaky `command:`). |
| `loop-status [name] [--loop-id id]` | `cmdLoopStatus` at `src/cli/index.ts:448` | Single loop detail if `--loop-id` given, else list of active loops. |
| `loop-cancel <loop_id>` | `cmdLoopCancel` at `src/cli/index.ts:477` | Cancel a running loop. |
| `loop-approve <loop_id>` | `cmdLoopApprove` at `src/cli/index.ts:490` | Approve a loop waiting for human review. |
| `loop-reject <loop_id> [--feedback ...]` | `cmdLoopReject` at `src/cli/index.ts:503` | Reject and optionally restart the loop with feedback. |
| `loop-list [name] [--limit N] [--active]` | `cmdLoopList` at `src/cli/index.ts:518` | Table of loops. |
| `loop-history <loop_id>` | `cmdLoopHistory` at `src/cli/index.ts:534` | Per-iteration history for one loop. |

See `03-orchestration.md` for the loop state machine and plan-first mode (§1.6).

### Schedules

| Command | Handler | One-liner |
| --- | --- | --- |
| `schedule-add <agent> <prompt> --every <min> [--name ...] [--channel ...] [--chat-id ...] [--user-id ...] [--once]` | `cmdScheduleAdd` at `src/cli/index.ts:552` | Inserts a row in `schedules`; scheduler daemon picks it up. |
| `schedule-remove <name_or_id>` | `cmdScheduleRemove` at `src/cli/index.ts:576` | Delete by numeric id or name. |
| `schedule-list [--agent ...] [--all]` | `cmdScheduleList` at `src/cli/index.ts:587` | Default hides disabled; `--all` includes them. |
| `schedule-pause <name_or_id>` | `cmdSchedulePause` at `src/cli/index.ts:603` | Set `enabled=0`. |
| `schedule-resume <name_or_id>` | `cmdScheduleResume` at `src/cli/index.ts:611` | Set `enabled=1`. |

### Bot lifecycle

| Command | Handler | One-liner |
| --- | --- | --- |
| `start` | `cmdStart` at `src/cli/index.ts:676` | Launch daemon if installed, else start a tmux session running `claude` in `bot_dir`. Auto-enters on the two first-launch confirmation prompts. |
| `stop` | `cmdStop` at `src/cli/index.ts:751` | Stop daemon if installed, else kill tmux session. |
| `restart` | `cmdRestart` at `src/cli/index.ts:762` | Stop (best-effort) + start. |
| `attach` | `cmdAttach` at `src/cli/index.ts:826` | `tmux attach -t <session>`. See section 11. |
| `daemon-status` | `cmdDaemonStatus` at `src/cli/index.ts:802` | Platform, daemon install/status, session name/PID/uptime, log path. |
| `logs [--tail N] [--follow|-f]` | `cmdLogs` at `src/cli/index.ts:841` | `tail` on the bridge log file. |

### Setup / daemon

| Command | Handler | One-liner |
| --- | --- | --- |
| `setup-bot <dir> [--telegram-token ...] [--no-prompt] [--force]` | `cmdSetupBot` at `src/cli/setup-bot.ts:134` | Scaffold bot directory (section 5). |
| `install [--auto-start]` | `cmdInstall` at `src/cli/index.ts:772` | Write launchd plist / systemd unit; optionally start it. |
| `uninstall` | `cmdUninstall` at `src/cli/index.ts:796` | Remove daemon service file. |

### Diagnostics

| Command | Handler | One-liner |
| --- | --- | --- |
| `doctor` | `cmdDoctor` at `src/cli/doctor.ts:54` | Eleven ordered self-checks (section 9). |

## 5. `setup-bot`

Entry: `src/cli/setup-bot.ts:134`. Produces the directory layout that
`bridge start` spawns `claude` inside. The resulting `bot_dir` becomes the cwd
of the tmux session, so Claude Code auto-loads `CLAUDE.md` and `.mcp.json`
from it.

### Scaffolded layout

```
{bot_dir}/
  CLAUDE.md                        generateBridgeBotMd() output (MCP tool docs + behaviour rules)
  .mcp.json                        {"mcpServers": {"bridge": {"command": "bun", "args": ["run", "<repo>/src/mcp/server.ts"], "env": {...}}}}
  .claude/
    agents/                        empty — per-agent .md files land here on create-agent
    settings.local.json            permissions.allow baked with DEFAULT_ALLOW + defaultMode: acceptEdits
```

`CLAUDE.md` is sourced from `src/mcp/bridge-md.ts` (not from `src/cli/claude-md.ts`).
The scaffolder calls `generateBridgeBotMd()` at `src/cli/setup-bot.ts:168`.

`.mcp.json` is assembled inline at `src/cli/setup-bot.ts:198`. The `command`
is hard-coded to `bun`; `args[1]` is an absolute path resolved via
`findRepoRoot()` at `src/cli/setup-bot.ts:100` (walks up from
`import.meta.url` looking for a `package.json` whose `name` is
`"claude-bridge"`). The bot's `CLAUDE_BRIDGE_HOME` env is pinned so the MCP
server reads the right DB.

`.claude/settings.local.json` is written or merged by `writeSettingsLocal` at
`src/cli/setup-bot.ts:277`. `DEFAULT_ALLOW` at `src/cli/setup-bot.ts:246`
pre-approves the built-in tools (Read/Write/Edit/Bash/…) plus
`mcp__bridge__*`. On a pre-existing file the merger adds missing allow
entries, sets `defaultMode: acceptEdits` only if unset, forces
`enableAllProjectMcpServers: true`, and bails out without writing if the file
has an ambiguous shape. `--force` replaces the file outright.

### Config persistence

`setup-bot` also writes `{bridgeHome}/config.json` via `saveConfig` at
`src/cli/setup-bot.ts:28`, preserving prior keys and updating
`{ home_dir, db_path, bot_dir, telegram_token, telegram_chat_id }`. This is
what every subsequent `bridge` command reads via `loadConfig` at
`src/cli/index.ts:52`.

### Interactive vs non-interactive

| Mode | Trigger | Behaviour |
| --- | --- | --- |
| Interactive (default) | No `--no-prompt` | Prompts to overwrite a non-empty directory; prompts for a Telegram token if not supplied via flag or prior config. `ask()` at `src/cli/setup-bot.ts:72` uses Bun's `prompt()` or falls back to stdin. |
| Non-interactive | `--no-prompt` | Refuses to overwrite non-empty dirs unless `--force`; skips the token prompt (warns on stderr if unset). |
| Forced | `--force` | Allows overwriting a non-empty bot dir and rewriting `settings.local.json` unconditionally. |
| Token from CLI | `--telegram-token <tok>` | Always wins over prior config and over the interactive prompt. |

## 6. Agent `.md` generation

Entry: `generateAgentMd()` at `src/cli/agent-md.ts:53`. Template at
`src/cli/agent-md.ts:13`.

### Frontmatter schema

```yaml
---
name: bridge--{session_id}
model: {model}                      # sonnet | opus | haiku
tools: [Read, Edit, Write, Bash, Grep, Glob, Agent]
allowedTools: [mcp__claude-bridge__*]
isolation:
  type: worktree
memory:
  enabled: true
hooks:
  stop:
    - command: "CLAUDE_BRIDGE_HOME=... bridge on-complete --session-id <id>"
---
```

The `hooks.stop` block in frontmatter is **cosmetic**. Claude Code ignores it
— the real Stop hook must live in `{project_dir}/.claude/settings.local.json`
under the capitalised `Stop` key with the nested
`{ hooks: [{ type: "command", command: ... }] }` shape. `installStopHook` at
`src/cli/agent-md.ts:134` does the real wiring and also migrates legacy
lowercase `stop` entries and flat `{command}` groups into the current format.
See `02-execution-pipeline.md` §Stop-hook for the full semantics.

### Body

Static markdown with `# {agent_name}`, a `**Purpose:**` line, and a `Rules`
section. Purely informational for the agent to read at startup — the bridge
does not parse it back.

### Write location

`writeAgentMd` at `src/cli/agent-md.ts:73` writes to
`{bot_dir}/.claude/agents/bridge--{session_id}.md` when `bot_dir` is set in
config (the normal case), otherwise to `~/.claude/agents/` as a fallback.
Project-level placement is what gives each bot instance its own isolated
agent namespace — distinct `CLAUDE_BRIDGE_HOME` dirs get distinct
`config.bot_dir` dirs get distinct agent files.

`deleteAgentMd` at `src/cli/agent-md.ts:93` tries `bot_dir` first, falls back
to the home location.

## 7. `CLAUDE.md` generation

Two separate generators, not to be confused:

| File | Purpose | Invoked by |
| --- | --- | --- |
| `src/mcp/bridge-md.ts` (`generateBridgeBotMd`) | Builds the bot's own `CLAUDE.md` — MCP tool documentation, message-processing flow, behaviour rules. | `bridge setup-bot`, at `src/cli/setup-bot.ts:168`. |
| `src/cli/claude-md.ts` (`initClaudeMd`) | Spawns `claude -p` with a documentation prompt to write or append a generic project `CLAUDE.md`. | Not currently wired to any subcommand; exposed for future use / tests. |

The top-level `/Users/hieutran11/projects/claude-bridge/CLAUDE.md` is
hand-written (it documents claude-bridge itself) and is **not** a generated
artefact. Do not edit it via a tool.

## 8. `memory` command

Entry: `cmdMemory` at `src/cli/index.ts:392` → `formatMemoryReport` at
`src/cli/memory.ts:79`.

Claude Code stores per-project Auto Memory under
`~/.claude/projects/{encoded-project-dir}/memory/`, where the encoding
replaces `/` with `-`. `findMemoryDir` at `src/cli/memory.ts:23` applies that
encoding first, then falls back to a basename-suffix scan of
`~/.claude/projects/` so the command still works if Claude Code's encoding
scheme drifts.

The memory dir contains:

- `MEMORY.md` — the main rolling memory file. Rendered first, verbatim, under
  a `--- Main Memory ---` header.
- Any other `*.md` — topic files. Rendered as `[topic]` sections under a
  `--- Topics (N) ---` header.

If the directory does not exist the command prints
`No memory found for agent "<name>" (<project>)` and exits 0.

## 9. `doctor` checks

`cmdDoctor` at `src/cli/doctor.ts:54` runs checks in fixed order and counts
`[fail]` lines. Returns `0` if the failure count is zero, `1` otherwise.
`[warn]` never contributes to the failure count.

| # | Check | Source | `[ok]` when | `[warn]` when | `[fail]` when |
| --- | --- | --- | --- | --- | --- |
| 1 | `bridge` on PATH | `doctor.ts:58` | `which bridge` succeeds | Not on PATH (advises `bun link`) | — (warn only) |
| 2 | `claude` on PATH | `doctor.ts:65` | `which claude` succeeds | — | `claude` missing |
| 3 | `tmux` available | `doctor.ts:73` | `tmuxAvailable()` true | — | `tmux` not installed |
| 4 | `bot_dir` configured | `doctor.ts:81` | `config.bot_dir` set and dir exists | — | Unset, or set but missing |
| 5 | `CLAUDE.md` present | `doctor.ts:93` | `{bot_dir}/CLAUDE.md` exists | — | Missing (advises `setup-bot --force`) |
| 6 | `.mcp.json` valid | `doctor.ts:104` | File exists and parses as JSON | — | Missing or invalid JSON |
| 7 | `settings.local.json` allows bridge tools | `doctor.ts:121` | Parsed, `permissions.allow` contains an entry matching `mcp__bridge` | File missing, invalid JSON, or no bridge entry | — (warn only) |
| 8 | Telegram token configured | `doctor.ts:152` | `config.telegram_token` (or legacy `telegram_bot_token`) set | Unset | — (warn only) |
| 9 | Daemon `WorkingDirectory` matches `bot_dir` | `doctor.ts:162` | Not installed, **or** installed and plist/unit's `WorkingDirectory` equals `bot_dir` | Can't parse `WorkingDirectory` from the service file | Installed but `WorkingDirectory` differs from `bot_dir` (advises `uninstall && install`) |
| 10 | Daemon running (informational) | `doctor.ts:199` | Status is `running` / `active` | Any other status | — |
| 11 | tmux session running (informational) | `doctor.ts:208` | `sessionRunning(getSessionName(...))` true | Not running | — |

Check 9 is the subtle one. `getDaemonConfigPath` at `src/cli/doctor.ts:43`
looks for the launchd plist at
`~/Library/LaunchAgents/{label}.plist` on macOS and the systemd unit at
`~/.config/systemd/user/{service}.service` on Linux. The `WorkingDirectory`
is parsed with a regex — a plist with unusual whitespace or an XML comment
between `<key>` and `<string>` can produce a spurious `[warn]` even when the
daemon is correctly configured.

## 10. Adding a new subcommand

1. Write an `async function cmdFoo(ctx: CommandContext): Promise<number>` in
   `src/cli/index.ts` (or in a new file under `src/cli/` if the command has
   non-trivial logic — import and wire it like `cmdDoctor`).
2. Parse args via `getPositional` / `getArg` / `getFlag`. If you introduce a
   value-less flag, remember that `getPositional` will misalign positional
   indices unless you teach a local parser about it (as `setup-bot` does).
3. Write errors via `process.stderr.write(...)` with a trailing `\n`; write
   successes via `console.log`. Return `0` on success, `1` on failure.
4. Register the command in `COMMAND_HANDLERS` (`src/cli/index.ts:865`),
   add a description to `COMMAND_DESCRIPTIONS` (`src/cli/index.ts:901`),
   and append the name to the appropriate group in `COMMAND_GROUPS`
   (`src/cli/index.ts:938`). Commands with no group fall through to `Other`.
5. Add a test under `tests/wave5/` (or the wave matching its concern).
   Always mock subprocess spawns — `claude` is never called for real in
   tests.
6. Update the `## CLI commands` section of the top-level `CLAUDE.md` if the
   command is user-visible.

## 11. Gotchas

### `CLAUDE_BRIDGE_HOME` resolution

`getBridgeHome()` at `src/cli/index.ts:48` reads the env var once at process
start and caches nothing — every subprocess invocation must export it again.
The Stop hook embeds the value literally in the hook command
(`src/cli/agent-md.ts:152`), so changing `CLAUDE_BRIDGE_HOME` after
creating agents leaves stale hook commands pointing at the old home. Re-run
`create-agent` to refresh.

### Argument ordering

The manual positional walker treats every `--flag` as consuming the next
token. A user who writes
`bridge dispatch --chat-id 123 backend "add pagination"` gets the positional
`backend` as arg-0 and `"add pagination"` as arg-1, which works. But
`bridge dispatch backend --chat-id 123 "add pagination"` also works — the
parser skips `--chat-id 123` and keeps walking for the next positional. Do
**not** add a value-less flag without also updating the walker, or you will
shift positional indices for every user of that command.

### Global flags

There are no global flags. `--help`/`-h` are only recognised when they appear
as the first token (`src/cli/index.ts:1003`). Per-command usage strings are
the only in-CLI help.

### `attach` and tmux

`cmdAttach` at `src/cli/index.ts:826` shells out to `tmux attach -t <name>`
with `stdio: "inherit"`, so the user's terminal is handed over directly. It
intentionally swallows non-zero exit codes because `tmux` returns non-zero
when the user detaches with `Ctrl-b d` or interrupts. Session naming and the
list of tmux invariants live in `06-infrastructure.md`.

### DB lifecycle

The DB is opened in `main()` and closed in the `finally`
(`src/cli/index.ts:1017`-`1023`). Handlers that spawn long-running
orchestrators must not keep references to `ctx.db` past their own return —
the `Dispatcher` and `LoopOrchestrator` used by interactive handlers are
short-lived and safe. For persistent subsystems see `StartupOrchestrator` in
`src/infra/startup.ts`.

### `on-complete` is optimistic

`cmdOnComplete` at `src/cli/index.ts:621` deliberately no-ops when the result
file is not yet readable, because Claude Code's Stop hook fires *before*
stdout is flushed. `ProcessWatcher` is the authoritative completion path. Do
not add stderr output to this handler's fast path — it runs inside `claude`
and noisy stderr shows up in user-visible error logs. See
`02-execution-pipeline.md`.
