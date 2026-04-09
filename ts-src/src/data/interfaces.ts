/**
 * Data Layer Interfaces — abstractions for storage and session management.
 */

import type {
  Agent,
  Task,
  TaskCreateInput,
  TaskStatus,
  Loop,
  Schedule,
  BridgeConfig,
} from "../types.js";

// --- Database ---

export interface IDatabase {
  // Agents
  createAgent(
    name: string,
    projectPath: string,
    purpose: string,
    sessionId: string,
  ): Agent;
  getAgent(name: string): Agent | null;
  listAgents(): Agent[];
  deleteAgent(name: string): boolean;

  // Tasks
  createTask(input: TaskCreateInput): Task;
  getTask(id: number): Task | null;
  updateTaskStatus(
    id: number,
    status: TaskStatus,
    updates?: Partial<Task>,
  ): void;
  getRunningTasks(): Task[];
  getTasksByAgent(agentName: string, limit?: number): Task[];
  getRecentTasks(limit?: number): Task[];

  // Loops
  createLoop(loop: Omit<Loop, "id" | "created_at" | "updated_at">): Loop;
  getLoop(id: number): Loop | null;
  updateLoop(id: number, updates: Partial<Loop>): void;
  getActiveLoops(): Loop[];

  // Schedules
  createSchedule(
    schedule: Omit<Schedule, "id" | "created_at">,
  ): Schedule;
  getSchedule(id: number): Schedule | null;
  updateSchedule(id: number, updates: Partial<Schedule>): void;
  listSchedules(): Schedule[];
  deleteSchedule(id: number): boolean;

  // Lifecycle
  close(): void;
}

// --- Session Manager ---

export interface ISessionManager {
  /** Derive session_id from agent name + project path */
  deriveSessionId(agentName: string, projectPath: string): string;

  /** Get the worktree path for a session */
  getWorktreePath(sessionId: string): string;

  /** Get the agent .md file path for a session */
  getAgentMdPath(sessionId: string): string;
}

// --- Config ---

export interface IConfigProvider {
  /** Load bridge configuration from CLAUDE_BRIDGE_HOME */
  load(): BridgeConfig;

  /** Get the home directory */
  readonly homeDir: string;

  /** Get the database path */
  readonly dbPath: string;
}
