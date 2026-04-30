/**
 * W2.5: SessionManager & ConfigProvider Tests
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync, existsSync, readFileSync } from "fs";
import { join } from "path";
import { tmpdir, homedir } from "os";
import { SessionManager } from "../../src/data/session.js";
import { ConfigProvider } from "../../src/config.js";

let tmpDir: string;
let sm: SessionManager;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-session-test-"));
  sm = new SessionManager(tmpDir);
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W2.5: SessionManager", () => {
  describe("deriveSessionId", () => {
    test("basic derivation", () => {
      expect(sm.deriveSessionId("backend", "/projects/my-api")).toBe("backend--my-api");
    });

    test("handles trailing slash", () => {
      expect(sm.deriveSessionId("backend", "/projects/my-api/")).toBe("backend--my-api");
    });

    test("uses only basename", () => {
      expect(sm.deriveSessionId("fe", "/deep/nested/project-ui")).toBe("fe--project-ui");
    });
  });

  describe("deriveAgentFileName", () => {
    test("adds bridge-- prefix", () => {
      expect(sm.deriveAgentFileName("backend--my-api")).toBe("bridge--backend--my-api");
    });
  });

  describe("validateAgentName", () => {
    test("valid name returns null", () => {
      expect(sm.validateAgentName("backend")).toBeNull();
      expect(sm.validateAgentName("my-agent-1")).toBeNull();
    });

    test("empty name returns error", () => {
      expect(sm.validateAgentName("")).toBeString();
    });

    test("too long name returns error", () => {
      expect(sm.validateAgentName("a".repeat(31))).toBeString();
    });

    test("invalid chars returns error", () => {
      expect(sm.validateAgentName("bad name")).toBeString();
      expect(sm.validateAgentName("bad_name")).toBeString();
      expect(sm.validateAgentName("-starts-dash")).toBeString();
    });

    test("double-dash returns error", () => {
      expect(sm.validateAgentName("bad--name")).toBeString();
    });
  });

  describe("validateProjectDir", () => {
    test("valid dir returns null", () => {
      expect(sm.validateProjectDir(tmpDir)).toBeNull();
    });

    test("nonexistent dir returns error", () => {
      expect(sm.validateProjectDir("/nonexistent/path/xyz")).toBeString();
    });
  });

  describe("Path methods", () => {
    test("getWorktreePath returns correct path", () => {
      const path = sm.getWorktreePath("backend--api");
      expect(path).toBe(join(tmpDir, "workspaces", "backend--api"));
    });

    test("getTasksDir returns correct path", () => {
      const path = sm.getTasksDir("backend--api");
      expect(path).toBe(join(tmpDir, "workspaces", "backend--api", "tasks"));
    });

    test("getAgentMdPath without botDir uses global path", () => {
      const path = sm.getAgentMdPath("backend--api");
      expect(path).toBe(join(homedir(), ".claude", "agents", "bridge--backend--api.md"));
    });

    test("getAgentMdPath with botDir uses bot path", () => {
      const path = sm.getAgentMdPath("backend--api", "/projects/bot");
      expect(path).toBe(join("/projects/bot", ".claude", "agents", "bridge--backend--api.md"));
    });
  });

  describe("getInstancePrefix", () => {
    test("default home returns empty string", () => {
      const defaultSm = new SessionManager(join(homedir(), ".claude-bridge"));
      expect(defaultSm.getInstancePrefix()).toBe("");
    });

    test("non-default home returns prefix", () => {
      const customSm = new SessionManager(join(homedir(), ".claude-bridge-prod"));
      expect(customSm.getInstancePrefix()).toBe("prod");
    });

    test("deeply nested path returns sanitized basename", () => {
      const customSm = new SessionManager("/tmp/test-bridge");
      expect(customSm.getInstancePrefix()).toBe("test-bridge");
    });
  });

  describe("Workspace operations", () => {
    test("createWorkspace creates directory and metadata", () => {
      sm.createWorkspace("backend--api", "backend", "/projects/api", "API dev");
      const wsDir = join(tmpDir, "workspaces", "backend--api");
      expect(existsSync(wsDir)).toBe(true);
      expect(existsSync(join(wsDir, "tasks"))).toBe(true);

      const metadata = JSON.parse(readFileSync(join(wsDir, "metadata.json"), "utf-8"));
      expect(metadata.agent_name).toBe("backend");
      expect(metadata.project_dir).toBe("/projects/api");
      expect(metadata.session_id).toBe("backend--api");
      expect(metadata.purpose).toBe("API dev");
    });

    test("createWorkspace is idempotent", () => {
      sm.createWorkspace("backend--api", "backend", "/projects/api", "API dev");
      sm.createWorkspace("backend--api", "backend", "/projects/api", "API dev");
      expect(existsSync(join(tmpDir, "workspaces", "backend--api"))).toBe(true);
    });

    test("cleanupWorkspace removes directory", () => {
      sm.createWorkspace("backend--api", "backend", "/projects/api", "API dev");
      sm.cleanupWorkspace("backend--api");
      expect(existsSync(join(tmpDir, "workspaces", "backend--api"))).toBe(false);
    });

    test("cleanupWorkspace handles nonexistent directory", () => {
      // Should not throw
      sm.cleanupWorkspace("nonexistent--session");
    });
  });
});

describe("W2.5: ConfigProvider", () => {
  test("uses CLAUDE_BRIDGE_HOME env var", () => {
    const config = new ConfigProvider(tmpDir);
    expect(config.homeDir).toBe(tmpDir);
    expect(config.dbPath).toBe(join(tmpDir, "bridge.db"));
  });

  test("load returns config with defaults", () => {
    const config = new ConfigProvider(tmpDir);
    const loaded = config.load();
    expect(loaded.home_dir).toBe(tmpDir);
    expect(loaded.db_path).toBe(join(tmpDir, "bridge.db"));
    expect(loaded.bot_dir).toBeNull();
    // telegram_token may come from env var, so just check it's a string or null
    expect(loaded.telegram_token === null || typeof loaded.telegram_token === "string").toBe(true);
  });

  test("load reads config.json if present", () => {
    const configPath = join(tmpDir, "config.json");
    Bun.write(configPath, JSON.stringify({ bot_dir: "/projects/bot", telegram_token: "test-token" }));
    const config = new ConfigProvider(tmpDir);
    const loaded = config.load();
    expect(loaded.bot_dir).toBe("/projects/bot");
    expect(loaded.telegram_token).toBe("test-token");
  });
});
