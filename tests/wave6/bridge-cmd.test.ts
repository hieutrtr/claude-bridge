/**
 * W6.2: BridgeCmd Tests
 */
import { describe, test, expect } from "bun:test";
import {
  getSessionName,
  getLogPath,
  tmuxAvailable,
  validateConfig,
} from "../../src/infra/bridge-cmd.js";
import type { BridgeConfig } from "../../src/types.js";

describe("W6.2: BridgeCmd", () => {
  describe("getSessionName", () => {
    test("returns claude-bridge for default home", () => {
      // The actual value depends on homedir, but should contain "claude-bridge"
      const name = getSessionName();
      expect(name).toContain("claude-bridge");
    });

    test("returns unique name for custom home", () => {
      const name1 = getSessionName("/home/user/.claude-bridge-alice");
      const name2 = getSessionName("/home/user/.claude-bridge-bob");
      expect(name1).not.toBe(name2);
    });
  });

  describe("getLogPath", () => {
    test("returns bridge.log in home dir", () => {
      const path = getLogPath("/tmp/bridge");
      expect(path).toBe("/tmp/bridge/bridge.log");
    });
  });

  describe("tmuxAvailable", () => {
    test("returns boolean", () => {
      expect(typeof tmuxAvailable()).toBe("boolean");
    });
  });

  describe("validateConfig", () => {
    test("reports missing bot_dir", () => {
      const config = {
        home_dir: "/tmp",
        db_path: "/tmp/bridge.db",
        bot_dir: null,
        telegram_token: "test",
        telegram_chat_id: null,
      } as BridgeConfig;
      const errors = validateConfig(config);
      expect(errors.some(e => e.includes("bot_dir"))).toBe(true);
    });

    test("reports missing telegram_token", () => {
      const config = {
        home_dir: "/tmp",
        db_path: "/tmp/bridge.db",
        bot_dir: "/tmp/bot",
        telegram_token: null,
        telegram_chat_id: null,
      } as BridgeConfig;
      const errors = validateConfig(config);
      expect(errors.some(e => e.includes("telegram_token"))).toBe(true);
    });

    test("no errors for valid config (with existing bot_dir)", () => {
      const config = {
        home_dir: "/tmp",
        db_path: "/tmp/bridge.db",
        bot_dir: "/tmp",
        telegram_token: "test-token",
        telegram_chat_id: null,
      } as BridgeConfig;
      const errors = validateConfig(config);
      // bot_dir exists (/tmp), token set → only non-existing paths fail
      expect(errors.length).toBe(0);
    });
  });
});
