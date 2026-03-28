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
