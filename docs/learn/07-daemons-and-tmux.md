# Daemons, launchd/systemd, and tmux

For the developer who has shipped CLI apps but has never had one that
needs to *stay running* across reboots, crashes, and terminal closures.
By the end you should be able to read a process tree, write and debug a
launchd plist and a systemd user unit, use tmux as a detachable session,
and explain why claude-bridge runs tmux *inside* the supervisor rather
than letting launchd/systemd supervise the bridge process directly.

This is not a code tour of `src/infra/`. We point at the implementation
only where it connects to theory.

---

## 1. The Unix process model, in five minutes

Everything below is POSIX. macOS and Linux agree on the primitives; the
supervisors disagree on the packaging.

### Process vs thread

A **process** has its own address space, file descriptors, signal
handlers, and PID. A **thread** is concurrent execution sharing the
process's memory. For daemon work, think in processes: supervisors
kill processes, signals target processes, logs belong to processes.

### PIDs, PPIDs, process groups, sessions

- **PID** — small integer, unique while the process is alive, recycled
  after it exits.
- **PPID** — the forker's PID. If the parent dies first, the child is
  reparented to PID 1 (`init`, `launchd`, `systemd`). A reparented
  child is an **orphan**; an exited child whose status hasn't been
  read yet is a **zombie** (`Z` in `ps`).
- **Process group** — a set of processes you can signal together.
  `kill -TERM -- -$pgid` hits all of them. Shell pipelines get a group.
- **Session** — a set of process groups, usually tied to a controlling
  terminal. `setsid(2)` creates one with no controlling terminal — the
  traditional first step in daemonising.

Read bottom-up: sessions contain process groups, which contain
processes, which contain threads.

### Signals

Signals are asynchronous notifications. A process can catch most, block
some, ignore some; SIGKILL and SIGSTOP are the two it can't. Learn four:

- **SIGTERM (15)** — "please shut down." Default from `kill`, first
  thing a supervisor sends. Handler flushes buffers, closes sockets,
  releases locks, then `exit(0)`.
- **SIGKILL (9)** — "die now." Delivered by the kernel; no code runs
  after. Use only when SIGTERM was ignored long enough. In-flight
  writes are lost.
- **SIGHUP (1)** — historically "hangup" (terminal went away). Daemons
  conventionally reinterpret it as "reload config." nginx, sshd,
  postgres all do this.
- **SIGINT (2)** — Ctrl+C. Most programs handle it like SIGTERM.

Full list: `signal(7)`. Graceful shutdown: supervisor sends SIGTERM,
daemon runs cleanup and exits; if not done in N seconds, supervisor
sends SIGKILL. systemd calls this "the stop timeout" (90s default);
launchd calls it `ExitTimeOut` (20s default). Configure it, don't fight.

### Stdin, stdout, stderr, file descriptors

Every process starts with three open fds: fd 0 (stdin), fd 1 (stdout),
fd 2 (stderr). A daemon started by a supervisor has *no terminal*, so
writes to these fds land in the void (macOS) or the journal (Linux)
unless the supervisor redirects them.

Most common first-bug: "works when I run it, `launchctl start` shows
nothing." Answer: you forgot `StandardOutPath`/`StandardErrorPath`
(launchd) or didn't check `journalctl --user -u <name>` (systemd).

### Process tree

Commands to have in muscle memory:

    ps -ef              # Linux / macOS, flat list with PPID
    ps auxf             # Linux, tree-ish layout
    pstree -p $$        # Linux, real tree
    pgrep -f <pattern>  # find by full command line
    pkill -f <pattern>  # signal by full command line

On macOS, `pstree` is not installed by default. `pgrep -f` / `pkill -f`
match against the whole command line, which is what you want when your
daemon is spawned by a shell wrapper and the direct process name is
`bash`.

### Foreground vs background vs detached

A foreground process owns the terminal. A background process (`cmd &`)
still belongs to the terminal's session — close the terminal, it gets
SIGHUP and typically dies. `nohup` or `disown` breaks that link for the
current session, but a reboot kills everything.

