"""Daemon install/management for Claude Bridge.

Supports systemd (Linux) and launchd (macOS) for background service management.
Also supports a tmux fallback for systems without systemd/launchd.

Usage:
    bridge-cli daemon install   — install system service
    bridge-cli daemon start     — start service
    bridge-cli daemon stop      — stop service
    bridge-cli daemon status    — show service status
    bridge-cli daemon logs      — show recent log lines
    bridge-cli daemon uninstall — remove service files
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


SYSTEMD_SERVICE_NAME = "claude-bridge"
LAUNCHD_LABEL = "ai.claude-bridge"


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def get_platform() -> str:
    """Return 'linux', 'macos', or 'other'."""
    s = platform.system()
    if s == "Linux":
        return "linux"
    if s == "Darwin":
        return "macos"
    return "other"


def is_container_environment() -> bool:
    """Detect if running inside a container (Docker, LXC) without a systemd user session.

    Returns True if systemd --user is likely unavailable.
    """
    # Check for Docker/container markers
    if os.path.exists("/.dockerenv"):
        return True
    # No D-Bus session bus → systemctl --user will fail
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        # Also check if PID 1 is systemd (if not, likely a container)
        try:
            with open("/proc/1/comm") as f:
                init_name = f.read().strip()
            if init_name not in ("systemd", "init"):
                return True
        except OSError:
            pass
    return False


def _get_bridge_cmd() -> str:
    """Return the bridge command path (bridge binary or python -m invocation)."""
    bridge = shutil.which("bridge")
    if bridge:
        return bridge
    # Fall back to python module
    return f"{sys.executable} -m claude_bridge.bridge_cmd"


# ---------------------------------------------------------------------------
# systemd (Linux)
# ---------------------------------------------------------------------------

SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=Claude Bridge Bot
After=network.target

[Service]
Type=simple
ExecStart={bridge_cmd} start --foreground
Restart=on-failure
RestartSec=10
StandardOutput=append:{log_path}
StandardError=append:{log_path}
Environment="CLAUDE_BRIDGE_HOME={bridge_home}"
Environment="PATH={path}"
WorkingDirectory={bot_dir}

[Install]
WantedBy=default.target
"""


def _systemd_unit_path() -> Path:
    """~/.config/systemd/user/claude-bridge.service"""
    return Path.home() / ".config" / "systemd" / "user" / f"{SYSTEMD_SERVICE_NAME}.service"


def install_systemd(bot_dir: str, bridge_home: str, log_path: str) -> tuple[bool, str]:
    """Install the systemd user service. Returns (success, message)."""
    # Detect container environments where systemd --user is unavailable
    if is_container_environment():
        return False, (
            "Container environment detected (no systemd user session). "
            "systemctl --user requires a D-Bus session bus which is not available in Docker/LXC. "
            "Alternatives: use 'bridge start' in a persistent shell, or add a cron job with 'bridge-cli setup-cron'."
        )

    unit_path = _systemd_unit_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)

    bridge_cmd = _get_bridge_cmd()
    # Include current PATH so pipx/local bin directories are accessible in the service
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    content = SYSTEMD_UNIT_TEMPLATE.format(
        bridge_cmd=bridge_cmd,
        log_path=log_path,
        bridge_home=bridge_home,
        bot_dir=bot_dir,
        path=path_env,
    )
    unit_path.write_text(content)

    # Reload systemd and enable
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True, check=True,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", SYSTEMD_SERVICE_NAME],
            capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return False, (
            f"systemctl error: {e}. "
            "If running in a container or SSH session without D-Bus, systemd user services "
            "are unavailable. Use 'bridge start' instead, or install a cron job with "
            "'bridge-cli setup-cron'."
        )

    return True, str(unit_path)


def uninstall_systemd() -> tuple[bool, str]:
    """Remove the systemd user service. Returns (success, message)."""
    unit_path = _systemd_unit_path()
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", SYSTEMD_SERVICE_NAME],
            capture_output=True,
        )
        subprocess.run(
            ["systemctl", "--user", "disable", SYSTEMD_SERVICE_NAME],
            capture_output=True,
        )
    except FileNotFoundError:
        pass

    if unit_path.exists():
        unit_path.unlink()
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        except FileNotFoundError:
            pass
        return True, str(unit_path)
    return False, "Service file not found"


def start_systemd() -> tuple[bool, str]:
    """Start the systemd service."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "start", SYSTEMD_SERVICE_NAME],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return True, "Started"
        return False, r.stderr.strip()
    except FileNotFoundError:
        return False, "systemctl not found"


def stop_systemd() -> tuple[bool, str]:
    """Stop the systemd service."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "stop", SYSTEMD_SERVICE_NAME],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return True, "Stopped"
        return False, r.stderr.strip()
    except FileNotFoundError:
        return False, "systemctl not found"


