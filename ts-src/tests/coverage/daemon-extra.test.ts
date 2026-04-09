/**
 * Extra coverage tests for src/infra/daemon.ts
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync, existsSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import {
  getPlatform,
  isContainerEnvironment,
  getServiceName,
  getLaunchdLabel,
  installDaemon,
  uninstallDaemon,
  startDaemon,
  stopDaemon,
  getDaemonStatus,
  isDaemonInstalled,
} from "../../src/infra/daemon.js";

describe("daemon.ts coverage", () => {
  describe("getPlatform", () => {
    test("returns macos on darwin", () => {
      const p = getPlatform();
      if (process.platform === "darwin") expect(p).toBe("macos");
      if (process.platform === "linux") expect(p).toBe("linux");
    });
  });

  describe("isContainerEnvironment", () => {
    test("returns boolean", () => {
      const result = isContainerEnvironment();
      expect(typeof result).toBe("boolean");
      // On macOS, should be false (no /.dockerenv, no /proc)
      if (process.platform === "darwin") {
        expect(result).toBe(false);
      }
    });
  });

  describe("getServiceName", () => {
    test("default home", () => {
      expect(getServiceName("/Users/test/.claude-bridge")).toBe("claude-bridge");
    });

    test("custom home strips dots", () => {
      expect(getServiceName("/Users/test/.my.bridge")).toBe("mybridge");
    });

    test("uses default when undefined", () => {
      const name = getServiceName();
      expect(typeof name).toBe("string");
      expect(name.length).toBeGreaterThan(0);
    });
  });

  describe("getLaunchdLabel", () => {
    test("prefixes with ai.", () => {
      expect(getLaunchdLabel("/Users/test/.claude-bridge")).toBe("ai.claude-bridge");
    });

    test("uses default when undefined", () => {
      const label = getLaunchdLabel();
      expect(label).toMatch(/^ai\./);
    });
  });

  describe("installDaemon", () => {
    test("installs on current platform", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "daemon-inst-"));
      const botDir = mkdtempSync(join(tmpdir(), "daemon-bot-"));
      const [ok, msg] = installDaemon(botDir, tmpDir);
      const platform = getPlatform();

      if (platform === "macos" || platform === "linux") {
        expect(ok).toBe(true);
        expect(msg).toContain("Installed");
      } else {
        expect(ok).toBe(false);
        expect(msg).toContain("Unsupported");
      }

      rmSync(tmpDir, { recursive: true, force: true });
      rmSync(botDir, { recursive: true, force: true });
    });

    test("installs with custom log path", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "daemon-inst2-"));
      const botDir = mkdtempSync(join(tmpdir(), "daemon-bot2-"));
      const logPath = join(tmpDir, "custom.log");
      const [ok, msg] = installDaemon(botDir, tmpDir, logPath);
      const platform = getPlatform();

      if (platform === "macos" || platform === "linux") {
        expect(ok).toBe(true);
      }

      rmSync(tmpDir, { recursive: true, force: true });
      rmSync(botDir, { recursive: true, force: true });
    });
  });

  describe("uninstallDaemon", () => {
    test("returns not installed for nonexistent home", () => {
      const [ok, msg] = uninstallDaemon("/tmp/nonexistent-daemon-home-999");
      const platform = getPlatform();
      if (platform === "macos" || platform === "linux") {
        expect(ok).toBe(false);
        expect(msg).toContain("not installed");
      }
    });

    test("uninstalls previously installed daemon", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "daemon-uninst-"));
      const botDir = mkdtempSync(join(tmpdir(), "daemon-bot-uninst-"));

      // Install first
      installDaemon(botDir, tmpDir);

      // Then uninstall
      const [ok, msg] = uninstallDaemon(tmpDir);
      const platform = getPlatform();
      if (platform === "macos" || platform === "linux") {
        expect(ok).toBe(true);
        expect(msg).toContain("Uninstalled");
      }

      rmSync(tmpDir, { recursive: true, force: true });
      rmSync(botDir, { recursive: true, force: true });
    });
  });

  describe("startDaemon", () => {
    test("returns not installed for nonexistent home", () => {
      const [ok, msg] = startDaemon("/tmp/nonexistent-daemon-start-999");
      expect(ok).toBe(false);
    });
  });

  describe("stopDaemon", () => {
    test("returns error for nonexistent service", () => {
      const [ok, msg] = stopDaemon("/tmp/nonexistent-daemon-stop-999");
      expect(ok).toBe(false);
    });
  });

  describe("getDaemonStatus", () => {
    test("returns status string for nonexistent home", () => {
      const status = getDaemonStatus("/tmp/nonexistent-daemon-status-999");
      // May return "not installed" or "stopped" depending on platform behavior
      expect(["not installed", "stopped", "inactive"]).toContain(status);
    });
  });

  describe("isDaemonInstalled", () => {
    test("returns false for nonexistent home", () => {
      expect(isDaemonInstalled("/tmp/nonexistent-daemon-check-999")).toBe(false);
    });

    test("returns true after install", () => {
      const tmpDir = mkdtempSync(join(tmpdir(), "daemon-check-"));
      const botDir = mkdtempSync(join(tmpdir(), "daemon-bot-check-"));
      installDaemon(botDir, tmpDir);

      const platform = getPlatform();
      if (platform === "macos" || platform === "linux") {
        expect(isDaemonInstalled(tmpDir)).toBe(true);
      }

      // Clean up
      uninstallDaemon(tmpDir);
      rmSync(tmpDir, { recursive: true, force: true });
      rmSync(botDir, { recursive: true, force: true });
    });
  });
});
