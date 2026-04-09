"""Tests for schedules DB CRUD methods."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from claude_bridge.db import BridgeDB


@pytest.fixture
def db(tmp_path):
    d = BridgeDB(str(tmp_path / "test.db"))
    # Create a test agent so schedule foreign-key-like references work
    d.create_agent("testagent", "/tmp/proj", "testagent--proj", "/agents/test.md", "test purpose")
    yield d
    d.close()


class TestAddSchedule:
    def test_add_basic(self, db):
        sid = db.add_schedule(
            name="news-update",
            agent_name="testagent",
            prompt="run news update",
            interval_minutes=30,
        )
        assert isinstance(sid, int)
        assert sid > 0

    def test_add_returns_id(self, db):
        sid = db.add_schedule("s1", "testagent", "do it", 60)
        s = db.get_schedule_by_name("s1")
        assert s is not None
        assert s["id"] == sid

    def test_add_with_channel(self, db):
        db.add_schedule("s2", "testagent", "do it", 30, channel="telegram", channel_chat_id="123456")
        s = db.get_schedule_by_name("s2")
        assert s["channel"] == "telegram"
        assert s["channel_chat_id"] == "123456"

    def test_add_sets_next_run_at(self, db):
        before = datetime.now(timezone.utc)
        db.add_schedule("s3", "testagent", "do it", 15)
        after = datetime.now(timezone.utc)
        s = db.get_schedule_by_name("s3")
        next_run = datetime.fromisoformat(s["next_run_at"])
        assert next_run >= before + timedelta(minutes=14)
        assert next_run <= after + timedelta(minutes=16)

    def test_add_defaults(self, db):
        db.add_schedule("s4", "testagent", "do it", 10)
        s = db.get_schedule_by_name("s4")
        assert s["enabled"] == 1
        assert s["run_count"] == 0
        assert s["consecutive_errors"] == 0
        assert s["channel"] == "cli"
        assert s["run_once"] == 0

    def test_add_duplicate_name_same_agent_raises(self, db):
        db.add_schedule("dup", "testagent", "do it", 10)
        with pytest.raises(Exception):
            db.add_schedule("dup", "testagent", "do it again", 20)

    def test_add_run_once(self, db):
        db.add_schedule("once", "testagent", "do once", 60, run_once=True)
        s = db.get_schedule_by_name("once")
        assert s["run_once"] == 1


class TestGetDueSchedules:
    def test_returns_due(self, db):
        # Create a schedule whose next_run_at is in the past
        sid = db.add_schedule("past", "testagent", "do it", 60)
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.conn.execute("UPDATE schedules SET next_run_at = ? WHERE id = ?", (past, sid))
        db.conn.commit()

        due = db.get_due_schedules(datetime.now(timezone.utc))
        names = [d["name"] for d in due]
        assert "past" in names

    def test_skips_future(self, db):
        db.add_schedule("future", "testagent", "do it", 60)
        # next_run_at is now + 60m by default — should not be due
        due = db.get_due_schedules(datetime.now(timezone.utc))
        names = [d["name"] for d in due]
        assert "future" not in names

    def test_skips_disabled(self, db):
        sid = db.add_schedule("disabled", "testagent", "do it", 60)
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.conn.execute("UPDATE schedules SET next_run_at = ?, enabled = 0 WHERE id = ?", (past, sid))
        db.conn.commit()

        due = db.get_due_schedules(datetime.now(timezone.utc))
        names = [d["name"] for d in due]
        assert "disabled" not in names

    def test_exact_due_time(self, db):
        now = datetime.now(timezone.utc)
        sid = db.add_schedule("exact", "testagent", "do it", 60)
        db.conn.execute("UPDATE schedules SET next_run_at = ? WHERE id = ?", (now.isoformat(), sid))
        db.conn.commit()
        due = db.get_due_schedules(now)
        names = [d["name"] for d in due]
        assert "exact" in names


class TestUpdateScheduleSuccess:
    def test_updates_run_count_and_next_run(self, db):
        sid = db.add_schedule("s", "testagent", "do it", 30)
        now = datetime.now(timezone.utc)
        db.update_schedule_success(sid, now)
        s = db.get_schedule_by_name("s")
        assert s["run_count"] == 1
        assert s["consecutive_errors"] == 0
        assert s["last_run_at"] is not None
        # next_run_at should be now + 30m
        next_run = datetime.fromisoformat(s["next_run_at"])
        expected = now + timedelta(minutes=30)
        assert abs((next_run - expected).total_seconds()) < 2

    def test_resets_consecutive_errors(self, db):
        sid = db.add_schedule("s2", "testagent", "do it", 10)
        db.conn.execute("UPDATE schedules SET consecutive_errors = 3 WHERE id = ?", (sid,))
        db.conn.commit()
        db.update_schedule_success(sid, datetime.now(timezone.utc))
        s = db.get_schedule_by_name("s2")
        assert s["consecutive_errors"] == 0

    def test_run_once_disables_after_run(self, db):
        sid = db.add_schedule("once", "testagent", "do once", 60, run_once=True)
        db.update_schedule_success(sid, datetime.now(timezone.utc))
        s = db.get_schedule_by_name("once")
        assert s["enabled"] == 0


class TestUpdateScheduleError:
    def test_increments_consecutive_errors(self, db):
        sid = db.add_schedule("s", "testagent", "do it", 10)
        db.update_schedule_error(sid, "something went wrong")
        s = db.get_schedule_by_name("s")
        assert s["consecutive_errors"] == 1
        assert s["last_error"] == "something went wrong"

    def test_auto_pause_at_5_errors(self, db):
        sid = db.add_schedule("s5", "testagent", "do it", 10)
        db.conn.execute("UPDATE schedules SET consecutive_errors = 4 WHERE id = ?", (sid,))
        db.conn.commit()
        db.update_schedule_error(sid, "fatal error")
        s = db.get_schedule_by_name("s5")
        assert s["consecutive_errors"] == 5
        assert s["enabled"] == 0  # auto-paused

    def test_backoff_next_run(self, db):
        sid = db.add_schedule("s_back", "testagent", "do it", 60)
        now = datetime.now(timezone.utc)
        # Set last_run_at to now
        db.conn.execute("UPDATE schedules SET last_run_at = ?, consecutive_errors = 1 WHERE id = ?", (now.isoformat(), sid))
        db.conn.commit()
        db.update_schedule_error(sid, "err")
        s = db.get_schedule_by_name("s_back")
        # After 2nd error, consecutive_errors=2, backoff=min(2^2, 8)=4
        next_run = datetime.fromisoformat(s["next_run_at"])
        # next_run should be approx last_run_at + 60 * 4 = 240 minutes
        expected = now + timedelta(minutes=60 * 4)
        assert abs((next_run - expected).total_seconds()) < 5


class TestListSchedules:
    def test_list_all_enabled(self, db):
        db.add_schedule("a1", "testagent", "do it", 10)
        db.add_schedule("a2", "testagent", "do it", 20)
        schedules = db.list_schedules()
        names = [s["name"] for s in schedules]
        assert "a1" in names
        assert "a2" in names

    def test_list_excludes_disabled_by_default(self, db):
        sid = db.add_schedule("hidden", "testagent", "do it", 10)
        db.conn.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (sid,))
        db.conn.commit()
        schedules = db.list_schedules()
        names = [s["name"] for s in schedules]
        assert "hidden" not in names

    def test_list_all_includes_disabled(self, db):
        sid = db.add_schedule("hidden2", "testagent", "do it", 10)
        db.conn.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (sid,))
        db.conn.commit()
        schedules = db.list_schedules(include_disabled=True)
        names = [s["name"] for s in schedules]
        assert "hidden2" in names

    def test_list_filter_by_agent(self, db):
        db.create_agent("other", "/tmp/other", "other--other", "/agents/other.md", "other")
        db.add_schedule("x1", "testagent", "do it", 10)
        db.add_schedule("x2", "other", "do it", 10)
        schedules = db.list_schedules(agent_name="testagent")
        names = [s["name"] for s in schedules]
        assert "x1" in names
        assert "x2" not in names


class TestRemoveSchedule:
    def test_remove_by_name(self, db):
        db.add_schedule("rm-me", "testagent", "do it", 10)
        result = db.remove_schedule("rm-me")
        assert result is True
        assert db.get_schedule_by_name("rm-me") is None

    def test_remove_nonexistent_returns_false(self, db):
        assert db.remove_schedule("nope") is False

    def test_remove_by_id(self, db):
        sid = db.add_schedule("rm-id", "testagent", "do it", 10)
        result = db.remove_schedule(str(sid))
        assert result is True
        assert db.get_schedule_by_name("rm-id") is None


class TestPauseResume:
    def test_pause(self, db):
        db.add_schedule("ps", "testagent", "do it", 10)
        result = db.pause_schedule("ps")
        assert result is True
        s = db.get_schedule_by_name("ps")
        assert s["enabled"] == 0

    def test_resume(self, db):
        sid = db.add_schedule("rs", "testagent", "do it", 10)
        db.conn.execute("UPDATE schedules SET enabled = 0 WHERE id = ?", (sid,))
        db.conn.commit()
        result = db.resume_schedule("rs")
        assert result is True
        s = db.get_schedule_by_name("rs")
        assert s["enabled"] == 1

    def test_pause_nonexistent(self, db):
        assert db.pause_schedule("nope") is False

    def test_resume_nonexistent(self, db):
        assert db.resume_schedule("nope") is False