def status_systemd() -> str:
    """Get systemd service status as a string."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", SYSTEMD_SERVICE_NAME],
            capture_output=True, text=True,
        )
        active = r.stdout.strip()  # 'active', 'inactive', 'failed', etc.
        r2 = subprocess.run(
            ["systemctl", "--user", "is-enabled", SYSTEMD_SERVICE_NAME],
            capture_output=True, text=True,
        )
        enabled = r2.stdout.strip()  # 'enabled', 'disabled', etc.
        return f"{active} (enabled: {enabled})"
    except FileNotFoundError:
        return "systemctl not found"


# ---------------------------------------------------------------------------
# launchd (macOS)
# ---------------------------------------------------------------------------

LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        {program_args}
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>CLAUDE_BRIDGE_HOME</key>
        <string>{bridge_home}</string>
        <key>PATH</key>
        <string>{path}</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>{bot_dir}</string>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def _launchd_plist_path() -> Path:
    """~/Library/LaunchAgents/ai.claude-bridge.plist"""
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install_launchd(bot_dir: str, bridge_home: str, log_path: str) -> tuple[bool, str]:
    """Install the launchd agent plist. Returns (success, message)."""
    plist_path = _launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    # Build ProgramArguments XML entries
    bridge = shutil.which("bridge")
    if bridge:
        args = [bridge, "start", "--foreground"]
    else:
        args = [sys.executable, "-m", "claude_bridge.bridge_cmd", "start", "--foreground"]

    program_args = "\n        ".join(f"<string>{a}</string>" for a in args)
    path_env = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")

    content = LAUNCHD_PLIST_TEMPLATE.format(
        label=LAUNCHD_LABEL,
        program_args=program_args,
        bridge_home=bridge_home,
        path=path_env,
        bot_dir=bot_dir,
        log_path=log_path,
    )
    plist_path.write_text(content)

    # Load into launchd
    # macOS 12+ (Monterey+): use `launchctl bootstrap` (preferred over deprecated `load`)
    # macOS 11 and earlier: use `launchctl load` (bootstrap may not be available)
    try:
        mac_ver = platform.mac_ver()[0]  # e.g. "14.2.0" or "" on non-macOS
        major = int(mac_ver.split(".")[0]) if mac_ver else 0
        if major >= 12:
            # bootstrap target: gui/<uid>
            uid = str(os.getuid())
            subprocess.run(
                ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
                capture_output=True, check=True,
            )
        else:
            subprocess.run(
                ["launchctl", "load", str(plist_path)],
                capture_output=True, check=True,
            )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        return False, f"launchctl error: {e}"

    return True, str(plist_path)


def uninstall_launchd() -> tuple[bool, str]:
    """Remove the launchd agent plist. Returns (success, message)."""
    plist_path = _launchd_plist_path()
    try:
        mac_ver = platform.mac_ver()[0]
        major = int(mac_ver.split(".")[0]) if mac_ver else 0
        if major >= 12:
            uid = str(os.getuid())
            subprocess.run(
                ["launchctl", "bootout", f"gui/{uid}", str(plist_path)],
                capture_output=True,
            )
        else:
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
            )
    except FileNotFoundError:
        pass

    if plist_path.exists():
        plist_path.unlink()
        return True, str(plist_path)
    return False, "Plist file not found"


def start_launchd() -> tuple[bool, str]:
    """Start the launchd agent."""
    try:
        r = subprocess.run(
            ["launchctl", "start", LAUNCHD_LABEL],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return True, "Started"
        return False, r.stderr.strip()
    except FileNotFoundError:
        return False, "launchctl not found"


def stop_launchd() -> tuple[bool, str]:
    """Stop the launchd agent."""
    try:
        r = subprocess.run(
            ["launchctl", "stop", LAUNCHD_LABEL],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            return True, "Stopped"
        return False, r.stderr.strip()
    except FileNotFoundError:
        return False, "launchctl not found"


def status_launchd() -> str:
    """Get launchd agent status as a string."""
    try:
        r = subprocess.run(
            ["launchctl", "list", LAUNCHD_LABEL],
            capture_output=True, text=True,
        )
        if r.returncode == 0:
            # Output: PID  Status  Label
            parts = r.stdout.strip().split()
            if parts:
                pid = parts[0]
                status_code = parts[1] if len(parts) > 1 else "?"
                if pid != "-":
                    return f"running (PID {pid})"
                else:
                    return f"stopped (last exit: {status_code})"
        return "not loaded"
    except FileNotFoundError:
        return "launchctl not found"


# ---------------------------------------------------------------------------
# Public install/control API
# ---------------------------------------------------------------------------

def install_daemon(
    bot_dir: str,
    bridge_home: str,
    log_path: str,
) -> tuple[bool, str]:
    """Install daemon for current platform. Returns (success, message)."""
    plat = get_platform()
    if plat == "linux":
        return install_systemd(bot_dir, bridge_home, log_path)
    elif plat == "macos":
        return install_launchd(bot_dir, bridge_home, log_path)
    else:
        return False, f"Unsupported platform: {platform.system()}"


def uninstall_daemon() -> tuple[bool, str]:
    """Uninstall daemon for current platform."""
    plat = get_platform()
    if plat == "linux":
        return uninstall_systemd()
    elif plat == "macos":
        return uninstall_launchd()
    else:
        return False, f"Unsupported platform: {platform.system()}"


def start_daemon() -> tuple[bool, str]:
    """Start daemon for current platform."""
    plat = get_platform()
    if plat == "linux":
        return start_systemd()
    elif plat == "macos":
        return start_launchd()
    else:
        return False, f"Unsupported platform: {platform.system()}"


def stop_daemon() -> tuple[bool, str]:
    """Stop daemon for current platform."""
    plat = get_platform()
    if plat == "linux":
        return stop_systemd()
    elif plat == "macos":
        return stop_launchd()
    else:
        return False, f"Unsupported platform: {platform.system()}"


def get_daemon_status() -> str:
    """Get daemon status string for current platform."""
    plat = get_platform()
    if plat == "linux":
        return status_systemd()
    elif plat == "macos":
        return status_launchd()
    else:
        return f"unsupported platform ({platform.system()})"


def is_daemon_installed() -> bool:
    """Check if daemon service file exists for current platform."""
    plat = get_platform()
    if plat == "linux":
        return _systemd_unit_path().exists()
    elif plat == "macos":
        return _launchd_plist_path().exists()
    return False


def get_daemon_file_path() -> Path | None:
    """Return path to service file, or None if not installed."""
    plat = get_platform()
    if plat == "linux":
        p = _systemd_unit_path()
    elif plat == "macos":
        p = _launchd_plist_path()
    else:
        return None
    return p if p.exists() else None
