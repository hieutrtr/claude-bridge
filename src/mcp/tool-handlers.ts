/**
 * MCP Tool Handlers — native TS implementation.
 *
 * Wave 7: Replaces Python CLI fallback. Each tool delegates to
 * the appropriate TS layer (DB, orchestration, CLI).
 */

import { join } from "path";
import { homedir } from "os";
import { mkdirSync, writeFileSync } from "fs";
import { BridgeDatabase } from "../data/db.js";
import { MessageDatabase } from "../data/message-db.js";
import { SessionManager } from "../data/session.js";
import { Dispatcher } from "../execution/dispatcher.js";
import { LoopOrchestrator } from "../orchestration/loop.js";
import { LoopEvaluator } from "../orchestration/evaluator.js";
import { Notifier } from "../execution/notify.js";
import { generateAgentMd, writeAgentMd } from "../cli/agent-md.js";
import type { ToolResult } from "./tools.js";

function getBridgeHome(): string {
  return process.env["CLAUDE_BRIDGE_HOME"] ?? join(homedir(), ".claude-bridge");
}

function text(s: string): ToolResult {
  return { content: [{ type: "text", text: s }] };
}

function error(s: string): ToolResult {
  return { content: [{ type: "text", text: s }], isError: true };
}

/** Execute a tool natively using TS layers. */
export async function executeToolNative(
  toolName: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  const bridgeHome = getBridgeHome();
  const db = new BridgeDatabase(join(bridgeHome, "bridge.db"));

  try {
    return await handleTool(toolName, args, db, bridgeHome);
  } catch (err) {
    return error(`Tool error: ${(err as Error).message}`);
  } finally {
    db.close();
  }
}

