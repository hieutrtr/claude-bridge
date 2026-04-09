"""Tests for scheduler runner logic."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from claude_bridge.db import BridgeDB
from claude_bridge.scheduler import run_scheduler, compute_next_run


@pytest.fixture
def db(tmp_path):
    d = BridgeDB(str(tmp_path / "test.db"))
    d.create_agent("testagent", "/tmp/proj", "testagent--proj", "/agents/test.md", "test purpose")
    yield d
    d.close()


def _make_due_schedule(db, name="sched", interval=30, channel="cli", chat_id=None):
    """Create a schedule that is due right now."""
    sid = db.add_schedule(name, "testagent", "do the thing", interval, channel=channel, channel_chat_id=chat_id)
    past = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
    db.conn.execute("UPDATE schedules SET next_run_at = ? WHERE id = ?", (past, sid))
    db.conn.commit()
    return sid


class TestRunScheduler:
    def test_dispatches_due_schedule(self, db):
        _make_due_schedule(db, "s1")
        with patch("claude_bridge.scheduler.dispatch_for_schedule") as mock_dispatch:
            mock_dispatch.return_value = 42
            run_scheduler(db)
            mock_dispatch.assert_called_once()

    def test_updates_run_count_on_success(self, db):
        _make_due_schedule(db, "s2")
        with patch("claude_bridge.scheduler.dispatch_for_schedule", return_value=99):
            run_scheduler(db)
        s = db.get_schedule_by_name("s2")
        assert s["run_count"] == 1

    def test_skips_future_schedule(self, db):
        db.add_schedule("future", "testagent", "do it", 60)  # next_run_at = now + 60m
        with patch("claude_bridge.scheduler.dispatch_for_schedule") as mock_dispatch:
            run_scheduler(db)
            mock_dispatch.assert_not_called()

    def test_handles_dispatch_error(self, db):
        _make_due_schedule(db, "s3")
        with patch("claude_bridge.scheduler.dispatch_for_schedule", side_effect=RuntimeError("boom")):
            run_scheduler(db)  # should not raise
        s = db.get_schedule_by_name("s3")
        assert s["consecutive_errors"] == 1
        assert "boom" in s["last_error"]

    def test_auto_pause_at_5_errors(self, db):
        sid = _make_due_schedule(db, "s4")
        db.conn.execute("UPDATE schedules SET consecutive_errors = 4 WHERE id = ?", (sid,))
        db.conn.commit()
        with patch("claude_bridge.scheduler.dispatch_for_schedule", side_effect=RuntimeError("error")):
            run_scheduler(db)
        s = db.get_schedule_by_name("s4")
        assert s["enabled"] == 0

    def test_skips_agent_not_found(self, db):
        _make_due_schedule(db, "bad_agent")
        db.conn.execute("UPDATE schedules SET agent_name = 'nonexistent' WHERE name = 'bad_agent'")
        db.conn.commit()
        with patch("claude_bridge.scheduler.dispatch_for_schedule") as mock_dispatch:
            run_scheduler(db)
            mock_dispatch.assert_not_called()
        s = db.get_schedule_by_name("bad_agent")
        assert s["consecutive_errors"] == 1

    def test_skips_schedule_with_too_many_errors(self, db):
        """Schedule with >= 5 errors should be skipped (already paused by auto-pause)."""
        sid = _make_due_schedule(db, "maxerr")
        # Manually set to 5 errors but still enabled (edge case)
        db.conn.execute(
            "UPDATE schedules SET consecutive_errors = 5, enabled = 1 WHERE id = ?", (sid,)
        )
        db.conn.commit()
        with patch("claude_bridge.scheduler.dispatch_for_schedule") as mock_dispatch:
            run_scheduler(db)
            mock_dispatch.assert_not_called()

    def test_multiple_due_schedules(self, db):
        _make_due_schedule(db, "m1")
        _make_due_schedule(db, "m2")
        dispatch_calls = []
        def fake_dispatch(db, schedule, agent):
            dispatch_calls.append(schedule["name"])
            return 1
        with patch("claude_bridge.scheduler.dispatch_for_schedule", side_effect=fake_dispatch):
            run_scheduler(db)
        assert "m1" in dispatch_calls
        assert "m2" in dispatch_calls

    def test_logs_to_stderr_on_error(self, db, capsys):
        _make_due_schedule(db, "log_err")
        with patch("claude_bridge.scheduler.dispatch_for_schedule", side_effect=RuntimeError("fail")):
            run_scheduler(db)
        captured = capsys.readouterr()
        assert "fail" in captured.err or "log_err" in captured.err


class TestComputeNextRun:
    def test_success_anchor_based(self):
        now = datetime(2026, 1, 1, 10, 0, 0)
        schedule = {"last_run_at": now.isoformat(), "interval_minutes": 30, "consecutive_errors": 0}
        result = compute_next_run(schedule, now)
        expected = now + timedelta(minutes=30)
        assert result == expected

    def test_error_backoff_first_error(self):
        now = datetime(2026, 1, 1, 10, 0, 0)
        # consecutive_errors=1 means this is the 2nd error (backoff = 2^1 = 2)
        schedule = {"last_run_at": now.isoformat(), "interval_minutes": 60, "consecutive_errors": 1}
        result = compute_next_run(schedule, now, error=True)
        # backoff = min(2^1, 8) = 2 → 60 * 2 = 120 min
        expected = now + timedelta(minutes=60 * 2)
        assert result == expected

    def test_error_backoff_capped_at_8x(self):
        now = datetime(2026, 1, 1, 10, 0, 0)
        schedule = {"last_run_at": now.isoformat(), "interval_minutes": 60, "consecutive_errors": 10}
        result = compute_next_run(schedule, now, error=True)
        # backoff capped at 8 → 60 * 8 = 480 min
        expected = now + timedelta(minutes=60 * 8)
        assert result == expected

    def test_no_last_run_uses_now(self):
        now = datetime(2026, 1, 1, 10, 0, 0)
        schedule = {"last_run_at": None, "interval_minutes": 15, "consecutive_errors": 0}
        result = compute_next_run(schedule, now)
        expected = now + timedelta(minutes=15)
        assert result == expected
