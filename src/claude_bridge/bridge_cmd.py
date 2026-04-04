"""CLI entry point for bridge command — tmux session management.

Manages the Bridge Bot's tmux session lifecycle:
  bridge start    — start the bot in a tmux session (or foreground)
  bridge stop     — graceful stop
  bridge attach   — attach to the running session
  bridge logs     — tail the log file
  bridge restart  — stop + start
  bridge status   — show running/stopped + PID + uptime
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys

from . import __version__
from .tmux_session import (
    TMUX_SESSION_NAME,
    LOG_PATH,
    tmux_available,
    session_running,
    start_session,
    stop_session,
    attach_session,
    get_session_pid,
    get_session_uptime,
)

def _get_config_path() -> str:
    """Get config.json path respecting CLAUDE_BRIDGE_HOME env var."""
    from . import get_bridge_home
    return str(get_bridge_home() / "config.json")


CONFIG_PATH = _get_config_path()  # Computed at import; set CLAUDE_BRIDGE_HOME before running


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the bridge command."""
    parser = argparse.ArgumentParser(
        prog="bridge",
        description="Claude Bridge Bot session manager",
    )
    parser.add_argument("--version", action="version", version=f"claude-bridge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # start
    p = sub.add_parser("start", help="Start the Bridge Bot")
    p.add_argument("--foreground", action="store_true", help="Run in foreground (no tmux)")

    # stop
    sub.add_parser("stop", help="Stop the Bridge Bot")

    # attach
    sub.add_parser("attach", help="Attach to the running Bridge Bot session")

    # logs
    p = sub.add_parser("logs", help="Tail Bridge Bot logs")
    p.add_argument("-n", "--lines", type=int, default=50, help="Number of lines (default: 50)")
    p.add_argument("-f", "--follow", action="store_true", help="Follow log output")

    # restart
    p = sub.add_parser("restart", help="Restart the Bridge Bot")
    p.add_argument("--foreground", action="store_true", help="Run in foreground (no tmux)")

    # status
    sub.add_parser("status", help="Show Bridge Bot status")

    return parser


def _load_config(config_path: str | None = None) -> dict | None:
    """Load config from bridge home config.json. Returns None if missing/invalid.

    config_path overrides the default; if omitted, reads the module-level
    CONFIG_PATH which is computed from CLAUDE_BRIDGE_HOME / config.json.
    Tests may patch the module-level CONFIG_PATH directly.
    """
    if config_path is None:
        config_path = CONFIG_PATH  # module global — patchable in tests
    if not os.path.isfile(config_path):
        return None
    try:
        with open(config_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def _build_claude_command(config: dict) -> list[str]:
    """Build the claude CLI command based on config mode and bot_dir."""
    mode = config.get("mode", "mcp")
    bot_dir = config.get("bot_dir", "")

    cmd = ["claude"]

    if mode == "channel":
        cmd.extend([
            "--dangerously-load-development-channels", "server:bridge",
            "--dangerously-skip-permissions",
        ])
    else:
        cmd.append("--dangerously-skip-permissions")

    return cmd


def _build_expect_wrapper(claude_cmd: list[str], bot_dir: str) -> list[str]:
    """Build an expect script that auto-confirms the dev channel warning.

    The TUI prompt is not stdin-based — it uses terminal key events.
    We use expect to simulate pressing Enter on the confirmation prompt.
    """
    claude_str = ' '.join(claude_cmd)
    expect_script = f'''
set timeout -1
spawn bash -c "cd {bot_dir} && {claude_str}"
expect {{
    "Enter to confirm" {{ send "\\r" }}
    "What can I help" {{ }}
    timeout {{ }}
}}
interact
'''
    return ["expect", "-c", expect_script]


def _validate_config(config: dict | None) -> list[str]:
    """Validate bridge config and return a list of error strings (empty = OK)."""
    if config is None:
        return ["❌ Bridge not configured. Run: bridge-cli setup"]

    errors = []

    bot_dir = config.get("bot_dir")
    if not bot_dir:
        errors.append("❌ Bridge not configured (bot_dir missing). Run: bridge-cli setup")
    elif not os.path.isdir(bot_dir):
        errors.append(f"❌ bot_dir not found: {bot_dir}  →  Run: bridge-cli setup")

    token = config.get("telegram_bot_token", "")
    if not token:
        errors.append("❌ Telegram bot token missing. Run: bridge-cli setup")

    mode = config.get("mode", "")
    if mode not in ("channel", "mcp", ""):
        errors.append(f"❌ Unknown mode '{mode}'. Expected: channel or mcp")

    return errors


LAUNCHD_PLIST_PATH = os.path.expanduser("~/Library/LaunchAgents/ai.claude-bridge.plist")

# Patterns for bridge-related processes to kill on stop/uninstall
_KILL_PATTERNS = [
    "bun.*server\\.ts",
    "bun.*server\\.js",
    "claude.*dangerously-load-development-channels",
    "claude.*--channels server:bridge",
    r"bash -c .*(echo.*cat).*claude",
]


def _unload_launchd_plist() -> bool:
    """Unload the launchd plist if loaded. Returns True if unloaded, False otherwise."""
    if platform.system() != "Darwin":
        return False
    if not os.path.isfile(LAUNCHD_PLIST_PATH):
        return False
    try:
        mac_ver = platform.mac_ver()[0]
        major = int(mac_ver.split(".")[0]) if mac_ver else 0
        if major >= 12:
            uid = str(os.getuid())
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}", LAUNCHD_PLIST_PATH],
                capture_output=True,
            )
        else:
            subprocess.run(
                ["launchctl", "unload", LAUNCHD_PLIST_PATH],
                capture_output=True,
            )
        return True
    except (FileNotFoundError, OSError):
        return False


