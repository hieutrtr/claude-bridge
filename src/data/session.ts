/**
 * Session Manager — derives session IDs, paths, and manages workspaces.
 *
 * Session ID format: "agent--project" e.g. "backend--my-api"
 * Matches Python session.py exactly.
 */

import { basename, join, normalize } from "path";
import { homedir } from "os";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "fs";
import type { ISessionManager } from "./interfaces.js";

export class SessionManager implements ISessionManager {
  constructor(private homeDir: string) {}

  deriveSessionId(agentName: string, projectPath: string): string {
    const projectBasename = basename(normalize(projectPath));
    return `${agentName}--${projectBasename}`;
  }

  deriveAgentFileName(sessionId: string): string {
    return `bridge--${sessionId}`;
  }

  validateAgentName(name: string): string | null {
    if (!name) {
      return "Agent name cannot be empty.";
    }
    if (name.length > 30) {
      return "Agent name must be 30 characters or less.";
    }
    if (!/^[a-zA-Z0-9][a-zA-Z0-9-]*$/.test(name)) {
      return "Agent name must be alphanumeric + hyphens, starting with a letter or digit.";
    }
    if (name.includes("--")) {
      return "Agent name cannot contain double-dash (--)."
    }
    return null;
  }

  validateProjectDir(path: string): string | null {
    const expanded = path.startsWith("~") ? path.replace("~", homedir()) : path;
    if (!existsSync(expanded)) {
      return `Directory '${path}' does not exist.`;
    }
    return null;
  }

  getWorktreePath(sessionId: string): string {
    return join(this.homeDir, "workspaces", sessionId);
  }

  getTasksDir(sessionId: string): string {
    return join(this.getWorktreePath(sessionId), "tasks");
  }

  getAgentMdPath(sessionId: string, botDir?: string): string {
    const name = this.deriveAgentFileName(sessionId);
    if (botDir) {
      return join(botDir, ".claude", "agents", `${name}.md`);
    }
    return join(homedir(), ".claude", "agents", `${name}.md`);
  }

  getInstancePrefix(): string {
    const defaultHome = join(homedir(), ".claude-bridge");
    if (normalize(this.homeDir) === normalize(defaultHome)) {
      return "";
    }
    let name = basename(this.homeDir);
    // Strip common prefixes
    for (const strip of [".claude-bridge-", "claude-bridge-", ".bridge-", "bridge-"]) {
      if (name.startsWith(strip)) {
        name = name.slice(strip.length);
        break;
      }
    }
    // Sanitize: keep only alphanumeric and hyphens
    name = name.replace(/[^a-zA-Z0-9-]/g, "-").replace(/^-+|-+$/g, "");
    return (name || "custom").slice(0, 20);
  }

  createWorkspace(sessionId: string, agentName: string, projectDir: string, purpose: string): void {
    const wsDir = this.getWorktreePath(sessionId);
    const tasksDir = this.getTasksDir(sessionId);
    mkdirSync(tasksDir, { recursive: true });

    const metadata = {
      agent_name: agentName,
      project_dir: projectDir,
      session_id: sessionId,
      purpose,
      created_at: new Date().toISOString(),
    };
    writeFileSync(join(wsDir, "metadata.json"), JSON.stringify(metadata, null, 2));
  }

  cleanupWorkspace(sessionId: string): void {
    const wsDir = this.getWorktreePath(sessionId);
    if (existsSync(wsDir)) {
      rmSync(wsDir, { recursive: true, force: true });
    }
  }
}
