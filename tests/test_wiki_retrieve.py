"""Tests for M25.T1 — wiki.retrieve (grep + token-overlap rank)."""

from __future__ import annotations

import os
import time

import pytest


def _setup_sandbox(tmp_path, monkeypatch):
    """Minimal env setup — only CLAUDE_BRIDGE_HOME needed for retrieve."""
    monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))


def _seed_page(home, name, content):
    (home / name).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


class TestRetrieveEmpty:
    def test_fresh_wiki_returns_empty(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        wiki_home()  # triggers seed

        assert retrieve("anything") == []

    def test_only_operational_pages_returns_empty(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        # schema, index, log are seeded; the words in them must never surface
        # as answers — even if the question literally says "Karpathy"
        assert retrieve("Karpathy") == []

    def test_empty_question_returns_empty(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## Details\n\nSomething.\n")
        # Only stopwords → empty token set → empty result
        assert retrieve("the of and") == []


# ---------------------------------------------------------------------------
# Happy path — scoring, ordering, top_k
# ---------------------------------------------------------------------------


class TestRetrieveHappyPath:
    def test_single_match_returned(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "rate-limiting.md",
                   "# Rate Limiting\n\n## Summary\n\nToken bucket per API key.\n")

        results = retrieve("rate limiting")
        assert len(results) == 1
        r = results[0]
        assert r["path"] == "rate-limiting.md"
        assert r["score"] > 0
        assert r["title"] == "Rate Limiting"

    def test_multiple_pages_ranked_by_score(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        # "rate" in title of page A (weight 3)
        _seed_page(home, "rate-limiting.md",
                   "# Rate Limiting\n\n## Summary\n\nA token bucket pattern.\n")
        # "rate" only in body of page B (weight 1)
        _seed_page(home, "throughput.md",
                   "# Throughput\n\n## Notes\n\nRate calculations.\n")

        results = retrieve("rate")
        assert len(results) == 2
        assert results[0]["path"] == "rate-limiting.md"
        assert results[1]["path"] == "throughput.md"
        assert results[0]["score"] > results[1]["score"]

    def test_top_k_caps_results(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        for i in range(5):
            _seed_page(home, f"page-{i}.md",
                       f"# Page {i}\n\nThe auth topic appears here.\n")

        results = retrieve("auth", top_k=2)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------


class TestScoringWeights:
    def test_title_match_outranks_body_match(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "auth.md",
                   "# Authentication\n\n## Summary\n\nLong prose about sessions.\n")
        _seed_page(home, "sessions.md",
                   "# Sessions\n\n## Summary\n\nOne passing mention of authentication.\n")

        results = retrieve("authentication")
        assert results[0]["path"] == "auth.md", \
            f"title match should win; got {results[0]['path']}"

    def test_header_match_outranks_body_match(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "a.md",
                   "# A\n\n## Migration\n\nPage about migrations.\n")
        _seed_page(home, "b.md",
                   "# B\n\n## Other\n\nBriefly notes migration somewhere.\n")

        results = retrieve("migration")
        assert results[0]["path"] == "a.md", \
            f"header match should win; got {results[0]['path']}"


# ---------------------------------------------------------------------------
# Tiebreak — newer mtime wins
# ---------------------------------------------------------------------------


class TestTiebreak:
    def test_newer_page_wins_on_score_tie(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "old.md", "# Shared\n\nRate topic.\n")
        _seed_page(home, "new.md", "# Shared\n\nRate topic.\n")

        older = time.time() - 3600
        newer = time.time()
        os.utime(home / "old.md", (older, older))
        os.utime(home / "new.md", (newer, newer))

        results = retrieve("rate")
        assert len(results) == 2
        assert results[0]["path"] == "new.md", \
            f"newer page should win tiebreak; got {results[0]['path']}"


# ---------------------------------------------------------------------------
# Excerpts
# ---------------------------------------------------------------------------


class TestExcerpt:
    def test_excerpt_from_matched_header_section(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md",
                   "# API\n\n## Overview\n\nGeneric description.\n\n"
                   "## Rate Limiting\n\nToken bucket of 60rpm per key.\n"
                   "Applies to all authenticated endpoints.\n")

        results = retrieve("rate limiting")
        assert len(results) == 1
        excerpt = results[0]["excerpt"]
        assert "Token bucket" in excerpt, f"excerpt missing match: {excerpt!r}"

    def test_excerpt_when_no_header_matched_falls_back(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        # Token only appears in body, not in any header
        _seed_page(home, "notes.md",
                   "# Notes\n\n## Summary\n\nA casual reference to webhooks here.\n")

        results = retrieve("webhooks")
        assert len(results) == 1
        excerpt = results[0]["excerpt"]
        assert excerpt  # non-empty
        # Either title or first body line must appear
        assert "Notes" in excerpt or "webhooks" in excerpt.lower()


# ---------------------------------------------------------------------------
# Exclusions — operational pages never appear
# ---------------------------------------------------------------------------


class TestExclusions:
    def test_schema_never_returned(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        wiki_home()

        # schema.md contains the word "Karpathy" — but must never be returned
        assert retrieve("Karpathy") == []

    def test_log_and_index_never_returned(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        # Write something identifiable into log/index
        (home / "log.md").write_text("# Wiki Log\n\nSentinelToken appears here.\n")
        (home / "index.md").write_text("# Wiki Index\n\nSentinelToken also here.\n")

        assert retrieve("SentinelToken") == []


# ---------------------------------------------------------------------------
# Unicode
# ---------------------------------------------------------------------------


class TestUnicode:
    def test_vietnamese_content_matches(self, tmp_path, monkeypatch):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "xu-ly.md",
                   "# Xử lý lỗi\n\n## Tổng quan\n\nXử lý ngoại lệ trong Python.\n")

        results = retrieve("xử lý")
        assert len(results) == 1
        assert results[0]["path"] == "xu-ly.md"


# ---------------------------------------------------------------------------
# Stopwords
# ---------------------------------------------------------------------------


class TestStopwords:
    def test_question_with_stopwords_matches_same_as_bare_term(
        self, tmp_path, monkeypatch
    ):
        _setup_sandbox(tmp_path, monkeypatch)
        from claude_bridge.wiki import retrieve, wiki_home
        home = wiki_home()
        _seed_page(home, "api.md", "# API\n\n## Summary\n\nREST endpoints.\n")

        r1 = retrieve("api")
        r2 = retrieve("the api")
        assert r1[0]["path"] == r2[0]["path"]
        assert r1[0]["score"] == r2[0]["score"]
