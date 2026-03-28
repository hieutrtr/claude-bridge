"""Tests for Telegram poller thread."""

from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from claude_bridge.message_db import MessageDB
from claude_bridge.telegram_poller import (
    TelegramPoller,
    parse_updates,
    is_allowed_user,
    telegram_get_updates,
    telegram_send_message,
)


@pytest.fixture
def msg_db(tmp_path):
    db = MessageDB(str(tmp_path / "messages.db"))
    yield db
    db.close()


class TestParseUpdates:
    def test_parses_text_message(self):
        raw = {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 12345},
                        "from": {"id": 12345, "username": "hieu"},
                        "text": "hello bot",
                    },
                }
            ],
        }
        updates = parse_updates(raw)
        assert len(updates) == 1
        assert updates[0]["update_id"] == 100
        assert updates[0]["chat_id"] == "12345"
        assert updates[0]["user_id"] == "12345"
        assert updates[0]["username"] == "hieu"
        assert updates[0]["text"] == "hello bot"
        assert updates[0]["message_id"] == "1"

    def test_empty_result(self):
        raw = {"ok": True, "result": []}
        assert parse_updates(raw) == []

    def test_skips_non_text(self):
        raw = {
            "ok": True,
            "result": [
                {
                    "update_id": 100,
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 12345},
                        "from": {"id": 12345},
                        # no "text" field
                    },
                }
            ],
        }
        updates = parse_updates(raw)
        assert len(updates) == 0

    def test_not_ok(self):
        raw = {"ok": False, "description": "Unauthorized"}
        assert parse_updates(raw) == []


class TestIsAllowedUser:
    def test_allowed(self, tmp_path):
        access = tmp_path / "access.json"
        access.write_text(json.dumps({"allowFrom": ["12345", "67890"]}))
        assert is_allowed_user("12345", str(access)) is True

    def test_not_allowed(self, tmp_path):
        access = tmp_path / "access.json"
        access.write_text(json.dumps({"allowFrom": ["12345"]}))
        assert is_allowed_user("99999", str(access)) is False

    def test_no_access_file(self):
        assert is_allowed_user("12345", "/nonexistent/access.json") is True  # permissive if no file

    def test_empty_allowlist(self, tmp_path):
        access = tmp_path / "access.json"
        access.write_text(json.dumps({"allowFrom": []}))
        assert is_allowed_user("12345", str(access)) is True  # empty = allow all


