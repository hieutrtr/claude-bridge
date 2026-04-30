/**
 * Permission Relay — PreToolUse hook handler for dangerous command approval.
 *
 * Creates permission request in DB, polls for response, auto-denies on timeout.
 * Matches Python permission_relay.py behavior.
 *
 * Exit codes: 0 = approved, 2 = denied/timeout
 */

import type { IDatabase } from "../data/interfaces.js";

const DEFAULT_TIMEOUT = 300; // 5 minutes
const POLL_INTERVAL = 2000; // 2 seconds

export interface PermissionRequest {
  sessionId: string;
  tool?: string;
  command?: string;
  description?: string;
  timeout?: number;
}

export async function handlePermissionRequest(
  db: IDatabase,
  request: PermissionRequest,
): Promise<number> {
  const timeout = request.timeout ?? DEFAULT_TIMEOUT;

  // Create permission record
  const requestId = crypto.randomUUID().slice(0, 8);
  db.createPermission(
    requestId,
    request.sessionId,
    request.tool ?? "unknown",
    request.command ?? "",
    request.description ?? "",
  );

  process.stdout.write(
    `Permission request ${requestId}: ${request.tool} — ${request.command}\n`,
  );

  // Poll for response
  const deadline = Date.now() + timeout * 1000;

  while (Date.now() < deadline) {
    const perm = db.getPermission(requestId);
    if (!perm) return 2; // not found → deny

    if (perm.status === "approved") return 0;
    if (perm.status === "denied") return 2;

    // Still pending — wait
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL));
  }

  // Timeout → auto-deny
  db.respondPermission(requestId, false);
  return 2;
}

export async function main(db: IDatabase, argv?: string[]): Promise<number> {
  const args = argv ?? process.argv.slice(2);

  let sessionId = "";
  let tool = "";
  let command = "";
  let description = "";
  let timeout = DEFAULT_TIMEOUT;

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--session-id": sessionId = args[++i] ?? ""; break;
      case "--tool": tool = args[++i] ?? ""; break;
      case "--command": command = args[++i] ?? ""; break;
      case "--description": description = args[++i] ?? ""; break;
      case "--timeout": timeout = parseInt(args[++i] ?? "300", 10); break;
    }
  }

  if (!sessionId) {
    process.stderr.write("Error: --session-id required\n");
    return 1;
  }

  return handlePermissionRequest(db, { sessionId, tool, command, description, timeout });
}
