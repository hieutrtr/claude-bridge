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

function generateLaunchdPlist(
  botDir: string,
  bridgeHome: string,
  logPath: string,
): string {
  const label = getLaunchdLabel(bridgeHome);
  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>tmux</string>
    <string>new-session</string>
    <string>-d</string>
    <string>-s</string>
    <string>${getServiceName(bridgeHome)}</string>
    <string>CLAUDE_BRIDGE_HOME=${bridgeHome} claude --agent bridge-bot --resume</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${botDir}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CLAUDE_BRIDGE_HOME</key>
    <string>${bridgeHome}</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
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
  return `[Unit]
Description=Claude Bridge (${sessionName})
After=network.target

[Service]
Type=forking
WorkingDirectory=${botDir}
Environment=CLAUDE_BRIDGE_HOME=${bridgeHome}
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/tmux new-session -d -s ${sessionName} 'CLAUDE_BRIDGE_HOME=${bridgeHome} claude --agent bridge-bot --resume'
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
      execSync(`launchctl bootstrap gui/${process.getuid?.()} ${plistPath}`, { stdio: "pipe" });
      return [true, `Started ${label}`];
    }
    if (platform === "linux") {
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