"Detached," in the daemon sense, means no controlling terminal *and* a
supervisor that re-parents you across reboots. That's next.

---

## 2. What a daemon actually is

A daemon is a long-lived background process that survives the terminal
that launched it. That's the whole definition. Everything else —
logging, restart policy, single-instance locking — is accidental
complexity that supervisors now solve for you.

### The historical dance

Pre-launchd, pre-systemd, a well-behaved daemon would `fork()`, have
the parent exit, `setsid()` to drop its controlling terminal, `fork()`
a second time so it can never acquire a new one, `chdir("/")`, `umask(0)`,
close fds 0/1/2 and reopen them to `/dev/null` or a log file, write a
PID file to `/var/run/<name>.pid`, and install handlers for SIGTERM and
SIGHUP.

This is the "double fork." You'll see it in old C daemons and in
Python's `python-daemon`. **Don't do this anymore.** If you double-fork
under systemd with the default `Type=simple`, systemd decides your
daemon exited (the parent did) and marks it failed.

### Modern practice

> Don't daemonise yourself. Let launchd or systemd do it.

Write a program that logs to stdout/stderr, runs in the foreground,
handles SIGTERM with cleanup + `exit(0)`, and crashes loudly if it can't
start. Hand it to a supervisor, which handles fd redirection, restarts,
logging, and boot launch. You write ~20 lines of plist or unit file.

---

## 3. Supervisors — why

Four jobs, all tedious, all essential:

- **Start-on-boot.** Machine comes up, supervisor notices your service
  is `enabled`, starts it before login (system) or at login (user).
- **Restart-on-crash.** Nonzero exit, cool-off, restart. If it loops,
  the supervisor backs off or gives up — a policy knob.
- **Log management.** stdout/stderr captured to a file, the journal,
  or syslog. You never redirect fds yourself.
- **Single-instance enforcement.** One unit with a given label/name;
  a second start is a no-op or an error. No PID-file-and-flock dance.

On macOS, launchd. On Linux, systemd (in 2026, on every mainstream
distro). Both run as PID 1; everything else is their child.

---

## 4. macOS: launchd

launchd is the only supervisor on macOS. It starts everything from
WindowServer to `coreaudiod` to your user agents. Two concepts to
separate:

### User agents vs system daemons

- **User agents** run as *your user*, only while you're logged in.
  Live in `~/Library/LaunchAgents/`, loaded into the `gui/<uid>`
  domain. Perfect for tools that need your keychain, `HOME`, personal
  config. **What claude-bridge installs.**
- **System daemons** run as root (or a specified user) from before
  login. Live in `/Library/LaunchDaemons/`, loaded into the `system`
  domain. Admin rights required.

There's also `/Library/LaunchAgents/` (system-wide user agents) and
`/System/Library/…` (Apple-owned — leave alone).

### The plist format

A plist is an XML property list. Ugly but small. The keys that matter
for almost every user agent:

    <?xml version="1.0" encoding="UTF-8"?>
    <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
      "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    <plist version="1.0">
    <dict>
      <key>Label</key><string>com.example.hello</string>
      <key>ProgramArguments</key>
      <array>
        <string>/usr/local/bin/hello</string>
        <string>--flag</string>
      </array>
      <key>WorkingDirectory</key><string>/Users/alice/projects/hello</string>
      <key>EnvironmentVariables</key>
      <dict>
        <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HELLO_CONFIG</key><string>/Users/alice/.hello/config.toml</string>
      </dict>
      <key>RunAtLoad</key><true/>
      <key>KeepAlive</key><true/>
      <key>StandardOutPath</key><string>/Users/alice/.hello/hello.log</string>
      <key>StandardErrorPath</key><string>/Users/alice/.hello/hello.log</string>
    </dict>
    </plist>

Key by key:

