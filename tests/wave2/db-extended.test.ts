/**
 * W2.3: BridgeDatabase Extended Tests — Loops, Schedules, Permissions, Notifications, Teams, Cost
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
  db.createAgent("backend", "/projects/api", "backend--api", "bridge--backend--api", "API dev");
});

afterEach(() => {
  db.close();
  rmSync(tmpDir, { recursive: true, force: true });
});

describe("W2.3: BridgeDatabase Extended", () => {
  describe("Loop Operations", () => {
    test("createLoop returns loop_id", () => {
      const id = db.createLoop("backend", "/projects/api", "fix tests", "command:pytest");
      expect(id).toBeString();
      expect(id.length).toBe(8);
    });

    test("getLoop returns loop with all fields", () => {
      const id = db.createLoop("backend", "/projects/api", "fix tests", "command:pytest", "bridge", 5, 2, 10.0);
      const loop = db.getLoop(id);
      expect(loop).not.toBeNull();
      expect(loop!.agent).toBe("backend");
      expect(loop!.goal).toBe("fix tests");
      expect(loop!.done_when).toBe("command:pytest");
      expect(loop!.max_iterations).toBe(5);
      expect(loop!.max_consecutive_failures).toBe(2);
      expect(loop!.max_cost_usd).toBe(10.0);
      expect(loop!.status).toBe("running");
      expect(loop!.current_iteration).toBe(0);
    });

    test("getLoop returns null for nonexistent", () => {
      expect(db.getLoop("nope")).toBeNull();
    });

    test("getActiveLoopForAgent returns running loop", () => {
      db.createLoop("backend", "/projects/api", "fix tests", "command:pytest");
      const loop = db.getActiveLoopForAgent("backend");
      expect(loop).not.toBeNull();
      expect(loop!.agent).toBe("backend");
    });

    test("getActiveLoopForAgent returns null when no running loop", () => {
      const id = db.createLoop("backend", "/projects/api", "fix tests", "command:pytest");
      db.updateLoop(id, { status: "done" });
      expect(db.getActiveLoopForAgent("backend")).toBeNull();
    });

    test("updateLoop updates allowed fields", () => {
      const id = db.createLoop("backend", "/projects/api", "fix tests", "command:pytest");
      db.updateLoop(id, { current_iteration: 3, total_cost_usd: 1.5, status: "done", finish_reason: "completed" });
      const loop = db.getLoop(id)!;
      expect(loop.current_iteration).toBe(3);
      expect(loop.total_cost_usd).toBe(1.5);
      expect(loop.status).toBe("done");
      expect(loop.finish_reason).toBe("completed");
    });

    test("listLoops returns loops filtered by agent", () => {
      db.createLoop("backend", "/projects/api", "goal1", "cmd:test");
      db.createLoop("backend", "/projects/api", "goal2", "cmd:test");
      expect(db.listLoops("backend").length).toBe(2);
      expect(db.listLoops("frontend").length).toBe(0);
    });

    test("listLoops filters by status", () => {
      const id1 = db.createLoop("backend", "/projects/api", "goal1", "cmd:test");
      db.createLoop("backend", "/projects/api", "goal2", "cmd:test");
      db.updateLoop(id1, { status: "done" });
      expect(db.listLoops("backend", 20, "running").length).toBe(1);
    });

    test("getLoopByTaskId finds loop by current_task_id", () => {
      const id = db.createLoop("backend", "/projects/api", "fix", "cmd:test");
      db.updateLoop(id, { current_task_id: "42" });
      const loop = db.getLoopByTaskId("42");
      expect(loop).not.toBeNull();
      expect(loop!.loop_id).toBe(id);
    });
  });

  describe("Loop Iteration Operations", () => {
    let loopId: string;

    beforeEach(() => {
      loopId = db.createLoop("backend", "/projects/api", "fix", "cmd:test");
    });

    test("createLoopIteration returns ID", () => {
      const id = db.createLoopIteration(loopId, 1, "iteration prompt");
      expect(id).toBeGreaterThan(0);
    });

    test("getLoopIterations returns iterations in order", () => {
      db.createLoopIteration(loopId, 1, "p1");
      db.createLoopIteration(loopId, 2, "p2");
      db.createLoopIteration(loopId, 3, "p3");
      const iters = db.getLoopIterations(loopId);
      expect(iters.length).toBe(3);
      expect(iters[0]!.iteration_num).toBe(1);
      expect(iters[2]!.iteration_num).toBe(3);
    });

    test("updateLoopIteration updates allowed fields", () => {
      const id = db.createLoopIteration(loopId, 1, "p1");
      db.updateLoopIteration(id, { status: "done", done_check_passed: 1, cost_usd: 0.5 });
      const iters = db.getLoopIterations(loopId);
      expect(iters[0]!.status).toBe("done");
      expect(iters[0]!.done_check_passed).toBe(1);
      expect(iters[0]!.cost_usd).toBe(0.5);
    });

    test("getLastNIterations returns last N in ascending order", () => {
      db.createLoopIteration(loopId, 1, "p1");
      db.createLoopIteration(loopId, 2, "p2");
      db.createLoopIteration(loopId, 3, "p3");
      const last2 = db.getLastNIterations(loopId, 2);
      expect(last2.length).toBe(2);
      expect(last2[0]!.iteration_num).toBe(2);
      expect(last2[1]!.iteration_num).toBe(3);
    });
  });

  describe("Schedule Operations", () => {
    test("addSchedule returns ID", () => {
      const id = db.addSchedule("daily-check", "backend", "run tests", 60);
      expect(id).toBeGreaterThan(0);
    });

    test("getScheduleByName returns schedule", () => {
      db.addSchedule("daily-check", "backend", "run tests", 60);
      const sched = db.getScheduleByName("daily-check");
      expect(sched).not.toBeNull();
      expect(sched!.agent_name).toBe("backend");
      expect(sched!.interval_minutes).toBe(60);
      expect(sched!.enabled).toBe(1);
    });

    test("getScheduleById returns schedule", () => {
      const id = db.addSchedule("daily-check", "backend", "run tests", 60);
      const sched = db.getScheduleById(id);
      expect(sched).not.toBeNull();
      expect(sched!.name).toBe("daily-check");
    });

    test("getDueSchedules returns due schedules", () => {
      db.addSchedule("past-check", "backend", "run tests", 0); // 0 minutes = now
      const futureDate = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000); // 1 year from now
      const due = db.getDueSchedules(futureDate);
      expect(due.length).toBeGreaterThanOrEqual(1);
    });

    test("updateScheduleSuccess increments run_count and resets errors", () => {
      const id = db.addSchedule("check", "backend", "test", 30);
      db.updateScheduleSuccess(id, new Date());
      const sched = db.getScheduleById(id)!;
      expect(sched.run_count).toBe(1);
      expect(sched.consecutive_errors).toBe(0);
    });

    test("updateScheduleError increments error count", () => {
      const id = db.addSchedule("check", "backend", "test", 30);
      db.updateScheduleError(id, "connection failed");
      const sched = db.getScheduleById(id)!;
      expect(sched.consecutive_errors).toBe(1);
      expect(sched.last_error).toBe("connection failed");
    });

    test("updateScheduleError auto-pauses after 5 errors", () => {
      const id = db.addSchedule("check", "backend", "test", 30);
      for (let i = 0; i < 5; i++) {
        db.updateScheduleError(id, `error ${i}`);
      }
      const sched = db.getScheduleById(id)!;
      expect(sched.enabled).toBe(0);
      expect(sched.consecutive_errors).toBe(5);
    });

    test("listSchedules returns enabled schedules", () => {
      db.addSchedule("s1", "backend", "test1", 30);
      db.addSchedule("s2", "backend", "test2", 60);
      expect(db.listSchedules().length).toBe(2);
    });

    test("listSchedules filters by agent", () => {
      db.createAgent("frontend", "/projects/ui", "frontend--ui", "bridge--frontend--ui");
      db.addSchedule("s1", "backend", "test1", 30);
      db.addSchedule("s2", "frontend", "test2", 60);
      expect(db.listSchedules("backend").length).toBe(1);
    });

    test("removeSchedule by name", () => {
      db.addSchedule("daily-check", "backend", "test", 30);
      expect(db.removeSchedule("daily-check")).toBe(true);
      expect(db.getScheduleByName("daily-check")).toBeNull();
    });

    test("removeSchedule by id", () => {
      const id = db.addSchedule("daily-check", "backend", "test", 30);
      expect(db.removeSchedule(String(id))).toBe(true);
    });

    test("pauseSchedule disables", () => {
      db.addSchedule("check", "backend", "test", 30);
      db.pauseSchedule("check");
      expect(db.getScheduleByName("check")!.enabled).toBe(0);
    });

    test("resumeSchedule enables and resets errors", () => {
      const id = db.addSchedule("check", "backend", "test", 30);
      db.updateScheduleError(id, "err");
      db.pauseSchedule("check");
      db.resumeSchedule("check");
      const sched = db.getScheduleByName("check")!;
      expect(sched.enabled).toBe(1);
      expect(sched.consecutive_errors).toBe(0);
    });
  });

  describe("Permission Operations", () => {
    test("createPermission returns request_id", () => {
      const id = db.createPermission("req-1", "backend--api", "Bash", "rm -rf /", "dangerous");
      expect(id).toBe("req-1");
    });

    test("getPermission returns permission", () => {
      db.createPermission("req-1", "backend--api", "Bash", "rm -rf /", "dangerous", 600);
      const perm = db.getPermission("req-1");
      expect(perm).not.toBeNull();
      expect(perm!.tool_name).toBe("Bash");
      expect(perm!.status).toBe("pending");
      expect(perm!.timeout_seconds).toBe(600);
    });

    test("getPendingPermissions returns pending", () => {
      db.createPermission("req-1", "backend--api", "Bash");
      db.createPermission("req-2", "backend--api", "Write");
      expect(db.getPendingPermissions().length).toBe(2);
    });

    test("getPendingPermissions filters by session", () => {
      db.createAgent("frontend", "/projects/ui", "frontend--ui", "bridge--frontend--ui");
      db.createPermission("req-1", "backend--api", "Bash");
      db.createPermission("req-2", "frontend--ui", "Write");
      expect(db.getPendingPermissions("backend--api").length).toBe(1);
    });

    test("respondPermission approves", () => {
      db.createPermission("req-1", "backend--api", "Bash");
      expect(db.respondPermission("req-1", true)).toBe(true);
      expect(db.getPermission("req-1")!.status).toBe("approved");
    });

    test("respondPermission denies", () => {
      db.createPermission("req-1", "backend--api", "Bash");
      expect(db.respondPermission("req-1", false)).toBe(true);
      expect(db.getPermission("req-1")!.status).toBe("denied");
    });

    test("respondPermission returns false for already responded", () => {
      db.createPermission("req-1", "backend--api", "Bash");
      db.respondPermission("req-1", true);
      expect(db.respondPermission("req-1", false)).toBe(false);
    });
  });

  describe("Notification Operations", () => {
    test("createNotification returns ID", () => {
      const taskId = db.createTask({ session_id: "backend--api", prompt: "test" });
      const id = db.createNotification(taskId, "telegram", "123", "Task done");
      expect(id).toBeGreaterThan(0);
    });

    test("getNotification returns notification", () => {
      const taskId = db.createTask({ session_id: "backend--api", prompt: "test" });
      const id = db.createNotification(taskId, "telegram", "123", "Task done");
      const notif = db.getNotification(id);
      expect(notif).not.toBeNull();
      expect(notif!.channel).toBe("telegram");
      expect(notif!.status).toBe("pending");
    });

    test("getPendingNotifications returns pending", () => {
      const taskId = db.createTask({ session_id: "backend--api", prompt: "test" });
      db.createNotification(taskId, "telegram", "123", "msg1");
      db.createNotification(taskId, "telegram", "456", "msg2");
      expect(db.getPendingNotifications().length).toBe(2);
    });

    test("markNotificationSent updates status", () => {
      const taskId = db.createTask({ session_id: "backend--api", prompt: "test" });
      const id = db.createNotification(taskId, "telegram", "123", "msg");
      db.markNotificationSent(id);
      const notif = db.getNotification(id)!;
      expect(notif.status).toBe("sent");
      expect(notif.sent_at).toBeTruthy();
    });

    test("markNotificationFailed updates status", () => {
      const taskId = db.createTask({ session_id: "backend--api", prompt: "test" });
      const id = db.createNotification(taskId, "telegram", "123", "msg");
      db.markNotificationFailed(id);
      expect(db.getNotification(id)!.status).toBe("failed");
    });
  });

  describe("Team Operations", () => {
    test("createTeam creates team with members", () => {
      db.createAgent("frontend", "/projects/ui", "frontend--ui", "bridge--frontend--ui");
      db.createTeam("alpha", "backend", ["backend", "frontend"]);
      const team = db.getTeam("alpha");
      expect(team).not.toBeNull();
      expect(team!.lead_agent).toBe("backend");
    });

    test("getTeamMembers returns member names", () => {
      db.createTeam("alpha", "backend", ["backend", "frontend"]);
      const members = db.getTeamMembers("alpha");
      expect(members.length).toBe(2);
      expect(members).toContain("backend");
      expect(members).toContain("frontend");
    });

    test("listTeams returns all teams", () => {
      db.createTeam("alpha", "backend", ["backend"]);
      db.createTeam("beta", "backend", ["backend"]);
      expect(db.listTeams().length).toBe(2);
    });

    test("deleteTeam removes team and members", () => {
      db.createTeam("alpha", "backend", ["backend"]);
      expect(db.deleteTeam("alpha")).toBe(true);
      expect(db.getTeam("alpha")).toBeNull();
      expect(db.getTeamMembers("alpha").length).toBe(0);
    });

    test("deleteTeam returns false for nonexistent", () => {
      expect(db.deleteTeam("nope")).toBe(false);
    });
  });

  describe("Cost Summary", () => {
    test("getCostSummary returns zeroes for empty", () => {
      const cost = db.getCostSummary();
      expect(cost.total_cost_usd).toBe(0);
      expect(cost.task_count).toBe(0);
      expect(cost.avg_cost_usd).toBe(0);
    });

    test("getCostSummary calculates correctly", () => {
      const id1 = db.createTask({ session_id: "backend--api", prompt: "t1" });
      const id2 = db.createTask({ session_id: "backend--api", prompt: "t2" });
      db.updateTask(id1, { cost_usd: 1.0 });
      db.updateTask(id2, { cost_usd: 2.0 });
      const cost = db.getCostSummary();
      expect(cost.total_cost_usd).toBe(3.0);
      expect(cost.task_count).toBe(2);
      expect(cost.avg_cost_usd).toBe(1.5);
    });

    test("getCostSummary filters by session", () => {
      db.createAgent("frontend", "/projects/ui", "frontend--ui", "bridge--frontend--ui");
      const id1 = db.createTask({ session_id: "backend--api", prompt: "t1" });
      const id2 = db.createTask({ session_id: "frontend--ui", prompt: "t2" });
      db.updateTask(id1, { cost_usd: 1.0 });
      db.updateTask(id2, { cost_usd: 2.0 });
      const cost = db.getCostSummary("backend--api");
      expect(cost.total_cost_usd).toBe(1.0);
      expect(cost.task_count).toBe(1);
    });
  });
});
