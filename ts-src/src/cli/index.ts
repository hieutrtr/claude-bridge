#!/usr/bin/env bun
/**
 * CLI Entry Point — bridge-cli command dispatcher.
 *
 * Replaces Python's cli.py.
 * Uses manual arg parsing (no external deps).
 */

import { join } from "path";
import { homedir } from "os";
import { existsSync, readFileSync, writeFileSync } from "fs";
import { BridgeDatabase } from "../data/db.js";
import { SessionManager } from "../data/session.js";
import { Dispatcher } from "../execution/dispatcher.js";
import { LoopOrchestrator } from "../orchestration/loop.js";
import { LoopEvaluator } from "../orchestration/evaluator.js";
import { Scheduler } from "../orchestration/scheduler.js";
import { generateAgentMd, writeAgentMd, deleteAgentMd } from "./agent-md.js";
import { formatMemoryReport } from "./memory.js";
import type { BridgeConfig } from "../types.js";

// --- Config ---

export function getBridgeHome(): string {
  return process.env["CLAUDE_BRIDGE_HOME"] ?? join(homedir(), ".claude-bridge");
}

export function loadConfig(bridgeHome: string): BridgeConfig {
  const configPath = join(bridgeHome, "config.json");
  if (!existsSync(configPath)) return {} as BridgeConfig;
  try {
    return JSON.parse(readFileSync(configPath, "utf-8")) as BridgeConfig;
  } catch {
    return {} as BridgeConfig;
  }
}

export function saveConfig(bridgeHome: string, config: BridgeConfig): void {
  writeFileSync(join(bridgeHome, "config.json"), JSON.stringify(config, null, 2), "utf-8");
}

// --- Arg Parsing Helpers ---

function getArg(args: string[], name: string): string | undefined {
  const idx = args.indexOf(`--${name}`);
  if (idx >= 0 && idx + 1 < args.length) return args[idx + 1];
  return undefined;
}

function getFlag(args: string[], name: string): boolean {
  return args.includes(`--${name}`);
}

function getPositional(args: string[], index: number): string | undefined {
  let pos = 0;
  for (let i = 0; i < args.length; i++) {
    if (args[i]!.startsWith("--")) {
      i++; // skip flag value
      continue;
    }
    if (pos === index) return args[i];
    pos++;
  }
  return undefined;
}

// --- Command Definitions ---

export interface CommandContext {
  db: BridgeDatabase;
  bridgeHome: string;
  config: BridgeConfig;
  args: string[];
}

export type CommandHandler = (ctx: CommandContext) => Promise<number>;

// --- Core Commands (W5.1) ---

async function cmdCreateAgent(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  const path = getPositional(ctx.args, 1);
  const purpose = getArg(ctx.args, "purpose") ?? "General development";
  const model = getArg(ctx.args, "model") ?? "sonnet";

  if (!name || !path) {
    process.stderr.write("Usage: bridge-cli create-agent <name> <path> --purpose <purpose>\n");
    return 1;
  }

  const resolvedPath = path.startsWith("~")
    ? join(homedir(), path.slice(1))
    : join(process.cwd(), path);

  // Validate
  const session = new SessionManager(ctx.bridgeHome);
  const nameErr = session.validateAgentName(name);
  if (nameErr) {
    process.stderr.write(`Invalid agent name: ${nameErr}\n`);
    return 1;
  }

  if (ctx.db.getAgent(name)) {
    process.stderr.write(`Agent "${name}" already exists\n`);
    return 1;
  }

  const sessionId = session.deriveSessionId(name, resolvedPath);
  const agentFile = session.deriveAgentFileName(sessionId);

  // Generate and write agent.md
  const content = generateAgentMd(sessionId, name, resolvedPath, purpose, model, ctx.bridgeHome);
  const botDir = (ctx.config as Record<string, unknown>)["bot_dir"] as string | undefined;
  const filePath = writeAgentMd(sessionId, content, botDir);

  // Register in DB
  ctx.db.createAgent(name, resolvedPath, sessionId, agentFile, purpose);
  if (model !== "sonnet") ctx.db.updateAgentModel(sessionId, model);

  console.log(`Created agent "${name}" → ${sessionId}`);
  console.log(`Agent file: ${filePath}`);
  return 0;
}

