/**
 * `bridge doctor` — self-diagnose common setup issues.
 *
 * Prints one `[ok]` / `[warn]` / `[fail]` line per check.
 * Exits 0 if no `[fail]`, 1 otherwise.
 */

import { existsSync, readFileSync } from "fs";
import { join } from "path";
import { homedir } from "os";
import { execSync } from "child_process";
import { tmuxAvailable, sessionRunning, getSessionName } from "../infra/bridge-cmd.js";
import {
  getDaemonStatus,
  getPlatform,
  isDaemonInstalled,
  getLaunchdLabel,
  getServiceName,
} from "../infra/daemon.js";
import type { BridgeConfig } from "../types.js";

// Minimal context shape (duplicated to avoid circular import with ./index.ts).
export interface CommandContext {
  db: unknown;
  bridgeHome: string;
  config: BridgeConfig;
  args: string[];
}

function ok(msg: string): void { console.log(`[ok]   ${msg}`); }
function warn(msg: string): void { console.log(`[warn] ${msg}`); }
function fail(msg: string): void { console.log(`[fail] ${msg}`); }

function whichExists(bin: string): boolean {
  try {
    execSync(`which ${bin}`, { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

function getDaemonConfigPath(bridgeHome: string): string | null {
  const platform = getPlatform();
  if (platform === "macos") {
    return join(homedir(), "Library", "LaunchAgents", `${getLaunchdLabel(bridgeHome)}.plist`);
  }
  if (platform === "linux") {
    return join(homedir(), ".config", "systemd", "user", `${getServiceName(bridgeHome)}.service`);
  }
  return null;
}

export async function cmdDoctor(ctx: CommandContext): Promise<number> {
  let failures = 0;

  // 1. bridge binary on PATH
  if (whichExists("bridge")) {
    ok("bridge binary on PATH");
  } else {
    warn("bridge not on PATH — run 'bun link' in the claude-bridge repo");
  }

  // 2. claude binary on PATH
  if (whichExists("claude")) {
    ok("claude CLI on PATH");
  } else {
    fail("claude CLI not on PATH — install Claude Code and ensure `claude` is available");
    failures++;
  }

  // 3. tmux available
  if (tmuxAvailable()) {
    ok("tmux available");
  } else {
    fail("tmux not installed — required for the bot session");
    failures++;
  }

  // 4. bot_dir configured and exists
  const botDir = ctx.config.bot_dir ?? null;
  if (!botDir) {
    fail("config.bot_dir is not set — run `bridge setup-bot <dir>`");
    failures++;
  } else if (!existsSync(botDir)) {
    fail(`config.bot_dir does not exist: ${botDir}`);
    failures++;
  } else {
    ok(`bot_dir exists: ${botDir}`);
  }

  // 5. CLAUDE.md
  if (botDir && existsSync(botDir)) {
    const claudeMd = join(botDir, "CLAUDE.md");
    if (existsSync(claudeMd)) {
      ok(`CLAUDE.md present: ${claudeMd}`);
    } else {
      fail(`CLAUDE.md missing at ${claudeMd} — re-run \`bridge setup-bot ${botDir} --force\``);
      failures++;
    }
  }

  // 6. .mcp.json
  if (botDir && existsSync(botDir)) {
    const mcpJsonPath = join(botDir, ".mcp.json");
    if (!existsSync(mcpJsonPath)) {
      fail(`.mcp.json missing at ${mcpJsonPath}`);
      failures++;
    } else {
      try {
        JSON.parse(readFileSync(mcpJsonPath, "utf-8"));
        ok(`.mcp.json valid: ${mcpJsonPath}`);
      } catch (err) {
        fail(`.mcp.json is invalid JSON (${(err as Error).message})`);
        failures++;
      }
    }
  }

  // 7. settings.local.json
  if (botDir && existsSync(botDir)) {
    const settingsPath = join(botDir, ".claude", "settings.local.json");
    if (!existsSync(settingsPath)) {
      warn(
        `${settingsPath} missing — run \`bridge setup-bot ${botDir} --force\` to regenerate`,
      );
    } else {
      try {
        const parsed = JSON.parse(readFileSync(settingsPath, "utf-8")) as {
          permissions?: { allow?: unknown };
        };
        const allow = parsed.permissions?.allow;
        const hasBridge = Array.isArray(allow)
          && allow.some((entry) => {
            if (typeof entry !== "string") return false;
            return entry.includes("mcp__bridge");
          });
        if (hasBridge) {
          ok(`settings.local.json allows bridge tools: ${settingsPath}`);
        } else {
          warn(
            `${settingsPath} has no bridge allow entry — run \`bridge setup-bot ${botDir} --force\` to regenerate`,
          );
        }
      } catch (err) {
        warn(`${settingsPath} is not valid JSON (${(err as Error).message})`);
      }
    }
  }

  // 8. Telegram token
  const tgToken =
    ctx.config.telegram_token
    ?? (ctx.config as unknown as { telegram_bot_token?: string | null }).telegram_bot_token
    ?? null;
  if (tgToken) {
    ok("telegram token configured");
  } else {
    warn("telegram_token not configured — Telegram notifications will be skipped");
  }

  // 9. Daemon installed? WorkingDirectory match?
  const installed = isDaemonInstalled(ctx.bridgeHome);
  if (!installed) {
    ok("daemon not installed (tmux-session mode)");
  } else {
    const daemonPath = getDaemonConfigPath(ctx.bridgeHome);
    if (daemonPath && existsSync(daemonPath)) {
      ok(`daemon service file exists: ${daemonPath}`);
      if (botDir) {
        const contents = readFileSync(daemonPath, "utf-8");
        const platform = getPlatform();
        let configuredDir: string | null = null;
        if (platform === "macos") {
          // Look for: <key>WorkingDirectory</key>\s*<string>DIR</string>
          const m = contents.match(
            /<key>WorkingDirectory<\/key>\s*<string>([^<]+)<\/string>/,
          );
          if (m && m[1]) configuredDir = m[1].trim();
        } else if (platform === "linux") {
          const m = contents.match(/^WorkingDirectory=(.+)$/m);
          if (m && m[1]) configuredDir = m[1].trim();
        }
        if (configuredDir === null) {
          warn(`could not parse WorkingDirectory from ${daemonPath}`);
        } else if (configuredDir !== botDir) {
          fail(
            `daemon WorkingDirectory (${configuredDir}) does not match config.bot_dir (${botDir}); reinstall: \`bridge uninstall && bridge install\``,
          );
          failures++;
        } else {
          ok(`daemon WorkingDirectory matches bot_dir: ${botDir}`);
        }
      }
    }
  }

  // 10. Daemon running? (informational)
  if (installed) {
    const status = getDaemonStatus(ctx.bridgeHome);
    if (status === "running" || status === "active") {
      ok(`daemon status: ${status}`);
    } else {
      warn(`daemon status: ${status}`);
    }
  }

  // 11. Session running? (informational)
  const sessionName = getSessionName(ctx.bridgeHome);
  if (sessionRunning(sessionName)) {
    ok(`tmux session running: ${sessionName}`);
  } else {
    warn(`tmux session not running: ${sessionName} (run \`bridge start\`)`);
  }

  return failures === 0 ? 0 : 1;
}
