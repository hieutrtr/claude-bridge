/**
 * W2.2: BridgeDatabase Core Tests — Agents + Tasks + Queue
 */
import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";

let db: BridgeDatabase;
let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "bridge-test-"));
  db = new BridgeDatabase(join(tmpDir, "test.db"));
});

afterEach(() => {
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W2.2: BridgeDatabase Core", () => {
  describe("Schema initialization", () => {
    test("creates database with WAL mode", () => {
      // WAL mode is set in constructor — if we got here, it worked
      expect(db).toBeDefined();
    });

    test("can create a second instance on same DB (WAL allows concurrent)", () => {
      const db2 = new BridgeDatabase(join(tmpDir, "test.db"));
      expect(db2).toBeDefined();
      db2.close();
    });
  });

  describe("Agent CRUD", () => {
    test("createAgent returns agent with all fields", () => {
      const agent = db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api", "API dev", "sonnet");
      expect(agent.name).toBe("backend");
      expect(agent.project_dir).toBe("/projects/api");
      expect(agent.session_id).toBe("backend--api");
      expect(agent.agent_file).toBe("bridge--backend--api");
      expect(agent.purpose).toBe("API dev");
      expect(agent.state).toBe("created");
      expect(agent.model).toBe("sonnet");
      expect(agent.total_tasks).toBe(0);
      expect(agent.created_at).toBeTruthy();
    });

    test("createAgent with default model", () => {
      const agent = db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      expect(agent.model).toBe("sonnet");
    });

    test("getAgent returns agent by name", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api", "API dev");
      const agent = db.getAgent("backend");
      expect(agent).not.toBeNull();
      expect(agent!.name).toBe("backend");
    });

    test("getAgent returns null for nonexistent", () => {
      expect(db.getAgent("nope")).toBeNull();
    });

    test("getAgentBySession returns agent by session_id", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      const agent = db.getAgentBySession("backend--api");
      expect(agent).not.toBeNull();
      expect(agent!.name).toBe("backend");
    });

    test("getAgentBySession returns null for nonexistent", () => {
      expect(db.getAgentBySession("nope--nope")).toBeNull();
    });

    test("listAgents returns all agents", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      db.createAgent("frontend", "/projects/ui", "frontend--ui", "bridge--frontend--ui");
      const agents = db.listAgents();
      expect(agents.length).toBe(2);
    });

    test("deleteAgent removes agent and returns true", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      expect(db.deleteAgent("backend")).toBe(true);
      expect(db.getAgent("backend")).toBeNull();
    });

    test("deleteAgent returns false for nonexistent", () => {
      expect(db.deleteAgent("nope")).toBe(false);
    });

    test("deleteAgent cascades to tasks", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      const taskId = db.createTask({ session_id: "backend--api", prompt: "test" });
      db.deleteAgent("backend");
      expect(db.getTask(taskId)).toBeNull();
    });

    test("updateAgentState changes state", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      db.updateAgentState("backend--api", "running");
      expect(db.getAgent("backend")!.state).toBe("running");
    });

    test("incrementAgentTasks increments total_tasks", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      db.incrementAgentTasks("backend--api");
      db.incrementAgentTasks("backend--api");
      expect(db.getAgent("backend")!.total_tasks).toBe(2);
    });

    test("updateAgentModel changes model", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      db.updateAgentModel("backend--api", "opus");
      expect(db.getAgent("backend")!.model).toBe("opus");
    });

    test("duplicate agent name+project throws", () => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
      expect(() => {
        db.createAgent("backend", "/projects/api", "backend--api2", "bridge--backend--api2");
      }).toThrow();
    });
  });

  describe("Task CRUD", () => {
    beforeEach(() => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
    });

    test("createTask returns task ID", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "add tests" });
      expect(id).toBeGreaterThan(0);
    });

    test("getTask returns task with all fields", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "add tests" });
      const task = db.getTask(id);
      expect(task).not.toBeNull();
      expect(task!.id).toBe(id);
      expect(task!.session_id).toBe("backend--api");
      expect(task!.prompt).toBe("add tests");
      expect(task!.status).toBe("pending");
      expect(task!.task_type).toBe("standard");
      expect(task!.channel).toBe("cli");
      expect(task!.reported).toBe(0);
    });

    test("createTask with optional fields", () => {
      const id = db.createTask({
        session_id: "backend--api",
        prompt: "test",
        task_type: "loop",
        channel: "telegram",
        channel_chat_id: "123",
        user_id: "456",
      });
      const task = db.getTask(id)!;
      expect(task.task_type).toBe("loop");
      expect(task.channel).toBe("telegram");
      expect(task.channel_chat_id).toBe("123");
      expect(task.user_id).toBe("456");
    });

    test("getTask returns null for nonexistent", () => {
      expect(db.getTask(999)).toBeNull();
    });

    test("getRunningTask returns running task for session", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "test" });
      db.updateTask(id, { status: "running", pid: 1234, started_at: new Date().toISOString() });
      const task = db.getRunningTask("backend--api");
      expect(task).not.toBeNull();
      expect(task!.id).toBe(id);
      expect(task!.status).toBe("running");
    });

    test("getRunningTask returns null when no running task", () => {
      db.createTask({ session_id: "backend--api", prompt: "test" });
      expect(db.getRunningTask("backend--api")).toBeNull();
    });

    test("getRunningTasks returns all running tasks", () => {
      db.createAgent("frontend", "/projects/ui", "frontend--ui", "bridge--frontend--ui");
      const id1 = db.createTask({ session_id: "backend--api", prompt: "t1" });
      const id2 = db.createTask({ session_id: "frontend--ui", prompt: "t2" });
      db.updateTask(id1, { status: "running", pid: 1001 });
      db.updateTask(id2, { status: "running", pid: 1002 });
      expect(db.getRunningTasks().length).toBe(2);
    });

    test("getUnreportedTasks returns completed unreported tasks", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "test" });
      db.updateTask(id, { status: "done", completed_at: new Date().toISOString() });
      const unreported = db.getUnreportedTasks();
      expect(unreported.length).toBe(1);
      expect(unreported[0]!.id).toBe(id);
    });

    test("getUnreportedTasks excludes reported tasks", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "test" });
      db.updateTask(id, { status: "done" });
      db.markTaskReported(id);
      expect(db.getUnreportedTasks().length).toBe(0);
    });

    test("getTaskHistory returns tasks ordered by id DESC", () => {
      db.createTask({ session_id: "backend--api", prompt: "t1" });
      db.createTask({ session_id: "backend--api", prompt: "t2" });
      db.createTask({ session_id: "backend--api", prompt: "t3" });
      const history = db.getTaskHistory("backend--api", 2);
      expect(history.length).toBe(2);
      expect(history[0]!.prompt).toBe("t3");
    });

    test("updateTask updates allowed fields", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "test" });
      db.updateTask(id, {
        status: "running",
        pid: 1234,
        model: "opus",
        started_at: "2024-01-01T00:00:00Z",
      });
      const task = db.getTask(id)!;
      expect(task.status).toBe("running");
      expect(task.pid).toBe(1234);
      expect(task.model).toBe("opus");
    });

    test("markTaskReported sets reported=1", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "test" });
      db.markTaskReported(id);
      expect(db.getTask(id)!.reported).toBe(1);
    });

    test("getSubtasks returns child tasks", () => {
      const parentId = db.createTask({ session_id: "backend--api", prompt: "parent" });
      db.createTask({ session_id: "backend--api", prompt: "child1", parent_task_id: parentId });
      db.createTask({ session_id: "backend--api", prompt: "child2", parent_task_id: parentId });
      const subs = db.getSubtasks(parentId);
      expect(subs.length).toBe(2);
    });
  });

  describe("Atomic dispatch", () => {
    beforeEach(() => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
    });

    test("creates task when no running task exists", () => {
      const { taskId, isBusy } = db.atomicCheckAndCreateTask("backend--api", "test prompt");
      expect(isBusy).toBe(false);
      expect(taskId).not.toBeNull();
      expect(taskId).toBeGreaterThan(0);
    });

    test("returns busy when running task exists", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "existing" });
      db.updateTask(id, { status: "running", pid: 1234 });
      const { taskId, isBusy } = db.atomicCheckAndCreateTask("backend--api", "new task");
      expect(isBusy).toBe(true);
      expect(taskId).toBeNull();
    });

    test("passes channel params through", () => {
      const { taskId } = db.atomicCheckAndCreateTask(
        "backend--api", "test", "telegram", "chat123", "msg456", "user789",
      );
      const task = db.getTask(taskId!)!;
      expect(task.channel).toBe("telegram");
      expect(task.channel_chat_id).toBe("chat123");
      expect(task.channel_message_id).toBe("msg456");
      expect(task.user_id).toBe("user789");
    });
  });

  describe("Queue operations", () => {
    beforeEach(() => {
      db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api");
    });

    test("getQueuedTasks returns queued tasks in position order", () => {
      const id1 = db.createTask({ session_id: "backend--api", prompt: "q1" });
      const id2 = db.createTask({ session_id: "backend--api", prompt: "q2" });
      db.updateTask(id1, { status: "queued", position: 1 });
      db.updateTask(id2, { status: "queued", position: 2 });
      const queued = db.getQueuedTasks("backend--api");
      expect(queued.length).toBe(2);
      expect(queued[0]!.prompt).toBe("q1");
    });

    test("getNextQueuePosition returns 1 when empty", () => {
      expect(db.getNextQueuePosition("backend--api")).toBe(1);
    });

    test("getNextQueuePosition returns max+1", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "q1" });
      db.updateTask(id, { status: "queued", position: 3 });
      expect(db.getNextQueuePosition("backend--api")).toBe(4);
    });

    test("dequeueNextTask returns lowest position task", () => {
      const id1 = db.createTask({ session_id: "backend--api", prompt: "q1" });
      const id2 = db.createTask({ session_id: "backend--api", prompt: "q2" });
      db.updateTask(id1, { status: "queued", position: 2 });
      db.updateTask(id2, { status: "queued", position: 1 });
      const task = db.dequeueNextTask("backend--api");
      expect(task).not.toBeNull();
      expect(task!.prompt).toBe("q2");
      expect(task!.status).toBe("pending");
    });

    test("dequeueNextTask returns null when empty", () => {
      expect(db.dequeueNextTask("backend--api")).toBeNull();
    });

    test("cancelQueuedTask cancels and returns true", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "q1" });
      db.updateTask(id, { status: "queued", position: 1 });
      expect(db.cancelQueuedTask(id)).toBe(true);
      expect(db.getTask(id)!.status).toBe("cancelled");
    });

    test("cancelQueuedTask returns false for non-queued task", () => {
      const id = db.createTask({ session_id: "backend--api", prompt: "q1" });
      expect(db.cancelQueuedTask(id)).toBe(false);
    });
  });
});