async function cmdDeleteAgent(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  if (!name) {
    process.stderr.write("Usage: bridge-cli delete-agent <name>\n");
    return 1;
  }

  const agent = ctx.db.getAgent(name);
  if (!agent) {
    process.stderr.write(`Agent "${name}" not found\n`);
    return 1;
  }

  const botDir = (ctx.config as Record<string, unknown>)["bot_dir"] as string | undefined;
  deleteAgentMd(agent.session_id, botDir);
  ctx.db.deleteAgent(name);
  console.log(`Deleted agent "${name}"`);
  return 0;
}

async function cmdListAgents(ctx: CommandContext): Promise<number> {
  const agents = ctx.db.listAgents();
  if (agents.length === 0) {
    console.log("No agents configured.");
    return 0;
  }

  for (const agent of agents) {
    const state = agent.state === "busy" ? " [BUSY]" : "";
    console.log(`${agent.name}${state} — ${agent.project_dir} (${agent.model})`);
    if (agent.purpose) console.log(`  Purpose: ${agent.purpose}`);
  }
  return 0;
}

async function cmdStatus(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);

  if (name) {
    const agent = ctx.db.getAgent(name);
    if (!agent) {
      process.stderr.write(`Agent "${name}" not found\n`);
      return 1;
    }
    console.log(`Agent: ${agent.name} (${agent.state})`);
    console.log(`Project: ${agent.project_dir}`);
    console.log(`Session: ${agent.session_id}`);
    console.log(`Model: ${agent.model}`);
    console.log(`Tasks: ${agent.total_tasks}`);

    const running = ctx.db.getRunningTask(agent.session_id);
    if (running) {
      console.log(`\nRunning task #${running.id}: ${running.prompt.slice(0, 80)}`);
    }
    return 0;
  }

  // Global status
  const agents = ctx.db.listAgents();
  const running = ctx.db.getRunningTasks();
  console.log(`Agents: ${agents.length} | Running tasks: ${running.length}`);
  for (const agent of agents) {
    const state = agent.state === "busy" ? "🔴 BUSY" : "🟢 idle";
    console.log(`  ${agent.name}: ${state}`);
  }
  return 0;
}

async function cmdDispatch(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  const prompt = getPositional(ctx.args, 1);
  const channel = getArg(ctx.args, "channel") ?? "cli";
  const chatId = getArg(ctx.args, "chat-id");
  const userId = getArg(ctx.args, "user-id");
  const messageId = getArg(ctx.args, "message-id");

  if (!name || !prompt) {
    process.stderr.write("Usage: bridge-cli dispatch <agent> <prompt>\n");
    return 1;
  }

  const agent = ctx.db.getAgent(name);
  if (!agent) {
    process.stderr.write(`Agent "${name}" not found\n`);
    return 1;
  }

  // Try atomic dispatch or queue
  const result = ctx.db.atomicCheckAndCreateTask(
    agent.session_id,
    prompt,
    channel,
    chatId,
    messageId,
    userId,
  );

  if (result.isBusy) {
    // Agent busy — create queued task
    const taskId = ctx.db.createTask({
      session_id: agent.session_id,
      prompt,
      channel,
      channel_chat_id: chatId,
      channel_message_id: messageId,
      user_id: userId,
    });
    ctx.db.updateTask(taskId, { status: "queued" });
    console.log(`Task #${taskId} queued (agent busy)`);
  } else {
    console.log(`Task #${result.taskId} dispatched to ${name}`);
  }
  return 0;
}

// --- Extended Commands (W5.2) ---

async function cmdKill(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  if (!name) {
    process.stderr.write("Usage: bridge-cli kill <agent>\n");
    return 1;
  }

  const agent = ctx.db.getAgent(name);
  if (!agent) {
    process.stderr.write(`Agent "${name}" not found\n`);
    return 1;
  }

  const running = ctx.db.getRunningTask(agent.session_id);
  if (!running || !running.pid) {
    console.log(`No running task for "${name}"`);
    return 0;
  }

  const dispatcher = new Dispatcher(ctx.bridgeHome, ctx.db);
  const killed = await dispatcher.cancel(running.pid);
  if (killed) {
    ctx.db.updateTask(running.id, {
      status: "failed",
      error_message: "Killed by user",
      completed_at: new Date().toISOString(),
    });
    ctx.db.updateAgentState(agent.session_id, "idle");
    console.log(`Killed task #${running.id} (PID ${running.pid})`);
  } else {
    console.log(`Failed to kill PID ${running.pid}`);
  }
  return 0;
}

