/**
 * W3.4: ProcessWatcher Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { ProcessWatcher } from "../../src/execution/watcher.js";
import { BridgeDatabase } from "../../src/data/db.js";

function setup() {
  const tmpDir = mkdtempSync(join(tmpdir(), "bridge-watcher-"));
  const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  const watcher = new ProcessWatcher(tmpDir, db);
  return { tmpDir, db, watcher };
}

function teardown(ctx: { tmpDir: string; db: BridgeDatabase; watcher: ProcessWatcher }) {
  ctx.watcher.stop();
  ctx.db.close();
  rmSync(ctx.tmpDir, { recursive: true, force: true });
}

describe("W3.4: ProcessWatcher", () => {
  test("checkOnce marks dead processes as failed", async () => {
    const ctx = setup();
    ctx.db.createAgent("be", "/p", "be--p", "f");
    const taskId = ctx.db.createTask({ session_id: "be--p", prompt: "test" });
    ctx.db.updateTask(taskId, { status: "running", pid: 999999 });

    await ctx.watcher.checkOnce();

    const task = ctx.db.getTask(taskId)!;
    expect(task.status).toBe("failed");
    expect(task.error_message).toContain("Process");
    teardown(ctx);
  });

  test("checkOnce does not touch running processes", async () => {
    const ctx = setup();
    ctx.db.createAgent("be", "/p", "be--p", "f");
    const taskId = ctx.db.createTask({ session_id: "be--p", prompt: "test" });
    ctx.db.updateTask(taskId, { status: "running", pid: process.pid });

    await ctx.watcher.checkOnce();

    expect(ctx.db.getTask(taskId)!.status).toBe("running");
    teardown(ctx);
  });

  test("checkOnce handles timeout for dead process", async () => {
    const ctx = setup();
    ctx.db.createAgent("be", "/p", "be--p", "f");
    const taskId = ctx.db.createTask({ session_id: "be--p", prompt: "test" });
    const longAgo = new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString();
    // Use a dead PID so the watcher doesn't try to SIGTERM the test process
    ctx.db.updateTask(taskId, { status: "running", pid: 999998, started_at: longAgo });

    await ctx.watcher.checkOnce(360);

    // Dead PID + old started_at → could be either failed or timeout
    const task = ctx.db.getTask(taskId)!;
    expect(["failed", "timeout"]).toContain(task.status);
    teardown(ctx);
  });

  test("checkOnce detects timed-out alive processes", async () => {
    const ctx = setup();
    ctx.db.createAgent("be", "/p", "be--p", "f");
    const taskId = ctx.db.createTask({ session_id: "be--p", prompt: "test" });
    // Spawn a real sleep process so we have an alive PID that's not self
    const proc = Bun.spawn(["sleep", "60"], { stdout: "ignore", stderr: "ignore" });
    const longAgo = new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString();
    ctx.db.updateTask(taskId, { status: "running", pid: proc.pid, started_at: longAgo });

    await ctx.watcher.checkOnce(360);

    const task = ctx.db.getTask(taskId)!;
    expect(task.status).toBe("timeout");
    // Clean up the process
    try { process.kill(proc.pid, "SIGKILL"); } catch { /* ok */ }
    teardown(ctx);
  });
});
