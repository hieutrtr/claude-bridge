/**
 * Memory Reader — reads Claude Code's native Auto Memory.
 *
 * Finds and reads memory files from ~/.claude/projects/{encoded}/memory/.
 * Matches Python memory.py behavior.
 */

import { existsSync, readFileSync, readdirSync } from "fs";
import { join, basename } from "path";
import { homedir } from "os";

export interface MemoryReport {
  found: boolean;
  memoryDir: string | null;
  main: string;
  topics: Array<{ name: string; content: string }>;
}

/**
 * Find Claude Code's memory directory for a project.
 * Path encoding: /Users/hieutran/projects/my-api → -Users-hieutran-projects-my-api
 */
export function findMemoryDir(projectDir: string): string | null {
  const claudeDir = join(homedir(), ".claude", "projects");
  if (!existsSync(claudeDir)) return null;

  // Encode path: replace / with -
  const encoded = projectDir.replace(/\//g, "-");
  const memDir = join(claudeDir, encoded, "memory");
  if (existsSync(memDir)) return memDir;

  // Fallback: search by basename
  try {
    const projName = basename(projectDir);
    const entries = readdirSync(claudeDir);
    for (const entry of entries) {
      if (entry.endsWith(projName) || entry.endsWith(`-${projName}`)) {
        const candidate = join(claudeDir, entry, "memory");
        if (existsSync(candidate)) return candidate;
      }
    }
  } catch { /* ignore */ }

  return null;
}

/**
 * Read all memory files from a project's memory directory.
 */
export function readMemory(projectDir: string): MemoryReport {
  const memDir = findMemoryDir(projectDir);
  if (!memDir) {
    return { found: false, memoryDir: null, main: "", topics: [] };
  }

  let main = "";
  const mainPath = join(memDir, "MEMORY.md");
  if (existsSync(mainPath)) {
    main = readFileSync(mainPath, "utf-8");
  }

  const topics: Array<{ name: string; content: string }> = [];
  try {
    const files = readdirSync(memDir).filter(
      (f) => f.endsWith(".md") && f !== "MEMORY.md",
    );
    for (const file of files) {
      const content = readFileSync(join(memDir, file), "utf-8");
      topics.push({ name: file.replace(".md", ""), content });
    }
  } catch { /* ignore */ }

  return { found: true, memoryDir: memDir, main, topics };
}

/**
 * Format a human-readable memory report.
 */
export function formatMemoryReport(agentName: string, projectDir: string): string {
  const report = readMemory(projectDir);
  if (!report.found) {
    return `No memory found for agent "${agentName}" (${projectDir})`;
  }

  const lines: string[] = [`Memory for "${agentName}" (${projectDir})`];
  lines.push(`Directory: ${report.memoryDir}`);
  lines.push("");

  if (report.main) {
    lines.push("--- Main Memory ---");
    lines.push(report.main);
    lines.push("");
  }

  if (report.topics.length > 0) {
    lines.push(`--- Topics (${report.topics.length}) ---`);
    for (const topic of report.topics) {
      lines.push(`\n[${topic.name}]`);
      lines.push(topic.content);
    }
  }

  return lines.join("\n");
}
