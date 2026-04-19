/**
 * setup-bot command — interactively scaffolds a bridge bot directory.
 *
 * Creates:
 *   {bot-dir}/CLAUDE.md       (via generateBridgeBotMd)
 *   {bot-dir}/.mcp.json       (bridge MCP server wiring)
 *   {bot-dir}/.claude/agents/ (empty, for per-agent .md files)
 *
 * Persists bot_dir (and optionally telegram_token) to {bridgeHome}/config.json.
 */

import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "fs";
import { join, resolve, dirname } from "path";
import { homedir } from "os";
import { fileURLToPath } from "url";
import { generateBridgeBotMd } from "../mcp/bridge-md.js";
import type { BridgeConfig } from "../types.js";

// Minimal CommandContext shape — intentionally duplicated to avoid a circular
// import with ./index.ts (which imports cmdSetupBot from this file).
export interface CommandContext {
  db: unknown;
  bridgeHome: string;
  config: BridgeConfig;
  args: string[];
}

function saveConfig(bridgeHome: string, config: BridgeConfig): void {
  writeFileSync(
    join(bridgeHome, "config.json"),
    JSON.stringify(config, null, 2),
    "utf-8",
  );
}

// --- Helpers ---

function expandPath(p: string): string {
  if (p.startsWith("~")) return join(homedir(), p.slice(1));
  return resolve(process.cwd(), p);
}

function getArg(args: string[], name: string): string | undefined {
  const idx = args.indexOf(`--${name}`);
  if (idx >= 0 && idx + 1 < args.length) return args[idx + 1];
  return undefined;
}

function getFlag(args: string[], name: string): boolean {
  return args.includes(`--${name}`);
}

function getPositional(args: string[], index: number): string | undefined {
  let pos = 0;
  for (let i = 0; i < args.length; i++) {
    const a = args[i]!;
    if (a.startsWith("--")) {
      // Flags that do NOT take a value:
      if (a === "--no-prompt" || a === "--force") continue;
      i++; // skip flag value
      continue;
    }
    if (pos === index) return a;
    pos++;
  }
  return undefined;
}

/**
 * Read a single line from stdin, returning the trimmed response (or empty string on EOF).
 */
async function ask(question: string): Promise<string> {
  process.stdout.write(question);
  // Bun provides a global prompt(); fall back to stdin if unavailable.
  if (typeof (globalThis as { prompt?: unknown }).prompt === "function") {
    const r = (globalThis as { prompt: (msg?: string) => string | null }).prompt("");
    return (r ?? "").trim();
  }

  return await new Promise<string>((resolvePromise) => {
    let buf = "";
    const onData = (chunk: Buffer) => {
      buf += chunk.toString("utf-8");
      const nl = buf.indexOf("\n");
      if (nl >= 0) {
        process.stdin.off("data", onData);
        process.stdin.pause();
        resolvePromise(buf.slice(0, nl).trim());
      }
    };
    process.stdin.on("data", onData);
    process.stdin.resume();
  });
}

/**
 * Walk up from the CLI's own file location until we find the claude-bridge repo root
 * (identified by package.json with `"name": "claude-bridge"`). Returns absolute path.
 */