def _kill_bridge_processes() -> None:
    """Kill zombie bridge-related processes (bun server, claude channel, bash wrappers)."""
    for pattern in _KILL_PATTERNS:
        try:
            subprocess.run(
                ["pkill", "-f", pattern],
                capture_output=True,
            )
        except (FileNotFoundError, OSError):
            pass


def _bridge_processes_running() -> bool:
    """Check if any bridge-related processes are running (for daemon/foreground mode detection)."""
    for pattern in _KILL_PATTERNS:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, OSError):
            pass
    return False


def cmd_start(args) -> int:
    """Start the Bridge Bot."""
    config = _load_config()
    errors = _validate_config(config)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1

    bot_dir = config["bot_dir"]
    claude_cmd = _build_claude_command(config)

    # Foreground mode — replace current process
    if getattr(args, "foreground", False):
        os.chdir(bot_dir)
        os.execvp(claude_cmd[0], claude_cmd)
        return 1  # pragma: no cover

    # Tmux mode
    if not tmux_available():
        print("Error: tmux is not installed.", file=sys.stderr)
        print("  macOS: brew install tmux", file=sys.stderr)
        print("  Linux: sudo apt install tmux", file=sys.stderr)
        return 1

    if session_running():
        print(f"Error: Bridge Bot is already running.", file=sys.stderr)
        print(f"  Attach: bridge attach", file=sys.stderr)
        print(f"  Restart: bridge restart", file=sys.stderr)
        return 1

    # Run claude directly in tmux (tmux provides a real terminal)
    claude_str = ' '.join(claude_cmd)
    full_cmd = ["bash", "-c", f"cd {_shell_quote(bot_dir)} && {claude_str}"]

    if start_session(full_cmd):
        # Auto-confirm TUI prompts by sending Enter to tmux.
        # Claude Code shows two sequential prompts:
        #   1. "Yes, I trust this folder" (~2-3s after launch)
        #   2. "I am using this for local development" (~2-3s after first confirm)
        # Send Enter twice with delays to confirm both.
        import time
        for _ in range(2):
            time.sleep(3)
            subprocess.run(
                ["tmux", "send-keys", "-t", TMUX_SESSION_NAME, "Enter"],
                capture_output=True,
            )

        print(f"Bridge Bot started in tmux session '{TMUX_SESSION_NAME}'.")
        print()
        print(f"  Attach:  bridge attach")
        print(f"  Logs:    bridge logs -f")
        print(f"  Status:  bridge status")
        print(f"  Stop:    bridge stop")
        return 0
    else:
        print("Error: Failed to start tmux session.", file=sys.stderr)
        return 1


