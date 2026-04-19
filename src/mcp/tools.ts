/**
 * MCP Tool Definitions & Python CLI Fallback
 *
 * Wave 1: All tools shell out to `bridge` (Python) via subprocess.
 * Wave 7: Tools will be reimplemented with native TS layers.
 */

// --- Types ---

export interface ToolDefinition {
  name: string;
  description: string;
  inputSchema: {
    type: "object";
    properties?: Record<string, { type: string; description?: string; default?: unknown }>;
    required?: string[];
  };
}

export interface ToolResult {
  content: Array<{ type: "text"; text: string }>;
  isError?: boolean;
}

// --- Tool Names Registry ---

export const TOOL_NAMES = [
  "bridge_dispatch",
  "bridge_status",
  "bridge_agents",
  "bridge_history",
  "bridge_kill",
  "bridge_create_agent",
  "bridge_get_messages",
  "bridge_acknowledge",
  "bridge_reply",
  "bridge_get_notifications",
  "bridge_loop",
  "bridge_loop_status",
  "bridge_loop_cancel",
  "bridge_loop_approve",
  "bridge_loop_reject",
  "bridge_loop_list",
  "bridge_loop_history",
  "bridge_loop_notify",
  "bridge_parse_loop_command",
  "bridge_schedule_add",
  "bridge_schedule_remove",
  "bridge_schedule_list",
  "bridge_schedule_pause",
  "bridge_schedule_resume",
  "bridge_check_messages",
  "download_attachment",
] as const;

// --- Tool Definitions ---

