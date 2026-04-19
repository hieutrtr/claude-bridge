"""Tests for M25.T2 — wiki.query() runtime."""

from __future__ import annotations

import builtins
import os
import subprocess

import pytest


def _setup_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))


def _seed_page(home, name, content):
    (home / name).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Empty retrieve → structured empty answer, no subprocess
# ---------------------------------------------------------------------------


class TestQueryEmptyRetrieve:
    def test_empty_wiki_returns_empty_result(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        wiki_home()

        result = query("anything")
        assert result["empty"] is True
        assert result["answer"]
        assert "wiki" in result["answer"].lower()
        assert result["pages_retrieved"] == []
        assert result["sources_cited"] == []
        assert result["cost_usd"] == 0.0

    def test_empty_retrieve_does_not_call_subprocess(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        wiki_home()

        calls: list = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        monkeypatch.setattr(subprocess, "run", fake_run)

        query("anything")
        assert calls == []

    def test_empty_retrieve_writes_no_operation_row(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        from claude_bridge.db import BridgeDB
        wiki_home()

        query("anything")

        db = BridgeDB()
        try:
            row = db.conn.execute(
                "SELECT COUNT(*) AS n FROM wiki_operations"
            ).fetchone()
        finally:
            db.close()
        assert row["n"] == 0


# ---------------------------------------------------------------------------
# Happy path — retrieve, subprocess, parse
# ---------------------------------------------------------------------------


class TestQueryHappyPath:
    def test_subprocess_invoked_with_expected_args(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md",
                   "# API\n\n## Rate Limiting\n\n60rpm per key.\n")

        captured: dict = {}
        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.02, "duration_ms": 1200, '
                       '"result": "Rate limit is 60rpm [Source: api.md]."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        query("rate limiting")
        assert captured["cmd"][0] == "claude"
        assert "-p" in captured["cmd"]
        assert "--output-format" in captured["cmd"]
        assert captured["cwd"] == str(home)

    def test_result_has_answer_and_citations(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md",
                   "# API\n\n## Rate Limiting\n\n60rpm per key.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.02, "duration_ms": 1200, '
                       '"result": "Rate limit is 60rpm per API key '
                       '[Source: api.md]. Applied at the middleware '
                       '[Source: api.md]."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        result = query("rate limiting")
        assert result["empty"] is False
        assert "60rpm" in result["answer"]
        assert result["sources_cited"] == ["api.md"]
        assert "api.md" in result["pages_retrieved"]
        assert result["cost_usd"] == 0.02
        assert result["duration_ms"] == 1200
        assert result["exit_code"] == 0

    def test_operation_row_written(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        from claude_bridge.db import BridgeDB
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## R\n\nStuff.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.03, "duration_ms": 500, '
                       '"result": "Answer [Source: api.md]."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        query("stuff")
        db = BridgeDB()
        try:
            rows = db.conn.execute(
                "SELECT operation, exit_code, cost_usd FROM wiki_operations"
            ).fetchall()
        finally:
            db.close()
        assert len(rows) == 1
        assert rows[0]["operation"] == "QUERY"
        assert rows[0]["cost_usd"] == pytest.approx(0.03)


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------


class TestCitationExtraction:
    def test_dedupes_repeated_citation(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## R\n\nstuff\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100, '
                       '"result": "Fact A [Source: api.md]. '
                       'Fact B [Source: api.md]."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        result = query("stuff")
        assert result["sources_cited"] == ["api.md"]

    def test_preserves_first_occurrence_order(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "auth.md", "# Auth\n\n## S\n\nauth content.\n")
        _seed_page(home, "sessions.md", "# Sessions\n\n## S\n\nsession content.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100, '
                       '"result": "Tokens [Source: sessions.md]. '
                       'Check [Source: auth.md]. '
                       'Again [Source: sessions.md]."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        result = query("auth sessions")
        assert result["sources_cited"] == ["sessions.md", "auth.md"]

    def test_citation_to_unretrieved_page_filtered_out(self, tmp_path, monkeypatch):
        """Guards against false positives when the answer echoes a
        literal [Source: foo.md] example from inside a code fence that
        doesn't correspond to a retrieved page."""
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## R\n\nstuff.\n")

        def fake_run(cmd, **kwargs):
            # Claude's answer cites api.md (real) and also page.md (not retrieved)
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100, '
                       '"result": "real claim [Source: api.md]. '
                       'The wiki uses [Source: page.md] format."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        result = query("stuff")
        assert result["sources_cited"] == ["api.md"], \
            f"expected only api.md, got {result['sources_cited']}"

    def test_no_citations_yields_empty_list(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## R\n\nstuff.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100, '
                       '"result": "Answer with no citations."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        result = query("stuff")
        assert result["sources_cited"] == []


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestQueryFailure:
    def test_non_zero_exit_preserves_stderr(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## R\n\nstuff.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 2, "", "claude exploded")
        monkeypatch.setattr(subprocess, "run", fake_run)

        result = query("stuff")
        assert result["exit_code"] == 2
        assert "exploded" in result["stderr"]

    def test_failure_writes_operation_row(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        from claude_bridge.db import BridgeDB
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## R\n\nstuff.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 3, "", "boom")
        monkeypatch.setattr(subprocess, "run", fake_run)

        query("stuff")

        db = BridgeDB()
        try:
            rows = db.conn.execute(
                "SELECT exit_code, stderr FROM wiki_operations"
            ).fetchall()
        finally:
            db.close()
        assert len(rows) == 1
        assert rows[0]["exit_code"] == 3


# ---------------------------------------------------------------------------
# Read-only — query never writes under wiki or Auto Memory
# ---------------------------------------------------------------------------


class TestQueryReadOnly:
    def test_no_writes_under_wiki_home(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## R\n\nstuff.\n")

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
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100, '
                       '"result": "answer [Source: api.md]"}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        query("stuff")

        wiki_prefix = str(home)
        writes_in_wiki = [p for p in opened_for_write if p.startswith(wiki_prefix)]
        assert writes_in_wiki == [], \
            f"query() wrote to wiki files: {writes_in_wiki}"


# ---------------------------------------------------------------------------
# Integration — opt-in
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("CLAUDE_BRIDGE_RUN_INTEGRATION"),
    reason="integration test — set CLAUDE_BRIDGE_RUN_INTEGRATION=1 to enable",
)
class TestQueryRealClaude:
    def test_real_claude_query(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import query, wiki_home
        home = wiki_home()
        _seed_page(home, "rate-limiting.md",
                   "# Rate Limiting\n\n## Summary\n\n"
                   "We use a token bucket of 60 requests per minute, "
                   "scoped per API key.\n")

        result = query("what is the rate limit?")
        assert result["exit_code"] == 0
        assert result["empty"] is False
        assert result["cost_usd"] > 0
        assert "60" in result["answer"] or "rate" in result["answer"].lower()
