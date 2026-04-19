"""Tests for M24.T2 — wiki ingest runner.

The runner orchestrates collect_sources (M23.T2) + wiki_ingest.md (M24.T1)
+ `claude -p` subprocess. These tests mock subprocess.run so no real
`claude` CLI runs. One opt-in integration test exercises the real CLI
(run with `pytest -m integration`).
"""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import time

import pytest


# Reuse the helpers from test_wiki.py rather than duplicating them.
from .test_wiki import _setup_env, _register_agent, _seed_memory


# ---------------------------------------------------------------------------
# Empty state — no subprocess call, skipped result
# ---------------------------------------------------------------------------


class TestIngestEmptyState:
    def test_no_agents_returns_skipped(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        from claude_bridge.wiki import ingest

        result = ingest()
        assert result["skipped"] is True
        assert result["sources_count"] == 0
        assert result["exit_code"] == 0

    def test_no_agents_does_not_call_subprocess(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)

        calls: list = []
        def fake_run(cmd, **kwargs):
            calls.append((cmd, kwargs))
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        ingest()
        assert calls == []


# ---------------------------------------------------------------------------
# Happy path — subprocess invoked with correct args; row written
# ---------------------------------------------------------------------------


class TestIngestHappyPath:
    def test_subprocess_invoked_with_expected_args(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        from claude_bridge.wiki import wiki_home
        home = wiki_home()

        captured: dict = {}
        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            captured["capture_output"] = kwargs.get("capture_output")
            captured["timeout"] = kwargs.get("timeout")
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.12, "duration_ms": 3500}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        ingest()

        assert captured["cmd"][0] == "claude"
        assert "-p" in captured["cmd"]
        assert "--output-format" in captured["cmd"]
        json_idx = captured["cmd"].index("--output-format")
        assert captured["cmd"][json_idx + 1] == "json"
        assert captured["cwd"] == str(home)
        assert captured["capture_output"] is True

    def test_result_has_cost_and_duration(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.345, "duration_ms": 7200}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        result = ingest()
        assert result["skipped"] is False
        assert result["sources_count"] == 1
        assert result["exit_code"] == 0
        assert result["cost_usd"] == pytest.approx(0.345)
        assert result["duration_ms"] == 7200

    def test_pages_changed_detected(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        from claude_bridge.wiki import wiki_home
        home = wiki_home()

        def fake_run(cmd, **kwargs):
            # Simulate Claude writing a new page + appending to log
            (home / "backend-patterns.md").write_text("# Backend Patterns\n")
            with open(home / "log.md", "a") as f:
                f.write("\n2026-04-19 | INGEST | backend → backend-patterns.md\n")
            return subprocess.CompletedProcess(
                cmd, 0, '{"total_cost_usd": 0.01, "duration_ms": 100}', ""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        result = ingest()
        assert "backend-patterns.md" in result["pages_changed"]
        assert "log.md" in result["pages_changed"]

    def test_operation_row_written(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0, '{"total_cost_usd": 0.05, "duration_ms": 500}', ""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        from claude_bridge.db import BridgeDB
        ingest()

        db = BridgeDB()
        try:
            rows = db.conn.execute(
                "SELECT operation, exit_code, cost_usd, sources_count "
                "FROM wiki_operations"
            ).fetchall()
        finally:
            db.close()
        assert len(rows) == 1
        assert rows[0]["operation"] == "INGEST"
        assert rows[0]["exit_code"] == 0
        assert rows[0]["cost_usd"] == pytest.approx(0.05)
        assert rows[0]["sources_count"] == 1


# ---------------------------------------------------------------------------
# Idempotency — skip when sources haven't advanced
# ---------------------------------------------------------------------------


class TestIngestIdempotency:
    def test_second_run_with_unchanged_sources_skips(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        call_count = {"n": 0}
        def fake_run(cmd, **kwargs):
            call_count["n"] += 1
            return subprocess.CompletedProcess(
                cmd, 0, '{"total_cost_usd": 0.01, "duration_ms": 100}', ""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        first = ingest()
        assert first["skipped"] is False
        assert call_count["n"] == 1

        second = ingest()
        assert second["skipped"] is True
        assert call_count["n"] == 1  # no new subprocess call

    def test_second_run_after_new_source_runs(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        call_count = {"n": 0}
        def fake_run(cmd, **kwargs):
            call_count["n"] += 1
            return subprocess.CompletedProcess(
                cmd, 0, '{"total_cost_usd": 0.01, "duration_ms": 100}', ""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        ingest()
        assert call_count["n"] == 1

        # Advance source mtime by touching the memory file
        time.sleep(0.01)
        encoded = os.path.normpath("/projects/api").replace("/", "-")
        mem_file = fake_home / ".claude" / "projects" / encoded / "memory" / "MEMORY.md"
        future = time.time() + 5
        os.utime(mem_file, (future, future))

        ingest()
        assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestIngestFailure:
    def test_non_zero_exit_preserves_stderr(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 2, "", stderr="claude CLI exploded\n"
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        result = ingest()
        assert result["skipped"] is False
        assert result["exit_code"] == 2
        assert "exploded" in result["stderr"]

    def test_failure_still_writes_operation_row(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 3, "", "oops")
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        from claude_bridge.db import BridgeDB
        ingest()

        db = BridgeDB()
        try:
            rows = db.conn.execute(
                "SELECT exit_code, stderr FROM wiki_operations"
            ).fetchall()
        finally:
            db.close()
        assert len(rows) == 1
        assert rows[0]["exit_code"] == 3
        assert "oops" in (rows[0]["stderr"] or "")

    def test_malformed_json_yields_zero_cost(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0, "not json at all", ""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        result = ingest()
        assert result["cost_usd"] == 0.0
        assert result["duration_ms"] == 0
        # Parse failure does not crash ingest
        assert result["exit_code"] == 0


# ---------------------------------------------------------------------------
# Agent filter
# ---------------------------------------------------------------------------


class TestIngestAgentFilter:
    def test_filter_narrows_sources_in_prompt(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _register_agent("frontend", "/projects/web")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Backend-only marker\n"})
        _seed_memory(fake_home, "/projects/web", {"MEMORY.md": "# Frontend-only marker\n"})

        captured = {}
        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(
                cmd, 0, '{"total_cost_usd": 0.01, "duration_ms": 100}', ""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        result = ingest(agent_filter="backend")

        # The prompt is a positional argv slot after -p
        dash_p_idx = captured["cmd"].index("-p")
        prompt = captured["cmd"][dash_p_idx + 1]
        assert "Backend-only marker" in prompt
        assert "Frontend-only marker" not in prompt
        assert result["sources_count"] == 1


# ---------------------------------------------------------------------------
# Prompt assembly — pure function, no subprocess
# ---------------------------------------------------------------------------


class TestAssemblePrompt:
    def test_contains_static_template_and_sections(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Learned\n- X\n"})

        from claude_bridge.wiki import wiki_home, collect_sources, _assemble_ingest_prompt
        wiki_home()
        sources = collect_sources()
        prompt = _assemble_ingest_prompt(sources)

        # Static template content
        assert "synthesis agent" in prompt
        # Runtime sections
        assert "## Current Schema" in prompt
        assert "## New Sources" in prompt
        # Source content appears
        assert "backend" in prompt


# ---------------------------------------------------------------------------
# Boundary — ingest() must not open files under ~/.claude/projects/
# ---------------------------------------------------------------------------


class TestIngestNeverWritesToClaudeMemory:
    def test_no_writes_under_claude_projects(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        opened_for_write: list[str] = []
        real_open = builtins.open

        def tracking_open(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and any(
                m in mode for m in ("w", "a", "x", "+")
            ):
                opened_for_write.append(os.fspath(file))
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", tracking_open)

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0, '{"total_cost_usd": 0.01, "duration_ms": 100}', ""
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        from claude_bridge.wiki import ingest
        ingest()

        forbidden_prefix = str(fake_home / ".claude" / "projects")
        violations = [p for p in opened_for_write if p.startswith(forbidden_prefix)]
        assert not violations, f"ingest() wrote under forbidden path(s): {violations}"


# ---------------------------------------------------------------------------
# Integration — opt-in, uses the real `claude` CLI
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("CLAUDE_BRIDGE_RUN_INTEGRATION"),
    reason="integration test — set CLAUDE_BRIDGE_RUN_INTEGRATION=1 to enable",
)
class TestIngestRealClaude:
    def test_real_claude_ingest(self, tmp_path, monkeypatch):
        """Opt-in: requires `CLAUDE_BRIDGE_RUN_INTEGRATION=1` and a
        working `claude` CLI login. Proves the subprocess contract
        end-to-end against the real claude CLI.
        """
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {
            "MEMORY.md": "# Backend\n- Use Pydantic v2\n- Rate limit 60rpm per key\n",
        })

        from claude_bridge.wiki import ingest
        result = ingest()
        assert result["exit_code"] == 0
        assert result["sources_count"] >= 1
        # Real claude ran — cost should be non-zero
        assert result["cost_usd"] > 0
