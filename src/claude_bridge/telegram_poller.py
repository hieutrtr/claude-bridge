"""Telegram poller — polls getUpdates and sends outbound messages.

Runs as a background thread inside the Bridge MCP server.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from urllib.request import urlopen, Request

from .message_db import MessageDB


def parse_updates(raw: dict) -> list[dict]:
    """Parse Telegram getUpdates response into normalized messages."""
    if not raw.get("ok"):
        return []
    results = []
    for update in raw.get("result", []):
        msg = update.get("message", {})
        text = msg.get("text")
        if not text:
            continue
        chat = msg.get("chat", {})
        from_user = msg.get("from", {})
        results.append({
            "update_id": update["update_id"],
            "chat_id": str(chat.get("id", "")),
            "user_id": str(from_user.get("id", "")),
            "username": from_user.get("username", ""),
            "text": text,
            "message_id": str(msg.get("message_id", "")),
        })
    return results


def is_allowed_user(
    user_id: str,
    access_path: str = os.path.expanduser("~/.claude/channels/telegram/access.json"),
) -> bool:
    """Check if user_id is in the Telegram access allowlist."""
    if not os.path.isfile(access_path):
        return True  # no access file = permissive
    try:
        with open(access_path) as f:
            access = json.load(f)
        allowed = access.get("allowFrom", [])
        if not allowed:
            return True  # empty list = allow all
        return user_id in allowed
    except (json.JSONDecodeError, IOError):
        return True


def telegram_get_updates(
    token: str, offset: int = 0, timeout: int = 30,
) -> tuple[list[dict], dict]:
    """Call Telegram getUpdates. Returns (parsed_updates, raw_response)."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"offset": offset, "timeout": timeout}
    payload = json.dumps(params).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout + 10) as resp:
            raw = json.loads(resp.read())
        return parse_updates(raw), raw
    except Exception as e:
        print(f"[poller] getUpdates error: {e}", file=sys.stderr)
        return [], {}


def telegram_send_message(token: str, chat_id: str, text: str) -> bool:
    """Send a message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"[poller] sendMessage error: {e}", file=sys.stderr)
        return False


class TelegramPoller:
    """Polls Telegram and processes inbound/outbound messages."""

    def __init__(self, token: str, msg_db: MessageDB):
        self.token = token
        self._main_msg_db = msg_db  # kept for reference, not used in thread
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        """Start polling in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the poller thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self):
        """Main polling loop."""
        self.msg_db = MessageDB()  # create connection in this thread
        try:
            while self._running:
                try:
                    self.poll_once()
                except Exception as e:
                    print(f"[poller] error in poll cycle: {e}", file=sys.stderr)
                    time.sleep(5)
        finally:
            self.msg_db.close()

    def poll_once(self):
        """Run one poll cycle: fetch updates + send outbound."""
        # Get current offset
        offset_str = self.msg_db.get_state("telegram_offset")
        offset = int(offset_str) if offset_str else 0

        # Poll for inbound
        updates, raw = telegram_get_updates(self.token, offset=offset, timeout=1)
        for update in updates:
            if not is_allowed_user(update["user_id"]):
                print(f"[poller] rejected message from non-allowed user {update['user_id']}", file=sys.stderr)
                # Still advance offset
            else:
                self.msg_db.create_inbound(
                    platform="telegram",
                    chat_id=update["chat_id"],
                    user_id=update["user_id"],
                    message_text=update["text"],
                    message_id=update["message_id"],
                    username=update["username"],
                )

            # Advance offset past this update
            new_offset = update["update_id"] + 1
            self.msg_db.set_state("telegram_offset", str(new_offset))

        # Retry unacknowledged inbound messages (delivered but not acknowledged after 3s)
        unacked = self.msg_db.get_unacknowledged_inbound(timeout_seconds=3)
        for msg in unacked:
            if msg["retry_count"] + 1 >= msg["max_retries"]:
                self.msg_db.mark_inbound_failed(msg["id"])
                # Notify user their message was lost
                self.msg_db.create_outbound(
                    "telegram", msg["chat_id"],
                    "Sorry, your message could not be delivered to the Bridge Bot. Please try again.",
                    source="system",
                )
                print(f"[poller] inbound #{msg['id']} failed after {msg['max_retries']} retries", file=sys.stderr)
            else:
                self.msg_db.increment_inbound_retry(msg["id"])

        # Send pending outbound
        pending = self.msg_db.get_pending_outbound()
        for msg in pending:
            success = telegram_send_message(self.token, msg["chat_id"], msg["message_text"])
            if success:
                self.msg_db.mark_outbound_sent(msg["id"])
            else:
                self.msg_db.increment_outbound_retry(msg["id"])
                if msg["retry_count"] + 1 >= msg["max_retries"]:
                    self.msg_db.mark_outbound_failed(msg["id"])
