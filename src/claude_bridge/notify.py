"""Task completion notification delivery."""

from __future__ import annotations

import json
import os
from datetime import datetime
from urllib.request import urlopen, Request

from .db import BridgeDB


def get_default_telegram_chat_id() -> str | None:
    """Get the default Telegram chat_id from bridge config."""
    from . import get_bridge_home
    config_path = str(get_bridge_home() / "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
            chat_id = config.get("telegram_chat_id")
            if chat_id:
                return str(chat_id)
        except (json.JSONDecodeError, IOError):
            pass

    # Fallback: read from official plugin access.json (legacy)
    access_path = os.path.expanduser("~/.claude/channels/telegram/access.json")
    if os.path.isfile(access_path):
        try:
            with open(access_path) as f:
                access = json.load(f)
            allowed = access.get("allowFrom", [])
            return allowed[0] if allowed else None
        except (json.JSONDecodeError, IOError, IndexError):
            pass

    return None


def get_default_channel() -> tuple[str, str | None]:
    """Get default notification channel and chat_id. Returns (channel, chat_id)."""
    if get_bot_token():
        chat_id = get_default_telegram_chat_id()
        if chat_id:
            return "telegram", chat_id
    return "cli", None


def get_bot_token() -> str | None:
    """Get Telegram bot token from environment or config."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token

    # Read from bridge config
    from . import get_bridge_home
    config_path = str(get_bridge_home() / "config.json")
    if os.path.isfile(config_path):
        try:
            with open(config_path) as f:
                config = json.load(f)
            return config.get("telegram_bot_token")
        except (json.JSONDecodeError, IOError):
            pass

    return None


def format_completion_message(task, agent_name: str) -> str:
    """Format a task completion message for notification."""
    task_id = task["id"]
    status = task["status"]
    prompt = task["prompt"][:80].split("\n")[0]
    task_type = task["task_type"] or "standard"

    duration = ""
    if task["duration_ms"]:
        mins = task["duration_ms"] // 60000
        secs = (task["duration_ms"] % 60000) // 1000
        duration = f"{mins}m {secs}s"

    cost = f"${task['cost_usd']:.3f}" if task["cost_usd"] else ""

    if status == "done":
        icon = "🏁" if task_type == "team" else "✓"
        lines = [f"{icon} Task #{task_id} ({agent_name}) — done"]
        if duration:
            lines[0] += f" in {duration}"
        summary = task["result_summary"] or ""
        if summary:
            lines.append(summary[:200])
        if cost:
            lines.append(f"Cost: {cost}")
    else:
        lines = [f"✗ Task #{task_id} ({agent_name}) — {status}"]
        if duration:
            lines[0] += f" after {duration}"
        error = task["error_message"] or ""
        if error:
            lines.append(f"Error: {error[:200]}")
        if cost:
            lines.append(f"Cost: {cost}")

    return "\n".join(lines)


def send_telegram(bot_token: str, chat_id: str, message: str) -> bool:
    """Send a message via Telegram Bot API. Returns True on success."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            body = resp.read()
            result = json.loads(body)
            return result.get("ok", False)
    except Exception:
        return False


def deliver_notification(db: BridgeDB, notification_id: int) -> bool:
    """Attempt to deliver a notification. Returns True on success."""
    notif = db.get_notification(notification_id)
    if not notif or notif["status"] != "pending":
        return False

    channel = notif["channel"]
    if channel == "telegram":
        token = get_bot_token()
        if not token:
            return False
        success = send_telegram(token, notif["chat_id"], notif["message"])
    else:
        # Other channels not yet implemented
        return False

    if success:
        db.mark_notification_sent(notification_id)
    return success