async function cmdHistory(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  const limit = parseInt(getArg(ctx.args, "limit") ?? "10", 10);

  if (!name) {
    process.stderr.write("Usage: bridge-cli history <agent> [--limit N]\n");
    return 1;
  }

  const agent = ctx.db.getAgent(name);
  if (!agent) {
    process.stderr.write(`Agent "${name}" not found\n`);
    return 1;
  }

  const tasks = ctx.db.getTaskHistory(agent.session_id, limit);
  if (tasks.length === 0) {
    console.log(`No tasks for "${name}"`);
    return 0;
  }

  for (const task of tasks) {
    const cost = task.cost_usd !== null ? ` ($${task.cost_usd.toFixed(2)})` : "";
    const prompt = task.prompt.length > 60 ? task.prompt.slice(0, 60) + "..." : task.prompt;
    console.log(`#${task.id} ${task.status}${cost} — ${prompt}`);
  }
  return 0;
}

async function cmdCost(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  const period = getArg(ctx.args, "period") ?? "all";

  const summary = ctx.db.getCostSummary(name ?? undefined, period);
  console.log(`Cost summary (${period}):`);
  console.log(`  Total: $${summary.total_cost_usd.toFixed(2)}`);
  console.log(`  Tasks: ${summary.task_count}`);
  if (summary.avg_cost_usd > 0) {
    console.log(`  Average: $${summary.avg_cost_usd.toFixed(2)}`);
  }
  return 0;
}

async function cmdSetModel(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  const model = getPositional(ctx.args, 1);

  if (!name || !model) {
    process.stderr.write("Usage: bridge-cli set-model <agent> <model>\n");
    return 1;
  }

  const validModels = ["sonnet", "opus", "haiku"];
  if (!validModels.includes(model)) {
    process.stderr.write(`Invalid model: "${model}". Valid: ${validModels.join(", ")}\n`);
    return 1;
  }

  const agent = ctx.db.getAgent(name);
  if (!agent) {
    process.stderr.write(`Agent "${name}" not found\n`);
    return 1;
  }

  ctx.db.updateAgentModel(agent.session_id, model);
  console.log(`Set model for "${name}" to ${model}`);
  return 0;
}

async function cmdMemory(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  if (!name) {
    process.stderr.write("Usage: bridge-cli memory <agent>\n");
    return 1;
  }

  const agent = ctx.db.getAgent(name);
  if (!agent) {
    process.stderr.write(`Agent "${name}" not found\n`);
    return 1;
  }

  console.log(formatMemoryReport(name, agent.project_dir));
  return 0;
}

// --- Loop Commands ---

async function cmdLoop(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  const goal = getPositional(ctx.args, 1);
  const doneWhen = getArg(ctx.args, "done-when");
  const maxIter = parseInt(getArg(ctx.args, "max") ?? "10", 10);
  const maxFailures = parseInt(getArg(ctx.args, "max-failures") ?? "3", 10);
  const loopType = getArg(ctx.args, "type");
  const maxCost = getArg(ctx.args, "max-cost");

  if (!name || !goal || !doneWhen) {
    process.stderr.write("Usage: bridge-cli loop <agent> <goal> --done-when <condition>\n");
    return 1;
  }

  const evaluator = new LoopEvaluator();
  const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);

  const loopId = await orchestrator.startLoop(name, goal, doneWhen, {
    maxIterations: maxIter,
    maxConsecutiveFailures: maxFailures,
    loopType: loopType ?? undefined,
    maxCostUsd: maxCost ? parseFloat(maxCost) : null,
  });

  console.log(`Started loop ${loopId}`);
  return 0;
}

async function cmdLoopStatus(ctx: CommandContext): Promise<number> {
  const loopId = getArg(ctx.args, "loop-id");
  const name = getPositional(ctx.args, 0);

  if (loopId) {
    const loop = ctx.db.getLoop(loopId);
    if (!loop) {
      process.stderr.write(`Loop "${loopId}" not found\n`);
      return 1;
    }
    const iterations = ctx.db.getLoopIterations(loopId);
    const evaluator = new LoopEvaluator();
    const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);
    console.log(orchestrator.formatLoopHistory(loop, iterations));
    return 0;
  }

  // List active loops
  const loops = ctx.db.listLoops(name ?? undefined, 10, "running");
  if (loops.length === 0) {
    console.log("No active loops.");
    return 0;
  }
  const evaluator = new LoopEvaluator();
  const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);
  console.log(orchestrator.formatLoopList(loops));
  return 0;
}