- **`Label`** — unique identifier. Convention: reverse-DNS. Must match
  the filename (sans `.plist`).
- **`ProgramArguments`** — argv. First element is the executable, the
  rest are flags. No shell expansion; no `~`; absolute paths only.
- **`RunAtLoad`** — start the moment it's loaded. Usually yes.
- **`KeepAlive`** — `<true/>` (always restart) or a dict like
  `<dict><key>SuccessfulExit</key><false/></dict>` ("restart only on
  abnormal exit"). The bridge uses unconditional `<true/>`.
- **`WorkingDirectory`** — cwd at launch. Must exist and be readable.
- **`EnvironmentVariables`** — *critical*: launchd starts with an empty
  environment. Set `PATH`, `HOME`, and anything your program reads from
  the shell here.
- **`StandardOutPath`** / **`StandardErrorPath`** — absolute log paths.
  launchd appends. Rotate with `newsyslog.conf` or accept growth.

Other keys exist (`ThrottleInterval`, `StartInterval`, `WatchPaths`,
`Sockets`), but the seven above cover 90% of cases.

### `launchctl` verbs

The tool is `launchctl`. Modern macOS (10.10+) uses:

- **`bootstrap <domain> <plist>`** — load the plist into the domain.
- **`bootout <domain> <plist>`** — unload it.
- **`kickstart [-k] <domain>/<label>`** — start now (even if
  `RunAtLoad` was false). `-k` kills any existing instance first —
  effectively "restart."
- **`print <domain>/<label>`** — everything launchd knows about the
  service. Loaded? Last exit status? Paths? Your #1 debugging tool.

A *domain* identifies who the service belongs to. For a user agent:
`gui/<uid>`, e.g. `gui/501`. Get it with `id -u`:

    uid=$(id -u)
    plist=~/Library/LaunchAgents/com.example.hello.plist

    launchctl bootstrap "gui/$uid" "$plist"                # install + start
    launchctl kickstart    "gui/$uid/com.example.hello"    # force start
    launchctl kickstart -k "gui/$uid/com.example.hello"    # restart
    launchctl print        "gui/$uid/com.example.hello"    # inspect
    launchctl bootout "gui/$uid" "$plist"                  # stop + unload

You may see older docs using `launchctl load` / `unload`. Those are
deprecated; `bootstrap` / `bootout` are the modern replacements.
`bootstrap` refuses if the label is already loaded (whereas `load`
silently replaced it), so scripts generally `print` first and choose
between `bootstrap` and `kickstart -k`.

### How claude-bridge installs its plist

`bridge install` writes to `~/Library/LaunchAgents/ai.<service-name>.plist`
(service name derived from `CLAUDE_BRIDGE_HOME`). `bridge start` calls
`launchctl bootstrap` first time, `launchctl kickstart -k` afterwards;
`bridge stop` calls `launchctl bootout`. See
`docs/specs/06-infrastructure.md` for exact paths across instances.

---

## 5. Linux: systemd

systemd is the supervisor on essentially every modern Linux distro
(Ubuntu, Debian, Fedora, RHEL, Arch). Sprawling scope — boot, cgroups,
logging, networking, timers, sockets — but for our purposes we only
need **unit files**, specifically `.service` units, specifically in
the **user** manager.

### User vs system units

- **System units** live in `/etc/systemd/system/*.service`. They run
  as root (or the `User=` you set) and start at boot. Controlled by
  `systemctl <verb>`.
- **User units** live in `~/.config/systemd/user/*.service`. They run
  as your user, typically at login, controlled by `systemctl --user
  <verb>`. **The bridge uses these.**

After adding or editing a unit file, run `systemctl --user daemon-reload`
to make systemd re-read it.

### The `.service` file

Three sections. Simplest useful example:

    [Unit]
    Description=Hello daemon
    After=network.target

    [Service]
    Type=simple
    WorkingDirectory=/home/alice/projects/hello
    Environment=PATH=/home/alice/.local/bin:/usr/local/bin:/usr/bin:/bin
    Environment=HELLO_CONFIG=/home/alice/.hello/config.toml
    ExecStart=/usr/local/bin/hello --flag
    ExecStop=/usr/local/bin/hello --graceful-stop
    Restart=on-failure
    RestartSec=5
    StandardOutput=journal
    StandardError=journal

    [Install]
    WantedBy=default.target

Key directives:

- **`Description`** — free text, shown in `systemctl status`.
- **`After=network.target`** — ordering hint. Not a hard dependency;
  for that, use `Requires=`.
- **`Type=`** — `simple` (default; `ExecStart` is the service, must
  stay in foreground), `forking` (only if the program insists on
  double-forking), `oneshot` (run once, then considered active),
  `notify` / `exec` (advanced). Use `simple` 99% of the time.
- **`ExecStart=`** — what to run. One line. No shell; use
  `/bin/sh -c '…'` if you need shell features.
- **`Restart=`** — `no`, `on-success`, `on-failure`, `on-abnormal`,
  `on-abort`, `always`. `on-failure` is the sensible default.
- **`RestartSec=`** — seconds between restart attempts. Below 5s
  you risk tripping the rate limiter (`StartLimitBurst=5` over
  `StartLimitIntervalSec=10` by default).
- **`Environment=`** — one var per line. Same reason as launchd:
  environment starts empty-ish.
- **`StandardOutput=`** / **`StandardError=`** — `journal` (default,
  recommended), `file:/path`, `append:/path`, `null`, `syslog`.
- **`WantedBy=default.target`** — `enable` creates a symlink from
  `default.target.wants/` to this unit. For user units, `default.target`
  is "logged in."

### `systemctl --user` verbs

    systemctl --user daemon-reload              # re-read unit files
    systemctl --user enable hello               # start on login
    systemctl --user disable hello              # cancel enable
    systemctl --user start hello                # start now
    systemctl --user stop hello                 # stop now (SIGTERM, then SIGKILL)
    systemctl --user restart hello              # stop + start
    systemctl --user status hello               # running? last N log lines
    systemctl --user is-active hello            # just "active" or "inactive"

For logs, `journalctl --user -u hello` gives you everything the service
has written to stdout/stderr since installation. Useful flags:

    journalctl --user -u hello -f               # follow (tail -f)
    journalctl --user -u hello -n 200           # last 200 lines
    journalctl --user -u hello --since "1h ago"

### `loginctl enable-linger`

By default, systemd starts user units at login and stops them at logout.
To keep a daemon running on a headless server (no one logged in) or
across SSH sessions:

    loginctl enable-linger $USER

This keeps your user manager alive without an active session. Undo with
`disable-linger`.

### How claude-bridge installs its unit

`bridge install` writes `~/.config/systemd/user/<service-name>.service`
and runs `daemon-reload`. `bridge start` calls
`systemctl --user start <service-name>` (or `restart` if already
active); `bridge stop` calls `systemctl --user stop`. See
`docs/specs/06-infrastructure.md` for the service-name scheme.

---

## 6. tmux, quickly

tmux is a **terminal multiplexer**: one tmux process hosts **sessions**,
each session has **windows** (tabs), each window has **panes** (splits).
The magic bit: sessions are detachable. Start a session, type stuff in,
close your terminal, the session keeps running. Reattach later from a
different terminal.

For daemon work, a tmux session is a ready-made way to run a program
*with a terminal* but disconnected from any specific login shell.

### Key verbs

    tmux new-session -d -s foo 'some-command'   # start detached
    tmux has-session -t foo                     # exit 0 if exists
    tmux list-sessions                          # show all sessions
    tmux attach -t foo                          # jump in (Ctrl+b d to detach)
    tmux kill-session -t foo                    # stop it
    tmux send-keys -t foo 'echo hi' Enter       # paste into the session
    tmux pipe-pane -t foo 'cat >> /tmp/foo.log' # mirror pane output

`-d` means "start detached" — no attempt to open a window for you.
Without `-d`, tmux tries to `exec` into an interactive session and
fails if there's no terminal, which is exactly what happens when
launchd or systemd runs it.

`has-session` is how scripts check existence. It sets exit code with
no output — ideal for loops:

    while tmux has-session -t foo 2>/dev/null; do sleep 30; done

When attached, the **prefix key** is `Ctrl+b`. Useful chords:
`Ctrl+b d` (detach), `Ctrl+b c` (new window), `Ctrl+b n` / `p` (next /
prev window), `Ctrl+b "` / `%` (split horizontal / vertical),
`Ctrl+b [` (scroll, `q` to quit).

### Why tmux is supervisor-adjacent

tmux isn't a real supervisor — no crash restart (though
`remain-on-exit` comes close), no start-on-boot, no log rotation. What
it does very well: keeps a program alive beyond the starting shell,
lets you attach interactively and see live output (ANSI, cursor
control, TUI frames), and accepts keystrokes via `send-keys`.

