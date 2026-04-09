/**
 * Database Module — SQLite storage using bun:sqlite.
 *
 * Manages agents, tasks, loops, and schedules.
 * Uses WAL mode for concurrent read/write.
 *
 * TODO: Implement full logic in Wave 2 migration.
 */

import { Database } from "bun:sqlite";
import type { IDatabase } from "./interfaces.js";
import type {
  Agent,
  Task,
  TaskCreateInput,
  TaskStatus,
  Loop,
  Schedule,
} from "../types.js";

export class BridgeDatabase implements IDatabase {
  private db: Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath, { create: true });
    this.db.exec("PRAGMA journal_mode=WAL");
    this.initSchema();
  }

  private initSchema(): void {
    // TODO: Create tables — agents, tasks, loops, schedules
  }

  // --- Agents ---
  createAgent(name: string, projectPath: string, purpose: string, sessionId: string): Agent {
    throw new Error("Not implemented");
  }
  getAgent(name: string): Agent | null {
    throw new Error("Not implemented");
  }
  listAgents(): Agent[] {
    throw new Error("Not implemented");
  }
  deleteAgent(name: string): boolean {
    throw new Error("Not implemented");
  }

  // --- Tasks ---
  createTask(input: TaskCreateInput): Task {
    throw new Error("Not implemented");
  }
  getTask(id: number): Task | null {
    throw new Error("Not implemented");
  }
  updateTaskStatus(id: number, status: TaskStatus, updates?: Partial<Task>): void {
    throw new Error("Not implemented");
  }
  getRunningTasks(): Task[] {
    throw new Error("Not implemented");
  }
  getTasksByAgent(agentName: string, limit?: number): Task[] {
    throw new Error("Not implemented");
  }
  getRecentTasks(limit?: number): Task[] {
    throw new Error("Not implemented");
  }

  // --- Loops ---
  createLoop(loop: Omit<Loop, "id" | "created_at" | "updated_at">): Loop {
    throw new Error("Not implemented");
  }
  getLoop(id: number): Loop | null {
    throw new Error("Not implemented");
  }
  updateLoop(id: number, updates: Partial<Loop>): void {
    throw new Error("Not implemented");
  }
  getActiveLoops(): Loop[] {
    throw new Error("Not implemented");
  }

  // --- Schedules ---
  createSchedule(schedule: Omit<Schedule, "id" | "created_at">): Schedule {
    throw new Error("Not implemented");
  }
  getSchedule(id: number): Schedule | null {
    throw new Error("Not implemented");
  }
  updateSchedule(id: number, updates: Partial<Schedule>): void {
    throw new Error("Not implemented");
  }
  listSchedules(): Schedule[] {
    throw new Error("Not implemented");
  }
  deleteSchedule(id: number): boolean {
    throw new Error("Not implemented");
  }

  // --- Lifecycle ---
  close(): void {
    this.db.close();
  }
}