async function cmdLoopCancel(ctx: CommandContext): Promise<number> {
  const loopId = getPositional(ctx.args, 0);
  if (!loopId) {
    process.stderr.write("Usage: bridge-cli loop-cancel <loop_id>\n");
    return 1;
  }
  const evaluator = new LoopEvaluator();
  const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);
  const ok = await orchestrator.cancelLoop(loopId);
  console.log(ok ? `Cancelled loop ${loopId}` : `Could not cancel loop ${loopId}`);
  return ok ? 0 : 1;
}

async function cmdLoopApprove(ctx: CommandContext): Promise<number> {
  const loopId = getPositional(ctx.args, 0);
  if (!loopId) {
    process.stderr.write("Usage: bridge-cli loop-approve <loop_id>\n");
    return 1;
  }
  const evaluator = new LoopEvaluator();
  const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);
  const ok = await orchestrator.approveLoop(loopId);
  console.log(ok ? `Approved loop ${loopId}` : `Loop ${loopId} not pending approval`);
  return ok ? 0 : 1;
}

async function cmdLoopReject(ctx: CommandContext): Promise<number> {
  const loopId = getPositional(ctx.args, 0);
  const feedback = getArg(ctx.args, "feedback") ?? "";
  if (!loopId) {
    process.stderr.write("Usage: bridge-cli loop-reject <loop_id> [--feedback <text>]\n");
    return 1;
  }
  const evaluator = new LoopEvaluator();
  const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);
  const ok = await orchestrator.rejectLoop(loopId, feedback);
  console.log(ok ? `Rejected loop ${loopId}` : `Loop ${loopId} not pending approval`);
  return ok ? 0 : 1;
}

async function cmdLoopList(ctx: CommandContext): Promise<number> {
  const name = getPositional(ctx.args, 0);
  const limit = parseInt(getArg(ctx.args, "limit") ?? "10", 10);
  const active = getFlag(ctx.args, "active");

  const loops = ctx.db.listLoops(
    name ?? undefined,
    limit,
    active ? "running" : undefined,
  );
  const evaluator = new LoopEvaluator();
  const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);
  console.log(orchestrator.formatLoopList(loops));
  return 0;
}

async function cmdLoopHistory(ctx: CommandContext): Promise<number> {
  const loopId = getPositional(ctx.args, 0);
  if (!loopId) {
    process.stderr.write("Usage: bridge-cli loop-history <loop_id>\n");
    return 1;
  }
  const loop = ctx.db.getLoop(loopId);
  if (!loop) {
    process.stderr.write(`Loop "${loopId}" not found\n`);
    return 1;
  }
  const iterations = ctx.db.getLoopIterations(loopId);
  const evaluator = new LoopEvaluator();
  const orchestrator = new LoopOrchestrator(ctx.bridgeHome, ctx.db, evaluator);
  console.log(orchestrator.formatLoopHistory(loop, iterations));
  return 0;
}

// --- Schedule Commands ---

async function cmdScheduleAdd(ctx: CommandContext): Promise<number> {
  const agent = getPositional(ctx.args, 0);
  const prompt = getPositional(ctx.args, 1);
  const name = getArg(ctx.args, "name");
  const every = getArg(ctx.args, "every");
  const channel = getArg(ctx.args, "channel") ?? "cli";
  const chatId = getArg(ctx.args, "chat-id");
  const userId = getArg(ctx.args, "user-id");
  const once = getFlag(ctx.args, "once");

  if (!agent || !prompt || !every) {
    process.stderr.write("Usage: bridge-cli schedule-add <agent> <prompt> --every <minutes>\n");
    return 1;
  }

  const scheduleName = name ?? `${agent}-${Date.now()}`;
  const id = ctx.db.addSchedule(
    scheduleName, agent, prompt, parseInt(every, 10),
    undefined, channel, chatId, userId, once,
  );
  console.log(`Schedule #${id} "${scheduleName}" created (every ${every}m)`);
  return 0;
}

async function cmdScheduleRemove(ctx: CommandContext): Promise<number> {
  const nameOrId = getPositional(ctx.args, 0);
  if (!nameOrId) {
    process.stderr.write("Usage: bridge-cli schedule-remove <name_or_id>\n");
    return 1;
  }
  const ok = ctx.db.removeSchedule(nameOrId);
  console.log(ok ? `Removed schedule "${nameOrId}"` : `Schedule "${nameOrId}" not found`);
  return ok ? 0 : 1;
}