That last bit is why it's useful for programs that prompt once at
startup (license banners, "are you sure?") then run forever. Script
`send-keys Enter` once, the program clears the prompt, the session
holds it.

---

## 7. Why claude-bridge uses tmux-inside-launchd/systemd

The supervisor (launchd or systemd) supervises a shell wrapper that
runs `tmux new-session`, then sits in a
`while tmux has-session; do sleep 30; done` loop. The actual claude
process (`claude server:bridge …`) runs *inside* the tmux session.

Two layers, on purpose:

1. The supervisor restarts the wrapper on crash and on reboot.
2. The wrapper keeps itself alive as long as the tmux session lives;
   when the bridge dies inside tmux, tmux exits, the wrapper's loop
   exits, and the supervisor re-runs the wrapper.

**Benefit.** `bridge attach` gives you a real interactive view —
live logs, startup banners, any TUI the `claude` CLI throws up. Without
tmux you'd be stuck reading a log file, or piping stdout through a
fragile redirection and hoping it doesn't buffer.

**Tradeoff.** The supervisor is one level removed from the bridge.
If tmux dies (rare), the supervisor restarts it. If the bridge dies
inside tmux while tmux survives, the `has-session` loop notices, the
wrapper exits, and the supervisor restarts the wrapper, which recreates
the session. Either way the bridge comes back.

