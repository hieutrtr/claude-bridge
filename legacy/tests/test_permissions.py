"""Tests for permission relay system."""

import sys
import time
from unittest.mock import patch

import pytest

from claude_bridge.db import BridgeDB
from claude_bridge.permission_relay import main as relay_main
from claude_bridge.cli import cmd_permissions, cmd_approve, cmd_deny


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test.db")
    database = BridgeDB(db_path)
    yield database
    database.close()


class _Args:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class TestPermissionDB:
    def test_create_permission(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push", "push to remote")
        perm = db.get_permission("req-1")
        assert perm is not None
        assert perm["session_id"] == "backend--api"
        assert perm["tool_name"] == "Bash"
        assert perm["status"] == "pending"

    def test_get_pending_permissions(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push")
        db.create_permission("req-2", "frontend--web", "Bash", "rm -rf")
        pending = db.get_pending_permissions()
        assert len(pending) == 2

    def test_get_pending_by_session(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push")
        db.create_permission("req-2", "frontend--web", "Bash", "rm -rf")
        pending = db.get_pending_permissions("backend--api")
        assert len(pending) == 1
        assert pending[0]["id"] == "req-1"

    def test_approve_permission(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push")
        result = db.respond_permission("req-1", approved=True)
        assert result is True
        perm = db.get_permission("req-1")
        assert perm["status"] == "approved"
        assert perm["responded_at"] is not None

    def test_deny_permission(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push")
        result = db.respond_permission("req-1", approved=False)
        assert result is True
        perm = db.get_permission("req-1")
        assert perm["status"] == "denied"

    def test_respond_nonexistent(self, db):
        result = db.respond_permission("nope", approved=True)
        assert result is False

    def test_respond_already_responded(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push")
        db.respond_permission("req-1", approved=True)
        # Second response should fail
        result = db.respond_permission("req-1", approved=False)
        assert result is False

    def test_timeout_permissions(self, db):
        # Create a permission with 0 timeout (already expired)
        db.create_permission("req-1", "backend--api", "Bash", "git push", timeout_seconds=0)
        time.sleep(0.1)  # Ensure time passes
        count = db.timeout_permissions()
        assert count == 1
        perm = db.get_permission("req-1")
        assert perm["status"] == "denied"
        assert perm["response"] == "timeout"


class TestPermissionRelay:
    @patch("claude_bridge.permission_relay.time.sleep")
    def test_approved_returns_0(self, mock_sleep, db, monkeypatch):
        """If permission is approved while polling, return 0 (allow)."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")

        # Pre-approve after first poll
        call_count = 0
        original_sleep = mock_sleep

        def approve_on_second_poll(seconds):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                # Find the pending permission and approve it
                pending = db.get_pending_permissions("backend--api")
                if pending:
                    db.respond_permission(pending[0]["id"], approved=True)

        mock_sleep.side_effect = approve_on_second_poll

        monkeypatch.setattr(sys, "argv", [
            "permission-relay", "--session-id", "backend--api",
            "--tool", "Bash", "--command", "git push", "--timeout", "10",
        ])
        result = relay_main(db=db)
        assert result == 0

    @patch("claude_bridge.permission_relay.time.sleep")
    def test_denied_returns_2(self, mock_sleep, db, monkeypatch):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")

        call_count = 0
        def deny_on_second_poll(seconds):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                pending = db.get_pending_permissions("backend--api")
                if pending:
                    db.respond_permission(pending[0]["id"], approved=False)

        mock_sleep.side_effect = deny_on_second_poll

        monkeypatch.setattr(sys, "argv", [
            "permission-relay", "--session-id", "backend--api",
            "--tool", "Bash", "--command", "rm -rf", "--timeout", "10",
        ])
        result = relay_main(db=db)
        assert result == 2

    @patch("claude_bridge.permission_relay.time.sleep")
    @patch("claude_bridge.permission_relay.POLL_INTERVAL", 10)
    def test_timeout_returns_2(self, mock_sleep, db, monkeypatch):
        """If no response within timeout, auto-deny and return 2."""
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")

        monkeypatch.setattr(sys, "argv", [
            "permission-relay", "--session-id", "backend--api",
            "--tool", "Bash", "--command", "git push", "--timeout", "1",
        ])
        mock_sleep.side_effect = lambda s: None
        result = relay_main(db=db)
        assert result == 2

    def test_creates_permission_in_db(self, db, monkeypatch):
        db.create_agent("backend", "/p/api", "backend--api", "/a.md", "dev")

        # Pre-approve immediately so it doesn't block
        original_get = db.get_permission
        call_count = 0
        def auto_approve(request_id):
            nonlocal call_count
            call_count += 1
            perm = original_get(request_id)
            if perm and perm["status"] == "pending" and call_count > 1:
                db.respond_permission(request_id, approved=True)
                return db.get_permission(request_id)
            return perm

        monkeypatch.setattr(db, "get_permission", auto_approve)

        monkeypatch.setattr(sys, "argv", [
            "permission-relay", "--session-id", "backend--api",
            "--tool", "Bash", "--command", "git push", "--timeout", "5",
        ])

        with patch("claude_bridge.permission_relay.time.sleep"):
            relay_main(db=db)

        # Permission should exist in DB
        pending = db.get_pending_permissions("backend--api")
        # It was approved so won't be pending anymore
        all_perms = db.conn.execute("SELECT * FROM permissions").fetchall()
        assert len(all_perms) == 1
        assert all_perms[0]["tool_name"] == "Bash"


class TestPermissionCLI:
    def test_list_pending(self, db, capsys):
        db.create_permission("req-1", "backend--api", "Bash", "git push", "push to remote")
        result = cmd_permissions(db, _Args())
        assert result == 0
        captured = capsys.readouterr()
        assert "req-1" in captured.out
        assert "git push" in captured.out

    def test_list_empty(self, db, capsys):
        result = cmd_permissions(db, _Args())
        assert result == 0
        captured = capsys.readouterr()
        assert "No pending" in captured.out

    def test_approve_via_cli(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push")
        result = cmd_approve(db, _Args(request_id="req-1"))
        assert result == 0
        perm = db.get_permission("req-1")
        assert perm["status"] == "approved"

    def test_deny_via_cli(self, db):
        db.create_permission("req-1", "backend--api", "Bash", "git push")
        result = cmd_deny(db, _Args(request_id="req-1"))
        assert result == 0
        perm = db.get_permission("req-1")
        assert perm["status"] == "denied"

    def test_approve_nonexistent(self, db):
        result = cmd_approve(db, _Args(request_id="nope"))
        assert result == 1

    def test_deny_nonexistent(self, db):
        result = cmd_deny(db, _Args(request_id="nope"))
        assert result == 1


class TestAgentMdPermissionHook:
    def test_agent_md_contains_pretooluse_hook(self):
        from claude_bridge.agent_md import generate_agent_md
        content = generate_agent_md("backend--api", "backend", "/p/api", "dev")
        assert "PreToolUse" in content
        assert "permission_relay" in content
        assert "git push" in content
