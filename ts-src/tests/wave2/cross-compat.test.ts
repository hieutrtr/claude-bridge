/**
 * W2.6: Cross-Compatibility Test Suite
 *
 * Validates TS-created databases match Python schema expectations.
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { Database } from "bun:sqlite";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";
import { MessageDatabase } from "../../src/data/message-db.js";

let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-compat-"));
});

afterEach(() => {
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W2.6: Cross-Compatibility", () => {
  describe("Bridge Database schema", () => {
    test("passes PRAGMA integrity_check", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const result = rawDb.query("PRAGMA integrity_check").get() as { integrity_check: string };
      expect(result.integrity_check).toBe("ok");
      rawDb.close();
      db.close();
    });

    test("WAL mode is enabled", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const result = rawDb.query("PRAGMA journal_mode").get() as { journal_mode: string };
      expect(result.journal_mode).toBe("wal");
      rawDb.close();
      db.close();
    });

    test("has all expected tables", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const tables = rawDb.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
      ).all() as { name: string }[];
      const tableNames = tables.map((t) => t.name).sort();

      const expected = [
        "agents",
        "loop_iterations",
        "loops",
        "notifications",
        "permissions",
        "schedules",
        "tasks",
        "team_members",
        "teams",
      ].sort();

      expect(tableNames).toEqual(expected);
      rawDb.close();
      db.close();
    });

    test("agents table has correct columns", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const columns = rawDb.query("PRAGMA table_info(agents)").all() as { name: string }[];
      const colNames = columns.map((c) => c.name).sort();
      const expected = [
        "name", "project_dir", "session_id", "agent_file", "purpose",
        "state", "created_at", "last_task_at", "total_tasks", "model",
      ].sort();
      expect(colNames).toEqual(expected);
      rawDb.close();
      db.close();
    });

    test("tasks table has correct columns", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const columns = rawDb.query("PRAGMA table_info(tasks)").all() as { name: string }[];
      const colNames = columns.map((c) => c.name).sort();
      const expected = [
        "id", "session_id", "prompt", "status", "position", "pid",
        "result_file", "result_summary", "cost_usd", "duration_ms",
        "num_turns", "exit_code", "error_message", "model", "task_type",
        "parent_task_id", "channel", "channel_chat_id", "channel_message_id",
        "user_id", "created_at", "started_at", "completed_at", "reported",
      ].sort();
      expect(colNames).toEqual(expected);
      rawDb.close();
      db.close();
    });

    test("loops table has correct columns", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const columns = rawDb.query("PRAGMA table_info(loops)").all() as { name: string }[];
      const colNames = columns.map((c) => c.name).sort();
      const expected = [
        "loop_id", "agent", "project", "goal", "done_when", "loop_type",
        "status", "max_iterations", "max_consecutive_failures", "current_iteration",
        "consecutive_failures", "total_cost_usd", "max_cost_usd", "pending_approval",
        "started_at", "finished_at", "finish_reason", "current_task_id",
      ].sort();
      expect(colNames).toEqual(expected);
      rawDb.close();
      db.close();
    });

    test("schedules table has correct columns", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const columns = rawDb.query("PRAGMA table_info(schedules)").all() as { name: string }[];
      const colNames = columns.map((c) => c.name).sort();
      const expected = [
        "id", "name", "agent_name", "prompt", "interval_minutes", "cron_expr",
        "run_once", "enabled", "run_count", "consecutive_errors", "last_run_at",
        "next_run_at", "last_error", "channel", "channel_chat_id", "user_id",
        "created_at", "updated_at",
      ].sort();
      expect(colNames).toEqual(expected);
      rawDb.close();
      db.close();
    });

    test("has expected indexes", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const rawDb = new Database(join(tmpDir, "bridge.db"), { readonly: true });
      const indexes = rawDb.query(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name",
      ).all() as { name: string }[];
      const indexNames = indexes.map((i) => i.name).sort();

      expect(indexNames).toContain("idx_tasks_status");
      expect(indexNames).toContain("idx_tasks_session");
      expect(indexNames).toContain("idx_loops_status");
      expect(indexNames).toContain("idx_loops_agent");
      expect(indexNames).toContain("idx_notifications_status");
      expect(indexNames).toContain("idx_permissions_status");
      expect(indexNames).toContain("idx_schedules_next_run");

      rawDb.close();
      db.close();
    });
  });

  describe("Message Database schema", () => {
    test("passes PRAGMA integrity_check", () => {
      const db = new MessageDatabase(join(tmpDir, "messages.db"));
      const rawDb = new Database(join(tmpDir, "messages.db"), { readonly: true });
      const result = rawDb.query("PRAGMA integrity_check").get() as { integrity_check: string };
      expect(result.integrity_check).toBe("ok");
      rawDb.close();
      db.close();
    });

    test("has all expected tables", () => {
      const db = new MessageDatabase(join(tmpDir, "messages.db"));
      const rawDb = new Database(join(tmpDir, "messages.db"), { readonly: true });
      const tables = rawDb.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
      ).all() as { name: string }[];
      const tableNames = tables.map((t) => t.name).sort();
      expect(tableNames).toEqual(["inbound_messages", "outbound_messages", "poller_state"]);
      rawDb.close();
      db.close();
    });

    test("inbound_messages has correct columns", () => {
      const db = new MessageDatabase(join(tmpDir, "messages.db"));
      const rawDb = new Database(join(tmpDir, "messages.db"), { readonly: true });
      const columns = rawDb.query("PRAGMA table_info(inbound_messages)").all() as { name: string }[];
      const colNames = columns.map((c) => c.name).sort();
      const expected = [
        "id", "platform", "chat_id", "user_id", "username", "message_text",
        "message_id", "status", "retry_count", "max_retries",
        "created_at", "delivered_at", "acknowledged_at",
      ].sort();
      expect(colNames).toEqual(expected);
      rawDb.close();
      db.close();
    });

    test("outbound_messages has correct columns", () => {
      const db = new MessageDatabase(join(tmpDir, "messages.db"));
      const rawDb = new Database(join(tmpDir, "messages.db"), { readonly: true });
      const columns = rawDb.query("PRAGMA table_info(outbound_messages)").all() as { name: string }[];
      const colNames = columns.map((c) => c.name).sort();
      const expected = [
        "id", "platform", "chat_id", "message_text", "reply_to_message_id",
        "source", "status", "retry_count", "max_retries",
        "created_at", "sent_at", "task_id",
      ].sort();
      expect(colNames).toEqual(expected);
      rawDb.close();
      db.close();
    });
  });

  describe("Data roundtrip", () => {
    test("agent roundtrip", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const agent = db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api", "API dev", "opus");
      const read = db.getAgent("backend")!;
      expect(read.name).toBe(agent.name);
      expect(read.session_id).toBe(agent.session_id);
      expect(read.model).toBe("opus");
      db.close();
    });

    test("task roundtrip", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      db.createAgent("be", "/p", "be--p", "f");
      const id = db.createTask({ session_id: "be--p", prompt: "test", task_type: "loop", channel: "telegram" });
      const task = db.getTask(id)!;
      expect(task.prompt).toBe("test");
      expect(task.task_type).toBe("loop");
      expect(task.channel).toBe("telegram");
      db.close();
    });

    test("loop + iteration roundtrip", () => {
      const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
      const loopId = db.createLoop("be", "/p", "fix", "cmd:test", "bridge", 5, 2, 10.0);
      const iterId = db.createLoopIteration(loopId, 1, "prompt");
      db.updateLoopIteration(iterId, { done_check_passed: 1, cost_usd: 0.5 });
      const iters = db.getLoopIterations(loopId);
      expect(iters[0]!.done_check_passed).toBe(1);
      expect(iters[0]!.cost_usd).toBe(0.5);
      db.close();
    });

    test("message roundtrip", () => {
      const db = new MessageDatabase(join(tmpDir, "messages.db"));
      const inId = db.createInbound("telegram", "chat1", "user1", "hello", "msg1", "testuser");
      const outId = db.createOutbound("telegram", "chat1", "reply", "msg1", "bot", 42);
      const inMsg = db.getInbound(inId)!;
      const outMsg = db.getOutbound(outId)!;
      expect(inMsg.message_text).toBe("hello");
      expect(outMsg.task_id).toBe(42);
      db.close();
    });
  });
});