class TestTelegramGetUpdates:
    @patch("claude_bridge.telegram_poller.urlopen")
    def test_returns_parsed(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "ok": True,
            "result": [
                {
                    "update_id": 200,
                    "message": {
                        "message_id": 5,
                        "chat": {"id": 111},
                        "from": {"id": 111, "username": "user"},
                        "text": "dispatch backend fix",
                    },
                }
            ],
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        updates, raw = telegram_get_updates("fake-token", offset=0)
        assert len(updates) == 1
        assert updates[0]["text"] == "dispatch backend fix"

    @patch("claude_bridge.telegram_poller.urlopen")
    def test_network_error_returns_empty(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("connection refused")
        updates, raw = telegram_get_updates("fake-token", offset=0)
        assert updates == []


class TestTelegramSendMessage:
    @patch("claude_bridge.telegram_poller.urlopen")
    def test_sends_successfully(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = telegram_send_message("fake-token", "12345", "hello")
        assert result is True

    @patch("claude_bridge.telegram_poller.urlopen")
    def test_send_failure(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("error")
        result = telegram_send_message("fake-token", "12345", "hello")
        assert result is False


class TestPollerIntegration:
    @patch("claude_bridge.telegram_poller.telegram_send_message", return_value=True)
    @patch("claude_bridge.telegram_poller.telegram_get_updates")
    @patch("claude_bridge.telegram_poller.is_allowed_user", return_value=True)
    def test_poll_cycle_stores_inbound(self, mock_allowed, mock_get, mock_send, msg_db):
        mock_get.return_value = (
            [{"update_id": 100, "chat_id": "12345", "user_id": "12345", "username": "hieu", "text": "hello", "message_id": "1"}],
            {"ok": True, "result": []},
        )

        poller = TelegramPoller("fake-token", msg_db)
        poller.poll_once()

        pending = msg_db.get_pending_inbound()
        assert len(pending) == 1
        assert pending[0]["message_text"] == "hello"

        # Offset should advance
        assert msg_db.get_state("telegram_offset") == "101"

    @patch("claude_bridge.telegram_poller.telegram_send_message", return_value=True)
    @patch("claude_bridge.telegram_poller.telegram_get_updates")
    @patch("claude_bridge.telegram_poller.is_allowed_user", return_value=False)
    def test_rejects_non_allowed_user(self, mock_allowed, mock_get, mock_send, msg_db):
        mock_get.return_value = (
            [{"update_id": 100, "chat_id": "99999", "user_id": "99999", "username": "hacker", "text": "hello", "message_id": "1"}],
            {"ok": True, "result": []},
        )

        poller = TelegramPoller("fake-token", msg_db)
        poller.poll_once()

        pending = msg_db.get_pending_inbound()
        assert len(pending) == 0

    @patch("claude_bridge.telegram_poller.telegram_send_message", return_value=True)
    @patch("claude_bridge.telegram_poller.telegram_get_updates")
    def test_sends_pending_outbound(self, mock_get, mock_send, msg_db):
        mock_get.return_value = ([], {"ok": True, "result": []})

        msg_db.create_outbound("telegram", "12345", "Task done!")
        poller = TelegramPoller("fake-token", msg_db)
        poller.poll_once()

        mock_send.assert_called_once_with("fake-token", "12345", "Task done!")
        msg = msg_db.get_outbound(1)
        assert msg["status"] == "sent"

    @patch("claude_bridge.telegram_poller.telegram_send_message", return_value=False)
    @patch("claude_bridge.telegram_poller.telegram_get_updates")
    def test_outbound_send_failure_retries(self, mock_get, mock_send, msg_db):
        mock_get.return_value = ([], {"ok": True, "result": []})

        mid = msg_db.create_outbound("telegram", "12345", "Task done!")
        poller = TelegramPoller("fake-token", msg_db)
        poller.poll_once()

        msg = msg_db.get_outbound(mid)
        assert msg["status"] == "pending"  # still pending
        assert msg["retry_count"] == 1

    @patch("claude_bridge.telegram_poller.telegram_send_message", return_value=True)
    @patch("claude_bridge.telegram_poller.telegram_get_updates")
    def test_empty_poll(self, mock_get, mock_send, msg_db):
        mock_get.return_value = ([], {"ok": True, "result": []})
        poller = TelegramPoller("fake-token", msg_db)
        poller.poll_once()
        assert msg_db.get_pending_inbound() == []


class TestDeliveryRetry:
    @patch("claude_bridge.telegram_poller.telegram_send_message", return_value=True)
    @patch("claude_bridge.telegram_poller.telegram_get_updates")
    def test_retries_unacknowledged(self, mock_get, mock_send, msg_db):
        mock_get.return_value = ([], {"ok": True, "result": []})

        # Create a delivered-but-unacknowledged message with old timestamp
        mid = msg_db.create_inbound("telegram", "12345", "u1", "hello")
        # Manually set delivered_at to 10 seconds ago
        from claude_bridge.message_db import _utcnow_offset
        old_time = _utcnow_offset(-10)
        msg_db.conn.execute(
            "UPDATE inbound_messages SET status='delivered', delivered_at=? WHERE id=?",
            (old_time, mid),
        )
        msg_db.conn.commit()

        poller = TelegramPoller("fake-token", msg_db)
        poller.poll_once()

        msg = msg_db.get_inbound(mid)
        assert msg["status"] == "pending"  # reset to pending for retry
        assert msg["retry_count"] == 1

    @patch("claude_bridge.telegram_poller.telegram_send_message", return_value=True)
    @patch("claude_bridge.telegram_poller.telegram_get_updates")
    def test_max_retries_marks_failed(self, mock_get, mock_send, msg_db):
        mock_get.return_value = ([], {"ok": True, "result": []})

        mid = msg_db.create_inbound("telegram", "12345", "u1", "hello")
        # Set retry_count to max-1 and delivered with old timestamp
        from claude_bridge.message_db import _utcnow_offset
        old_time = _utcnow_offset(-10)
        msg_db.conn.execute(
            "UPDATE inbound_messages SET status='delivered', delivered_at=?, retry_count=4 WHERE id=?",
            (old_time, mid),
        )
        msg_db.conn.commit()

        poller = TelegramPoller("fake-token", msg_db)
        poller.poll_once()

        msg = msg_db.get_inbound(mid)
        assert msg["status"] == "failed"

        # Should have created an error outbound message (already sent by poller)
        outbound = msg_db.conn.execute("SELECT * FROM outbound_messages").fetchall()
        assert len(outbound) == 1
        assert "could not be delivered" in outbound[0]["message_text"]
