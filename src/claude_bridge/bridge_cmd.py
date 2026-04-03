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
import shutil
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

CONFIG_PATH = os.path.expanduser("~/.claude-bridge/config.json")


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


def _load_config() -> dict | None:
    """Load config from ~/.claude-bridge/config.json. Returns None if missing/invalid."""
    if not os.path.isfile(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
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


def cmd_start(args) -> int:
    """Start the Bridge Bot."""
    config = _load_config()
    if not config:
        print("Error: No config found. Run 'bridge-cli setup' first.", file=sys.stderr)
        return 1

    bot_dir = config.get("bot_dir")
    if not bot_dir or not os.path.isdir(bot_dir):
        print(f"Error: Bot directory not found: {bot_dir}", file=sys.stderr)
        print("Run 'bridge-cli setup' to configure.", file=sys.stderr)
        return 1

    claude_cmd = _build_claude_command(config)

    # Foreground mode — replace process
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

    # Build the full command: cd bot_dir && claude ...
    full_cmd = ["bash", "-c", f"cd {_shell_quote(bot_dir)} && {' '.join(claude_cmd)}"]

    if start_session(full_cmd):
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
    """Stop the Bridge Bot."""
    if not session_running():
        print("Bridge Bot is not running.", file=sys.stderr)
        print("  Start: bridge start", file=sys.stderr)
        return 1

    print("Stopping Bridge Bot...")
    if stop_session():
        print("Bridge Bot stopped.")
        return 0
    else:
        print("Error: Failed to stop Bridge Bot.", file=sys.stderr)
        return 1


def cmd_attach(args) -> int:
    """Attach to the running Bridge Bot session."""
    if not tmux_available():
        print("Error: tmux is not installed.", file=sys.stderr)
        return 1

    if not session_running():
        print("Bridge Bot is not running.", file=sys.stderr)
        print("  Start: bridge start", file=sys.stderr)
        return 1

    return attach_session()


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
    if session_running():
        print("Stopping Bridge Bot...")
        stop_session()
        print("Stopped.")

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
