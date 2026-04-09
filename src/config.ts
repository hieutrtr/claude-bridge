/**
 * Configuration — resolves CLAUDE_BRIDGE_HOME and loads bridge config.
 *
 * Replaces Python's __init__.py config resolution.
 */

import { homedir } from "os";
import { join } from "path";
import { existsSync, readFileSync } from "fs";
import type { BridgeConfig } from "./types.js";
import type { IConfigProvider } from "./data/interfaces.js";

const DEFAULT_HOME = join(homedir(), ".claude-bridge");

export class ConfigProvider implements IConfigProvider {
  readonly homeDir: string;
  readonly dbPath: string;

  constructor(homeDir?: string) {
    this.homeDir = homeDir ?? process.env["CLAUDE_BRIDGE_HOME"] ?? DEFAULT_HOME;
    this.dbPath = join(this.homeDir, "bridge.db");
  }

  load(): BridgeConfig {
    const configPath = join(this.homeDir, "config.json");
    let config: Record<string, unknown> = {};

    if (existsSync(configPath)) {
      config = JSON.parse(readFileSync(configPath, "utf-8")) as Record<string, unknown>;
    }

    return {
      home_dir: this.homeDir,
      db_path: this.dbPath,
      bot_dir: (config["bot_dir"] as string) ?? null,
      telegram_token: (config["telegram_token"] as string) ?? process.env["TELEGRAM_BOT_TOKEN"] ?? null,
      telegram_chat_id: (config["telegram_chat_id"] as string) ?? process.env["TELEGRAM_CHAT_ID"] ?? null,
    };
  }
}