The wrapper also handles two startup prompts via `tmux send-keys Enter`
(loading development channels, bypassing permissions). Doing that
through tmux is straightforward; through raw stdin under launchd it is
not.

For the concrete plist/unit templates and the wrapper script, see
`docs/specs/06-infrastructure.md` and `buildWrapperScript` in
`src/infra/daemon.ts`.

---

## 8. PID files, locks, and single-instance invariants

A daemon almost always wants exactly one copy per installation running
at a time. Options, roughly in ascending modernity:

**PID file.** Write your PID to `/var/run/foo.pid`; on start, read it
and check whether that PID is a live copy of you. Problems: PIDs
recycle (4321 might now be `bash`), stale files survive crashes, and
two parallel starts race.

**Advisory file lock (`flock`).** `open(path, O_CREAT)` then
`flock(fd, LOCK_EX | LOCK_NB)`. If the lock is taken, exit. The OS
releases the lock when the fd closes, so crashes don't leave stale
state. Still common. Downside: the lock-holding fd must stay open for
the life of the process — footgun if you double-fork.

**Supervisor as the lock.** Modern best. launchd refuses to bootstrap
the same `Label` twice; systemd refuses to start the same unit twice.
Your daemon doesn't have to care.

**tmux-session-name-as-lock.** What claude-bridge does. The session
name is derived deterministically from `CLAUDE_BRIDGE_HOME`; every
"is it running?" check is just:

    tmux has-session -t "<name>" 2>/dev/null

