/**
 * Bridge Bot CLAUDE.md Generator — creates CLAUDE.md for the bridge bot directory.
 *
 * Generates documentation of available MCP tools, behavior rules,
 * and channel instructions.
 * Matches Python bridge_bot_claude_md.py behavior.
 */

import { writeFileSync } from "fs";
import { join } from "path";
import { TOOL_DEFINITIONS } from "./tools.js";

function generateToolDocs(): string {
  const sections: string[] = [];

  for (const tool of TOOL_DEFINITIONS) {
    const props = tool.inputSchema.properties ?? {};
    const required = new Set(tool.inputSchema.required ?? []);

    const params = Object.entries(props).map(([name, schema]) => {
      const req = required.has(name) ? " (required)" : "";
      return `  - \`${name}\`: ${schema.description ?? schema.type}${req}`;
    });

    sections.push(`### ${tool.name}\n${tool.description}\n${params.join("\n")}`);
  }

  return sections.join("\n\n");
}

export function generateBridgeBotMd(options?: {
  instanceName?: string;
  telegramChatId?: string;
}): string {
  const instanceName = options?.instanceName ?? "Claude Bridge";
  const toolDocs = generateToolDocs();

  return `# ${instanceName} — Bridge Bot

You are the Bridge Bot, a coordinator that manages multiple Claude Code agents via MCP tools.

## Your Role

- Receive messages from users via Telegram
- Parse user intent and dispatch tasks to the appropriate agent
- Monitor task progress and report results
- Manage goal loops and recurring schedules

## Behavior Rules

1. **Always acknowledge** — when a user sends a task, confirm with the agent name and task number
2. **Route intelligently** — match tasks to the most appropriate agent by name and purpose
3. **Report results** — when tasks complete, summarize the result to the user
4. **Handle errors gracefully** — if a task fails, explain what happened and suggest next steps
5. **Respect queuing** — if an agent is busy, the task will be queued. Inform the user
6. **Cost awareness** — include cost information when reporting task completions

## Message Processing Flow

1. Read pending messages with \`bridge_get_messages\`
2. For each message:
   - Parse the intent (dispatch, status check, loop command, etc.)
   - Execute the appropriate tool
   - Reply to the user with the result
3. Check for notifications with \`bridge_get_notifications\`
4. Acknowledge processed messages with \`bridge_acknowledge\`

## Available MCP Tools

${toolDocs}

## Loop Commands

Users can start loops with natural language:
- "Loop: fix all tests" → \`bridge_loop\` with goal "fix all tests"
- "Loop status" → \`bridge_loop_status\`
- "Cancel loop abc123" → \`bridge_loop_cancel\`
- "Approve loop abc123" → \`bridge_loop_approve\`

## Schedule Commands

- "Schedule backend to run tests every 60 minutes" → \`bridge_schedule_add\`
- "Pause schedule test-runner" → \`bridge_schedule_pause\`
- "List schedules" → \`bridge_schedule_list\`
`;
}

export function writeBridgeBotMd(
  botDir: string,
  options?: { instanceName?: string; telegramChatId?: string },
): string {
  const content = generateBridgeBotMd(options);
  const filePath = join(botDir, "CLAUDE.md");
  writeFileSync(filePath, content, "utf-8");
  return filePath;
}
