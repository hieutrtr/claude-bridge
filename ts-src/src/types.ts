/**
 * Core type definitions for Claude Bridge.
 *
 * Shared types used across all modules: data layer, execution, channels, orchestration.
 */

// --- Agent & Session ---

export interface Agent {
  name: string;
  project_path: string;
  purpose: string;
  session_id: string;
  created_at: string;
  updated_at: string;
}

export interface Session {
  session_id: string; // format: "agent--project" e.g. "backend--my-api"
  agent_name: string;
  project_path: string;
}

// --- Task ---

export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "timeout";

export interface Task {
  id: number;
  agent_name: string;
  session_id: string;
  prompt: string;
  status: TaskStatus;
  pid: number | null;
  worktree_path: string | null;
  result_summary: string | null;
  exit_code: number | null;
  cost_usd: number | null;
  duration_seconds: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface TaskCreateInput {
  agent_name: string;
  session_id: string;
  prompt: string;
}

// --- Loop ---

export type LoopStatus = "running" | "paused" | "completed" | "failed" | "cancelled";

export interface Loop {
  id: number;
  agent_name: string;
  session_id: string;
  goal: string;
  done_condition: string;
  status: LoopStatus;
  current_iteration: number;
  max_iterations: number;
  created_at: string;
  updated_at: string;
}

// --- Schedule ---

export interface Schedule {
  id: number;
  agent_name: string;
  session_id: string;
  cron_expression: string;
  prompt: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

// --- Configuration ---

export interface BridgeConfig {
  home_dir: string;
  db_path: string;
  bot_dir: string | null;
  telegram_token: string | null;
  telegram_chat_id: string | null;
}

// --- Notification ---

export interface Notification {
  task_id: number;
  agent_name: string;
  status: TaskStatus;
  summary: string | null;
  cost_usd: number | null;
  duration_seconds: number | null;
}