export const TOOL_DEFINITIONS: ToolDefinition[] = [
  {
    name: "bridge_dispatch",
    description: "Dispatch a task to a Claude Bridge agent",
    inputSchema: {
      type: "object",
      properties: {
        agent: { type: "string", description: "Agent name" },
        prompt: { type: "string", description: "Task prompt" },
        model: { type: "string", description: "Optional model override" },
        chat_id: { type: "string", description: "Telegram chat_id for notification routing" },
        user_id: { type: "string", description: "Telegram user_id for multi-user tracking" },
      },
      required: ["agent", "prompt"],
    },
  },
  {
    name: "bridge_status",
    description: "Get status of running tasks. Optionally filter by agent name",
    inputSchema: {
      type: "object",
      properties: {
        agent: { type: "string", description: "Optional agent name filter" },
      },
    },
  },
  {
    name: "bridge_agents",
    description: "List all registered agents with their state and project",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "bridge_history",
    description: "Get task history for an agent",
    inputSchema: {
      type: "object",
      properties: {
        agent: { type: "string", description: "Agent name" },
        limit: { type: "number", description: "Max results (default 10)" },
      },
      required: ["agent"],
    },
  },
  {
    name: "bridge_kill",
    description: "Kill a running task on an agent",
    inputSchema: {
      type: "object",
      properties: {
        agent: { type: "string", description: "Agent name" },
      },
      required: ["agent"],
    },
  },
  {
    name: "bridge_create_agent",
    description: "Create a new agent for a project directory",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Agent name" },
        path: { type: "string", description: "Project directory path" },
        purpose: { type: "string", description: "Agent purpose description" },
        model: { type: "string", description: "Model (default: opus)" },
      },
      required: ["name", "path", "purpose"],
    },
  },
  {
    name: "bridge_get_messages",
    description: "Get pending inbound messages from users",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "bridge_acknowledge",
    description: "Acknowledge that a message was processed",
    inputSchema: {
      type: "object",
      properties: {
        message_id: { type: "number", description: "Message ID to acknowledge" },
      },
      required: ["message_id"],
    },
  },
  {
    name: "bridge_reply",
    description: "Send a reply to a user via Telegram",
    inputSchema: {
      type: "object",
      properties: {
        chat_id: { type: "string", description: "Telegram chat_id" },
        text: { type: "string", description: "Reply text" },
        reply_to_message_id: { type: "string", description: "Optional message to reply to" },
      },
      required: ["chat_id", "text"],
    },
  },
  {
    name: "bridge_get_notifications",
    description: "Get pending task completion notifications",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "bridge_loop",
    description: "Start a goal loop for an agent. Repeats tasks until done condition is met",
    inputSchema: {
      type: "object",
      properties: {
        agent: { type: "string", description: "Agent name" },
        goal: { type: "string", description: "Goal description" },
        done_when: { type: "string", description: "Done condition (command:, file_exists:, file_contains:, llm_judge:, manual:)" },
        max_iterations: { type: "number", description: "Max iterations (default 10)" },
        loop_type: { type: "string", description: "Loop type: bridge, agent, or auto" },
        max_cost_usd: { type: "number", description: "Optional cost ceiling in USD" },
      },
      required: ["agent", "goal", "done_when"],
    },
  },
  {
    name: "bridge_loop_status",
    description: "Get goal loop status",
    inputSchema: {
      type: "object",
      properties: {
        loop_id: { type: "string", description: "Loop ID" },
        agent: { type: "string", description: "Filter by agent name" },
      },
    },
  },
  {
    name: "bridge_loop_cancel",
    description: "Cancel a running goal loop",
    inputSchema: {
      type: "object",
      properties: {
        loop_id: { type: "string", description: "Loop ID to cancel" },
      },
      required: ["loop_id"],
    },
  },
  {
    name: "bridge_loop_approve",
    description: "Approve a loop waiting for manual done condition",
    inputSchema: {
      type: "object",
      properties: {
        loop_id: { type: "string", description: "Loop ID to approve" },
      },
      required: ["loop_id"],
    },
  },
  {
    name: "bridge_loop_reject",
    description: "Reject a loop — continue to next iteration with optional feedback",
    inputSchema: {
      type: "object",
      properties: {
        loop_id: { type: "string", description: "Loop ID to reject" },
        feedback: { type: "string", description: "Optional feedback for next iteration" },
      },
      required: ["loop_id"],
    },
  },
  {
    name: "bridge_loop_list",
    description: "List goal loops with status and progress",
    inputSchema: {
      type: "object",
      properties: {
        agent: { type: "string", description: "Filter by agent name" },
        limit: { type: "number", description: "Max results (default 10)" },
        active_only: { type: "boolean", description: "Show only running loops" },
      },
    },
  },
  {
    name: "bridge_loop_history",
    description: "Get full iteration history for a loop",
    inputSchema: {
      type: "object",
      properties: {
        loop_id: { type: "string", description: "Loop ID" },
      },
      required: ["loop_id"],
    },
  },
  {
    name: "bridge_loop_notify",
    description: "Send a Telegram notification about loop status",
    inputSchema: {
      type: "object",
      properties: {
        loop_id: { type: "string", description: "Loop ID" },
        chat_id: { type: "string", description: "Telegram chat_id" },
      },
      required: ["loop_id", "chat_id"],
    },
  },
  {
    name: "bridge_parse_loop_command",
    description: "Parse a natural language loop command from Telegram",
    inputSchema: {
      type: "object",
      properties: {
        text: { type: "string", description: "Raw message text" },
      },
      required: ["text"],
    },
  },
  {
    name: "bridge_schedule_add",
    description: "Create a recurring scheduled task",
    inputSchema: {
      type: "object",
      properties: {
        agent_name: { type: "string", description: "Agent name" },
        prompt: { type: "string", description: "Task prompt" },
        interval_minutes: { type: "number", description: "Interval in minutes" },
        name: { type: "string", description: "Schedule name (auto-generated if omitted)" },
        chat_id: { type: "string", description: "Telegram chat_id for notifications" },
        user_id: { type: "string", description: "Telegram user_id" },
      },
      required: ["agent_name", "prompt", "interval_minutes"],
    },
  },
  {
    name: "bridge_schedule_remove",
    description: "Remove a schedule by name or ID",
    inputSchema: {
      type: "object",
      properties: {
        name_or_id: { type: "string", description: "Schedule name or numeric ID" },
      },
      required: ["name_or_id"],
    },
  },
  {
    name: "bridge_schedule_list",
    description: "List active schedules",
    inputSchema: {
      type: "object",
      properties: {
        agent_name: { type: "string", description: "Filter by agent name" },
      },
    },
  },
  {
    name: "bridge_schedule_pause",
    description: "Pause a schedule",
    inputSchema: {
      type: "object",
      properties: {
        name_or_id: { type: "string", description: "Schedule name or numeric ID" },
      },
      required: ["name_or_id"],
    },
  },
  {
    name: "bridge_schedule_resume",
    description: "Resume a paused schedule",
    inputSchema: {
      type: "object",
      properties: {
        name_or_id: { type: "string", description: "Schedule name or numeric ID" },
      },
      required: ["name_or_id"],
    },
  },
  {
    name: "bridge_check_messages",
    description: "Check for pending inbound Telegram messages that push notifications may have missed. Safety net; call after each response.",
    inputSchema: { type: "object", properties: {} },
  },
  {
    name: "download_attachment",
    description: "Download a Telegram file attachment by file_id. Returns the local file path.",
    inputSchema: {
      type: "object",
      properties: {
        file_id: { type: "string", description: "attachment_file_id from a channel message's meta" },
      },
      required: ["file_id"],
    },
  },
];

// --- CLI Argument Builder ---

/**
 * Convert MCP tool name + args into bridge CLI arguments.
 * Used in Wave 1 Python fallback mode.
 */
