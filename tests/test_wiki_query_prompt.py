"""Tests for M25.T2 — wiki_query.md prompt template (structural + SHA pin)."""

from __future__ import annotations

import hashlib
from importlib import resources


EXPECTED_SHA = "0cbc1ba598228d056120827119e2bdddb67bdf419172bd976ce223d1956ba82f"


def _load() -> str:
    return (
        resources.files("claude_bridge.prompts")
        .joinpath("wiki_query.md")
        .read_text(encoding="utf-8")
    )


class TestLoadable:
    def test_file_exists_and_non_empty(self):
        assert _load().strip()


class TestCitationContract:
    def test_mentions_source_citation_format(self):
        content = _load()
        assert "[Source:" in content
        assert ".md]" in content or ".md" in content

    def test_instructs_inline_citations(self):
        content = _load().lower()
        assert "cit" in content


class TestNoToolInvocation:
    def test_explicitly_forbids_tools(self):
        content = _load().lower()
        assert "do not invoke" in content or "no tool" in content


class TestFidelity:
    def test_warns_against_hallucination(self):
        content = _load().lower()
        assert "never invent" in content or "never fill" in content \
            or "do not" in content and "plausible" in content


class TestExamples:
    def test_has_two_good_and_two_bad_markers(self):
        content = _load()
        good = content.count("✓") + content.lower().count("good example")
        bad = content.count("✗") + content.lower().count("bad example")
        assert good >= 2, f"expected >= 2 good markers, found {good}"
        assert bad >= 2, f"expected >= 2 bad markers, found {bad}"


class TestSnapshot:
    def test_sha_matches_pinned(self):
        actual = hashlib.sha256(_load().encode("utf-8")).hexdigest()
        assert actual == EXPECTED_SHA, (
            f"wiki_query.md changed. If intentional, update EXPECTED_SHA to: {actual}"
        )
