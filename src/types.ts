/**
 * Core type definitions for Claude Bridge.
 *
 * Shared types used across all modules: data layer, execution, channels, orchestration.
 * Field names match Python SQLite schema for cross-compatibility.
 */

// --- Agent & Session ---

export type AgentState = "created" | "idle" | "running";

export interface Agent {
  name: string;
  project_dir: string;
  session_id: string;
  agent_file: string;
  purpose: string | null;
  state: AgentState;
  created_at: string;
  last_task_at: string | null;
  total_tasks: number;
  model: string;
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
  | "done"
  | "failed"
  | "cancelled"
  | "timeout"
  | "queued";

export type TaskType = "standard" | "loop" | "schedule";

export interface Task {
  id: number;
  session_id: string;
  prompt: string;
  status: TaskStatus;
  position: number | null;
  pid: number | null;
  result_file: string | null;
  result_summary: string | null;
  cost_usd: number | null;
  duration_ms: number | null;
  num_turns: number | null;
  exit_code: number | null;
  error_message: string | null;
  model: string | null;
  task_type: TaskType;
  parent_task_id: number | null;
  channel: string;
  channel_chat_id: string | null;
  channel_message_id: string | null;
  user_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  reported: number;
}

export interface TaskCreateInput {
  session_id: string;
  prompt: string;
  task_type?: TaskType;
  parent_task_id?: number;
  channel?: string;
  channel_chat_id?: string;
  channel_message_id?: string;
  user_id?: string;
}

// --- Loop ---

export type LoopStatus = "running" | "paused" | "done" | "failed" | "timeout" | "cancelled";

export interface Loop {
  loop_id: string;
  agent: string;
  project: string;
  goal: string;
  done_when: string;
  loop_type: string;
  status: LoopStatus;
  max_iterations: number;
  max_consecutive_failures: number;
  current_iteration: number;
  consecutive_failures: number;
  total_cost_usd: number;
  max_cost_usd: number | null;
  pending_approval: number;
  started_at: string;
  finished_at: string | null;
  finish_reason: string | null;
  current_task_id: string | null;
  channel: string | null;
  channel_chat_id: string | null;
  user_id: string | null;
  plan: string | null;
  plan_enabled: number;
}

/** Parsed plan stored JSON-serialized in `Loop.plan`. */
export interface LoopPlan {
  steps: LoopPlanStep[];
  truncated?: boolean;
}

export interface LoopPlanStep {
  id: number;
  title: string;
  description: string;
  verification?: string;
}

export interface LoopIteration {
  id: number;
  loop_id: string;
  iteration_num: number;
  task_id: string | null;
  prompt: string | null;
  result_summary: string | null;
  done_check_passed: number;
  cost_usd: number;
  started_at: string;
  finished_at: string | null;
  status: string;
}

// --- Schedule ---

export interface Schedule {
  id: number;
  name: string;
  agent_name: string;
  prompt: string;
  interval_minutes: number | null;
  cron_expr: string | null;
  run_once: number;
  enabled: number;
  run_count: number;
  consecutive_errors: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
  channel: string;
  channel_chat_id: string | null;
  user_id: string | null;
  created_at: string;
  updated_at: string;
}

// --- Permission ---

export type PermissionStatus = "pending" | "approved" | "denied" | "timeout";

export interface Permission {
  id: string;
  session_id: string;
  tool_name: string;
  command: string | null;
  description: string | null;
  status: PermissionStatus;
  response: string | null;
  created_at: string;
  responded_at: string | null;
  timeout_seconds: number;
}

// --- Notification ---

export type NotificationStatus = "pending" | "sent" | "failed";

export interface Notification {
  id: number;
  task_id: number;
  channel: string;
  chat_id: string;
  message: string;
  status: NotificationStatus;
  created_at: string;
  sent_at: string | null;
}

// --- Team ---

export interface Team {
  name: string;
  lead_agent: string;
  created_at: string;
}

// --- Message (Channel I/O) ---

export type MessageStatus = "pending" | "delivered" | "acknowledged" | "failed";
export type OutboundStatus = "pending" | "sent" | "failed" | "notified";

export interface InboundMessage {
  id: number;
  platform: string;
  chat_id: string;
  user_id: string;
  username: string | null;
  message_text: string;
  message_id: string | null;
  status: MessageStatus;
  retry_count: number;
  max_retries: number;
  created_at: string;
  delivered_at: string | null;
  acknowledged_at: string | null;
}

export interface OutboundMessage {
  id: number;
  platform: string;
  chat_id: string;
  message_text: string;
  reply_to_message_id: string | null;
  source: string;
  status: OutboundStatus;
  retry_count: number;
  max_retries: number;
  created_at: string;
  sent_at: string | null;
  task_id: number | null;
}

// --- Configuration ---

export interface BridgeConfig {
  home_dir: string;
  db_path: string;
  bot_dir: string | null;
  telegram_token: string | null;
  telegram_chat_id: string | null;
}

// --- Cost Summary ---

export interface CostSummary {
  total_cost_usd: number;
  task_count: number;
  avg_cost_usd: number;
}