export function buildCliArgs(
  toolName: string,
  args: Record<string, unknown>,
): string[] {
  switch (toolName) {
    case "bridge_dispatch": {
      const result = ["dispatch", String(args["agent"]), String(args["prompt"])];
      if (args["model"]) result.push("--model", String(args["model"]));
      if (args["chat_id"]) result.push("--chat-id", String(args["chat_id"]));
      if (args["user_id"]) result.push("--user-id", String(args["user_id"]));
      return result;
    }
    case "bridge_status": {
      const result = ["status"];
      if (args["agent"]) result.push("--agent", String(args["agent"]));
      return result;
    }
    case "bridge_agents":
      return ["list-agents"];
    case "bridge_history": {
      const result = ["history", String(args["agent"])];
      if (args["limit"] !== undefined) result.push("--limit", String(args["limit"]));
      return result;
    }
    case "bridge_kill":
      return ["kill", String(args["agent"])];
    case "bridge_create_agent": {
      const result = ["create-agent", String(args["name"]), String(args["path"])];
      if (args["purpose"]) result.push("--purpose", String(args["purpose"]));
      if (args["model"]) result.push("--model", String(args["model"]));
      return result;
    }
    case "bridge_get_messages":
      return ["get-messages"];
    case "bridge_acknowledge":
      return ["acknowledge", String(args["message_id"])];
    case "bridge_reply": {
      const result = ["reply", String(args["chat_id"]), String(args["text"])];
      if (args["reply_to_message_id"]) result.push("--reply-to", String(args["reply_to_message_id"]));
      return result;
    }
    case "bridge_get_notifications":
      return ["get-notifications"];
    case "bridge_loop": {
      const result = [
        "loop", "start", String(args["agent"]), String(args["goal"]),
        "--done-when", String(args["done_when"]),
      ];
      if (args["max_iterations"] !== undefined) result.push("--max-iterations", String(args["max_iterations"]));
      if (args["loop_type"]) result.push("--loop-type", String(args["loop_type"]));
      if (args["max_cost_usd"] !== undefined) result.push("--max-cost", String(args["max_cost_usd"]));
      return result;
    }
    case "bridge_loop_status": {
      const result = ["loop", "status"];
      if (args["loop_id"]) result.push(String(args["loop_id"]));
      if (args["agent"]) result.push("--agent", String(args["agent"]));
      return result;
    }
    case "bridge_loop_cancel":
      return ["loop", "cancel", String(args["loop_id"])];
    case "bridge_loop_approve":
      return ["loop", "approve", String(args["loop_id"])];
    case "bridge_loop_reject": {
      const result = ["loop", "reject", String(args["loop_id"])];
      if (args["feedback"]) result.push("--feedback", String(args["feedback"]));
      return result;
    }
    case "bridge_loop_list": {
      const result = ["loop", "list"];
      if (args["agent"]) result.push("--agent", String(args["agent"]));
      if (args["limit"] !== undefined) result.push("--limit", String(args["limit"]));
      if (args["active_only"]) result.push("--active-only");
      return result;
    }
    case "bridge_loop_history":
      return ["loop", "history", String(args["loop_id"])];
    case "bridge_loop_notify":
      return ["loop", "notify", String(args["loop_id"]), "--chat-id", String(args["chat_id"])];
    case "bridge_parse_loop_command":
      return ["loop", "parse", String(args["text"])];
    case "bridge_schedule_add": {
      const result = [
        "schedule", "add", String(args["agent_name"]), String(args["prompt"]),
        "--interval", String(args["interval_minutes"]),
      ];
      if (args["name"]) result.push("--name", String(args["name"]));
      if (args["chat_id"]) result.push("--chat-id", String(args["chat_id"]));
      if (args["user_id"]) result.push("--user-id", String(args["user_id"]));
      return result;
    }
    case "bridge_schedule_remove":
      return ["schedule", "remove", String(args["name_or_id"])];
    case "bridge_schedule_list": {
      const result = ["schedule", "list"];
      if (args["agent_name"]) result.push("--agent", String(args["agent_name"]));
      return result;
    }
    case "bridge_schedule_pause":
      return ["schedule", "pause", String(args["name_or_id"])];
    case "bridge_schedule_resume":
      return ["schedule", "resume", String(args["name_or_id"])];
    case "bridge_check_messages":
      return ["get-messages"];
    case "download_attachment":
      // No Python CLI fallback — grammy-only.
      throw new Error("download_attachment has no CLI fallback (grammy-only)");
    default:
      throw new Error(`Unknown tool: ${toolName}`);
  }
}

// --- Python Fallback Handler ---

/**
 * Execute a tool by shelling out to bridge (Python).
 * This is the Wave 1 fallback — replaced with native TS in later waves.
 */
export async function executeTool(
  toolName: string,
  args: Record<string, unknown>,
): Promise<ToolResult> {
  const cliArgs = buildCliArgs(toolName, args);

  try {
    const proc = Bun.spawn(["bridge", ...cliArgs], {
      stdout: "pipe",
      stderr: "pipe",
      env: { ...process.env },
    });

    const stdout = await new Response(proc.stdout).text();
    const stderr = await new Response(proc.stderr).text();
    const exitCode = await proc.exited;

    if (exitCode !== 0) {
      return {
        content: [{ type: "text", text: stderr || `bridge exited with code ${exitCode}` }],
        isError: true,
      };
    }

    return {
      content: [{ type: "text", text: stdout }],
    };
  } catch (err) {
    return {
      content: [{ type: "text", text: `Failed to execute bridge: ${err}` }],
      isError: true,
    };
  }
}
