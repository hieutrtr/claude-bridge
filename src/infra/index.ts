/**
 * Infrastructure Layer — daemon, session management, permissions.
 */

export {
  getPlatform,
  installDaemon,
  uninstallDaemon,
  startDaemon,
  stopDaemon,
  getDaemonStatus,
  isDaemonInstalled,
  getServiceName,
  getLaunchdLabel,
} from "./daemon.js";

export {
  getSessionName,
  getLogPath,
  tmuxAvailable,
  sessionRunning,
  startSession,
  stopSession,
  getSessionPid,
  getSessionUptime,
  validateConfig,
  killBridgeProcesses,
  bridgeProcessesRunning,
} from "./bridge-cmd.js";

export { handlePermissionRequest, main as permissionRelayMain } from "./permissions.js";

export { StartupOrchestrator } from "./startup.js";
