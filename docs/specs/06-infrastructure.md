# Infrastructure Layer

Reference for the daemon, tmux session, permission relay, config resolution,
and multi-instance support. Read this when debugging "bridge won't start as a
daemon," rebuilding the launchd/systemd unit after an upgrade, or standing up
a second instance under a distinct `CLAUDE_BRIDGE_HOME`.

## 1. Files in scope

| File | Role |
| --- | --- |
| `src/infra/daemon.ts` | launchd plist + systemd unit generation, install/uninstall, start/stop/status. |
| `src/infra/startup.ts` | `StartupOrchestrator` — boots `ProcessWatcher`, notification loop, MCP server. |
| `src/infra/permissions.ts` | Permission-relay hook handler: writes request, polls DB, exits 0/2. |
| `src/infra/bridge-cmd.ts` | tmux helpers (name, start, stop, pid, uptime), config validation, cleanup. |
| `src/infra/index.ts` | Barrel export. |
| `src/config.ts` | `ConfigProvider` — resolves `CLAUDE_BRIDGE_HOME`, loads `config.json`, env fallbacks. |
| `src/cli/index.ts` lifecycle handlers | Thin CLI shims: `cmdStart`, `cmdStop`, `cmdRestart`, `cmdInstall`, `cmdUninstall`, `cmdDaemonStatus`, `cmdAttach`, `cmdLogs`. |

## 2. Command → mechanism map

| Command | CLI handler | Underlying call | Effect |
| --- | --- | --- | --- |
| `bridge install` | `cmdInstall` (`src/cli/index.ts:772`) | `installDaemon` (`src/infra/daemon.ts:206`) | Writes plist or unit; `--auto-start` also calls `startDaemon`. |
| `bridge uninstall` | `cmdUninstall` (`src/cli/index.ts:796`) | `uninstallDaemon` (`src/infra/daemon.ts:242`) | `bootout` (macOS) / `stop && disable` (Linux), deletes unit. |
| `bridge start` | `cmdStart` (`src/cli/index.ts:676`) | `startDaemon` (`src/infra/daemon.ts:276`) if installed, else `startSession` (`src/infra/bridge-cmd.ts:50`). | Loads/kickstarts supervisor, or spawns a direct tmux session. |
| `bridge stop` | `cmdStop` (`src/cli/index.ts:751`) | `stopDaemon` (`src/infra/daemon.ts:333`) or `stopSession` (`src/infra/bridge-cmd.ts:88`). | Unloads plist / `systemctl stop`, or sends `C-c` then kills tmux. |
| `bridge restart` | `cmdRestart` (`src/cli/index.ts:762`) | `cmdStop` then `cmdStart`. | Best-effort stop. |
| `bridge attach` | `cmdAttach` (`src/cli/index.ts:826`) | `tmux attach -t <session>`. | Interactive (`stdio: "inherit"`). |
| `bridge daemon-status` | `cmdDaemonStatus` (`src/cli/index.ts:802`) | `getDaemonStatus` + `sessionRunning` + `getSessionPid` + `getSessionUptime`. | Prints platform, install state, session pid/uptime, log path. |
| `bridge logs [--tail N] [-f]` | `cmdLogs` (`src/cli/index.ts:841`) | `tail -n N [-f] <logPath>`. | Streams the combined log. |
| `bridge status` | `cmdStatus` (`src/cli/index.ts:192`) | `db.listAgents` + `db.getRunningTasks`. | Application status, not daemon. |

## 3. Daemon model

### 3.1 Platform detection

`getPlatform()` (`src/infra/daemon.ts:17`) maps `process.platform` to
`"macos" | "linux" | "other"`. `installDaemon` (`src/infra/daemon.ts:206`)
dispatches on that value; `"other"` bails with `Unsupported platform`.
`isContainerEnvironment()` (`src/infra/daemon.ts:24`) is exported but not
wired into any flow — callers that need container-safe behavior must call
it explicitly.

### 3.2 Service names and file paths

Both service name and launchd label derive from `basename(CLAUDE_BRIDGE_HOME)`:

- `getServiceName` (`src/infra/daemon.ts:35`) — strips `.` from the basename.
  `~/.claude-bridge` → `claude-bridge`; `~/.claude-bridge-tam` →
  `claude-bridge-tam`.
- `getLaunchdLabel` (`src/infra/daemon.ts:41`) — prefixes `ai.`, yielding
  `ai.claude-bridge` or `ai.claude-bridge-tam`.

| Resource | Path |
| --- | --- |
| macOS plist | `~/Library/LaunchAgents/ai.<service>.plist` (`src/infra/daemon.ts:45`) |
| Linux unit | `~/.config/systemd/user/<service>.service` (`src/infra/daemon.ts:49`) |
| Log file | `<CLAUDE_BRIDGE_HOME>/bridge.log` (`src/infra/bridge-cmd.ts:24`; default in `installDaemon` at `src/infra/daemon.ts:211`) |

### 3.3 Wrapper script

Both plist and unit delegate to a shared shell wrapper built by
`buildWrapperScript` (`src/infra/daemon.ts:71`):

1. Checks `tmux has-session`; if absent calls `tmux new-session -d -s
   <session> -c <botDir>` with the inner command
   `CLAUDE_BRIDGE_HOME=<home> claude --dangerously-load-development-channels
   server:bridge --dangerously-skip-permissions` (`src/infra/daemon.ts:83`).
2. `tmux pipe-pane` routes pane output to `$logfile`
   (`src/infra/daemon.ts:84`).
3. Sends two `Enter` keystrokes spaced by `sleep` to auto-acknowledge the
   "Loading development channels" and "bypass permissions" warnings
   (`src/infra/daemon.ts:86-91`).
4. `while tmux has-session ... do sleep 30; done` keeps the wrapper alive
   so launchd `KeepAlive=true` / systemd `Restart=on-failure` only respawns
   on real death (`src/infra/daemon.ts:95`).

Step 4 is load-bearing: without it, the wrapper exits after spawning, and
the supervisor would treat that as death and respawn endlessly.

### 3.4 launchd plist

`generateLaunchdPlist` (`src/infra/daemon.ts:130`) emits:

- `Label` = `getLaunchdLabel`.
- `ProgramArguments = ["/bin/bash", "-lc", <xml-escaped wrapper>]` — `-l`
  sources the login-shell rc.
- `WorkingDirectory = botDir`.
- `EnvironmentVariables`: `CLAUDE_BRIDGE_HOME`, `HOME`, `PATH` (see §3.6).
- `RunAtLoad = true`, `KeepAlive = true`.
- `StandardOutPath` / `StandardErrorPath` = log path.

The script is inlined via `xmlEscape` (`src/infra/daemon.ts:104`); the
script deliberately avoids `<`, `>`, `&` (comment at
`src/infra/daemon.ts:67`) so escaping cannot mangle it.

### 3.5 systemd unit

`generateSystemdUnit` (`src/infra/daemon.ts:173`) flattens the wrapper into
`; `-joined statements and wraps it as `ExecStart=/bin/bash -lc "<script>"`
(`src/infra/daemon.ts:195`). Fixed choices:

- `Type=simple` — wrapper stays alive, no forking.
- `Restart=on-failure`, `RestartSec=10`.
- `ExecStop=/usr/bin/tmux kill-session -t <service>` — explicit teardown.
- `Environment=CLAUDE_BRIDGE_HOME=...`, `HOME=...`, `PATH=<resolveServicePath>`.
- `WantedBy=default.target` (user unit under `systemctl --user`).

### 3.6 PATH resolution

`resolveServicePath()` (`src/infra/daemon.ts:111`) builds PATH from scratch:

```
~/.local/bin:~/.bun/bin:~/.cargo/bin:/opt/homebrew/bin:/opt/homebrew/sbin:
/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
```

This list is the single most common cause of daemon startup failures. If
`claude`, `bun`, or `tmux` lives outside this list (asdf shims, nix store,
`~/go/bin`, Volta), the wrapper fails silently and the supervisor keeps
respawning. Symptom: log shows `claude: command not found` or the session
never appears in `tmux ls`.

### 3.7 Install / uninstall

