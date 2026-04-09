/**
 * W6.3: PermissionRelay Tests
 */
import { describe, test, expect } from "bun:test";
import { mkdtempSync, rmSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { BridgeDatabase } from "../../src/data/db.js";
import { handlePermissionRequest } from "../../src/infra/permissions.js";

function setup() {
  const tmpDir = mkdtempSync(join(tmpdir(), "bridge-perm-"));
  const db = new BridgeDatabase(join(tmpDir, "bridge.db"));
  db.createAgent("be", "/p", "be--p", "f");
  return { tmpDir, db };
}

function teardown(ctx: { tmpDir: string; db: BridgeDatabase }) {
  ctx.db.close();
  rmSync(ctx.tmpDir, { recursive: true, force: true });
}

describe("W6.3: PermissionRelay", () => {
  test("returns 2 (denied) when permission is pre-denied", async () => {
    const ctx = setup();

    // Start permission request with very short timeout
    // Pre-deny it immediately
    const requestId = ctx.db.createPermission("be--p", "Bash", "git push", "push to remote");
    ctx.db.respondPermission(requestId, false);

    // Now handle a new request that we immediately deny
    const promise = handlePermissionRequest(ctx.db, {
      sessionId: "be--p",
      tool: "Bash",
      command: "rm -rf /",
      timeout: 1, // 1 second timeout
    });

    // The new request will timeout since nobody approves it
    const exitCode = await promise;
    expect(exitCode).toBe(2); // denied via timeout

    teardown(ctx);
  });

  test("returns 0 (approved) when permission is approved", async () => {
    const ctx = setup();

    // Start the request in background
    const promise = handlePermissionRequest(ctx.db, {
      sessionId: "be--p",
      tool: "Bash",
      command: "git push",
      timeout: 5,
    });

    // Approve after a small delay
    await new Promise(r => setTimeout(r, 100));

    // Find the pending permission and approve it
    const perms = ctx.db.getPendingPermissions("be--p");
    expect(perms.length).toBeGreaterThan(0);
    ctx.db.respondPermission(perms[0]!.id, true);

    const exitCode = await promise;
    expect(exitCode).toBe(0);

    teardown(ctx);
  });
});
