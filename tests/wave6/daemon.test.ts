/**
 * W6.1: DaemonManager Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, existsSync, readFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import {
  getPlatform,
  getServiceName,
  getLaunchdLabel,
  installDaemon,
  uninstallDaemon,
  isDaemonInstalled,
} from "../../src/infra/daemon.js";

describe("W6.1: DaemonManager", () => {
  describe("getPlatform", () => {
    test("returns macos or linux", () => {
      const platform = getPlatform();
      expect(["macos", "linux", "other"]).toContain(platform);
    });
  });

  describe("getServiceName", () => {
    test("derives name from default home", () => {
      const name = getServiceName("/home/user/.claude-bridge");
      expect(name).toBe("claude-bridge");
    });

    test("derives name from custom home", () => {
      const name = getServiceName("/home/user/.claude-bridge-alice");
      expect(name).toBe("claude-bridge-alice");
    });

    test("strips dots from name", () => {
      const name = getServiceName("/home/user/.special.bridge");
      expect(name).toBe("specialbridge");
    });
  });

  describe("getLaunchdLabel", () => {
    test("prefixes with ai.", () => {
      const label = getLaunchdLabel("/home/user/.claude-bridge");
      expect(label).toBe("ai.claude-bridge");
    });
  });

  describe("installDaemon", () => {
    test("generates service file", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "bridge-daemon-"));
      const botDir = mkdtempSync(join(tmpdir(), "bridge-bot-"));

      // installDaemon writes to ~/Library/LaunchAgents or ~/.config/systemd
      // We test the return value, not the file (would need to mock home)
      const [ok, msg] = installDaemon(botDir, tmpDir);
      const platform = getPlatform();

      if (platform === "macos" || platform === "linux") {
        expect(ok).toBe(true);
        expect(msg).toContain("Installed");
      } else {
        expect(ok).toBe(false);
      }

      // Must uninstall — installDaemon writes into real ~/Library/LaunchAgents
      // (or ~/.config/systemd/user) and macOS flags every leftover plist via
      // the "Background Items Added" notification.
      uninstallDaemon(tmpDir);
      rmSync(tmpDir, { recursive: true, force: true });
      rmSync(botDir, { recursive: true, force: true });
    });
  });

  describe("isDaemonInstalled", () => {
    test("returns boolean", () => {
      const result = isDaemonInstalled("/tmp/nonexistent-bridge-home");
      expect(typeof result).toBe("boolean");
    });
  });
});
