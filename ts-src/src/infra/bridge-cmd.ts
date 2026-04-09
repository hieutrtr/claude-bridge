/**
 * Bridge Command — session management (tmux, start/stop, status).
 *
 * Matches Python bridge_cmd.py + tmux_session.py behavior.
 */

import { existsSync, readFileSync } from "fs";
import { join, basename } from "path";
import { homedir } from "os";
import { execSync } from "child_process";
import type { BridgeConfig } from "../types.js";

// --- Session Naming ---

export function getSessionName(bridgeHome?: string): string {
  const home = bridgeHome ?? join(homedir(), ".claude-bridge");
  const base = basename(home);
  if (base === ".claude-bridge") return "claude-bridge";
  // Hash for uniqueness
  const hash = Bun.hash(base).toString(16).slice(0, 8);
  return `claude-bridge-${hash}`;
}

export function getLogPath(bridgeHome?: string): string {
  const home = bridgeHome ?? join(homedir(), ".claude-bridge");
  return join(home, "bridge.log");
}

// --- Tmux Operations ---

export function tmuxAvailable(): boolean {
  try {
    execSync("which tmux", { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

export function sessionRunning(name?: string): boolean {
  const sessionName = name ?? getSessionName();
  try {
    execSync(`tmux has-session -t ${sessionName} 2>/dev/null`, { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

export function startSession(
  command: string[],
  bridgeHome?: string,
): [boolean, string] {
  const sessionName = getSessionName(bridgeHome);
  const logPath = getLogPath(bridgeHome);

  if (sessionRunning(sessionName)) {
    return [false, `Session "${sessionName}" already running`];
  }

  if (!tmuxAvailable()) {
    return [false, "tmux not installed"];
  }

  try {
    const cmd = command.map(shellQuote).join(" ");
    execSync(
      `tmux new-session -d -s ${sessionName} '${cmd}'`,
      { stdio: "pipe" },
    );

    // Pipe output to log
    try {
      execSync(
        `tmux pipe-pane -t ${sessionName} "cat >> ${logPath}"`,
        { stdio: "pipe" },
      );
    } catch { /* ok if pipe-pane fails */ }

    return [true, `Started session "${sessionName}"`];
  } catch (err) {
    return [false, `Failed to start: ${(err as Error).message}`];
  }
}

export function stopSession(bridgeHome?: string, timeout: number = 5): [boolean, string] {
  const sessionName = getSessionName(bridgeHome);

  if (!sessionRunning(sessionName)) {
    return [false, `Session "${sessionName}" not running`];
  }

  try {
    // Graceful: send C-c
    execSync(`tmux send-keys -t ${sessionName} C-c`, { stdio: "pipe" });

    // Wait for graceful stop
    const deadline = Date.now() + timeout * 1000;
    while (Date.now() < deadline && sessionRunning(sessionName)) {
      execSync("sleep 0.5", { stdio: "pipe" });
    }

    // Force kill if still running
    if (sessionRunning(sessionName)) {
      execSync(`tmux kill-session -t ${sessionName}`, { stdio: "pipe" });
    }

    return [true, `Stopped session "${sessionName}"`];
  } catch (err) {
    return [false, `Failed to stop: ${(err as Error).message}`];
  }
}

export function getSessionPid(bridgeHome?: string): number | null {
  const sessionName = getSessionName(bridgeHome);
  try {
    const output = execSync(
      `tmux list-panes -t ${sessionName} -F "#{pane_pid}"`,
      { stdio: "pipe" },
    ).toString().trim();
    const pid = parseInt(output.split("\n")[0]!, 10);
    return isNaN(pid) ? null : pid;
  } catch {
    return null;
  }
}

export function getSessionUptime(bridgeHome?: string): string | null {
  const sessionName = getSessionName(bridgeHome);
  try {
    const output = execSync(
      `tmux display-message -t ${sessionName} -p "#{session_created}"`,
      { stdio: "pipe" },
    ).toString().trim();
    const created = parseInt(output, 10);
    if (isNaN(created)) return null;

    const elapsed = Math.floor(Date.now() / 1000) - created;
    return formatDuration(elapsed);
  } catch {
    return null;
  }
}

// --- Config Validation ---

export function validateConfig(config: BridgeConfig): string[] {
  const errors: string[] = [];

  const botDir = config.bot_dir ?? undefined;
  if (!botDir) {
    errors.push("bot_dir not configured");
  } else if (!existsSync(botDir)) {
    errors.push(`bot_dir not found: ${botDir}`);
  }

  if (!config.telegram_token) {
    errors.push("telegram_token not configured");
  }

  return errors;
}

// --- Process Cleanup ---

const KILL_PATTERNS = [
  "claude.*bridge-bot",
  "bun.*bridge",
  "claude-bridge",
];

export function killBridgeProcesses(): void {
  for (const pattern of KILL_PATTERNS) {
    try {
      execSync(`pkill -f "${pattern}" 2>/dev/null || true`, { stdio: "pipe" });
    } catch { /* ignore */ }
  }
}

export function bridgeProcessesRunning(): boolean {
  for (const pattern of KILL_PATTERNS) {
    try {
      execSync(`pgrep -f "${pattern}"`, { stdio: "pipe" });
      return true;
    } catch { /* not found */ }
  }
  return false;
}

// --- Helpers ---

function shellQuote(s: string): string {
  return s.replace(/'/g, "'\\''");
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (hours < 24) return `${hours}h ${mins}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}
