/**
 * Database Module — SQLite storage using bun:sqlite.
 *
 * Manages agents, tasks, loops, schedules, permissions, notifications, teams.
 * Uses WAL mode for concurrent read/write. Schema matches Python db.py exactly.
 */

import { Database } from "bun:sqlite";
import type { IDatabase } from "./interfaces.js";
import type {
  Agent,
  Task,
  TaskCreateInput,
  Loop,
  LoopIteration,
  Schedule,
  Permission,
  Notification,
  Team,
  CostSummary,
} from "../types.js";

// Allowed columns for update operations (security whitelist)
const TASK_UPDATABLE = new Set([
  "status", "pid", "result_file", "result_summary", "cost_usd", "duration_ms",
  "num_turns", "exit_code", "error_message", "model", "task_type", "parent_task_id",
  "channel", "channel_chat_id", "channel_message_id", "user_id",
  "started_at", "completed_at", "reported", "position",
]);

const LOOP_UPDATABLE = new Set([
  "status", "current_iteration", "consecutive_failures", "total_cost_usd",
  "finished_at", "finish_reason", "current_task_id", "loop_type",
  "max_cost_usd", "pending_approval",
]);

const LOOP_ITER_UPDATABLE = new Set([
  "task_id", "result_summary", "done_check_passed", "cost_usd",
  "started_at", "finished_at", "status",
]);

function utcnow(): string {
  return new Date().toISOString().replace("T", " ").replace("Z", "");
}

export class BridgeDatabase implements IDatabase {
  private db: Database;

  constructor(dbPath: string) {
    this.db = new Database(dbPath, { create: true });
    this.db.exec("PRAGMA journal_mode=WAL");
    this.db.exec("PRAGMA foreign_keys=ON");
    this.initSchema();
  }

  private initSchema(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS agents (
        name TEXT NOT NULL,
        project_dir TEXT NOT NULL,
        session_id TEXT NOT NULL UNIQUE,
        agent_file TEXT NOT NULL,
        purpose TEXT,
        state TEXT DEFAULT 'created',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_task_at TIMESTAMP,
        total_tasks INTEGER DEFAULT 0,
        model TEXT DEFAULT 'sonnet',
        PRIMARY KEY (name, project_dir)
      );

      CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES agents(session_id) ON DELETE CASCADE,
        prompt TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        position INTEGER,
        pid INTEGER,
        result_file TEXT,
        result_summary TEXT,
        cost_usd REAL,
        duration_ms INTEGER,
        num_turns INTEGER,
        exit_code INTEGER,
        error_message TEXT,
        model TEXT,
        task_type TEXT DEFAULT 'standard',
        parent_task_id INTEGER REFERENCES tasks(id),
        channel TEXT DEFAULT 'cli',
        channel_chat_id TEXT,
        channel_message_id TEXT,
        user_id TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        completed_at TIMESTAMP,
        reported INTEGER DEFAULT 0
      );

      CREATE TABLE IF NOT EXISTS permissions (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        tool_name TEXT NOT NULL,
        command TEXT,
        description TEXT,
        status TEXT DEFAULT 'pending',
        response TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        responded_at TIMESTAMP,
        timeout_seconds INTEGER DEFAULT 300
      );

      CREATE TABLE IF NOT EXISTS teams (
        name TEXT PRIMARY KEY,
        lead_agent TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS team_members (
        team_name TEXT NOT NULL REFERENCES teams(name) ON DELETE CASCADE,
        agent_name TEXT NOT NULL,
        PRIMARY KEY (team_name, agent_name)
      );

      CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER REFERENCES tasks(id),
        channel TEXT NOT NULL,
        chat_id TEXT NOT NULL,
        message TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        sent_at TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS loops (
        loop_id TEXT PRIMARY KEY,
        agent TEXT NOT NULL,
        project TEXT NOT NULL,
        goal TEXT NOT NULL,
        done_when TEXT NOT NULL,
        loop_type TEXT NOT NULL DEFAULT 'bridge',
        status TEXT NOT NULL DEFAULT 'running',
        max_iterations INTEGER NOT NULL DEFAULT 10,
        max_consecutive_failures INTEGER NOT NULL DEFAULT 3,
        current_iteration INTEGER NOT NULL DEFAULT 0,
        consecutive_failures INTEGER NOT NULL DEFAULT 0,
        total_cost_usd REAL NOT NULL DEFAULT 0.0,
        max_cost_usd REAL,
        pending_approval INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        finish_reason TEXT,
        current_task_id TEXT
      );

      CREATE TABLE IF NOT EXISTS loop_iterations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        loop_id TEXT NOT NULL,
        iteration_num INTEGER NOT NULL,
        task_id TEXT,
        prompt TEXT,
        result_summary TEXT,
        done_check_passed INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0.0,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL DEFAULT 'running'
      );

      CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        prompt TEXT NOT NULL,
        interval_minutes INTEGER,
        cron_expr TEXT,
        run_once INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        run_count INTEGER DEFAULT 0,
        consecutive_errors INTEGER DEFAULT 0,
        last_run_at TIMESTAMP,
        next_run_at TIMESTAMP,
        last_error TEXT,
        channel TEXT DEFAULT 'cli',
        channel_chat_id TEXT,
        user_id TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name, agent_name)
      );

      CREATE INDEX IF NOT EXISTS idx_schedules_next_run ON schedules(next_run_at, enabled);
      CREATE INDEX IF NOT EXISTS idx_loops_status ON loops(status);
      CREATE INDEX IF NOT EXISTS idx_loops_agent ON loops(agent);
      CREATE INDEX IF NOT EXISTS idx_loop_iterations_loop ON loop_iterations(loop_id);
      CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
      CREATE INDEX IF NOT EXISTS idx_permissions_status ON permissions(status);
      CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
      CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
      CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
    `);
  }

  // ===================== Agent Operations =====================

  createAgent(
    name: string,
    projectDir: string,
    sessionId: string,
    agentFile: string,
    purpose: string = "",
    model: string = "sonnet",
  ): Agent {
    this.db.run(
      `INSERT INTO agents (name, project_dir, session_id, agent_file, purpose, model)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [name, projectDir, sessionId, agentFile, purpose, model],
    );
    return this.getAgent(name)!;
  }

  getAgent(name: string): Agent | null {
    return (this.db.query("SELECT * FROM agents WHERE name = ?").get(name) as Agent | null) ?? null;
  }

  getAgentBySession(sessionId: string): Agent | null {
    return (this.db.query("SELECT * FROM agents WHERE session_id = ?").get(sessionId) as Agent | null) ?? null;
  }

  listAgents(): Agent[] {
    return this.db.query("SELECT * FROM agents ORDER BY created_at DESC").all() as Agent[];
  }

  deleteAgent(name: string): boolean {
    const result = this.db.run("DELETE FROM agents WHERE name = ?", [name]);
    return result.changes > 0;
  }

  updateAgentState(sessionId: string, state: string): void {
    this.db.run("UPDATE agents SET state = ? WHERE session_id = ?", [state, sessionId]);
  }

  incrementAgentTasks(sessionId: string): void {
    this.db.run(
      "UPDATE agents SET total_tasks = total_tasks + 1, last_task_at = ? WHERE session_id = ?",
      [utcnow(), sessionId],
    );
  }

  updateAgentModel(sessionId: string, model: string): void {
    this.db.run("UPDATE agents SET model = ? WHERE session_id = ?", [model, sessionId]);
  }

  // ===================== Task Operations =====================

  createTask(input: TaskCreateInput): number {
    const result = this.db.run(
      `INSERT INTO tasks (session_id, prompt, task_type, parent_task_id, channel, channel_chat_id, channel_message_id, user_id)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        input.session_id,
        input.prompt,
        input.task_type ?? "standard",
        input.parent_task_id ?? null,
        input.channel ?? "cli",
        input.channel_chat_id ?? null,
        input.channel_message_id ?? null,
        input.user_id ?? null,
      ],
    );
    return Number(result.lastInsertRowid);
  }

  getTask(id: number): Task | null {
    return (this.db.query("SELECT * FROM tasks WHERE id = ?").get(id) as Task | null) ?? null;
  }

  getRunningTask(sessionId: string): Task | null {
    return (this.db.query(
      "SELECT * FROM tasks WHERE session_id = ? AND status = 'running' LIMIT 1",
    ).get(sessionId) as Task | null) ?? null;
  }

  getRunningTasks(): Task[] {
    return this.db.query("SELECT * FROM tasks WHERE status = 'running'").all() as Task[];
  }

  getUnreportedTasks(): Task[] {
    return this.db.query(
      "SELECT * FROM tasks WHERE status IN ('done', 'failed', 'timeout') AND reported = 0",
    ).all() as Task[];
  }

  getTaskHistory(sessionId: string, limit: number = 10): Task[] {
    return this.db.query(
      "SELECT * FROM tasks WHERE session_id = ? ORDER BY id DESC LIMIT ?",
    ).all(sessionId, limit) as Task[];
  }

  updateTask(id: number, updates: Partial<Task>): void {
    const setClauses: string[] = [];
    const values: unknown[] = [];
    for (const [key, value] of Object.entries(updates)) {
      if (TASK_UPDATABLE.has(key)) {
        setClauses.push(`${key} = ?`);
        values.push(value ?? null);
      }
    }
    if (setClauses.length === 0) return;
    values.push(id);
    this.db.run(`UPDATE tasks SET ${setClauses.join(", ")} WHERE id = ?`, values);
  }

  markTaskReported(id: number): void {
    this.db.run("UPDATE tasks SET reported = 1 WHERE id = ?", [id]);
  }

  atomicCheckAndCreateTask(
    sessionId: string,
    prompt: string,
    channel: string = "cli",
    channelChatId?: string,
    channelMessageId?: string,
    userId?: string,
  ): { taskId: number | null; isBusy: boolean } {
    // Use transaction for atomicity
    const txn = this.db.transaction(() => {
      const running = this.db.query(
        "SELECT id FROM tasks WHERE session_id = ? AND status = 'running' LIMIT 1",
      ).get(sessionId);
      if (running) {
        return { taskId: null, isBusy: true };
      }
      const result = this.db.run(
        `INSERT INTO tasks (session_id, prompt, channel, channel_chat_id, channel_message_id, user_id)
         VALUES (?, ?, ?, ?, ?, ?)`,
        [sessionId, prompt, channel, channelChatId ?? null, channelMessageId ?? null, userId ?? null],
      );
      return { taskId: Number(result.lastInsertRowid), isBusy: false };
    });
    return txn.exclusive();
  }

  // ===================== Queue Operations =====================

  getQueuedTasks(sessionId: string): Task[] {
    return this.db.query(
      "SELECT * FROM tasks WHERE session_id = ? AND status = 'queued' ORDER BY position ASC",
    ).all(sessionId) as Task[];
  }

  getNextQueuePosition(sessionId: string): number {
    const result = this.db.query(
      "SELECT MAX(position) as max_pos FROM tasks WHERE session_id = ? AND status = 'queued'",
    ).get(sessionId) as { max_pos: number | null } | null;
    return (result?.max_pos ?? 0) + 1;
  }

  dequeueNextTask(sessionId: string): Task | null {
    const txn = this.db.transaction(() => {
      const task = this.db.query(
        "SELECT * FROM tasks WHERE session_id = ? AND status = 'queued' ORDER BY position ASC LIMIT 1",
      ).get(sessionId) as Task | null;
      if (!task) return null;
      this.db.run("UPDATE tasks SET status = 'pending', position = NULL WHERE id = ?", [task.id]);
      // Shift remaining positions down
      this.db.run(
        "UPDATE tasks SET position = position - 1 WHERE session_id = ? AND status = 'queued' AND position > ?",
        [sessionId, task.position],
      );
      return this.getTask(task.id);
    });
    return txn();
  }

  cancelQueuedTask(taskId: number): boolean {
    const result = this.db.run(
      "UPDATE tasks SET status = 'cancelled', position = NULL WHERE id = ? AND status = 'queued'",
      [taskId],
    );
    return result.changes > 0;
  }

  // ===================== Sub-task Operations =====================

  getSubtasks(parentTaskId: number): Task[] {
    return this.db.query(
      "SELECT * FROM tasks WHERE parent_task_id = ? ORDER BY id",
    ).all(parentTaskId) as Task[];
  }

  // ===================== Permission Operations =====================

  createPermission(
    requestId: string,
    sessionId: string,
    toolName: string,
    command: string = "",
    description: string = "",
    timeoutSeconds: number = 300,
  ): string {
    this.db.run(
      `INSERT INTO permissions (id, session_id, tool_name, command, description, timeout_seconds)
       VALUES (?, ?, ?, ?, ?, ?)`,
      [requestId, sessionId, toolName, command, description, timeoutSeconds],
    );
    return requestId;
  }

  getPermission(requestId: string): Permission | null {
    return (this.db.query("SELECT * FROM permissions WHERE id = ?").get(requestId) as Permission | null) ?? null;
  }

  getPendingPermissions(sessionId?: string): Permission[] {
    if (sessionId) {
      return this.db.query(
        "SELECT * FROM permissions WHERE status = 'pending' AND session_id = ? ORDER BY created_at",
      ).all(sessionId) as Permission[];
    }
    return this.db.query(
      "SELECT * FROM permissions WHERE status = 'pending' ORDER BY created_at",
    ).all() as Permission[];
  }

  respondPermission(requestId: string, approved: boolean): boolean {
    const result = this.db.run(
      "UPDATE permissions SET status = ?, response = ?, responded_at = ? WHERE id = ? AND status = 'pending'",
      [approved ? "approved" : "denied", approved ? "approved" : "denied", utcnow(), requestId],
    );
    return result.changes > 0;
  }

  timeoutPermissions(): number {
    const result = this.db.run(
      `UPDATE permissions SET status = 'timeout', responded_at = ?
       WHERE status = 'pending'
       AND datetime(created_at, '+' || timeout_seconds || ' seconds') < datetime('now')`,
      [utcnow()],
    );
    return result.changes;
  }

  // ===================== Notification Operations =====================

  createNotification(taskId: number, channel: string, chatId: string, message: string): number {
    const result = this.db.run(
      "INSERT INTO notifications (task_id, channel, chat_id, message) VALUES (?, ?, ?, ?)",
      [taskId, channel, chatId, message],
    );
    return Number(result.lastInsertRowid);
  }

  getNotification(id: number): Notification | null {
    return (this.db.query("SELECT * FROM notifications WHERE id = ?").get(id) as Notification | null) ?? null;
  }

  getPendingNotifications(): Notification[] {
    return this.db.query(
      "SELECT * FROM notifications WHERE status = 'pending' ORDER BY created_at",
    ).all() as Notification[];
  }

  markNotificationSent(id: number): void {
    this.db.run("UPDATE notifications SET status = 'sent', sent_at = ? WHERE id = ?", [utcnow(), id]);
  }

  markNotificationFailed(id: number): void {
    this.db.run("UPDATE notifications SET status = 'failed' WHERE id = ?", [id]);
  }

  // ===================== Team Operations =====================

  createTeam(name: string, leadAgent: string, members: string[]): void {
    const txn = this.db.transaction(() => {
      this.db.run("INSERT INTO teams (name, lead_agent) VALUES (?, ?)", [name, leadAgent]);
      for (const member of members) {
        this.db.run("INSERT INTO team_members (team_name, agent_name) VALUES (?, ?)", [name, member]);
      }
    });
    txn();
  }

  getTeam(name: string): Team | null {
    return (this.db.query("SELECT * FROM teams WHERE name = ?").get(name) as Team | null) ?? null;
  }

  getTeamMembers(teamName: string): string[] {
    const rows = this.db.query(
      "SELECT agent_name FROM team_members WHERE team_name = ?",
    ).all(teamName) as { agent_name: string }[];
    return rows.map((r) => r.agent_name);
  }

  listTeams(): Team[] {
    return this.db.query("SELECT * FROM teams ORDER BY created_at DESC").all() as Team[];
  }

  deleteTeam(name: string): boolean {
    const result = this.db.run("DELETE FROM teams WHERE name = ?", [name]);
    return result.changes > 0;
  }

  // ===================== Loop Operations =====================

  createLoop(
    agent: string,
    project: string,
    goal: string,
    doneWhen: string,
    loopType: string = "bridge",
    maxIterations: number = 10,
    maxConsecutiveFailures: number = 3,
    maxCostUsd: number | null = null,
  ): string {
    const loopId = crypto.randomUUID().slice(0, 8);
    this.db.run(
      `INSERT INTO loops (loop_id, agent, project, goal, done_when, loop_type, max_iterations, max_consecutive_failures, max_cost_usd, started_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [loopId, agent, project, goal, doneWhen, loopType, maxIterations, maxConsecutiveFailures, maxCostUsd, utcnow()],
    );
    return loopId;
  }

  getLoop(loopId: string): Loop | null {
    return (this.db.query("SELECT * FROM loops WHERE loop_id = ?").get(loopId) as Loop | null) ?? null;
  }

  getActiveLoopForAgent(agent: string): Loop | null {
    return (this.db.query(
      "SELECT * FROM loops WHERE agent = ? AND status = 'running' ORDER BY started_at DESC LIMIT 1",
    ).get(agent) as Loop | null) ?? null;
  }

  updateLoop(loopId: string, updates: Partial<Loop>): void {
    const setClauses: string[] = [];
    const values: unknown[] = [];
    for (const [key, value] of Object.entries(updates)) {
      if (LOOP_UPDATABLE.has(key)) {
        setClauses.push(`${key} = ?`);
        values.push(value ?? null);
      }
    }
    if (setClauses.length === 0) return;
    values.push(loopId);
    this.db.run(`UPDATE loops SET ${setClauses.join(", ")} WHERE loop_id = ?`, values);
  }

  listLoops(agent?: string, limit: number = 20, status?: string): Loop[] {
    let sql = "SELECT * FROM loops WHERE 1=1";
    const params: unknown[] = [];
    if (agent) { sql += " AND agent = ?"; params.push(agent); }
    if (status) { sql += " AND status = ?"; params.push(status); }
    sql += " ORDER BY started_at DESC LIMIT ?";
    params.push(limit);
    return this.db.query(sql).all(...params) as Loop[];
  }

  createLoopIteration(loopId: string, iterationNum: number, prompt: string): number {
    const result = this.db.run(
      `INSERT INTO loop_iterations (loop_id, iteration_num, prompt, started_at)
       VALUES (?, ?, ?, ?)`,
      [loopId, iterationNum, prompt, utcnow()],
    );
    return Number(result.lastInsertRowid);
  }

  updateLoopIteration(iterationId: number, updates: Partial<LoopIteration>): void {
    const setClauses: string[] = [];
    const values: unknown[] = [];
    for (const [key, value] of Object.entries(updates)) {
      if (LOOP_ITER_UPDATABLE.has(key)) {
        setClauses.push(`${key} = ?`);
        values.push(value ?? null);
      }
    }
    if (setClauses.length === 0) return;
    values.push(iterationId);
    this.db.run(`UPDATE loop_iterations SET ${setClauses.join(", ")} WHERE id = ?`, values);
  }

  getLoopIterations(loopId: string): LoopIteration[] {
    return this.db.query(
      "SELECT * FROM loop_iterations WHERE loop_id = ? ORDER BY iteration_num",
    ).all(loopId) as LoopIteration[];
  }

  getLastNIterations(loopId: string, n: number): LoopIteration[] {
    return this.db.query(
      "SELECT * FROM (SELECT * FROM loop_iterations WHERE loop_id = ? ORDER BY iteration_num DESC LIMIT ?) ORDER BY iteration_num ASC",
    ).all(loopId, n) as LoopIteration[];
  }

  getLoopByTaskId(taskId: string): Loop | null {
    return (this.db.query(
      "SELECT * FROM loops WHERE current_task_id = ?",
    ).get(taskId) as Loop | null) ?? null;
  }

  // ===================== Schedule Operations =====================

  addSchedule(
    name: string,
    agentName: string,
    prompt: string,
    intervalMinutes: number,
    cronExpr?: string,
    channel: string = "cli",
    channelChatId?: string,
    userId?: string,
    runOnce: boolean = false,
  ): number {
    const now = utcnow();
    const nextRun = new Date(Date.now() + intervalMinutes * 60 * 1000)
      .toISOString().replace("T", " ").replace("Z", "");
    const result = this.db.run(
      `INSERT INTO schedules (name, agent_name, prompt, interval_minutes, cron_expr, run_once, channel, channel_chat_id, user_id, next_run_at, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [name, agentName, prompt, intervalMinutes, cronExpr ?? null, runOnce ? 1 : 0, channel, channelChatId ?? null, userId ?? null, nextRun, now, now],
    );
    return Number(result.lastInsertRowid);
  }

  getScheduleByName(name: string): Schedule | null {
    return (this.db.query("SELECT * FROM schedules WHERE name = ?").get(name) as Schedule | null) ?? null;
  }

  getScheduleById(id: number): Schedule | null {
    return (this.db.query("SELECT * FROM schedules WHERE id = ?").get(id) as Schedule | null) ?? null;
  }

  getDueSchedules(now: Date): Schedule[] {
    const nowStr = now.toISOString().replace("T", " ").replace("Z", "");
    return this.db.query(
      "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at",
    ).all(nowStr) as Schedule[];
  }

  updateScheduleSuccess(id: number, now: Date): void {
    const sched = this.getScheduleById(id);
    if (!sched) return;
    const nextRun = new Date(now.getTime() + (sched.interval_minutes ?? 60) * 60 * 1000)
      .toISOString().replace("T", " ").replace("Z", "");
    const nowStr = now.toISOString().replace("T", " ").replace("Z", "");
    this.db.run(
      `UPDATE schedules SET run_count = run_count + 1, consecutive_errors = 0,
       last_run_at = ?, next_run_at = ?, updated_at = ? WHERE id = ?`,
      [nowStr, nextRun, nowStr, id],
    );
  }

  updateScheduleError(id: number, errorMsg: string): void {
    const sched = this.getScheduleById(id);
    if (!sched) return;
    const errors = sched.consecutive_errors + 1;
    const now = utcnow();
    if (errors >= 5) {
      this.db.run(
        "UPDATE schedules SET consecutive_errors = ?, last_error = ?, enabled = 0, updated_at = ? WHERE id = ?",
        [errors, errorMsg, now, id],
      );
    } else {
      // Exponential backoff: interval * 2^errors, capped at 8x
      const backoffMultiplier = Math.min(Math.pow(2, errors), 8);
      const interval = sched.interval_minutes ?? 60;
      const nextRun = new Date(Date.now() + interval * backoffMultiplier * 60 * 1000)
        .toISOString().replace("T", " ").replace("Z", "");
      this.db.run(
        "UPDATE schedules SET consecutive_errors = ?, last_error = ?, next_run_at = ?, updated_at = ? WHERE id = ?",
        [errors, errorMsg, nextRun, now, id],
      );
    }
  }

  listSchedules(agentName?: string, includeDisabled: boolean = false): Schedule[] {
    let sql = "SELECT * FROM schedules WHERE 1=1";
    const params: unknown[] = [];
    if (agentName) { sql += " AND agent_name = ?"; params.push(agentName); }
    if (!includeDisabled) { sql += " AND enabled = 1"; }
    sql += " ORDER BY created_at DESC";
    return this.db.query(sql).all(...params) as Schedule[];
  }

  removeSchedule(nameOrId: string): boolean {
    // Try by numeric ID first
    const asNum = parseInt(nameOrId, 10);
    if (!isNaN(asNum)) {
      const result = this.db.run("DELETE FROM schedules WHERE id = ?", [asNum]);
      if (result.changes > 0) return true;
    }
    // Then by name
    const result = this.db.run("DELETE FROM schedules WHERE name = ?", [nameOrId]);
    return result.changes > 0;
  }

  pauseSchedule(nameOrId: string): boolean {
    const asNum = parseInt(nameOrId, 10);
    if (!isNaN(asNum)) {
      const result = this.db.run("UPDATE schedules SET enabled = 0 WHERE id = ?", [asNum]);
      if (result.changes > 0) return true;
    }
    const result = this.db.run("UPDATE schedules SET enabled = 0 WHERE name = ?", [nameOrId]);
    return result.changes > 0;
  }

  resumeSchedule(nameOrId: string): boolean {
    const asNum = parseInt(nameOrId, 10);
    if (!isNaN(asNum)) {
      const result = this.db.run(
        "UPDATE schedules SET enabled = 1, consecutive_errors = 0 WHERE id = ?", [asNum],
      );
      if (result.changes > 0) return true;
    }
    const result = this.db.run(
      "UPDATE schedules SET enabled = 1, consecutive_errors = 0 WHERE name = ?", [nameOrId],
    );
    return result.changes > 0;
  }

  // ===================== Cost Operations =====================

  getCostSummary(sessionId?: string, period: string = "all"): CostSummary {
    let sql = "SELECT COALESCE(SUM(cost_usd), 0) as total, COUNT(*) as cnt FROM tasks WHERE cost_usd IS NOT NULL";
    const params: unknown[] = [];
    if (sessionId) { sql += " AND session_id = ?"; params.push(sessionId); }
    if (period === "today") {
      sql += " AND date(completed_at) = date('now')";
    } else if (period === "week") {
      sql += " AND completed_at >= datetime('now', '-7 days')";
    } else if (period === "month") {
      sql += " AND completed_at >= datetime('now', '-30 days')";
    }
    const row = this.db.query(sql).get(...params) as { total: number; cnt: number };
    return {
      total_cost_usd: row.total,
      task_count: row.cnt,
      avg_cost_usd: row.cnt > 0 ? row.total / row.cnt : 0,
    };
  }

  // ===================== Lifecycle =====================

  close(): void {
    this.db.close();
  }
}
