/**
 * Data Layer Interfaces — abstractions for storage and session management.
 *
 * Expanded in Wave 2.1 to match full Python db.py/message_db.py/session.py feature set.
 */

import type {
  Agent,
  Task,
  TaskCreateInput,
  TaskStatus,
  Loop,
  LoopIteration,
  Schedule,
  Permission,
  Notification,
  Team,
  InboundMessage,
  OutboundMessage,
  BridgeConfig,
  CostSummary,
} from "../types.js";

// --- Database ---

export interface IDatabase {
  // --- Agent Operations ---
  createAgent(
    name: string,
    projectDir: string,
    sessionId: string,
    agentFile: string,
    purpose?: string,
    model?: string,
  ): Agent;
  getAgent(name: string): Agent | null;
  getAgentBySession(sessionId: string): Agent | null;
  listAgents(): Agent[];
  deleteAgent(name: string): boolean;
  updateAgentState(sessionId: string, state: string): void;
  incrementAgentTasks(sessionId: string): void;
  updateAgentModel(sessionId: string, model: string): void;

  // --- Task Operations ---
  createTask(input: TaskCreateInput): number;
  getTask(id: number): Task | null;
  getRunningTask(sessionId: string): Task | null;
  getRunningTasks(): Task[];
  getUnreportedTasks(): Task[];
  getTaskHistory(sessionId: string, limit?: number): Task[];
  updateTask(id: number, updates: Partial<Task>): void;
  markTaskReported(id: number): void;
  atomicCheckAndCreateTask(
    sessionId: string,
    prompt: string,
    channel?: string,
    channelChatId?: string,
    channelMessageId?: string,
    userId?: string,
  ): { taskId: number | null; isBusy: boolean };

  // --- Queue Operations ---
  getQueuedTasks(sessionId: string): Task[];
  getNextQueuePosition(sessionId: string): number;
  dequeueNextTask(sessionId: string): Task | null;
  cancelQueuedTask(taskId: number): boolean;

  // --- Permission Operations ---
  createPermission(
    requestId: string,
    sessionId: string,
    toolName: string,
    command?: string,
    description?: string,
    timeoutSeconds?: number,
  ): string;
  getPermission(requestId: string): Permission | null;
  getPendingPermissions(sessionId?: string): Permission[];
  respondPermission(requestId: string, approved: boolean): boolean;
  timeoutPermissions(): number;

  // --- Notification Operations ---
  createNotification(taskId: number, channel: string, chatId: string, message: string): number;
  getNotification(id: number): Notification | null;
  getPendingNotifications(): Notification[];
  markNotificationSent(id: number): void;
  markNotificationFailed(id: number): void;

  // --- Team Operations ---
  createTeam(name: string, leadAgent: string, members: string[]): void;
  getTeam(name: string): Team | null;
  getTeamMembers(teamName: string): string[];
  listTeams(): Team[];
  deleteTeam(name: string): boolean;

  // --- Sub-task Operations ---
  getSubtasks(parentTaskId: number): Task[];

  // --- Loop Operations ---
  createLoop(
    agent: string,
    project: string,
    goal: string,
    doneWhen: string,
    loopType?: string,
    maxIterations?: number,
    maxConsecutiveFailures?: number,
    maxCostUsd?: number | null,
  ): string;
  getLoop(loopId: string): Loop | null;
  getActiveLoopForAgent(agent: string): Loop | null;
  updateLoop(loopId: string, updates: Partial<Loop>): void;
  listLoops(agent?: string, limit?: number, status?: string): Loop[];
  createLoopIteration(loopId: string, iterationNum: number, prompt: string): number;
  updateLoopIteration(iterationId: number, updates: Partial<LoopIteration>): void;
  getLoopIterations(loopId: string): LoopIteration[];
  getLastNIterations(loopId: string, n: number): LoopIteration[];
  getLoopByTaskId(taskId: string): Loop | null;

  // --- Schedule Operations ---
  addSchedule(
    name: string,
    agentName: string,
    prompt: string,
    intervalMinutes: number,
    cronExpr?: string,
    channel?: string,
    channelChatId?: string,
    userId?: string,
    runOnce?: boolean,
  ): number;
  getScheduleByName(name: string): Schedule | null;
  getScheduleById(id: number): Schedule | null;
  getDueSchedules(now: Date): Schedule[];
  updateScheduleSuccess(id: number, now: Date): void;
  updateScheduleError(id: number, errorMsg: string): void;
  listSchedules(agentName?: string, includeDisabled?: boolean): Schedule[];
  removeSchedule(nameOrId: string): boolean;
  pauseSchedule(nameOrId: string): boolean;
  resumeSchedule(nameOrId: string): boolean;

  // --- Cost Operations ---
  getCostSummary(sessionId?: string, period?: string): CostSummary;

  // --- Lifecycle ---
  close(): void;
}

// --- Message Database ---

export interface IMessageDatabase {
  // --- Inbound Operations ---
  createInbound(
    platform: string,
    chatId: string,
    userId: string,
    messageText: string,
    messageId?: string,
    username?: string,
  ): number;
  getInbound(id: number): InboundMessage | null;
  getPendingInbound(): InboundMessage[];
  getUnacknowledgedInbound(timeoutSeconds?: number): InboundMessage[];
  markInboundDelivered(id: number): void;
  markInboundAcknowledged(id: number): void;
  markInboundFailed(id: number): void;
  incrementInboundRetry(id: number): void;

  // --- Outbound Operations ---
  createOutbound(
    platform: string,
    chatId: string,
    messageText: string,
    replyToMessageId?: string,
    source?: string,
    taskId?: number,
  ): number;
  hasNotificationForTask(taskId: number): boolean;
  updatePendingOutboundForTask(taskId: number, messageText: string, source?: string): boolean;
  getOutbound(id: number): OutboundMessage | null;
  getPendingOutbound(): OutboundMessage[];
  markOutboundSent(id: number): void;
  markOutboundFailed(id: number): void;
  incrementOutboundRetry(id: number): void;
  cleanupOldOutbound(maxAgeHours?: number): void;

  // --- Poller State Operations ---
  getState(key: string): string | null;
  setState(key: string, value: string): void;

  // --- Lifecycle ---
  close(): void;
}

// --- Session Manager ---

export interface ISessionManager {
  deriveSessionId(agentName: string, projectPath: string): string;
  deriveAgentFileName(sessionId: string): string;
  validateAgentName(name: string): string | null;
  validateProjectDir(path: string): string | null;
  getWorktreePath(sessionId: string): string;
  getTasksDir(sessionId: string): string;
  getAgentMdPath(sessionId: string, botDir?: string): string;
  getInstancePrefix(): string;
  createWorkspace(sessionId: string, agentName: string, projectDir: string, purpose: string): void;
  cleanupWorkspace(sessionId: string): void;
}

// --- Config ---

export interface IConfigProvider {
  load(): BridgeConfig;
  readonly homeDir: string;
  readonly dbPath: string;
}