def cmd_stop(args) -> int:
    """Stop the Bridge Bot (tmux session, launchd daemon, and child processes)."""
    tmux_was_running = session_running() if tmux_available() else False
    launchd_unloaded = False
    had_processes = _bridge_processes_running()

    # 1. Stop tmux session if running
    if tmux_was_running:
        print("Stopping Bridge Bot tmux session...")
        if not stop_session():
            print("Warning: Failed to stop tmux session.", file=sys.stderr)

    # 2. Unload launchd plist if on macOS
    launchd_unloaded = _unload_launchd_plist()
    if launchd_unloaded:
        print("Unloaded launchd daemon.")

    # 3. Kill zombie bridge processes
    _kill_bridge_processes()

    if tmux_was_running or launchd_unloaded or had_processes:
        print("Bridge Bot stopped.")
        return 0
    else:
        print("Bridge Bot is not running.", file=sys.stderr)
        print("  Start: bridge start", file=sys.stderr)
        return 1


def cmd_attach(args) -> int:
    """Attach to the running Bridge Bot session (tmux or log tail fallback)."""
    # 1. If tmux session exists, attach to it
    if tmux_available() and session_running():
        return attach_session()

    # 2. If no tmux but daemon/processes running, tail the log file
    if _bridge_processes_running():
        if os.path.isfile(LOG_PATH):
            print(f"Bridge Bot running in daemon mode. Showing logs (read-only):")
            print(f"  (Press Ctrl+C to detach)\n")
            os.execvp("tail", ["tail", "-n50", "-f", LOG_PATH])
            return 1  # pragma: no cover
        else:
            print("Bridge Bot is running in daemon mode but no log file found.", file=sys.stderr)
            print(f"  Expected: {LOG_PATH}", file=sys.stderr)
            return 1

    # 3. Nothing running
    print("Bridge Bot is not running.", file=sys.stderr)
    print("  Start: bridge start", file=sys.stderr)
    return 1


def cmd_logs(args) -> int:
    """Tail Bridge Bot logs."""
    if not os.path.isfile(LOG_PATH):
        print("No log file found. Start the Bridge Bot first.", file=sys.stderr)
        print(f"  Expected: {LOG_PATH}", file=sys.stderr)
        return 1

    lines = getattr(args, "lines", 50)
    follow = getattr(args, "follow", False)

    tail_cmd = ["tail", f"-n{lines}"]
    if follow:
        tail_cmd.append("-f")
    tail_cmd.append(LOG_PATH)

    os.execvp("tail", tail_cmd)
    return 1  # pragma: no cover


def cmd_restart(args) -> int:
    """Restart the Bridge Bot (stop + start)."""
    tmux_running = session_running() if tmux_available() else False
    if tmux_running or _bridge_processes_running():
        cmd_stop(args)

    return cmd_start(args)


def cmd_status(args) -> int:
    """Show Bridge Bot status."""
    running = session_running() if tmux_available() else False

    if running:
        pid = get_session_pid()
        uptime = get_session_uptime()
        print(f"Bridge Bot: running")
        if pid:
            print(f"  PID:     {pid}")
        if uptime:
            print(f"  Uptime:  {uptime}")
        print(f"  Session: {TMUX_SESSION_NAME}")
        print(f"  Log:     {LOG_PATH}")
    else:
        print(f"Bridge Bot: stopped")
        print(f"  Start:   bridge start")

    # Show config info
    config = _load_config()
    if config:
        mode = config.get("mode", "mcp")
        bot_dir = config.get("bot_dir", "(not set)")
        print(f"  Mode:    {mode}")
        print(f"  Bot dir: {bot_dir}")
    else:
        print(f"  Config:  not found (run 'bridge-cli setup')")

    return 0


def _shell_quote(s: str) -> str:
    """Shell-quote a string."""
    if s and not any(c in s for c in " \t\n\"'\\$`!#&|;(){}[]<>?*~"):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "attach": cmd_attach,
    "logs": cmd_logs,
    "restart": cmd_restart,
    "status": cmd_status,
}


def main():
    """Entry point for the bridge command."""
    parser = build_parser()
    args = parser.parse_args()

    handler = COMMANDS.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