async function cmdScheduleList(ctx: CommandContext): Promise<number> {
  const agent = getArg(ctx.args, "agent");
  const all = getFlag(ctx.args, "all");
  const schedules = ctx.db.listSchedules(agent ?? undefined, all);
  if (schedules.length === 0) {
    console.log("No schedules.");
    return 0;
  }
  for (const s of schedules) {
    const status = s.enabled ? "active" : "paused";
    const next = s.next_run_at ?? "—";
    console.log(`#${s.id} "${s.name}" ${s.agent_name} every ${s.interval_minutes}m [${status}] next: ${next}`);
  }
  return 0;
}

async function cmdSchedulePause(ctx: CommandContext): Promise<number> {
  const nameOrId = getPositional(ctx.args, 0);
  if (!nameOrId) { process.stderr.write("Usage: bridge-cli schedule-pause <name_or_id>\n"); return 1; }
  const ok = ctx.db.pauseSchedule(nameOrId);
  console.log(ok ? `Paused "${nameOrId}"` : `Not found: "${nameOrId}"`);
  return ok ? 0 : 1;
}

async function cmdScheduleResume(ctx: CommandContext): Promise<number> {
  const nameOrId = getPositional(ctx.args, 0);
  if (!nameOrId) { process.stderr.write("Usage: bridge-cli schedule-resume <name_or_id>\n"); return 1; }
  const ok = ctx.db.resumeSchedule(nameOrId);
  console.log(ok ? `Resumed "${nameOrId}"` : `Not found: "${nameOrId}"`);
  return ok ? 0 : 1;
}

// --- Command Registry ---

export const COMMAND_HANDLERS: Record<string, CommandHandler> = {
  "create-agent": cmdCreateAgent,
  "delete-agent": cmdDeleteAgent,
  "list-agents": cmdListAgents,
  status: cmdStatus,
  dispatch: cmdDispatch,
  kill: cmdKill,
  history: cmdHistory,
  cost: cmdCost,
  "set-model": cmdSetModel,
  memory: cmdMemory,
  loop: cmdLoop,
  "loop-status": cmdLoopStatus,
  "loop-cancel": cmdLoopCancel,
  "loop-approve": cmdLoopApprove,
  "loop-reject": cmdLoopReject,
  "loop-list": cmdLoopList,
  "loop-history": cmdLoopHistory,
  "schedule-add": cmdScheduleAdd,
  "schedule-remove": cmdScheduleRemove,
  "schedule-list": cmdScheduleList,
  "schedule-pause": cmdSchedulePause,
  "schedule-resume": cmdScheduleResume,
};

const COMMAND_DESCRIPTIONS: Record<string, string> = {
  "create-agent": "Create a new agent",
  "delete-agent": "Delete an agent",
  "list-agents": "List all agents",
  status: "Show status of agents and tasks",
  dispatch: "Dispatch a task to an agent",
  kill: "Kill a running task",
  history: "Show task history for an agent",
  cost: "Show cost summary",
  "set-model": "Set model for an agent",
  memory: "Show Auto Memory for an agent",
  loop: "Start a goal loop",
  "loop-status": "Show loop status",
  "loop-cancel": "Cancel a running loop",
  "loop-approve": "Approve a pending loop",
  "loop-reject": "Reject a pending loop",
  "loop-list": "List loops",
  "loop-history": "Show loop iteration history",
  "schedule-add": "Add a recurring schedule",
  "schedule-remove": "Remove a schedule",
  "schedule-list": "List schedules",
  "schedule-pause": "Pause a schedule",
  "schedule-resume": "Resume a schedule",
};

function printUsage(): void {
  console.log("Usage: bridge-cli <command> [options]\n");
  console.log("Commands:");
  for (const [cmd, desc] of Object.entries(COMMAND_DESCRIPTIONS)) {
    console.log(`  ${cmd.padEnd(20)} ${desc}`);
  }
}

// --- Main Entry ---

export async function main(argv?: string[]): Promise<number> {
  const args = argv ?? process.argv.slice(2);
  const command = args[0];

  if (!command || command === "--help" || command === "-h") {
    printUsage();
    return 0;
  }

  const handler = COMMAND_HANDLERS[command];
  if (!handler) {
    process.stderr.write(`Unknown command: ${command}\n`);
    printUsage();
    return 1;
  }

  const bridgeHome = getBridgeHome();
  const config = loadConfig(bridgeHome);
  const db = new BridgeDatabase(join(bridgeHome, "bridge.db"));

  try {
    return await handler({ db, bridgeHome, config, args: args.slice(1) });
  } finally {
    db.close();
  }
}

// Direct execution
if (import.meta.main) {
  main().then((code) => process.exit(code));
}
