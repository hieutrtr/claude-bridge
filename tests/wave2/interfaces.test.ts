/**
 * W2.1: Interface Expansion Tests
 *
 * Validates that IDatabase, IMessageDatabase, and ISessionManager
 * have all required methods and that types.ts has all entity types.
 */
import { describe, test, expect } from "bun:test";
import type { IDatabase, IMessageDatabase, ISessionManager, IConfigProvider } from "../../src/data/interfaces.js";
import type {
  Agent,
  Task,
  Loop,
  LoopIteration,
  Schedule,
  Permission,
  Notification,
  Team,
  InboundMessage,
  OutboundMessage,
  CostSummary,
  TaskStatus,
  LoopStatus,
  AgentState,
  TaskType,
  PermissionStatus,
  NotificationStatus,
  MessageStatus,
  OutboundStatus,
} from "../../src/types.js";

describe("W2.1: Interface Expansion", () => {
  describe("Type definitions exist", () => {
    test("Agent type has all fields", () => {
      const agent: Agent = {
        name: "backend",
        project_dir: "/projects/api",
        session_id: "backend--api",
        agent_file: "bridge--backend--api",
        purpose: "API dev",
        state: "created",
        created_at: "2024-01-01",
        last_task_at: null,
        total_tasks: 0,
        model: "sonnet",
      };
      expect(agent.name).toBe("backend");
      expect(agent.state).toBe("created");
    });

    test("Task type has all fields", () => {
      const task: Task = {
        id: 1,
        session_id: "backend--api",
        prompt: "test",
        status: "pending",
        position: null,
        pid: null,
        result_file: null,
        result_summary: null,
        cost_usd: null,
        duration_ms: null,
        num_turns: null,
        exit_code: null,
        error_message: null,
        model: null,
        task_type: "standard",
        parent_task_id: null,
        channel: "cli",
        channel_chat_id: null,
        channel_message_id: null,
        user_id: null,
        created_at: "2024-01-01",
        started_at: null,
        completed_at: null,
        reported: 0,
      };
      expect(task.id).toBe(1);
      expect(task.task_type).toBe("standard");
    });

    test("Loop type has all fields", () => {
      const loop: Loop = {
        loop_id: "abc123",
        agent: "backend",
        project: "/projects/api",
        goal: "fix tests",
        done_when: "command:pytest",
        loop_type: "bridge",
        status: "running",
        max_iterations: 10,
        max_consecutive_failures: 3,
        current_iteration: 0,
        consecutive_failures: 0,
        total_cost_usd: 0,
        max_cost_usd: null,
        pending_approval: 0,
        started_at: "2024-01-01",
        finished_at: null,
        finish_reason: null,
        current_task_id: null,
      };
      expect(loop.loop_id).toBe("abc123");
    });

    test("LoopIteration type has all fields", () => {
      const iter: LoopIteration = {
        id: 1,
        loop_id: "abc123",
        iteration_num: 1,
        task_id: null,
        prompt: null,
        result_summary: null,
        done_check_passed: 0,
        cost_usd: 0,
        started_at: "2024-01-01",
        finished_at: null,
        status: "running",
      };
      expect(iter.id).toBe(1);
    });

    test("Schedule type has all fields", () => {
      const sched: Schedule = {
        id: 1,
        name: "daily-check",
        agent_name: "backend",
        prompt: "run tests",
        interval_minutes: 60,
        cron_expr: null,
        run_once: 0,
        enabled: 1,
        run_count: 0,
        consecutive_errors: 0,
        last_run_at: null,
        next_run_at: null,
        last_error: null,
        channel: "cli",
        channel_chat_id: null,
        user_id: null,
        created_at: "2024-01-01",
        updated_at: "2024-01-01",
      };
      expect(sched.name).toBe("daily-check");
    });

    test("Permission type has all fields", () => {
      const perm: Permission = {
        id: "req-123",
        session_id: "backend--api",
        tool_name: "Bash",
        command: "rm -rf /",
        description: "dangerous",
        status: "pending",
        response: null,
        created_at: "2024-01-01",
        responded_at: null,
        timeout_seconds: 300,
      };
      expect(perm.status).toBe("pending");
    });

    test("Notification type has all fields", () => {
      const notif: Notification = {
        id: 1,
        task_id: 1,
        channel: "telegram",
        chat_id: "123",
        message: "Task done",
        status: "pending",
        created_at: "2024-01-01",
        sent_at: null,
      };
      expect(notif.channel).toBe("telegram");
    });

    test("Team type has all fields", () => {
      const team: Team = {
        name: "alpha",
        lead_agent: "backend",
        created_at: "2024-01-01",
      };
      expect(team.lead_agent).toBe("backend");
    });

    test("InboundMessage type has all fields", () => {
      const msg: InboundMessage = {
        id: 1,
        platform: "telegram",
        chat_id: "123",
        user_id: "456",
        username: "user",
        message_text: "hello",
        message_id: "789",
        status: "pending",
        retry_count: 0,
        max_retries: 5,
        created_at: "2024-01-01",
        delivered_at: null,
        acknowledged_at: null,
      };
      expect(msg.platform).toBe("telegram");
    });

    test("OutboundMessage type has all fields", () => {
      const msg: OutboundMessage = {
        id: 1,
        platform: "telegram",
        chat_id: "123",
        message_text: "hello",
        reply_to_message_id: null,
        source: "bot",
        status: "pending",
        retry_count: 0,
        max_retries: 3,
        created_at: "2024-01-01",
        sent_at: null,
        task_id: null,
      };
      expect(msg.source).toBe("bot");
    });

    test("CostSummary type has all fields", () => {
      const cost: CostSummary = {
        total_cost_usd: 1.5,
        task_count: 3,
        avg_cost_usd: 0.5,
      };
      expect(cost.task_count).toBe(3);
    });
  });

  describe("Status type unions", () => {
    test("TaskStatus values", () => {
      const statuses: TaskStatus[] = ["pending", "running", "done", "failed", "cancelled", "timeout", "queued"];
      expect(statuses.length).toBe(7);
    });

    test("LoopStatus values", () => {
      const statuses: LoopStatus[] = ["running", "paused", "done", "failed", "timeout", "cancelled"];
      expect(statuses.length).toBe(6);
    });

    test("AgentState values", () => {
      const states: AgentState[] = ["created", "idle", "running"];
      expect(states.length).toBe(3);
    });
  });

  describe("IDatabase interface method count", () => {
    // We validate the interface by creating a mock that must satisfy it
    test("IDatabase has agent methods", () => {
      // Type-level test — if this compiles, the interface has these methods
      const checkMethods = (db: IDatabase) => {
        db.createAgent;
        db.getAgent;
        db.getAgentBySession;
        db.listAgents;
        db.deleteAgent;
        db.updateAgentState;
        db.incrementAgentTasks;
        db.updateAgentModel;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has task methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.createTask;
        db.getTask;
        db.getRunningTask;
        db.getRunningTasks;
        db.getUnreportedTasks;
        db.getTaskHistory;
        db.updateTask;
        db.markTaskReported;
        db.atomicCheckAndCreateTask;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has queue methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.getQueuedTasks;
        db.getNextQueuePosition;
        db.dequeueNextTask;
        db.cancelQueuedTask;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has loop methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.createLoop;
        db.getLoop;
        db.getActiveLoopForAgent;
        db.updateLoop;
        db.listLoops;
        db.createLoopIteration;
        db.updateLoopIteration;
        db.getLoopIterations;
        db.getLastNIterations;
        db.getLoopByTaskId;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has schedule methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.addSchedule;
        db.getScheduleByName;
        db.getScheduleById;
        db.getDueSchedules;
        db.updateScheduleSuccess;
        db.updateScheduleError;
        db.listSchedules;
        db.removeSchedule;
        db.pauseSchedule;
        db.resumeSchedule;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has permission methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.createPermission;
        db.getPermission;
        db.getPendingPermissions;
        db.respondPermission;
        db.timeoutPermissions;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has notification methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.createNotification;
        db.getNotification;
        db.getPendingNotifications;
        db.markNotificationSent;
        db.markNotificationFailed;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has team methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.createTeam;
        db.getTeam;
        db.getTeamMembers;
        db.listTeams;
        db.deleteTeam;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("IDatabase has cost and lifecycle methods", () => {
      const checkMethods = (db: IDatabase) => {
        db.getCostSummary;
        db.getSubtasks;
        db.close;
      };
      expect(typeof checkMethods).toBe("function");
    });
  });

  describe("IMessageDatabase interface", () => {
    test("has inbound methods", () => {
      const checkMethods = (db: IMessageDatabase) => {
        db.createInbound;
        db.getInbound;
        db.getPendingInbound;
        db.getUnacknowledgedInbound;
        db.markInboundDelivered;
        db.markInboundAcknowledged;
        db.markInboundFailed;
        db.incrementInboundRetry;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("has outbound methods", () => {
      const checkMethods = (db: IMessageDatabase) => {
        db.createOutbound;
        db.hasNotificationForTask;
        db.updatePendingOutboundForTask;
        db.getOutbound;
        db.getPendingOutbound;
        db.markOutboundSent;
        db.markOutboundFailed;
        db.incrementOutboundRetry;
        db.cleanupOldOutbound;
      };
      expect(typeof checkMethods).toBe("function");
    });

    test("has poller state methods", () => {
      const checkMethods = (db: IMessageDatabase) => {
        db.getState;
        db.setState;
        db.close;
      };
      expect(typeof checkMethods).toBe("function");
    });
  });

  describe("ISessionManager interface", () => {
    test("has all methods", () => {
      const checkMethods = (sm: ISessionManager) => {
        sm.deriveSessionId;
        sm.deriveAgentFileName;
        sm.validateAgentName;
        sm.validateProjectDir;
        sm.getWorktreePath;
        sm.getTasksDir;
        sm.getAgentMdPath;
        sm.getInstancePrefix;
        sm.createWorkspace;
        sm.cleanupWorkspace;
      };
      expect(typeof checkMethods).toBe("function");
    });
  });
});