`installLaunchd` (`src/infra/daemon.ts:219`) — `mkdir -p` the LaunchAgents
dir, write the plist. Does **not** load it; `bridge install` only writes,
and `bridge start` bootstraps (unless `--auto-start` — see
`src/cli/index.ts:786`).

`installSystemd` (`src/infra/daemon.ts:228`) — create dir, write unit, run
`systemctl --user daemon-reload`. Also does not start.

`uninstallDaemon` (`src/infra/daemon.ts:242`) — macOS: `launchctl bootout
gui/<uid> <plistPath>` (errors swallowed), then `unlinkSync`. Linux:
`systemctl --user stop && disable`, unlink, `daemon-reload`.

## 4. `bridge start` process lifecycle

`cmdStart` (`src/cli/index.ts:676`) splits on `isDaemonInstalled`:

**Daemon installed.** `startDaemon` (`src/infra/daemon.ts:276`):

- macOS: `launchctl print gui/<uid>/<label>` probes prior bootstrap
  (`src/infra/daemon.ts:291`). Loaded → `launchctl kickstart -k` (force
  restart). Not loaded → `launchctl bootstrap gui/<uid> <plistPath>`.
- Linux: `systemctl --user is-active` → `restart` if active, else `start`
  (`src/infra/daemon.ts:306`).

On error strings containing `"input/output error"`, `"already"`, or
`"bootstrap"`, `cmdStart` diagnoses via `plistLoaded`
(`src/cli/index.ts:665`, macOS-only, `launchctl list | grep <label>`) and
recommends `bridge uninstall && bridge install`
(`src/cli/index.ts:707-713`).

**No daemon.** `cmdStart` calls `startSession` (`src/infra/bridge-cmd.ts:50`)
with the command array at `src/cli/index.ts:722`:

```ts
["env", `CLAUDE_BRIDGE_HOME=${ctx.bridgeHome}`, "claude",
 "--dangerously-load-development-channels", "server:bridge",
 "--dangerously-skip-permissions"]
```

The `env VAR=...` prefix sidesteps tmux's unreliable env inheritance over
ssh/login-shell boundaries. After the session comes up, `cmdStart` replays
the same two-`Enter` auto-accept sequence the wrapper uses
(`src/cli/index.ts:737`).

### 4.1 Fork model

There is no `fork()`. Process tree under the daemon:

```
launchd / systemd --user
 └─ /bin/bash -lc "<wrapper>"                [persistent]
     └─ tmux new-session -d ... "env CLAUDE_BRIDGE_HOME=... claude ..."
         └─ (tmux server — itself a daemon)
             └─ claude (MCP stdio)
                 └─ dispatcher-spawned subprocesses
```

Without the daemon, the top two layers are replaced by a one-shot
foreground `bridge` CLI that calls `tmux new-session -d` once and exits;
the tmux server is the daemon in that configuration.

## 5. `StartupOrchestrator`

`src/infra/startup.ts:22`. Invoked not by `bridge start` directly, but by
`server:bridge` once `claude` loads the MCP entrypoint inside the tmux
session. Construction order (`src/infra/startup.ts:31-54`):

1. Open SQLite at `<home>/bridge.db`.
2. Build `Dispatcher(home)`.
3. Build `LoopOrchestrator(home, db, new LoopEvaluator(), dispatcher)`.
4. Build `ProcessWatcher(home, db, dispatcher, orchestrator.onTaskComplete)`
   — the callback wiring lets the watcher finalise the task, advance any
   loop, and dequeue the next task in one pass when `claude` exits.
5. `watcher.start(WATCHER_INTERVAL_MS)` — polls every **5,000 ms**
   (`WATCHER_INTERVAL_MS` at `src/infra/startup.ts:19`).
6. `startNotificationLoop()` sets a `setInterval` at `NOTIFICATION_INTERVAL_MS`
   = **5,000 ms** (`src/infra/startup.ts:20`, timer at `:63`). Each tick
   reads `db.getPendingNotifications()` and flushes via `Notifier.notify`.
   Timer is `.unref()`ed (`src/infra/startup.ts:84`) so it does not anchor
   process liveness.
7. `await startServer()` — MCP stdio, blocks for the rest of the process's
   life (`src/infra/startup.ts:54`).

