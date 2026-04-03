"""Tmux session management for claude-bridge.

Pure functions for managing the Bridge Bot's tmux session lifecycle.
All tmux interaction via subprocess calls — stdlib only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

TMUX_SESSION_NAME = "claude-bridge"


def _get_log_path() -> str:
    """Get log path respecting CLAUDE_BRIDGE_HOME env var."""
    from . import get_bridge_home
    return str(get_bridge_home() / "bridge-bot.log")


LOG_PATH = _get_log_path()


def tmux_available() -> bool:
    """Check if tmux is installed."""
    return shutil.which("tmux") is not None


def session_running(name: str = TMUX_SESSION_NAME) -> bool:
    """Check if a tmux session with the given name exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def start_session(
    command: list[str],
    name: str = TMUX_SESSION_NAME,
    log_path: str = LOG_PATH,
) -> bool:
    """Start a new tmux session running the given command.

    Pipes pane output to log_path for offline log tailing.
    Returns True if session was started, False if already running.
    """
    if session_running(name):
        return False

    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    # Create detached session with the command
    shell_cmd = " ".join(_quote_arg(a) for a in command)
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, shell_cmd],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False

    # Enable pipe-pane for log capture
    subprocess.run(
        ["tmux", "pipe-pane", "-t", name, f"cat >> {log_path}"],
        capture_output=True,
        text=True,
    )

    return True


def stop_session(name: str = TMUX_SESSION_NAME, timeout: float = 5.0) -> bool:
    """Stop a tmux session gracefully.

    Sends C-c first, waits up to timeout seconds, then kills if still alive.
    Returns True if session was stopped, False if not running.
    """
    if not session_running(name):
        return False

    # Send C-c for graceful shutdown
    subprocess.run(
        ["tmux", "send-keys", "-t", name, "C-c", ""],
        capture_output=True,
        text=True,
    )

    # Wait for process to exit
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not session_running(name):
            return True
        time.sleep(0.5)

    # Force kill if still alive
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        capture_output=True,
        text=True,
    )
    return True


def attach_session(name: str = TMUX_SESSION_NAME) -> int:
    """Attach to an existing tmux session.

    Replaces the current process with tmux attach.
    Returns 1 if session is not running (exec failed or session missing).
    """
    if not session_running(name):
        return 1
    os.execvp("tmux", ["tmux", "attach-session", "-t", name])
    # execvp never returns on success
    return 1  # pragma: no cover


def get_session_pid(name: str = TMUX_SESSION_NAME) -> int | None:
    """Get the PID of the main pane process in the tmux session."""
    if not session_running(name):
        return None
    result = subprocess.run(
        ["tmux", "list-panes", "-t", name, "-F", "#{pane_pid}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        return int(result.stdout.strip().splitlines()[0])
    except ValueError:
        return None


def get_session_uptime(name: str = TMUX_SESSION_NAME) -> str | None:
    """Get human-readable uptime of the tmux session.

    Returns a string like '2h 15m' or '3d 1h', or None if not running.
    """
    if not session_running(name):
        return None
    result = subprocess.run(
        ["tmux", "display-message", "-t", name, "-p", "#{session_created}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        created = int(result.stdout.strip())
    except ValueError:
        return None

    elapsed = int(time.time()) - created
    return _format_duration(elapsed)


def _format_duration(seconds: int) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining_min = minutes % 60
    if hours < 24:
        if remaining_min:
            return f"{hours}h {remaining_min}m"
        return f"{hours}h"
    days = hours // 24
    remaining_hours = hours % 24
    if remaining_hours:
        return f"{days}d {remaining_hours}h"
    return f"{days}d"


def _quote_arg(arg: str) -> str:
    """Shell-quote an argument if it contains special characters."""
    if arg and not any(c in arg for c in " \t\n\"'\\$`!#&|;(){}[]<>?*~"):
        return arg
    return "'" + arg.replace("'", "'\\''") + "'"
