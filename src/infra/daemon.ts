/**
 * Daemon Manager — launchd (macOS) and systemd (Linux) integration.
 *
 * Generates service files, installs/manages system daemons.
 * Matches Python daemon.py behavior.
 */

import { existsSync, writeFileSync, unlinkSync, readFileSync, mkdirSync } from "fs";
import { join, basename } from "path";
import { homedir } from "os";
import { execSync } from "child_process";

// --- Platform Detection ---

export type Platform = "macos" | "linux" | "other";

export function getPlatform(): Platform {
  const p = process.platform;
  if (p === "darwin") return "macos";
  if (p === "linux") return "linux";
  return "other";
}

export function isContainerEnvironment(): boolean {
  if (existsSync("/.dockerenv")) return true;
  try {
    const comm = readFileSync("/proc/1/comm", "utf-8").trim();
    if (comm !== "systemd" && comm !== "init") return true;
  } catch { /* not Linux or no access */ }
  return false;
}

// --- Service Names ---

export function getServiceName(bridgeHome?: string): string {
  const home = bridgeHome ?? join(homedir(), ".claude-bridge");
  const base = basename(home).replace(/\./g, "");
  return base;
}

export function getLaunchdLabel(bridgeHome?: string): string {
  return `ai.${getServiceName(bridgeHome)}`;
}

function getLaunchdPlistPath(bridgeHome?: string): string {
  return join(homedir(), "Library", "LaunchAgents", `${getLaunchdLabel(bridgeHome)}.plist`);
}

function getSystemdUnitPath(bridgeHome?: string): string {
  const configDir = join(homedir(), ".config", "systemd", "user");
  return join(configDir, `${getServiceName(bridgeHome)}.service`);
}

// --- Templates ---

/**
 * Build the shell wrapper script used by both launchd and systemd.
 *
 * Why a wrapper rather than invoking `tmux new-session` directly?
 *   - `tmux new-session -d` detaches immediately; its pty output goes to tmux's
 *     own buffer, not to launchd's StandardOutPath. Without pipe-pane the log
 *     file stays empty.
 *   - `KeepAlive=true` (launchd) / `Restart=on-failure` (systemd) expects the
 *     launched process to remain alive while the service is healthy. The
 *     wrapper polls `tmux has-session` and exits when the session dies so the
 *     supervisor respawns it cleanly.
 *   - Avoid any `<`, `>`, `&` characters so it's safe to embed in plist XML
 *     without escaping. (`2>/dev/null` is intentionally omitted for that
 *     reason — the has-session probe's stderr is harmless in the log.)
 */
function buildWrapperScript(
  botDir: string,
  bridgeHome: string,
  logPath: string,
  sessionName: string,
): string {
  return `set -e
session=${shSingleQuote(sessionName)}
logfile=${shSingleQuote(logPath)}
botdir=${shSingleQuote(botDir)}
bridge_home=${shSingleQuote(bridgeHome)}
if ! tmux has-session -t "$session"; then
  tmux new-session -d -s "$session" -c "$botdir" "CLAUDE_BRIDGE_HOME=$bridge_home claude --dangerously-load-development-channels server:bridge --dangerously-skip-permissions"
  tmux pipe-pane -t "$session" "cat >> $logfile"
  # Auto-confirm two warning prompts in order:
  #   1) "Loading development channels" (default: local development)
  #   2) --dangerously-skip-permissions bypass-permissions acknowledgement
  sleep 3
  tmux send-keys -t "$session" Enter
  sleep 2
  tmux send-keys -t "$session" Enter
fi
# Keep this wrapper alive as long as the session exists so the supervisor
# (launchd KeepAlive / systemd Restart) only respawns on real death.
while tmux has-session -t "$session"; do sleep 30; done`;
}

/** POSIX single-quote a string (safe inside plist XML — no special chars). */
function shSingleQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

/** Escape text for embedding inside a plist `<string>` element. */
function xmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function resolveServicePath(): string {
  // launchd/systemd start with a minimal PATH and don't source user shell rc files.
  // Include common user bin dirs so `claude`, `bun`, `tmux` (Homebrew) all resolve.
  const home = homedir();
  const parts = [
    `${home}/.local/bin`,
    `${home}/.bun/bin`,
    `${home}/.cargo/bin`,
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
  ];
  return parts.join(":");
}

