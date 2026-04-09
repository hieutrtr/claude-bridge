/**
 * Agent .md Generator — creates native Claude Code agent files.
 *
 * Generates YAML frontmatter (tools, model, isolation, memory, hooks)
 * and markdown body with purpose and behavior rules.
 * Matches Python agent_md.py behavior.
 */

import { existsSync, mkdirSync, writeFileSync, unlinkSync, readFileSync } from "fs";
import { join, dirname } from "path";
import { homedir } from "os";

const AGENT_TEMPLATE = `---
name: bridge--{session_id}
model: {model}
tools:
  - Read
  - Edit
  - Write
  - Bash
  - Grep
  - Glob
  - Agent
allowedTools:
  - mcp__claude-bridge__*
isolation:
  type: worktree
memory:
  enabled: true
hooks:
  stop:
    - command: "{stop_hook_cmd}"
---

# {agent_name}

**Purpose:** {purpose}

## Behavior

- You are an autonomous agent working on: {purpose}
- Project directory: {project_dir}
- Session ID: {session_id}

## Rules

- Focus on the task at hand
- Write clean, tested code
- Commit your changes when done
- Report progress clearly in your result summary
`;

export function generateAgentMd(
  sessionId: string,
  agentName: string,
  projectDir: string,
  purpose: string,
  model: string = "sonnet",
  bridgeHome?: string,
): string {
  const home = bridgeHome ?? join(homedir(), ".claude-bridge");
  const stopHookCmd = `CLAUDE_BRIDGE_HOME=${home} bridge-cli on-complete --session-id ${sessionId}`;

  return AGENT_TEMPLATE
    .replace(/{session_id}/g, sessionId)
    .replace(/{agent_name}/g, agentName)
    .replace(/{project_dir}/g, projectDir)
    .replace(/{purpose}/g, purpose)
    .replace(/{model}/g, model)
    .replace(/{stop_hook_cmd}/g, stopHookCmd);
}

export function writeAgentMd(
  sessionId: string,
  content: string,
  botDir?: string | null,
): string {
  const agentFileName = `bridge--${sessionId}.md`;
  let targetDir: string;

  if (botDir) {
    targetDir = join(botDir, ".claude", "agents");
  } else {
    targetDir = join(homedir(), ".claude", "agents");
  }

  mkdirSync(targetDir, { recursive: true });
  const filePath = join(targetDir, agentFileName);
  writeFileSync(filePath, content, "utf-8");
  return filePath;
}

export function deleteAgentMd(
  sessionId: string,
  botDir?: string | null,
): boolean {
  const agentFileName = `bridge--${sessionId}.md`;

  // Try bot_dir first
  if (botDir) {
    const path = join(botDir, ".claude", "agents", agentFileName);
    if (existsSync(path)) {
      unlinkSync(path);
      return true;
    }
  }

  // Fallback to ~/.claude/agents/
  const path = join(homedir(), ".claude", "agents", agentFileName);
  if (existsSync(path)) {
    unlinkSync(path);
    return true;
  }

  return false;
}

export function installStopHook(
  projectDir: string,
  sessionId: string,
  bridgeHome?: string,
): string {
  const home = bridgeHome ?? join(homedir(), ".claude-bridge");
  const settingsDir = join(projectDir, ".claude");
  mkdirSync(settingsDir, { recursive: true });

  const settingsPath = join(settingsDir, "settings.local.json");
  let settings: Record<string, unknown> = {};

  if (existsSync(settingsPath)) {
    try {
      settings = JSON.parse(readFileSync(settingsPath, "utf-8")) as Record<string, unknown>;
    } catch { /* start fresh */ }
  }

  const hookCmd = `CLAUDE_BRIDGE_HOME=${home} bridge-cli on-complete --session-id ${sessionId}`;

  // Ensure hooks.stop array exists and contains our hook
  if (!settings["hooks"]) settings["hooks"] = {};
  const hooks = settings["hooks"] as Record<string, unknown>;
  if (!Array.isArray(hooks["stop"])) hooks["stop"] = [];
  const stopHooks = hooks["stop"] as Array<Record<string, string>>;

  // Check if hook already exists
  const exists = stopHooks.some((h) => h["command"]?.includes("on-complete"));
  if (!exists) {
    stopHooks.push({ command: hookCmd });
  }

  writeFileSync(settingsPath, JSON.stringify(settings, null, 2), "utf-8");
  return settingsPath;
}