Database open before `Dispatcher` matters for worktree setup. Watcher
needs both Dispatcher (for dequeue) and the orchestrator callback (for
loops). MCP server last because it blocks.

`stop()` (`src/infra/startup.ts:90`) stops the watcher, clears the interval,
closes the DB. Called only from tests — in production, process exit tears
it all down.

## 6. PID / liveness

There is no dedicated pid file. Liveness is derived from tmux:

- `sessionRunning` (`src/infra/bridge-cmd.ts:40`) — `tmux has-session -t
  <name>`.
- `getSessionPid` (`src/infra/bridge-cmd.ts:116`) — `tmux list-panes -t
  <name> -F "#{pane_pid}"`, first line. This is the pane shell pid, not
  necessarily `claude`'s pid.
- `getSessionUptime` (`src/infra/bridge-cmd.ts:130`) — `now -
  #{session_created}`, rendered by `formatDuration`
  (`src/infra/bridge-cmd.ts:198`).

`cmdDaemonStatus` (`src/cli/index.ts:802`) composes the report:

```
Platform:         macos | linux | other
Daemon installed: yes | no
Daemon status:    running | stopped | active | inactive | not installed
Session:          <tmux session name>
Session running:  yes | no
Session PID:      <pane pid>           # only if running
Session uptime:   <Nd Nh Nm>           # only if running
Log path:         <home>/bridge.log
```

`getDaemonStatus` (`src/infra/daemon.ts:356`) returns `"running"` only when
`launchctl print` includes `state = running`; otherwise macOS reads
`"stopped"` or (on exception) `"not installed"`. Linux mirrors
`systemctl --user is-active`.

## 7. Log management

Single combined log at `<home>/bridge.log` (`src/infra/bridge-cmd.ts:24`).
Every pane write flows through `tmux pipe-pane "cat >> <logfile>"`
(`src/infra/daemon.ts:84`, `src/infra/bridge-cmd.ts:77`). No rotation, no
size cap — rotate externally.

Under the daemon, launchd also writes `StandardOutPath` /
`StandardErrorPath` to the same file (`src/infra/daemon.ts:165-168`): the
wrapper's stdout/stderr goes through this path, the tmux pane goes through
`pipe-pane`. Both append to the same file, interleaved.

`cmdLogs` (`src/cli/index.ts:841`) shells out to `tail -n <N> [-f]
<logPath>`. Defaults: `--tail 50`, no follow. Non-zero exit from `tail -f`
on Ctrl-C is treated as clean (`src/cli/index.ts:857`).

## 8. tmux integration

tmux is used in every configuration — no non-tmux path. `tmuxAvailable()`
(`src/infra/bridge-cmd.ts:31`) gates `startSession`, and the wrapper
script uses tmux unconditionally.

### 8.1 Session naming

`getSessionName` (`src/infra/bridge-cmd.ts:15`): default home →
`claude-bridge`; any other home → `claude-bridge-<hash>` where hash is
`Bun.hash(basename).toString(16).slice(0, 8)`.

This differs from `getServiceName` (`src/infra/daemon.ts:35`), which
preserves the basename verbatim (minus dots). The two diverge for custom
homes: the daemon wrapper uses the plain service name as the tmux session
(`src/infra/daemon.ts:136-137`), while the direct path uses the hashed
form (`src/infra/bridge-cmd.ts:55`). For the default home they collide.
**Latent inconsistency**: under the daemon branch for a custom home, the
wrapper may spawn a session named `claude-bridge-tam` while
`bridge daemon-status` probes for `claude-bridge-<hash>`. See §11.

### 8.2 Attach and stop

`cmdAttach` (`src/cli/index.ts:826`) — `tmux attach -t <hashed-name>` with
`stdio: "inherit"`. Non-zero exit on detach (Ctrl-b d) is swallowed.

`stopSession` (`src/infra/bridge-cmd.ts:88`) — `C-c`, poll `has-session`
every 500 ms up to `timeout` (default 5 s), then `tmux kill-session` as
last resort. `C-c` is what lets `claude` flush buffers and close sqlite
cleanly; `kill-session` is a hard kill.