async function handleTool(
  toolName: string,
  args: Record<string, unknown>,
  db: BridgeDatabase,
  bridgeHome: string,
): Promise<ToolResult> {
  switch (toolName) {
    // --- Agent Operations ---
    case "bridge_agents": {
      const agents = db.listAgents();
      if (agents.length === 0) return text("No agents configured.");
      const lines = agents.map((a) => {
        const state = a.state === "running" ? " [BUSY]" : "";
        return `${a.name}${state} — ${a.project_dir} (${a.model})`;
      });
      return text(lines.join("\n"));
    }

    case "bridge_create_agent": {
      const name = String(args["name"]);
      const path = String(args["path"]);
      const purpose = String(args["purpose"] ?? "General development");
      const model = String(args["model"] ?? "sonnet");

      if (db.getAgent(name)) return error(`Agent "${name}" already exists`);

      const session = new SessionManager(bridgeHome);
      const sessionId = session.deriveSessionId(name, path);
      const agentFile = session.deriveAgentFileName(sessionId);
      const content = generateAgentMd(sessionId, name, path, purpose, model, bridgeHome);
      const config = {};
      const botDir = (config as Record<string, unknown>)["bot_dir"] as string | undefined;
      writeAgentMd(sessionId, content, botDir);
      db.createAgent(name, path, sessionId, agentFile, purpose, model);
      return text(`Created agent "${name}" → ${sessionId}`);
    }

    // --- Task Operations ---
    case "bridge_dispatch": {
      const agentName = String(args["agent"]);
      const prompt = String(args["prompt"]);
      const chatId = args["chat_id"] ? String(args["chat_id"]) : undefined;
      const userId = args["user_id"] ? String(args["user_id"]) : undefined;

      const agent = db.getAgent(agentName);
      if (!agent) return error(`Agent "${agentName}" not found`);

      const result = db.atomicCheckAndCreateTask(
        agent.session_id, prompt, "telegram", chatId, undefined, userId,
      );

      if (result.isBusy) {
        const taskId = db.createTask({
          session_id: agent.session_id, prompt,
          channel: "telegram", channel_chat_id: chatId, user_id: userId,
        });
        db.updateTask(taskId, { status: "queued" });
        return text(`Task #${taskId} queued (agent busy)`);
      }
      return text(`Task #${result.taskId} dispatched to ${agentName}`);
    }

    case "bridge_status": {
      const agentName = args["agent"] ? String(args["agent"]) : undefined;
      if (agentName) {
        const agent = db.getAgent(agentName);
        if (!agent) return error(`Agent "${agentName}" not found`);
        const running = db.getRunningTask(agent.session_id);
        const lines = [`Agent: ${agent.name} (${agent.state})`];
        if (running) {
          lines.push(`Running: #${running.id} — ${running.prompt.slice(0, 80)}`);
        }
        return text(lines.join("\n"));
      }
      const agents = db.listAgents();
      const running = db.getRunningTasks();
      const lines = [`Agents: ${agents.length} | Running: ${running.length}`];
      for (const a of agents) {
        lines.push(`  ${a.name}: ${a.state === "running" ? "BUSY" : "idle"}`);
      }
      return text(lines.join("\n"));
    }

    case "bridge_history": {
      const agentName = String(args["agent"]);
      const limit = args["limit"] ? Number(args["limit"]) : 10;
      const agent = db.getAgent(agentName);
      if (!agent) return error(`Agent "${agentName}" not found`);

      const tasks = db.getTaskHistory(agent.session_id, limit);
      if (tasks.length === 0) return text(`No tasks for "${agentName}"`);

      const lines = tasks.map((t) => {
        const cost = t.cost_usd !== null ? ` ($${t.cost_usd.toFixed(2)})` : "";
        return `#${t.id} ${t.status}${cost} — ${t.prompt.slice(0, 60)}`;
      });
      return text(lines.join("\n"));
    }

    case "bridge_kill": {
      const agentName = String(args["agent"]);
      const agent = db.getAgent(agentName);
      if (!agent) return error(`Agent "${agentName}" not found`);

      const running = db.getRunningTask(agent.session_id);
      if (!running || !running.pid) return text(`No running task for "${agentName}"`);

      const dispatcher = new Dispatcher(bridgeHome);
      await dispatcher.cancel(running.pid);
      db.updateTask(running.id, {
        status: "failed", error_message: "Killed via MCP",
        completed_at: new Date().toISOString(),
      });
      db.updateAgentState(agent.session_id, "idle");
      return text(`Killed task #${running.id}`);
    }

    // --- Message Operations ---
    case "bridge_get_messages": {
      const msgDb = new MessageDatabase(join(bridgeHome, "messages.db"));
      try {
        const messages = msgDb.getPendingInbound();
        if (messages.length === 0) return text("No pending messages.");
        const lines = messages.map((m) =>
          `[${m.id}] ${m.username ?? m.chat_id}: ${m.message_text?.slice(0, 100) ?? "(no text)"}`,
        );
        return text(lines.join("\n"));
      } finally {
        msgDb.close();
      }
    }

    case "bridge_acknowledge": {
      const msgDb = new MessageDatabase(join(bridgeHome, "messages.db"));
      try {
        msgDb.markInboundAcknowledged(Number(args["message_id"]));
        return text(`Acknowledged message #${args["message_id"]}`);
      } finally {
        msgDb.close();
      }
    }

    case "bridge_reply": {
      const chatId = String(args["chat_id"]);
      const replyText = String(args["text"]);
      const notifier = new Notifier(bridgeHome);
      const ok = await notifier.notify({ chat_id: chatId, message: replyText });
      return ok ? text("Reply sent") : error("Failed to send reply");
    }

    case "bridge_get_notifications": {
      const notifications = db.getPendingNotifications();
      if (notifications.length === 0) return text("No pending notifications.");
      const lines = notifications.map((n) =>
        `[${n.id}] Task #${n.task_id}: ${n.message.slice(0, 100)}`,
      );
      return text(lines.join("\n"));
    }

    // --- Loop Operations ---
    case "bridge_loop": {
      const evaluator = new LoopEvaluator();
      const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
      const loopId = await orchestrator.startLoop(
        String(args["agent"]),
        String(args["goal"]),
        String(args["done_when"]),
        {
          maxIterations: args["max_iterations"] ? Number(args["max_iterations"]) : undefined,
          loopType: args["loop_type"] ? String(args["loop_type"]) : undefined,
          maxCostUsd: args["max_cost_usd"] ? Number(args["max_cost_usd"]) : null,
        },
      );
      return text(`Started loop ${loopId}`);
    }

    case "bridge_loop_status": {
      const loopId = args["loop_id"] ? String(args["loop_id"]) : undefined;
      if (loopId) {
        const loop = db.getLoop(loopId);
        if (!loop) return error(`Loop "${loopId}" not found`);
        const iterations = db.getLoopIterations(loopId);
        const evaluator = new LoopEvaluator();
        const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
        return text(orchestrator.formatLoopHistory(loop, iterations));
      }
      const agentName = args["agent"] ? String(args["agent"]) : undefined;
      const loops = db.listLoops(agentName, 10, "running");
      const evaluator = new LoopEvaluator();
      const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
      return text(orchestrator.formatLoopList(loops));
    }

    case "bridge_loop_cancel": {
      const evaluator = new LoopEvaluator();
      const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
      const ok = await orchestrator.cancelLoop(String(args["loop_id"]));
      return ok ? text("Loop cancelled") : error("Could not cancel loop");
    }

    case "bridge_loop_approve": {
      const evaluator = new LoopEvaluator();
      const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
      const ok = await orchestrator.approveLoop(String(args["loop_id"]));
      return ok ? text("Loop approved") : error("Loop not pending approval");
    }

    case "bridge_loop_reject": {
      const evaluator = new LoopEvaluator();
      const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
      const ok = await orchestrator.rejectLoop(
        String(args["loop_id"]),
        args["feedback"] ? String(args["feedback"]) : undefined,
      );
      return ok ? text("Loop rejected, next iteration dispatched") : error("Loop not pending approval");
    }

    case "bridge_loop_list": {
      const agentName = args["agent"] ? String(args["agent"]) : undefined;
      const limit = args["limit"] ? Number(args["limit"]) : 10;
      const active = args["active_only"] ? "running" : undefined;
      const loops = db.listLoops(agentName, limit, active);
      const evaluator = new LoopEvaluator();
      const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
      return text(orchestrator.formatLoopList(loops));
    }

    case "bridge_loop_history": {
      const loopId = String(args["loop_id"]);
      const loop = db.getLoop(loopId);
      if (!loop) return error(`Loop "${loopId}" not found`);
      const iterations = db.getLoopIterations(loopId);
      const evaluator = new LoopEvaluator();
      const orchestrator = new LoopOrchestrator(bridgeHome, db, evaluator);
      return text(orchestrator.formatLoopHistory(loop, iterations));
    }

    case "bridge_loop_notify": {
      const loopId = String(args["loop_id"]);
      const chatId = String(args["chat_id"]);
      const loop = db.getLoop(loopId);
      if (!loop) return error(`Loop "${loopId}" not found`);
      const notifier = new Notifier(bridgeHome);
      const msg = `Loop ${loopId}: ${loop.status} — iter ${loop.current_iteration}/${loop.max_iterations}`;
      const ok = await notifier.notify({ chat_id: chatId, message: msg });
      return ok ? text("Notification sent") : error("Failed to send notification");
    }

    case "bridge_parse_loop_command": {
      // Simple parser for natural language loop commands
      const cmdText = String(args["text"]);
      return text(`Parsed: ${cmdText}`);
    }

    // --- Schedule Operations ---
    case "bridge_schedule_add": {
      const id = db.addSchedule(
        args["name"] ? String(args["name"]) : `sched-${Date.now()}`,
        String(args["agent_name"]),
        String(args["prompt"]),
        Number(args["interval_minutes"]),
        undefined,
        "telegram",
        args["chat_id"] ? String(args["chat_id"]) : undefined,
        args["user_id"] ? String(args["user_id"]) : undefined,
      );
      return text(`Schedule #${id} created`);
    }

    case "bridge_schedule_remove": {
      const ok = db.removeSchedule(String(args["name_or_id"]));
      return ok ? text("Schedule removed") : error("Schedule not found");
    }

    case "bridge_schedule_list": {
      const agentName = args["agent_name"] ? String(args["agent_name"]) : undefined;
      const schedules = db.listSchedules(agentName);
      if (schedules.length === 0) return text("No schedules.");
      const lines = schedules.map((s) =>
        `#${s.id} "${s.name}" ${s.agent_name} every ${s.interval_minutes}m [${s.enabled ? "active" : "paused"}]`,
      );
      return text(lines.join("\n"));
    }

    case "bridge_schedule_pause": {
      const ok = db.pauseSchedule(String(args["name_or_id"]));
      return ok ? text("Schedule paused") : error("Schedule not found");
    }

    case "bridge_schedule_resume": {
      const ok = db.resumeSchedule(String(args["name_or_id"]));
      return ok ? text("Schedule resumed") : error("Schedule not found");
    }

    // --- Channel / Push support ---
    case "bridge_check_messages": {
      const msgDb = new MessageDatabase(join(bridgeHome, "messages.db"));
      try {
        const pending = msgDb.getPendingInbound();
        if (pending.length === 0) return text("No pending messages");
        const messages = pending.map((m) => ({
          tracking_id: m.id,
          chat_id: m.chat_id,
          user: m.username,
          text: m.message_text,
        }));
        return text(JSON.stringify({ pending_count: pending.length, messages }));
      } finally {
        msgDb.close();
      }
    }

    case "download_attachment": {
      const fileId = args["file_id"] ? String(args["file_id"]) : "";
      if (!fileId) return error("file_id is required");

      const notifier = new Notifier(bridgeHome);
      const token = notifier.getBotToken();
      if (!token) return error("TELEGRAM_BOT_TOKEN not configured");

      const inboxDir = join(bridgeHome, "inbox");
      mkdirSync(inboxDir, { recursive: true });
      try {
        // Call getFile via plain HTTP (no grammy dep needed at handler level).
        const getFileResp = await fetch(
          `https://api.telegram.org/bot${token}/getFile?file_id=${encodeURIComponent(fileId)}`,
        );
        if (!getFileResp.ok) return error(`getFile HTTP ${getFileResp.status}`);
        const body = (await getFileResp.json()) as {
          ok: boolean;
          result?: { file_path?: string; file_unique_id?: string; file_size?: number };
          description?: string;
        };
        if (!body.ok || !body.result?.file_path) {
          return error(`getFile failed: ${body.description ?? "no file_path"}`);
        }

        const filePath = body.result.file_path;
        const fileSize = body.result.file_size ?? 0;
        const FILE_LIMIT = 20 * 1024 * 1024;
        if (fileSize && fileSize > FILE_LIMIT) {
          return error(`File too large (${(fileSize / 1024 / 1024).toFixed(1)}MB > 20MB)`);
        }

        const dlResp = await fetch(
          `https://api.telegram.org/file/bot${token}/${filePath}`,
        );
        if (!dlResp.ok) return error(`download HTTP ${dlResp.status}`);
        const buf = Buffer.from(await dlResp.arrayBuffer());
        if (buf.length > FILE_LIMIT) return error("Downloaded file exceeds 20MB limit");

        const ext = (filePath.split(".").pop() ?? "bin").replace(/[^a-zA-Z0-9]/g, "");
        const uniqueId = (body.result.file_unique_id ?? fileId).replace(/[^a-zA-Z0-9_-]/g, "");
        const localPath = join(inboxDir, `${Date.now()}-${uniqueId}.${ext}`);
        writeFileSync(localPath, buf);
        return text(localPath);
      } catch (err) {
        return error(`download error: ${(err as Error).message}`);
      }
    }

    default:
      return error(`Unknown tool: ${toolName}`);
  }
}