Start logic is idempotent: `tmux new-session -d -s <name> …` refuses
duplicates. Two parallel `bridge start` invocations produce one
session, not two. Combined with the supervisor and the wrapper's
`if ! tmux has-session` guard, you get three layers of single-instance
enforcement for free.

---

## 9. Logs

You will live in log files. Three venues, one per runtime:

### launchd

Whatever you named in `StandardOutPath` / `StandardErrorPath` is where
your daemon's stdout/stderr goes. The bridge points both at the same
file, usually `~/.claude-bridge/bridge.log`:

    tail -f ~/.claude-bridge/bridge.log

launchd itself logs to the unified Apple logging system. If your daemon
crashes before writing a byte, the supervisor-level error is there:

    log show --last 30m --predicate 'processImagePath CONTAINS "claude"' --info

### systemd

The journal has everything:

    journalctl --user -u <unit>                  # all history
    journalctl --user -u <unit> -f               # follow
    journalctl --user -u <unit> -n 200           # last 200 lines
    journalctl --user -u <unit> --since "10m ago"
    journalctl --user -u <unit> -p err           # errors only

If you set `StandardOutput=file:/path` in the unit, it also lands in
that file — but the journal still has it, and the journal has rotation
built in. Prefer the journal.

### tmux

tmux captures terminal contents in a per-pane buffer. To persist it to
a file from the start of a session, use `pipe-pane`:

    tmux pipe-pane -t <session> -o 'cat >> /path/to/log'

(`-o` toggles: once on, once off.) The bridge wrapper does this
automatically. You can also scrollback-dump a running pane:

    tmux capture-pane -t <session> -p -S -3000 > /tmp/snapshot.log

`-S -3000` starts 3000 lines above the cursor — useful for grabbing
everything a TUI has shown since startup when you didn't set up
`pipe-pane` in advance.

---

## 10. Debugging daemons that won't start

Symptom: "I ran `bridge start` and nothing's happening" or "it starts
but immediately exits." Work through this list in order.

**1. Is the unit file loaded and valid?**

macOS: `launchctl print gui/$(id -u)/<label>`. "Could not find service"
means the plist wasn't bootstrapped — re-run install. A nonzero
`last exit code = N` means it ran but died — skip to step 3.

Linux: `systemctl --user status <unit>`. Shows loaded state, active
state, and recent log lines. `Loaded: bad-setting` means systemd
rejected the file; try `systemd-analyze --user verify <unit-path>`.

**2. Are the logs saying anything?**

Almost always yes. `tail -100 ~/.claude-bridge/bridge.log` (macOS) or
`journalctl --user -u <unit> -n 100` (Linux). The error is usually
specific.

**3. The four boring causes, in frequency order.**

1. **PATH.** Supervisors start with nearly empty `$PATH` — often just
   `/usr/bin:/bin`. If your plist/unit calls `claude`, `bun`, or `tmux`
   by bare name, they won't resolve. Set `PATH` in
   `EnvironmentVariables` / `Environment=` and include the Homebrew
   prefix (`/opt/homebrew/bin`) on macOS.
2. **HOME.** Some tools read config relative to `$HOME`. launchd user
   agents get it; systemd user units sometimes need it explicit.
3. **WorkingDirectory.** If it doesn't exist or isn't readable, the
   service fails before your code runs.
4. **Quoting.** Shell metacharacters in plist `<string>` or systemd
   `ExecStart=` rarely do what you think. Prefer `/bin/bash -lc 'SCRIPT'`
   with the script single-quoted.

**4. Run the exact command by hand.**

Take the `ExecStart` line (or `ProgramArguments` joined with spaces),
paste into a terminal *in the same working directory*, *with only the
env vars the supervisor sets*, and run. Or have launchd do it:
`launchctl kickstart -k gui/$(id -u)/<label>`. Then check the log.
If it works by hand but not under the supervisor, the gap is
environment or cwd — 95% of the time.

**5. tmux-specific gotchas.**

- `tmux new-session` without `-d` fails under a supervisor (no
  terminal). Always `-d`.
