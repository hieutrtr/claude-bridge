"""Tests for M24.T1 — wiki_ingest.md prompt template.

Pinned-snapshot tests: EXPECTED_SHA is updated only when the template
changes deliberately. A silent edit to wiki_ingest.md fails this suite.
"""

from __future__ import annotations

import hashlib
from importlib import resources


# Update this constant when wiki_ingest.md is intentionally changed.
# The failure message points at the new value so authors can paste it in.
EXPECTED_SHA = "df8946c6d4e532fab5509bc35558d49d364f21677396548ed770dc62e5352e15"


def _load() -> str:
    return (
        resources.files("claude_bridge.prompts")
        .joinpath("wiki_ingest.md")
        .read_text(encoding="utf-8")
    )


class TestLoadable:
    def test_file_exists_and_non_empty(self):
        content = _load()
        assert content.strip(), "wiki_ingest.md is empty"


class TestToolAllowlist:
    def test_names_read_tool(self):
        assert "Read" in _load()

    def test_names_edit_or_write_tool(self):
        content = _load()
        assert "Edit" in content or "Write" in content

    def test_excludes_bash(self):
        # Bash is not allowed for synthesis
        content = _load()
        assert " Bash" not in content and "`Bash`" not in content

    def test_excludes_webfetch(self):
        content = _load()
        assert "WebFetch" not in content

    def test_excludes_task_tool(self):
        content = _load()
        # Avoid false positives: "task" as a noun is fine, but "Task" as a tool is not
        assert "`Task`" not in content


class TestBoundary:
    def test_mentions_wiki_home_boundary(self):
        content = _load().lower()
        # Accept "wiki home", "wiki/", or "inside the wiki"
        assert any(token in content for token in ("wiki home", "wiki/", "inside the wiki"))

    def test_mentions_never_writing_outside(self):
        content = _load().lower()
        # Some wording asserting the boundary
        assert "never" in content or "only inside" in content or "outside" in content


class TestLogLineFormat:
    def test_has_iso_date_placeholder(self):
        assert "YYYY-MM-DD" in _load()

    def test_has_ingest_token(self):
        assert "INGEST" in _load()

    def test_shows_log_format_example(self):
        content = _load()
        # Format: YYYY-MM-DD | INGEST | <sources> → <pages>
        assert "YYYY-MM-DD | INGEST" in content


class TestTemplateSections:
    def test_mentions_page_template_sections(self):
        content = _load()
        for section in ("Summary", "Key Facts", "Cross-references", "Open Questions"):
            assert section in content, f"wiki_ingest.md missing section reference: {section}"


class TestExamples:
    def test_has_at_least_two_good_markers(self):
        content = _load()
        # Accept ✓ or the literal phrase "Good example"
        count = content.count("✓") + content.lower().count("good example")
        assert count >= 2, f"expected >= 2 good-example markers, found {count}"

    def test_has_at_least_two_bad_markers(self):
        content = _load()
        count = content.count("✗") + content.lower().count("bad example")
        assert count >= 2, f"expected >= 2 bad-example markers, found {count}"


class TestSnapshot:
    def test_template_hash_matches_pinned_sha(self):
        """Pin the exact template bytes. When you deliberately change
        wiki_ingest.md, run this test and update EXPECTED_SHA to the
        value printed in the failure message.
        """
        content = _load()
        actual = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert actual == EXPECTED_SHA, (
            f"wiki_ingest.md changed. If intentional, update EXPECTED_SHA "
            f"to: {actual}"
        )


class TestSchemaTemplateStillLoads:
    """Refactor guard — _load_schema_template must still work after M24.T1
    generalizes it into _load_template(name)."""

    def test_schema_template_content_is_stable(self):
        from claude_bridge.wiki import _load_schema_template

        content = _load_schema_template()
        assert "Karpathy" in content
        assert "Summary" in content
