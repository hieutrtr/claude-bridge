/**
 * Extra coverage tests for src/infra/permissions.ts
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";
import { handlePermissionRequest, main } from "../../src/infra/permissions.js";

function setup() {
  const tmpDir = mkdtempSync(join(tmpdir(), "bridge-perm-cov-"));
  const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  db.createAgent("be", "/p", "be--p", "f");
  return { tmpDir, db };
}

function teardown(ctx: { tmpDir: string; db: BridgeDatabase }) {
  ctx.db.close();
  rmSync(ctx.tmpDir, { recursive: true, force: true });
}

describe("permissions.ts coverage", () => {
  test("handlePermissionRequest uses defaults for missing fields", async () => {
    const ctx = setup();

    // Request with no optional fields — exercises default branches
    const promise = handlePermissionRequest(ctx.db, {
      sessionId: "be--p",
      timeout: 1,
    });

    const exitCode = await promise;
    expect(exitCode).toBe(2); // timeout → deny

    teardown(ctx);
  });

  test("handlePermissionRequest returns 2 when permission not found", async () => {
    const ctx = setup();

    // Override getPermission to return null
    const origGet = ctx.db.getPermission.bind(ctx.db);
    let callCount = 0;
    ctx.db.getPermission = (id: string) => {
      callCount++;
      if (callCount === 1) return null; // first poll → not found
      return origGet(id);
    };

    const exitCode = await handlePermissionRequest(ctx.db, {
      sessionId: "be--p",
      tool: "Bash",
      command: "test",
      timeout: 2,
    });

    expect(exitCode).toBe(2);
    teardown(ctx);
  });

  test("handlePermissionRequest returns 2 when denied", async () => {
    const ctx = setup();

    const promise = handlePermissionRequest(ctx.db, {
      sessionId: "be--p",
      tool: "Bash",
      command: "rm -rf /",
      description: "dangerous",
      timeout: 5,
    });

    // Deny after small delay
    await new Promise((r) => setTimeout(r, 100));
    const perms = ctx.db.getPendingPermissions("be--p");
    expect(perms.length).toBeGreaterThan(0);
    ctx.db.respondPermission(perms[0]!.id, false);

    const exitCode = await promise;
    expect(exitCode).toBe(2);

    teardown(ctx);
  });

  test("main() returns 1 when --session-id is missing", async () => {
    const ctx = setup();
    const exitCode = await main(ctx.db, ["--tool", "Bash"]);
    expect(exitCode).toBe(1);
    teardown(ctx);
  });

  test("main() calls handlePermissionRequest with parsed args", async () => {
    const ctx = setup();
    const exitCode = await main(ctx.db, [
      "--session-id", "be--p",
      "--tool", "Bash",
      "--command", "ls",
      "--description", "list files",
      "--timeout", "1",
    ]);
    // Will timeout since nobody approves
    expect(exitCode).toBe(2);
    teardown(ctx);
  });

  test("main() uses default argv when none provided", async () => {
    const ctx = setup();
    // Save and set process.argv
    const saved = process.argv;
    process.argv = ["bun", "test", "--session-id", "be--p", "--timeout", "1"];
    const exitCode = await main(ctx.db);
    process.argv = saved;
    expect(exitCode).toBe(2);
    teardown(ctx);
  });
});