- tmux uses `$TMUX_TMPDIR` or `/tmp` for its socket. Multi-user
  machines can collide; set `$TMUX_TMPDIR` per user.
- `tmux pipe-pane` is silent about errors. Unwritable log file = no
  output. Check permissions.

---

## 11. Exercises

Do these in a scratch directory, not in a claude-bridge checkout.

### Exercise A — launchd, macOS

A plist that runs a one-shot command every time it's kicked.

1. Create `~/Library/LaunchAgents/com.example.date.plist`:

        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
          "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
          <key>Label</key><string>com.example.date</string>
          <key>ProgramArguments</key>
          <array>
            <string>/bin/sh</string>
            <string>-c</string>
            <string>/bin/date &gt;&gt; /tmp/date.log</string>
          </array>
          <key>RunAtLoad</key><true/>
        </dict>
        </plist>

2. Install, inspect, kickstart, uninstall:

        uid=$(id -u)
        plist=~/Library/LaunchAgents/com.example.date.plist

        launchctl bootstrap "gui/$uid" "$plist"
        launchctl print     "gui/$uid/com.example.date"
        for i in 1 2 3; do launchctl kickstart -k "gui/$uid/com.example.date"; done
        cat /tmp/date.log
        launchctl bootout   "gui/$uid" "$plist"
        rm "$plist"

Notice: `RunAtLoad` fires once at bootstrap; each `kickstart -k` fires
it again. No `KeepAlive`, so it doesn't restart on normal exit — classic
one-shot shape.

### Exercise B — systemd user unit, Linux

Run a Python HTTP server on :8001 as a user unit.

1. `mkdir -p ~/scratch/www && echo hi > ~/scratch/www/index.html`
2. Create `~/.config/systemd/user/hello-http.service`:

        [Unit]
        Description=Trivial Python HTTP server on :8001

        [Service]
        Type=simple
        WorkingDirectory=%h/scratch/www
        ExecStart=/usr/bin/python3 -m http.server 8001
        Restart=on-failure
        RestartSec=3

        [Install]
        WantedBy=default.target

   (`%h` expands to your home directory.)

3. Reload, enable+start, verify, tear down:

        systemctl --user daemon-reload
        systemctl --user enable --now hello-http
        systemctl --user status hello-http
        curl -s http://localhost:8001/
        journalctl --user -u hello-http -n 20
        systemctl --user disable --now hello-http
        rm ~/.config/systemd/user/hello-http.service
        systemctl --user daemon-reload

Notice: `enable --now` enables *and* starts in one step — common
shorthand; `disable --now` is the inverse. Logs land in the journal by
default.

### Exercise C — tmux

    tmux new-session -d -s foo 'top'      # start detached
    tmux list-sessions                    # foo: 1 windows [80x24]
    tmux attach -t foo                    # watch top
                                          # Ctrl+b d to detach
    tmux send-keys -t foo 'q'             # make top quit
    tmux list-sessions                    # session auto-exits with last pane
    tmux kill-session -t foo 2>/dev/null || true

Notice: `send-keys` literally simulates typing — a key name like
`Enter` sends the Enter key, a bare string is typed as characters.
That's exactly how the bridge's wrapper gets past its startup prompts.

---

## 12. Further reading

Canonical links only. If you want to go deep:

- **launchd**:
  - https://www.launchd.info — the best unofficial tutorial.
  - https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html
- **systemd**:
  - https://www.freedesktop.org/software/systemd/man/systemd.service.html
  - https://www.freedesktop.org/software/systemd/man/systemctl.html
- **tmux**:
  - https://github.com/tmux/tmux/wiki/Getting-Started
  - https://man.openbsd.org/tmux.1 — the canonical man page.
- **Signals**:
  - https://man7.org/linux/man-pages/man7/signal.7.html

Once you've done the three exercises and can read the plist and unit
generated by `src/infra/daemon.ts` without flinching, you're ready to
maintain the bridge's daemon story.
