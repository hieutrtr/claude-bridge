# Wave 6: Infrastructure (W6.1-W6.4)

## W6.1: DaemonManager
- Port daemon.py (24 fns, 500 LOC)
- Platform detection (macOS/Linux)
- launchd plist generation and management
- systemd unit generation and management
- install/uninstall/start/stop/status/logs

## W6.2: BridgeCmd (session management)
- Port bridge_cmd.py (17 fns, 426 LOC) + tmux_session.py
- tmux session lifecycle (start/stop/attach/status)
- Config validation
- Process cleanup (multi-strategy: tmux → launchd → pkill)

## W6.3: PermissionRelay
- Port permission_relay.py (1 fn, 89 LOC)
- PreToolUse hook handler for dangerous command approval
- Create permission in DB, poll for response, auto-deny on timeout

## W6.4: Python removal verification
- Verify no Python subprocess calls remain in TS codebase
