"""Tests for tmux_session module — mock all subprocess calls."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock, call
import os

import pytest

from claude_bridge.tmux_session import (
    TMUX_SESSION_NAME,
    LOG_PATH,
    tmux_available,
    session_running,
    start_session,
    stop_session,
    get_session_pid,
    get_session_uptime,
    _format_duration,
)


class TestTmuxAvailable:
    def test_available(self):
        with patch("shutil.which", return_value="/usr/bin/tmux"):
            assert tmux_available() is True

    def test_not_available(self):
        with patch("shutil.which", return_value=None):
            assert tmux_available() is False


class TestSessionRunning:
    def test_running(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert session_running() is True
            mock_run.assert_called_once_with(
                ["tmux", "has-session", "-t", TMUX_SESSION_NAME],
                capture_output=True,
                text=True,
            )

    def test_not_running(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)
            assert session_running() is False

    def test_custom_name(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert session_running("my-session") is True
            mock_run.assert_called_once_with(
                ["tmux", "has-session", "-t", "my-session"],
                capture_output=True,
                text=True,
            )


class TestStartSession:
    @patch("os.makedirs")
    @patch("subprocess.run")
    def test_start_success(self, mock_run, mock_makedirs):
        # has-session returns 1 (not running), new-session returns 0, pipe-pane returns 0
        mock_run.side_effect = [
            MagicMock(returncode=1),  # has-session
            MagicMock(returncode=0),  # new-session
            MagicMock(returncode=0),  # pipe-pane
        ]
        assert start_session(["claude", "--dangerously-skip-permissions"]) is True
        assert mock_run.call_count == 3

    @patch("subprocess.run")
    def test_start_already_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)  # has-session succeeds
        assert start_session(["claude"]) is False

    @patch("os.makedirs")
    @patch("subprocess.run")
    def test_start_tmux_fails(self, mock_run, mock_makedirs):
        mock_run.side_effect = [
            MagicMock(returncode=1),  # has-session (not running)
            MagicMock(returncode=1),  # new-session fails
        ]
        assert start_session(["claude"]) is False

    @patch("os.makedirs")
    @patch("subprocess.run")
    def test_start_creates_log_dir(self, mock_run, mock_makedirs):
        mock_run.side_effect = [
            MagicMock(returncode=1),
            MagicMock(returncode=0),
            MagicMock(returncode=0),
        ]
        start_session(["claude"], log_path="/tmp/test/bridge.log")
        mock_makedirs.assert_called_with("/tmp/test", exist_ok=True)


class TestStopSession:
    @patch("time.sleep")
    @patch("time.monotonic")
    @patch("subprocess.run")
    def test_stop_graceful(self, mock_run, mock_mono, mock_sleep):
        # Session running, then stops after C-c
        mock_run.side_effect = [
            MagicMock(returncode=0),  # has-session (running)
            MagicMock(returncode=0),  # send-keys C-c
            MagicMock(returncode=1),  # has-session (stopped)
        ]
        mock_mono.side_effect = [0.0, 0.5]
        assert stop_session() is True

    @patch("subprocess.run")
    def test_stop_not_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)  # has-session fails
        assert stop_session() is False

    @patch("time.sleep")
    @patch("time.monotonic")
    @patch("subprocess.run")
    def test_stop_force_kill(self, mock_run, mock_mono, mock_sleep):
        # Session stays running after C-c, needs kill-session
        running = MagicMock(returncode=0)
        mock_run.side_effect = [
            running,   # has-session (running) — initial check
            MagicMock(returncode=0),  # send-keys C-c
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            running,   # has-session (still running)
            MagicMock(returncode=0),  # kill-session
        ]
        # Simulate time passing past the deadline
        mock_mono.side_effect = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
        assert stop_session(timeout=5.0) is True


class TestGetSessionPid:
    @patch("subprocess.run")
    def test_get_pid(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # has-session
            MagicMock(returncode=0, stdout="12345\n"),  # list-panes
        ]
        assert get_session_pid() == 12345

    @patch("subprocess.run")
    def test_not_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert get_session_pid() is None

    @patch("subprocess.run")
    def test_invalid_output(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # has-session
            MagicMock(returncode=0, stdout="not-a-pid\n"),  # list-panes
        ]
        assert get_session_pid() is None

    @patch("subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # has-session
            MagicMock(returncode=0, stdout=""),  # list-panes
        ]
        assert get_session_pid() is None


class TestGetSessionUptime:
    @patch("time.time")
    @patch("subprocess.run")
    def test_uptime(self, mock_run, mock_time):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # has-session
            MagicMock(returncode=0, stdout="1700000000\n"),  # display-message
        ]
        mock_time.return_value = 1700003600  # 1 hour later
        result = get_session_uptime()
        assert result == "1h"

    @patch("subprocess.run")
    def test_not_running(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1)
        assert get_session_uptime() is None

    @patch("subprocess.run")
    def test_invalid_timestamp(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout="invalid\n"),
        ]
        assert get_session_uptime() is None


class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(30) == "30s"

    def test_minutes(self):
        assert _format_duration(120) == "2m"

    def test_hours(self):
        assert _format_duration(7200) == "2h"

    def test_hours_and_minutes(self):
        assert _format_duration(7500) == "2h 5m"

    def test_days(self):
        assert _format_duration(86400) == "1d"

    def test_days_and_hours(self):
        assert _format_duration(90000) == "1d 1h"
