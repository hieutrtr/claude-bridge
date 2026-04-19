"""Tests for M25.T3 — MCP wiki_query tool."""

from __future__ import annotations

import json
import subprocess

import pytest


def _setup_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))


def _seed_page(home, name, content):
    (home / name).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestInputValidation:
    def test_empty_question_returns_error(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.mcp_tools import tool_wiki_query
        from claude_bridge.db import BridgeDB

        db = BridgeDB()
        try:
            result = json.loads(tool_wiki_query(db, ""))
        finally:
            db.close()
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_whitespace_only_question_returns_error(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.mcp_tools import tool_wiki_query
        from claude_bridge.db import BridgeDB

        db = BridgeDB()
        try:
            result = json.loads(tool_wiki_query(db, "   \t  \n  "))
        finally:
            db.close()
        assert "error" in result


# ---------------------------------------------------------------------------
# Empty wiki → empty-state JSON
# ---------------------------------------------------------------------------


class TestEmptyWiki:
    def test_empty_wiki_returns_empty_true(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.mcp_tools import tool_wiki_query
        from claude_bridge.wiki import wiki_home
        from claude_bridge.db import BridgeDB
        wiki_home()

        db = BridgeDB()
        try:
            result = json.loads(tool_wiki_query(db, "what is X?"))
        finally:
            db.close()
        assert result["empty"] is True
        assert result["answer"]
        assert result["sources_cited"] == []


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_full_json_payload(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.mcp_tools import tool_wiki_query
        from claude_bridge.wiki import wiki_home
        from claude_bridge.db import BridgeDB

        home = wiki_home()
        _seed_page(home, "api.md",
                   "# API\n\n## Rate Limiting\n\n60rpm per key.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.04, "duration_ms": 900, '
                       '"result": "60rpm per key [Source: api.md]."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        db = BridgeDB()
        try:
            raw = tool_wiki_query(db, "rate limiting")
        finally:
            db.close()
        result = json.loads(raw)
        # All documented keys
        for k in ("answer", "sources_cited", "pages_retrieved",
                  "cost_usd", "duration_ms", "empty", "exit_code"):
            assert k in result, f"missing key: {k}"
        assert result["empty"] is False
        assert "60rpm" in result["answer"]
        assert result["sources_cited"] == ["api.md"]
        assert "api.md" in result["pages_retrieved"]
        assert result["cost_usd"] == 0.04
        assert result["exit_code"] == 0

    def test_top_k_is_respected(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.mcp_tools import tool_wiki_query
        from claude_bridge.wiki import wiki_home
        from claude_bridge.db import BridgeDB

        home = wiki_home()
        for i in range(5):
            _seed_page(home, f"page-{i}.md",
                       f"# Page {i}\n\n## Summary\n\nauth content.\n")

        captured = {"top_k": None}
        import claude_bridge.wiki as wiki_mod
        real_query = wiki_mod.query

        def capturing_query(question, top_k=5, db=None):
            captured["top_k"] = top_k
            return real_query(question, top_k=top_k, db=db)

        monkeypatch.setattr(wiki_mod, "query", capturing_query)

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100, '
                       '"result": "x [Source: page-0.md]"}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        db = BridgeDB()
        try:
            tool_wiki_query(db, "auth", top_k=2)
        finally:
            db.close()
        assert captured["top_k"] == 2


# ---------------------------------------------------------------------------
# Server registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_wiki_query_listed_in_tool_names(self):
        from claude_bridge.mcp_server import TOOL_NAMES
        assert "wiki_query" in TOOL_NAMES