### 8.3 Bulk cleanup

`killBridgeProcesses` (`src/infra/bridge-cmd.ts:174`) — `pkill -f` over
three patterns: `claude.*bridge-bot`, `bun.*bridge`, `claude-bridge`
(`src/infra/bridge-cmd.ts:168`). Exported, not wired into any CLI command
— reserved for `bridge doctor` / manual recovery.
`bridgeProcessesRunning` (`src/infra/bridge-cmd.ts:182`) is its read-only
`pgrep` counterpart.

## 9. Permission relay

`src/infra/permissions.ts` implements the `PreToolUse` hook that Claude
Code fires before a dangerous tool call. Invoked as `bridge
permission-relay --session-id ... --tool ... --command ... --description
... [--timeout N]` (`src/infra/permissions.ts:71`).

Flow:

1. `handlePermissionRequest` (`src/infra/permissions.ts:23`) mints an 8-char
   UUID slice, calls `db.createPermission(requestId, sessionId, tool,
   command, description)`. Channel adapter surfaces it to the user.
2. Poll every `POLL_INTERVAL` = **2,000 ms** (`src/infra/permissions.ts:13`)
   reading `db.getPermission(requestId)`. Exit 0 on `"approved"`, exit 2
   on `"denied"` or record-missing (`:48`).
3. On timeout (`DEFAULT_TIMEOUT` = **300 s**; `src/infra/permissions.ts:12`),
   call `db.respondPermission(requestId, false)` and exit 2 (`:57`).

| Exit | Meaning |
| --- | --- |
| 0 | Approved — tool call proceeds. |
| 2 | Denied or timed out — tool call blocked. |
| 1 | Caller error (`--session-id` missing). |

The relay is fire-and-wait: one shell slot per pending request for up to
5 minutes. The approve/deny UI lives in the channel adapter.

## 10. Configuration

`ConfigProvider` (`src/config.ts:15`) is the single source of truth.

### 10.1 Home directory resolution

Precedence (`src/config.ts:20`):

1. Explicit `homeDir` constructor arg (CLI plumbing passes `ctx.bridgeHome`).
2. `process.env.CLAUDE_BRIDGE_HOME`.
3. `~/.claude-bridge` (`DEFAULT_HOME` at `src/config.ts:13`).

### 10.2 `config.json` keys

Loaded from `<home>/config.json` (`src/config.ts:25`); missing file is not
an error — all fields fall back. Shape is `BridgeConfig` in
`src/types.ts:225`.

| Key | Type | Source (in order) | Notes |
| --- | --- | --- | --- |
| `home_dir` | string | Constructor / env / default | Set at construction; never read from config.json. |
| `db_path` | string | Derived | `<home_dir>/bridge.db`; not user-configurable. |
| `bot_dir` | string \| null | `config.json.bot_dir` | Required before `bridge start`. |
| `telegram_token` | string \| null | `config.json.telegram_token` → env `TELEGRAM_BOT_TOKEN` | Required before start. |
| `telegram_chat_id` | string \| null | `config.json.telegram_chat_id` → env `TELEGRAM_CHAT_ID` | Default chat for outbound. |

No other keys are read — extra entries in `config.json` are ignored.

### 10.3 Validation

`validateConfig` (`src/infra/bridge-cmd.ts:149`) runs from `cmdStart`
before any daemon or tmux call. It accumulates errors for:
`bot_dir` unset, `bot_dir` does not exist, `telegram_token` unset.
`cmdStart` prints each prefixed with `  - ` and returns exit 1
(`src/cli/index.ts:684-687`).

## 11. Multi-instance pattern

All identity flows from `CLAUDE_BRIDGE_HOME`:

```
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge install
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge start
CLAUDE_BRIDGE_HOME=~/.claude-bridge-tam bridge daemon-status
```

