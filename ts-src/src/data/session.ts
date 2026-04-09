/**
 * Session Manager — derives session IDs and paths from agent + project.
 *
 * Session ID format: "agent--project" e.g. "backend--my-api"
 * Replaces Python's session.py.
 *
 * TODO: Implement full logic in Wave 2 migration.
 */

import { basename } from "path";
import type { ISessionManager } from "./interfaces.js";

export class SessionManager implements ISessionManager {
  constructor(private homeDir: string) {}

  deriveSessionId(agentName: string, projectPath: string): string {
    const projectName = basename(projectPath).replace(/[^a-zA-Z0-9-]/g, "-");
    return `${agentName}--${projectName}`;
  }

  getWorktreePath(sessionId: string): string {
    throw new Error("Not implemented");
  }

  getAgentMdPath(sessionId: string): string {
    throw new Error("Not implemented");
  }
}
