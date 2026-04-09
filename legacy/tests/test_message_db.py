"""Tests for message queue database."""

from __future__ import annotations

import pytest

from claude_bridge.message_db import MessageDB


@pytest.fixture
def db(tmp_path):
    db = MessageDB(str(tmp_path / "messages.db"))
    yield db
    db.close()


class TestInboundMessages:
    def test_create_and_get(self, db):
        mid = db.create_inbound("telegram", "12345", "user1", "hello", username="hieu")
        msg = db.get_inbound(mid)
        assert msg["platform"] == "telegram"
        assert msg["chat_id"] == "12345"
        assert msg["user_id"] == "user1"
        assert msg["message_text"] == "hello"
        assert msg["username"] == "hieu"
        assert msg["status"] == "pending"
        assert msg["retry_count"] == 0

    def test_get_pending(self, db):
        db.create_inbound("telegram", "12345", "u1", "msg1")
        db.create_inbound("telegram", "12345", "u1", "msg2")
        pending = db.get_pending_inbound()
        assert len(pending) == 2

    def test_mark_delivered(self, db):
        mid = db.create_inbound("telegram", "12345", "u1", "hello")
        db.mark_inbound_delivered(mid)
        msg = db.get_inbound(mid)
        assert msg["status"] == "delivered"
        assert msg["delivered_at"] is not None

    def test_mark_acknowledged(self, db):
        mid = db.create_inbound("telegram", "12345", "u1", "hello")
        db.mark_inbound_delivered(mid)
        db.mark_inbound_acknowledged(mid)
        msg = db.get_inbound(mid)
        assert msg["status"] == "acknowledged"
        assert msg["acknowledged_at"] is not None

    def test_mark_failed(self, db):
        mid = db.create_inbound("telegram", "12345", "u1", "hello")
        db.mark_inbound_failed(mid)
        msg = db.get_inbound(mid)
        assert msg["status"] == "failed"

    def test_increment_retry(self, db):
        mid = db.create_inbound("telegram", "12345", "u1", "hello")
        db.increment_inbound_retry(mid)
        msg = db.get_inbound(mid)
        assert msg["retry_count"] == 1
        assert msg["status"] == "pending"

    def test_get_unacknowledged(self, db):
        m1 = db.create_inbound("telegram", "12345", "u1", "msg1")
        m2 = db.create_inbound("telegram", "12345", "u1", "msg2")
        db.mark_inbound_delivered(m1)
        db.mark_inbound_delivered(m2)
        db.mark_inbound_acknowledged(m1)
        unacked = db.get_unacknowledged_inbound(timeout_seconds=0)
        assert len(unacked) == 1
        assert unacked[0]["id"] == m2

    def test_no_pending_returns_empty(self, db):
        assert db.get_pending_inbound() == []


class TestOutboundMessages:
    def test_create_and_get(self, db):
        mid = db.create_outbound("telegram", "12345", "Task done!", source="notification")
        msg = db.get_outbound(mid)
        assert msg["platform"] == "telegram"
        assert msg["chat_id"] == "12345"
        assert msg["message_text"] == "Task done!"
        assert msg["source"] == "notification"
        assert msg["status"] == "pending"

    def test_get_pending(self, db):
        db.create_outbound("telegram", "12345", "msg1")
        db.create_outbound("telegram", "12345", "msg2")
        pending = db.get_pending_outbound()
        assert len(pending) == 2

    def test_mark_sent(self, db):
        mid = db.create_outbound("telegram", "12345", "hello")
        db.mark_outbound_sent(mid)
        msg = db.get_outbound(mid)
        assert msg["status"] == "sent"
        assert msg["sent_at"] is not None

    def test_mark_failed(self, db):
        mid = db.create_outbound("telegram", "12345", "hello")
        db.mark_outbound_failed(mid)
        msg = db.get_outbound(mid)
        assert msg["status"] == "failed"

    def test_increment_retry(self, db):
        mid = db.create_outbound("telegram", "12345", "hello")
        db.increment_outbound_retry(mid)
        msg = db.get_outbound(mid)
        assert msg["retry_count"] == 1

    def test_no_pending_returns_empty(self, db):
        assert db.get_pending_outbound() == []


class TestOutboundDeduplication:
    def test_has_notification_false_when_empty(self, db):
        assert db.has_notification_for_task(42) is False

    def test_has_notification_true_after_create(self, db):
        db.create_outbound("telegram", "111", "done", source="notification", task_id=7)
        assert db.has_notification_for_task(7) is True

    def test_has_notification_only_matches_notification_source(self, db):
        db.create_outbound("telegram", "111", "done", source="bot", task_id=9)
        assert db.has_notification_for_task(9) is False

    def test_has_notification_false_for_other_task_id(self, db):
        db.create_outbound("telegram", "111", "done", source="notification", task_id=1)
        assert db.has_notification_for_task(2) is False

    def test_task_id_persisted_in_outbound_row(self, db):
        mid = db.create_outbound("telegram", "222", "hello", source="notification", task_id=99)
        msg = db.get_outbound(mid)
        assert msg["task_id"] == 99

    def test_create_outbound_without_task_id(self, db):
        mid = db.create_outbound("telegram", "333", "hi")
        msg = db.get_outbound(mid)
        assert msg["task_id"] is None


class TestUpdatePendingOutbound:
    def test_updates_pending_notification(self, db):
        """Pending notification message_text is updated with new content."""
        mid = db.create_outbound("telegram", "111", "Task done (no summary)", source="notification", task_id=5)
        updated = db.update_pending_outbound_for_task(5, "Task done\nActual summary here")
        assert updated is True
        msg = db.get_outbound(mid)
        assert msg["message_text"] == "Task done\nActual summary here"
        assert msg["status"] == "pending"

    def test_resets_notified_to_pending(self, db):
        """'notified' status is reset to 'pending' after update so processOutbound re-sends it."""
        mid = db.create_outbound("telegram", "111", "old text", source="notification", task_id=10)
        db.conn.execute("UPDATE outbound_messages SET status = 'notified' WHERE id = ?", (mid,))
        db.conn.commit()
        updated = db.update_pending_outbound_for_task(10, "new text with summary")
        assert updated is True
        msg = db.get_outbound(mid)
        assert msg["message_text"] == "new text with summary"
        assert msg["status"] == "pending"

    def test_returns_false_when_already_sent(self, db):
        """Already sent notification cannot be updated — returns False."""
        mid = db.create_outbound("telegram", "111", "Task done", source="notification", task_id=6)
        db.mark_outbound_sent(mid)
        updated = db.update_pending_outbound_for_task(6, "Updated message")
        assert updated is False

    def test_returns_false_when_no_notification(self, db):
        """No notification for task — returns False."""
        updated = db.update_pending_outbound_for_task(99, "anything")
        assert updated is False

    def test_only_matches_notification_source(self, db):
        """Does not update outbound with a different source (e.g. 'bot')."""
        mid = db.create_outbound("telegram", "111", "bot reply", source="bot", task_id=20)
        updated = db.update_pending_outbound_for_task(20, "new text", source="notification")
        assert updated is False
        msg = db.get_outbound(mid)
        assert msg["message_text"] == "bot reply"  # unchanged


class TestPollerState:
    def test_set_and_get(self, db):
        db.set_state("telegram_offset", "12345")
        assert db.get_state("telegram_offset") == "12345"

    def test_get_missing_returns_none(self, db):
        assert db.get_state("nonexistent") is None

    def test_update_existing(self, db):
        db.set_state("offset", "100")
        db.set_state("offset", "200")
        assert db.get_state("offset") == "200"