| Resource | Main (default) | Tam instance |
| --- | --- | --- |
| DB | `~/.claude-bridge/bridge.db` | `~/.claude-bridge-tam/bridge.db` |
| Log | `~/.claude-bridge/bridge.log` | `~/.claude-bridge-tam/bridge.log` |
| Config | `~/.claude-bridge/config.json` | `~/.claude-bridge-tam/config.json` |
| Launchd label | `ai.claude-bridge` | `ai.claude-bridge-tam` |
| Systemd unit | `claude-bridge.service` | `claude-bridge-tam.service` |
| Plist path | `~/Library/LaunchAgents/ai.claude-bridge.plist` | `~/Library/LaunchAgents/ai.claude-bridge-tam.plist` |
| Unit path | `~/.config/systemd/user/claude-bridge.service` | `~/.config/systemd/user/claude-bridge-tam.service` |
| tmux (daemon) | `claude-bridge` | `claude-bridge-tam` (service name — see §8.1) |
| tmux (direct) | `claude-bridge` | `claude-bridge-<hash>` (`getSessionName`) |

Names coincide on the default home; they diverge for custom homes. An
operator who toggles between `install && start` and raw `start` on the
same custom home may end up with two parallel tmux sessions — check
`tmux ls` before diagnosing.

Session IDs in the DB (`<agent>--<project-basename>`) are per-DB-file and
therefore per-instance. Two instances can hold the same agent name against
the same project without conflict — they never share storage.

## 12. Gotchas

- **Stale plist.** If `claude` moved, `bridge uninstall && bridge install`
  regenerates the wrapper. `cmdStart` detects the stuck state and emits the
  recovery hint (`src/cli/index.ts:708-712`).
- **`bootout` vs. `remove`.** `stopDaemon` uses `bootout`
  (`src/infra/daemon.ts:343`), which fully unloads the plist rather than
  just stopping the process. Consequence: the next `bridge start` takes
  the `bootstrap` branch (`src/infra/daemon.ts:303`), not `kickstart`.
  Functionally equivalent; the telemetry line differs.
- **Orphaned tmux sessions.** systemd runs `ExecStop=tmux kill-session`, but
  launchd has no parallel — `bootout` kills the wrapper, which notices the
  session is gone on its 30 s poll. Manually running `tmux kill-session`
  causes launchd to respawn the wrapper within seconds. To fully stop on
  macOS, always use `bridge stop`.
- **Re-installing after an update.** The wrapper is templated with absolute
  paths at install time. Upgrading `claude` / `bun` within a directory
  already listed in `resolveServicePath` is fine; installing to a new
  directory (`~/.volta/bin`, a nix store path) requires a code change —
  `resolveServicePath` itself is static. Re-run `bridge uninstall && bridge
  install` after any such code change.
- **`bridge start` when already running.** On macOS `startDaemon`
  (`src/infra/daemon.ts:282`) detects load via `launchctl print` and force-
  restarts via `kickstart -k`; idempotent. Linux mirrors via `is-active` →
  `restart`. Direct-tmux branch bails out in `startSession` with "Session
  ... already running" (`src/infra/bridge-cmd.ts:58`).
- **`plistLoaded` is macOS-only.** The stale-plist diagnostic
  (`src/cli/index.ts:707`) returns false on Linux. systemd
  `restart` / `start` is symmetric and avoids the stuck path, so the
  diagnostic is not needed there.
- **Direct-mode has no supervisor.** Running `bridge start` without first
  running `bridge install` takes the direct-tmux branch; if `claude`
  crashes, nothing respawns it. `bridge daemon-status` will show `Daemon
  installed: no`, `Session running: no`.
- **`CLAUDE_BRIDGE_HOME` propagation into `.mcp.json`.** The env var flows
  into `claude` via `env VAR=...` and is read back in the
  `StartupOrchestrator` constructor default (`src/infra/startup.ts:27`).
  If the bot dir's `.mcp.json` spawns `bridge` as a child MCP server, pass
  `CLAUDE_BRIDGE_HOME` through explicitly — otherwise the child inherits
  the shell's value, which may be wrong when a bot dir is shared between
  instances.
- **Log file ownership.** The daemon runs under `gui/<uid>` or
  `systemctl --user`, both as the invoking user. If an operator ever ran
  `bridge start` via `sudo`, the log may be owned by root and subsequent
  runs will silently drop output through `pipe-pane`'s `cat >>`. Check
  `ls -l <home>/bridge.log` if logs go quiet.