function generateLaunchdPlist(
  botDir: string,
  bridgeHome: string,
  logPath: string,
): string {
  const label = getLaunchdLabel(bridgeHome);
  const sessionName = getServiceName(bridgeHome);
  const script = buildWrapperScript(botDir, bridgeHome, logPath, sessionName);
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>-lc</string>
    <string>${xmlEscape(script)}</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${botDir}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CLAUDE_BRIDGE_HOME</key>
    <string>${bridgeHome}</string>
    <key>HOME</key>
    <string>${homedir()}</string>
    <key>PATH</key>
    <string>${resolveServicePath()}</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${logPath}</string>
  <key>StandardErrorPath</key>
  <string>${logPath}</string>
</dict>
</plist>`;
}

function generateSystemdUnit(
  botDir: string,
  bridgeHome: string,
  logPath: string,
): string {
  const sessionName = getServiceName(bridgeHome);
  const script = buildWrapperScript(botDir, bridgeHome, logPath, sessionName);
  // systemd ExecStart on a single line: escape newlines into `; ` separators.
  // Using Type=simple (default) because the wrapper stays alive; no longer forking.
  const oneLineScript = script.replace(/\n/g, "; ");
  // Single-quote the whole script for /bin/bash -lc 'SCRIPT'; the script itself
  // already uses single-quoted substrings, so wrap in double quotes here.
  return `[Unit]
Description=Claude Bridge (${sessionName})
After=network.target

[Service]
Type=simple
WorkingDirectory=${botDir}
Environment=CLAUDE_BRIDGE_HOME=${bridgeHome}
Environment=HOME=${homedir()}
Environment=PATH=${resolveServicePath()}
ExecStart=/bin/bash -lc "${oneLineScript.replace(/"/g, `\\"`)}"
ExecStop=/usr/bin/tmux kill-session -t ${sessionName}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target`;
}

// --- Install/Uninstall ---

export function installDaemon(
  botDir: string,
  bridgeHome: string,
  logPath?: string,
): [boolean, string] {
  const log = logPath ?? join(bridgeHome, "bridge.log");
  const platform = getPlatform();

  if (platform === "macos") return installLaunchd(botDir, bridgeHome, log);
  if (platform === "linux") return installSystemd(botDir, bridgeHome, log);
  return [false, `Unsupported platform: ${platform}`];
}

function installLaunchd(botDir: string, bridgeHome: string, logPath: string): [boolean, string] {
  const plistPath = getLaunchdPlistPath(bridgeHome);
  const plist = generateLaunchdPlist(botDir, bridgeHome, logPath);

  mkdirSync(join(homedir(), "Library", "LaunchAgents"), { recursive: true });
  writeFileSync(plistPath, plist, "utf-8");
  return [true, `Installed launchd plist: ${plistPath}`];
}

function installSystemd(botDir: string, bridgeHome: string, logPath: string): [boolean, string] {
  const unitPath = getSystemdUnitPath(bridgeHome);
  const unit = generateSystemdUnit(botDir, bridgeHome, logPath);

  mkdirSync(join(homedir(), ".config", "systemd", "user"), { recursive: true });
  writeFileSync(unitPath, unit, "utf-8");

  try {
    execSync("systemctl --user daemon-reload", { stdio: "pipe" });
  } catch { /* ignore */ }

  return [true, `Installed systemd unit: ${unitPath}`];
}

export function uninstallDaemon(bridgeHome?: string): [boolean, string] {
  const platform = getPlatform();

  if (platform === "macos") {
    const plistPath = getLaunchdPlistPath(bridgeHome);
    if (existsSync(plistPath)) {
      try {
        execSync(`launchctl bootout gui/${process.getuid?.()} ${plistPath}`, { stdio: "pipe" });
      } catch { /* already unloaded */ }
      unlinkSync(plistPath);
      return [true, "Uninstalled launchd daemon"];
    }
    return [false, "Daemon not installed"];
  }

  if (platform === "linux") {
    const unitPath = getSystemdUnitPath(bridgeHome);
    if (existsSync(unitPath)) {
      try {
        execSync(`systemctl --user stop ${getServiceName(bridgeHome)}`, { stdio: "pipe" });
        execSync(`systemctl --user disable ${getServiceName(bridgeHome)}`, { stdio: "pipe" });
      } catch { /* ignore */ }
      unlinkSync(unitPath);
      try { execSync("systemctl --user daemon-reload", { stdio: "pipe" }); } catch { /* ignore */ }
      return [true, "Uninstalled systemd daemon"];
    }
    return [false, "Daemon not installed"];
  }

  return [false, `Unsupported platform: ${platform}`];
}

// --- Start/Stop/Status ---

export function startDaemon(bridgeHome?: string): [boolean, string] {
  const platform = getPlatform();
  const label = getLaunchdLabel(bridgeHome);
  const service = getServiceName(bridgeHome);

  try {
    if (platform === "macos") {
      const plistPath = getLaunchdPlistPath(bridgeHome);
      if (!existsSync(plistPath)) return [false, "Daemon not installed"];
      const uid = process.getuid?.();
      const target = `gui/${uid}/${label}`;
      // Check whether the plist is already bootstrapped. `launchctl print` exits
      // 0 when the service is loaded, non-zero otherwise (service not found).
      let alreadyLoaded = false;
      try {
        execSync(`launchctl print ${target}`, { stdio: "pipe" });
        alreadyLoaded = true;
      } catch {
        alreadyLoaded = false;
      }

      if (alreadyLoaded) {
        // `-k` forces a restart if already running; harmless if stopped.
        execSync(`launchctl kickstart -k ${target}`, { stdio: "pipe" });
        return [true, `Kickstarted ${label}`];
      }

      execSync(`launchctl bootstrap gui/${uid} ${plistPath}`, { stdio: "pipe" });
      return [true, `Bootstrapped ${label}`];
    }
    if (platform === "linux") {
      // `systemctl --user start` is idempotent but doesn't restart a running unit
      // to pick up a refreshed unit file. Mirror the macOS kickstart semantics:
      // if already active, restart; otherwise start.
      let active = false;
      try {
        const out = execSync(`systemctl --user is-active ${service}`, { stdio: "pipe" })
          .toString()
          .trim();
        active = out === "active";
      } catch {
        active = false;
      }

      if (active) {
        execSync(`systemctl --user restart ${service}`, { stdio: "pipe" });
        return [true, `Restarted ${service}`];
      }
      execSync(`systemctl --user start ${service}`, { stdio: "pipe" });
      return [true, `Started ${service}`];
    }
    return [false, `Unsupported platform: ${platform}`];
  } catch (err) {
    return [false, `Failed to start: ${(err as Error).message}`];
  }
}

export function stopDaemon(bridgeHome?: string): [boolean, string] {
  const platform = getPlatform();
  const label = getLaunchdLabel(bridgeHome);
  const service = getServiceName(bridgeHome);

  try {
    if (platform === "macos") {
      // `bootout` fully UNLOADS the plist (not just stops the process). This is
      // appropriate for `bridge stop` — `bridge start` reloads via `bootstrap`
      // (or `kickstart` if something left the plist loaded).
      execSync(`launchctl bootout gui/${process.getuid?.()} ${getLaunchdPlistPath(bridgeHome)}`, { stdio: "pipe" });
      return [true, `Stopped ${label}`];
    }
    if (platform === "linux") {
      execSync(`systemctl --user stop ${service}`, { stdio: "pipe" });
      return [true, `Stopped ${service}`];
    }
    return [false, `Unsupported platform: ${platform}`];
  } catch (err) {
    return [false, `Failed to stop: ${(err as Error).message}`];
  }
}

export function getDaemonStatus(bridgeHome?: string): string {
  const platform = getPlatform();

  try {
    if (platform === "macos") {
      const label = getLaunchdLabel(bridgeHome);
      const output = execSync(`launchctl print gui/${process.getuid?.()} ${label}`, { stdio: "pipe" }).toString();
      return output.includes("state = running") ? "running" : "stopped";
    }
    if (platform === "linux") {
      const service = getServiceName(bridgeHome);
      const output = execSync(`systemctl --user is-active ${service}`, { stdio: "pipe" }).toString().trim();
      return output;
    }
  } catch { /* not running or not installed */ }

  return "not installed";
}

export function isDaemonInstalled(bridgeHome?: string): boolean {
  const platform = getPlatform();
  if (platform === "macos") return existsSync(getLaunchdPlistPath(bridgeHome));
  if (platform === "linux") return existsSync(getSystemdUnitPath(bridgeHome));
  return false;
}
