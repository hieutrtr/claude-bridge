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
  const stopHookCmd = `CLAUDE_BRIDGE_HOME=${home} bridge on-complete --session-id ${sessionId}`;

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

/**
 * Install a Stop hook that fires `bridge on-complete` when Claude Code
 * finishes a task in `projectDir`.
 *
 * Claude Code's actual schema (from its plugin docs) is:
 *
 *   { "hooks": { "Stop": [ { "hooks": [ { "type": "command", "command": "..." } ] } ] } }
 *
 * — event name is capitalized, and each group has a nested `hooks: [{ type, command }]`
 * array. Earlier versions of this function emitted `{ hooks: { stop: [{ command }] } }`
 * which Claude Code silently ignored, so tasks never triggered on-complete and got
 * stranded until ProcessWatcher marked them failed.
 *
 * When upgrading an existing settings.local.json, we also rewrite any legacy
 * lowercase `stop` entries and flat `{command}` shapes into the correct form.
 */
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

  const hookCmd = `CLAUDE_BRIDGE_HOME=${home} bridge on-complete --session-id ${sessionId}`;

  if (!settings["hooks"] || typeof settings["hooks"] !== "object") {
    settings["hooks"] = {};
  }
  const hooks = settings["hooks"] as Record<string, unknown>;

  // Migrate legacy lowercase `stop` entries, if any.
  if (hooks["stop"] && !hooks["Stop"]) {
    hooks["Stop"] = hooks["stop"];
  }
  delete hooks["stop"];

  if (!Array.isArray(hooks["Stop"])) hooks["Stop"] = [];
  const stopGroups = hooks["Stop"] as Array<Record<string, unknown>>;

  // Rewrite legacy flat `{ command }` groups into the nested Claude Code shape.
  for (let i = 0; i < stopGroups.length; i++) {
    const group = stopGroups[i]!;
    const flatCmd = typeof group["command"] === "string" ? (group["command"] as string) : null;
    if (flatCmd && !Array.isArray(group["hooks"])) {
      stopGroups[i] = { hooks: [{ type: "command", command: flatCmd }] };
    }
  }

  // Remove any existing on-complete hook for this session — older installs
  // pointed at the legacy Python `bridge-cli` binary which no longer exists.
  // Other sessions' hooks are left alone. Drop groups that end up empty.
  const sessionMarker = `--session-id ${sessionId}`;
  for (let i = stopGroups.length - 1; i >= 0; i--) {
    const group = stopGroups[i]!;
    const inner = group["hooks"];
    if (!Array.isArray(inner)) continue;
    const innerArr = inner as Array<Record<string, unknown>>;
    const filtered = innerArr.filter((h) => {
      const cmd = typeof h["command"] === "string" ? (h["command"] as string) : "";
      return !(cmd.includes("on-complete") && cmd.includes(sessionMarker));
    });
    if (filtered.length === 0) {
      stopGroups.splice(i, 1);
    } else {
      group["hooks"] = filtered;
    }
  }

  stopGroups.push({ hooks: [{ type: "command", command: hookCmd }] });

  writeFileSync(settingsPath, JSON.stringify(settings, null, 2), "utf-8");
  return settingsPath;
}
