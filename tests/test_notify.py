"""Tests for task completion notifications."""

import json
import sys
from unittest.mock import patch, MagicMock

import pytest

from claude_bridge.db import BridgeDB
from claude_bridge.notify import (
    format_completion_message,
    send_telegram,
    deliver_notification,
    get_bot_token,
)
from claude_bridge.on_complete import main as on_complete_main


@pytest.fixture
def db(tmp_path):
    db = BridgeDB(str(tmp_path / "test.db"))
    yield db
    db.close()


class TestFormatCompletionMessage:
    def test_successful_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "add pagination")
        db.update_task(tid, status="done", cost_usd=0.04, duration_ms=120000,
                       num_turns=5, result_summary="Added pagination to /users")

        task = db.get_task(tid)
        msg = format_completion_message(task, "backend")
        assert "done" in msg.lower() or "✓" in msg
        assert "pagination" in msg
        assert "$0.04" in msg or "0.040" in msg

    def test_failed_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug")
        db.update_task(tid, status="failed", cost_usd=0.02, duration_ms=30000,
                       error_message="npm test failed")

        task = db.get_task(tid)
        msg = format_completion_message(task, "backend")
        assert "failed" in msg.lower() or "✗" in msg
        assert "npm test" in msg

    def test_team_task(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "build profile", task_type="team")
        db.update_task(tid, status="done", cost_usd=0.10,
                       result_summary="[backend] done\n[frontend] done")

        task = db.get_task(tid)
        msg = format_completion_message(task, "backend")
        assert "team" in msg.lower() or "🏁" in msg


class TestSendTelegram:
    @patch("claude_bridge.notify.urlopen")
    def test_successful_send(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok":true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = send_telegram("fake-token", "12345", "Task done!")
        assert result is True
        mock_urlopen.assert_called_once()

        # Verify the request
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "fake-token" in req.full_url
        assert "sendMessage" in req.full_url
        body = json.loads(req.data)
        assert body["chat_id"] == "12345"
        assert body["text"] == "Task done!"

    @patch("claude_bridge.notify.urlopen")
    def test_failed_send(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("connection refused")
        result = send_telegram("fake-token", "12345", "Task done!")
        assert result is False


class TestDeliverNotification:
    @patch("claude_bridge.notify.send_telegram", return_value=True)
    @patch("claude_bridge.notify.get_bot_token", return_value="fake-token")
    def test_delivers_and_marks_sent(self, mock_token, mock_send, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug", channel="telegram", channel_chat_id="12345")
        nid = db.create_notification(tid, "telegram", "12345", "Task done!")

        result = deliver_notification(db, nid)
        assert result is True

        notif = db.get_notification(nid)
        assert notif["status"] == "sent"
        assert notif["sent_at"] is not None

    @patch("claude_bridge.notify.send_telegram", return_value=False)
    @patch("claude_bridge.notify.get_bot_token", return_value="fake-token")
    def test_failed_delivery_stays_pending(self, mock_token, mock_send, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug", channel="telegram", channel_chat_id="12345")
        nid = db.create_notification(tid, "telegram", "12345", "Task done!")

        result = deliver_notification(db, nid)
        assert result is False

        notif = db.get_notification(nid)
        assert notif["status"] == "pending"

    @patch("claude_bridge.notify.get_bot_token", return_value=None)
    def test_no_token_stays_pending(self, mock_token, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug", channel="telegram", channel_chat_id="12345")
        nid = db.create_notification(tid, "telegram", "12345", "Task done!")

        result = deliver_notification(db, nid)
        assert result is False


class TestNotificationInDB:
    def test_create_and_get_notification(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug")
        nid = db.create_notification(tid, "telegram", "12345", "Done!")

        notif = db.get_notification(nid)
        assert notif["task_id"] == tid
        assert notif["channel"] == "telegram"
        assert notif["chat_id"] == "12345"
        assert notif["message"] == "Done!"
        assert notif["status"] == "pending"

    def test_get_pending_notifications(self, db):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug")
        db.create_notification(tid, "telegram", "12345", "Done!")
        db.create_notification(tid, "telegram", "12345", "Also done!")

        pending = db.get_pending_notifications()
        assert len(pending) == 2


class TestOnCompleteCreatesNotification:
    def test_creates_outbound_for_telegram_task(self, db, tmp_path, monkeypatch):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug", channel="telegram", channel_chat_id="12345")
        result_file = str(tmp_path / f"task-{tid}-result.json")
        db.update_task(tid, status="running", pid=111, result_file=result_file)
        db.update_agent_state("backend--api", "running")

        with open(result_file, "w") as f:
            json.dump({"is_error": False, "result": "Fixed the bug", "total_cost_usd": 0.03, "duration_ms": 60000, "num_turns": 4}, f)

        from claude_bridge.message_db import MessageDB
        msg_db_path = str(tmp_path / "messages.db")

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])
        on_complete_main(db=db, msg_db_path=msg_db_path)

        # Should have created an outbound message in messages.db
        msg_db = MessageDB(msg_db_path)
        outbound = msg_db.conn.execute("SELECT * FROM outbound_messages").fetchall()
        msg_db.close()
        assert len(outbound) >= 1
        assert outbound[0]["chat_id"] == "12345"
        assert outbound[0]["source"] == "notification"

    def test_no_notification_for_cli_task(self, db, tmp_path, monkeypatch):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")
        tid = db.create_task("backend--api", "fix bug")  # default channel='cli'
        result_file = str(tmp_path / f"task-{tid}-result.json")
        db.update_task(tid, status="running", pid=111, result_file=result_file)
        db.update_agent_state("backend--api", "running")

        with open(result_file, "w") as f:
            json.dump({"is_error": False, "result": "done", "total_cost_usd": 0.01, "duration_ms": 5000, "num_turns": 1}, f)

        from claude_bridge.message_db import MessageDB
        msg_db_path = str(tmp_path / "messages.db")

        monkeypatch.setattr(sys, "argv", ["on-complete", "--session-id", "backend--api"])
        on_complete_main(db=db, msg_db_path=msg_db_path)

        # No outbound for CLI tasks
        msg_db = MessageDB(msg_db_path)
        outbound = msg_db.conn.execute("SELECT * FROM outbound_messages").fetchall()
        msg_db.close()
        assert len(outbound) == 0