function findRepoRoot(): string {
  // import.meta.url points to this file; walk up looking for package.json.
  let dir = dirname(fileURLToPath(import.meta.url));
  for (let i = 0; i < 10; i++) {
    const pkgPath = join(dir, "package.json");
    if (existsSync(pkgPath)) {
      try {
        const pkg = JSON.parse(readFileSync(pkgPath, "utf-8")) as {
          name?: string;
        };
        if (pkg.name === "claude-bridge") return dir;
      } catch {
        /* keep walking */
      }
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  // Fallback: two levels up from this file (src/cli/ -> repo root)
  return resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
}

function directoryNonEmpty(dir: string): boolean {
  if (!existsSync(dir)) return false;
  try {
    return readdirSync(dir).length > 0;
  } catch {
    return false;
  }
}

// --- Command ---

export async function cmdSetupBot(ctx: CommandContext): Promise<number> {
  const rawBotDir = getPositional(ctx.args, 0);
  if (!rawBotDir) {
    process.stderr.write(
      "Usage: bridge setup-bot <bot-dir> [--telegram-token TOKEN] [--no-prompt] [--force]\n",
    );
    return 1;
  }

  const botDir = expandPath(rawBotDir);
  const noPrompt = getFlag(ctx.args, "no-prompt");
  const force = getFlag(ctx.args, "force");
  const cliToken = getArg(ctx.args, "telegram-token");

  // 1. Overwrite check
  if (directoryNonEmpty(botDir) && !force) {
    if (noPrompt) {
      process.stderr.write(
        `Directory ${botDir} exists and is non-empty. Use --force to overwrite.\n`,
      );
      return 1;
    }
    const answer = await ask(`Directory ${botDir} exists. Overwrite? [y/N] `);
    if (!/^y(es)?$/i.test(answer)) {
      console.log("Aborted.");
      return 1;
    }
  }

  // 2. Create directory structure
  mkdirSync(join(botDir, ".claude", "agents"), { recursive: true });

  // 3. Write CLAUDE.md
  const claudeMdPath = join(botDir, "CLAUDE.md");
  writeFileSync(claudeMdPath, generateBridgeBotMd(), "utf-8");

  // 4. Resolve Telegram token FIRST so we can bake it into .mcp.json env below.
  let telegramToken: string | null = ctx.config.telegram_token ?? null;
  if (cliToken) {
    telegramToken = cliToken;
  } else if (!noPrompt) {
    const entered = await ask("Telegram bot token (leave blank to skip): ");
    if (entered) telegramToken = entered;
    else if (!telegramToken) {
      process.stderr.write(
        "Warning: no telegram_token set. `bridge start` will fail until you configure one.\n",
      );
    }
  } else if (!telegramToken) {
    process.stderr.write(
      "Warning: no telegram_token set (--no-prompt and no --telegram-token). "
        + "`bridge start` will fail until you configure one.\n",
    );
  }

  // 5. Write .mcp.json — include TELEGRAM_BOT_TOKEN in env only if we have one.
  const repoRoot = findRepoRoot();
  const serverPath = join(repoRoot, "src", "mcp", "server.ts");
  const mcpEnv: Record<string, string> = {
    CLAUDE_BRIDGE_HOME: ctx.bridgeHome,
  };
  if (telegramToken) {
    mcpEnv["TELEGRAM_BOT_TOKEN"] = telegramToken;
  }
  const mcpJson = {
    mcpServers: {
      bridge: {
        command: "bun",
        args: ["run", serverPath],
        env: mcpEnv,
      },
    },
  };
  writeFileSync(
    join(botDir, ".mcp.json"),
    JSON.stringify(mcpJson, null, 2),
    "utf-8",
  );

  // 5b. Write .claude/settings.local.json (permissions allowlist for bridge tools)
  const settingsPath = join(botDir, ".claude", "settings.local.json");
  const settingsSummary = writeSettingsLocal(settingsPath, force);

  // 6. Save config
  mkdirSync(ctx.bridgeHome, { recursive: true });
  const newConfig = {
    ...ctx.config,
    home_dir: ctx.bridgeHome,
    db_path: join(ctx.bridgeHome, "bridge.db"),
    bot_dir: botDir,
    telegram_token: telegramToken,
    telegram_chat_id: ctx.config.telegram_chat_id ?? null,
  };
  saveConfig(ctx.bridgeHome, newConfig);

  console.log(`Setup complete in ${botDir}`);
  console.log(`  CLAUDE.md: ${claudeMdPath}`);
  console.log(`  .mcp.json: ${join(botDir, ".mcp.json")}`);
  console.log(`  settings.local.json ${settingsSummary}${settingsPath}`);
  console.log(`  Agents dir: ${join(botDir, ".claude", "agents")}`);
  console.log("");
  console.log("Next: `bridge start` to launch the bot.");
  return 0;
}

/**
 * Default allowlist baked into a fresh `.claude/settings.local.json`.
 *
 * The bridge bot runs autonomously (no human to answer permission prompts),
 * so we pre-approve every built-in tool it needs plus the bridge MCP wildcard.
 * `defaultMode: acceptEdits` short-circuits approval prompts for edits.
 */
const DEFAULT_ALLOW = [
  "Read",
  "Write",
  "Edit",
  "MultiEdit",
  "NotebookEdit",
  "Bash",
  "Glob",
  "Grep",
  "WebFetch",
  "WebSearch",
  "TodoWrite",
  "Task",
  "mcp__bridge__*",
];

/**
 * Write or merge `.claude/settings.local.json` so the bridge bot can run its
 * tools non-interactively.
 *
 * Behaviour:
 * - File missing             → write a fresh file with the full default allow-list.
 * - File exists, --force     → overwrite.
 * - File exists, mergeable   → add any missing entries from DEFAULT_ALLOW to
 *                              `permissions.allow`, set `defaultMode` if unset
 *                              (never override a user-set value), and ensure
 *                              `enableAllProjectMcpServers` is true.
 * - File exists, ambiguous   → warn and skip. User can re-run with --force.
 *
 * Returns a short human-readable suffix used in the setup summary.
 */
function writeSettingsLocal(settingsPath: string, force: boolean): string {
  const defaults = {
    permissions: {
      allow: [...DEFAULT_ALLOW],
      defaultMode: "acceptEdits",
    },
    enableAllProjectMcpServers: true,
  };

  mkdirSync(dirname(settingsPath), { recursive: true });

  if (!existsSync(settingsPath) || force) {
    writeFileSync(settingsPath, JSON.stringify(defaults, null, 2), "utf-8");
    return " → ";
  }

  // Conservative merge: only mutate if we understand the existing shape.
  let existing: unknown;
  try {
    existing = JSON.parse(readFileSync(settingsPath, "utf-8"));
  } catch {
    process.stderr.write(
      `Warning: ${settingsPath} is not valid JSON; leaving as-is. Re-run with --force to overwrite.\n`,
    );
    return " (skipped; invalid JSON) → ";
  }

  if (existing === null || typeof existing !== "object" || Array.isArray(existing)) {
    process.stderr.write(
      `Warning: ${settingsPath} is not an object; leaving as-is. Re-run with --force to overwrite.\n`,
    );
    return " (skipped; unexpected shape) → ";
  }

  const obj = existing as Record<string, unknown>;
  const perms = obj["permissions"];
  let changed = false;

  if (perms === undefined) {
    obj["permissions"] = {
      allow: [...DEFAULT_ALLOW],
      defaultMode: "acceptEdits",
    };
    changed = true;
  } else if (perms !== null && typeof perms === "object" && !Array.isArray(perms)) {
    const p = perms as Record<string, unknown>;
    const allow = p["allow"];
    if (allow === undefined) {
      p["allow"] = [...DEFAULT_ALLOW];
      changed = true;
    } else if (Array.isArray(allow)) {
      for (const entry of DEFAULT_ALLOW) {
        if (!allow.includes(entry)) {
          allow.push(entry);
          changed = true;
        }
      }
    } else {
      process.stderr.write(
        `Warning: ${settingsPath}: permissions.allow is not an array; skipping merge. Re-run with --force to overwrite.\n`,
      );
      return " (skipped; ambiguous shape) → ";
    }

    // Only set defaultMode if user hasn't set one — don't clobber their choice.
    if (p["defaultMode"] === undefined) {
      p["defaultMode"] = "acceptEdits";
      changed = true;
    }
  } else {
    process.stderr.write(
      `Warning: ${settingsPath}: permissions is not an object; skipping merge. Re-run with --force to overwrite.\n`,
    );
    return " (skipped; ambiguous shape) → ";
  }

  if (obj["enableAllProjectMcpServers"] !== true) {
    obj["enableAllProjectMcpServers"] = true;
    changed = true;
  }

  if (changed) {
    writeFileSync(settingsPath, JSON.stringify(obj, null, 2), "utf-8");
    return " (merged) → ";
  }
  return " (unchanged) → ";
}
