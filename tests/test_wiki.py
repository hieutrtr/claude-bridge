"""Tests for M23.T1 — Wiki home + schema seed.

Covers wiki_home(), safe_write(), safe_read(), and the seeded schema/index/log
bundled at src/claude_bridge/prompts/wiki_schema_template.md.

These tests fail until src/claude_bridge/wiki.py exists. That's intentional (TDD).
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# wiki_home() — lazy init, idempotency, env-var override
# ---------------------------------------------------------------------------


class TestWikiHome:
    def test_returns_path_under_bridge_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        result = wiki_home()
        assert isinstance(result, Path)
        assert result == tmp_path / "wiki"

    def test_first_call_creates_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        assert not (tmp_path / "wiki").exists()
        wiki_home()
        assert (tmp_path / "wiki").is_dir()

    def test_first_call_seeds_schema_index_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        home = wiki_home()
        assert (home / "schema.md").is_file()
        assert (home / "index.md").is_file()
        assert (home / "log.md").is_file()

    def test_schema_contains_expected_sections(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        schema = (wiki_home() / "schema.md").read_text()
        # Attribution
        assert "Karpathy" in schema
        # Operations
        for op in ("Ingest", "Query", "Lint"):
            assert op in schema, f"schema.md missing operation: {op}"
        # Template fields
        for section in ("Summary", "Key Facts", "Cross-references", "Open Questions"):
            assert section in schema, f"schema.md missing template section: {section}"
        # Cross-ref convention
        assert "[[" in schema and "]]" in schema
        # Naming convention hint
        assert "kebab-case" in schema or "kebab case" in schema.lower()

    def test_index_has_last_updated_iso_date(self, tmp_path, monkeypatch):
        import re

        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        index = (wiki_home() / "index.md").read_text()
        assert "# Wiki Index" in index
        assert re.search(r"Last updated:\s*\d{4}-\d{2}-\d{2}", index)

    def test_log_is_header_only_initially(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        log = (wiki_home() / "log.md").read_text()
        assert "# Wiki Log" in log
        # No ingest/query/lint entries yet
        assert "| INGEST |" not in log
        assert "| QUERY |" not in log
        assert "| LINT |" not in log


# ---------------------------------------------------------------------------
# Idempotency — never overwrite user edits
# ---------------------------------------------------------------------------


class TestIdempotentInit:
    def test_second_call_does_not_rewrite_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        home = wiki_home()
        custom = "# My Custom Schema\n\nUser edited this.\n"
        (home / "schema.md").write_text(custom)

        wiki_home()  # re-init
        assert (home / "schema.md").read_text() == custom

    def test_second_call_does_not_rewrite_index(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        home = wiki_home()
        custom = "# Custom index\n"
        (home / "index.md").write_text(custom)

        wiki_home()
        assert (home / "index.md").read_text() == custom

    def test_second_call_does_not_rewrite_log(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import wiki_home

        home = wiki_home()
        with_entry = (home / "log.md").read_text() + "\n2026-04-19 | INGEST | test\n"
        (home / "log.md").write_text(with_entry)

        wiki_home()
        assert (home / "log.md").read_text() == with_entry


# ---------------------------------------------------------------------------
# safe_write() — happy path, overwrite, nested dirs
# ---------------------------------------------------------------------------


class TestSafeWriteHappyPath:
    def test_writes_to_wiki_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write, wiki_home

        path = safe_write("foo.md", "hello")
        assert path == (wiki_home() / "foo.md").resolve()
        assert path.read_text() == "hello"

    def test_creates_parent_directories(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write, wiki_home

        path = safe_write("entities/api/patterns.md", "x")
        assert path.read_text() == "x"
        assert (wiki_home() / "entities" / "api").is_dir()

    def test_overwrite_false_rejects_existing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write

        safe_write("foo.md", "first")
        with pytest.raises(FileExistsError):
            safe_write("foo.md", "second")

    def test_overwrite_true_replaces(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write

        safe_write("foo.md", "first")
        path = safe_write("foo.md", "second", overwrite=True)
        assert path.read_text() == "second"


# ---------------------------------------------------------------------------
# safe_read() — happy path
# ---------------------------------------------------------------------------


class TestSafeRead:
    def test_reads_seeded_schema(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_read, wiki_home

        wiki_home()  # trigger seed
        content = safe_read("schema.md")
        assert "Karpathy" in content

    def test_read_missing_raises_filenotfound(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_read, wiki_home

        wiki_home()
        with pytest.raises(FileNotFoundError):
            safe_read("nonexistent.md")


# ---------------------------------------------------------------------------
# Path-boundary guard — the load-bearing security property
# ---------------------------------------------------------------------------


class TestBoundaryGuard:
    def test_parent_traversal_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write

        with pytest.raises(ValueError):
            safe_write("../outside.md", "x")

    def test_deep_traversal_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write

        with pytest.raises(ValueError):
            safe_write("../../../../etc/passwd", "x")

    def test_absolute_path_outside_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write

        escape = tmp_path.parent / "escape.md"
        with pytest.raises(ValueError):
            safe_write(str(escape), "x")

    def test_safe_read_rejects_traversal(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_read, wiki_home

        wiki_home()
        with pytest.raises(ValueError):
            safe_read("../../../etc/passwd")

    def test_symlink_escape_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        from claude_bridge.wiki import safe_write, wiki_home

        home = wiki_home()
        outside = tmp_path.parent / "outside_target"
        outside.mkdir(exist_ok=True)
        link = home / "escape"
        link.symlink_to(outside)

        # Writing through the symlink must be rejected because the
        # resolved path is outside wiki home.
        with pytest.raises(ValueError):
            safe_write("escape/pwned.md", "x")


# ---------------------------------------------------------------------------
# The ownership-boundary invariant: never write to Claude Code's memory
# ---------------------------------------------------------------------------


class TestNeverWritesToClaudeMemory:
    def test_init_does_not_touch_claude_projects(self, tmp_path, monkeypatch):
        """wiki_home() init must not write anywhere under ~/.claude/projects/."""
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))

        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        (fake_home / ".claude" / "projects").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        opened_for_write: list[str] = []
        real_open = builtins.open

        def tracking_open(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and any(
                m in mode for m in ("w", "a", "x", "+")
            ):
                opened_for_write.append(os.fspath(file))
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", tracking_open)

        from claude_bridge.wiki import wiki_home

        wiki_home()

        forbidden_prefix = str(fake_home / ".claude" / "projects")
        violations = [p for p in opened_for_write if p.startswith(forbidden_prefix)]
        assert not violations, f"wiki_home() wrote to forbidden path(s): {violations}"

    def test_safe_write_does_not_touch_claude_projects(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(tmp_path))
        fake_home = tmp_path / "fake_home"
        fake_home.mkdir()
        (fake_home / ".claude" / "projects").mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))

        opened_for_write: list[str] = []
        real_open = builtins.open

        def tracking_open(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and any(
                m in mode for m in ("w", "a", "x", "+")
            ):
                opened_for_write.append(os.fspath(file))
            return real_open(file, mode, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", tracking_open)

        from claude_bridge.wiki import safe_write

        safe_write("entities/foo.md", "x")

        forbidden_prefix = str(fake_home / ".claude" / "projects")
        violations = [p for p in opened_for_write if p.startswith(forbidden_prefix)]
        assert not violations, f"safe_write wrote to forbidden path(s): {violations}"


# ---------------------------------------------------------------------------
# CLAUDE_BRIDGE_HOME override is honored end-to-end
# ---------------------------------------------------------------------------


class TestCustomBridgeHome:
    def test_custom_home_redirects_wiki(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom-bridge"
        monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(custom))
        from claude_bridge.wiki import wiki_home

        home = wiki_home()
        assert home == custom / "wiki"
        assert (home / "schema.md").is_file()


# ---------------------------------------------------------------------------
# M23.T2 — collect_sources(): fan out across agents, read Auto Memory,
# compute source_mtime, never write to ~/.claude/projects/.
# ---------------------------------------------------------------------------


def _setup_env(tmp_path, monkeypatch):
    """Set CLAUDE_BRIDGE_HOME and HOME to tmp_path subdirs."""
    bridge_home = tmp_path / "bridge"
    fake_home = tmp_path / "home"
    bridge_home.mkdir(parents=True, exist_ok=True)
    fake_home.mkdir(parents=True, exist_ok=True)
    (fake_home / ".claude" / "projects").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_BRIDGE_HOME", str(bridge_home))
    monkeypatch.setenv("HOME", str(fake_home))
    return bridge_home, fake_home


def _register_agent(name, project_dir, model="sonnet"):
    """Insert an agent into the default BridgeDB."""
    from claude_bridge.db import BridgeDB

    db = BridgeDB()
    session_id = f"{name}--{os.path.basename(project_dir)}"
    db.create_agent(
        name=name,
        project_dir=project_dir,
        session_id=session_id,
        agent_file=f"/fake/agents/bridge--{session_id}.md",
        purpose="",
        model=model,
    )
    db.close()


def _seed_memory(fake_home, project_dir, files: dict):
    """Write Auto Memory files for the given project under fake_home."""
    encoded = os.path.normpath(project_dir).replace("/", "-")
    mem_dir = fake_home / ".claude" / "projects" / encoded / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    for fname, content in files.items():
        (mem_dir / fname).write_text(content)
    return mem_dir


class TestCollectSourcesEmpty:
    def test_no_agents_returns_empty_list(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        from claude_bridge.wiki import collect_sources

        assert collect_sources() == []

    def test_filter_for_nonexistent_agent_returns_empty(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        from claude_bridge.wiki import collect_sources

        assert collect_sources(agent_filter="frontend") == []


class TestCollectSourcesHappyPath:
    def test_returns_records_for_all_agents_with_memory(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _register_agent("frontend", "/projects/web")
        _seed_memory(fake_home, "/projects/api", {
            "MEMORY.md": "# Backend\n- Use Pydantic\n",
            "testing.md": "# Testing\nUse pytest\n",
        })
        _seed_memory(fake_home, "/projects/web", {
            "MEMORY.md": "# Frontend\n- Use React\n",
        })
        from claude_bridge.wiki import collect_sources

        records = collect_sources()
        assert len(records) == 2
        by_name = {r["agent"]: r for r in records}
        assert set(by_name.keys()) == {"backend", "frontend"}
        assert by_name["backend"]["found"] is True
        assert "Pydantic" in by_name["backend"]["main_memory"]
        assert any("pytest" in t["content"] for t in by_name["backend"]["topics"])
        assert by_name["frontend"]["main_memory"].startswith("# Frontend")
        assert by_name["frontend"]["topics"] == []

    def test_record_has_session_id(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        from claude_bridge.wiki import collect_sources

        [record] = collect_sources()
        assert record["session_id"] == "backend--api"

    def test_filter_narrows_to_one_agent(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _register_agent("frontend", "/projects/web")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "x"})
        _seed_memory(fake_home, "/projects/web", {"MEMORY.md": "y"})
        from claude_bridge.wiki import collect_sources

        records = collect_sources(agent_filter="backend")
        assert len(records) == 1
        assert records[0]["agent"] == "backend"


class TestCollectSourcesMissingMemory:
    def test_agent_without_memory_returns_not_found_record(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        from claude_bridge.wiki import collect_sources

        [record] = collect_sources()
        assert record["agent"] == "backend"
        assert record["found"] is False
        assert record["main_memory"] == ""
        assert record["topics"] == []
        assert record["source_mtime"] is None
        assert record["memory_dir"] is None

    def test_empty_memory_dir_has_none_mtime(self, tmp_path, monkeypatch):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        # Create empty memory dir (no .md files)
        _seed_memory(fake_home, "/projects/api", {})
        from claude_bridge.wiki import collect_sources

        [record] = collect_sources()
        assert record["found"] is True
        assert record["source_mtime"] is None


class TestCollectSourcesMtime:
    def test_mtime_is_max_across_memory_files(self, tmp_path, monkeypatch):
        import time as _time

        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        mem_dir = _seed_memory(fake_home, "/projects/api", {
            "MEMORY.md": "# Main\n",
            "topic_a.md": "A\n",
            "topic_b.md": "B\n",
        })

        # Backdate MEMORY.md and topic_a; leave topic_b as "now"
        older = _time.time() - 3600
        os.utime(mem_dir / "MEMORY.md", (older, older))
        os.utime(mem_dir / "topic_a.md", (older, older))
        newest = _time.time()
        os.utime(mem_dir / "topic_b.md", (newest, newest))

        from claude_bridge.wiki import collect_sources
        [record] = collect_sources()

        assert record["source_mtime"] is not None
        assert record["source_mtime"] == pytest.approx(newest, abs=1.0)

    def test_mtime_ignores_non_md_files(self, tmp_path, monkeypatch):
        import time as _time

        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        mem_dir = _seed_memory(fake_home, "/projects/api", {
            "MEMORY.md": "# Main\n",
        })
        # Add a non-md file with a much newer mtime — must be ignored
        junk = mem_dir / "notes.txt"
        junk.write_text("ignore me")
        future = _time.time() + 10_000
        os.utime(junk, (future, future))

        from claude_bridge.wiki import collect_sources
        [record] = collect_sources()

        assert record["source_mtime"] is not None
        assert record["source_mtime"] < future - 100


class TestCollectSourcesNeverWritesToClaudeMemory:
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

        from claude_bridge.wiki import collect_sources
        collect_sources()

        forbidden_prefix = str(fake_home / ".claude" / "projects")
        violations = [p for p in opened_for_write if p.startswith(forbidden_prefix)]
        assert not violations, f"collect_sources wrote to forbidden path(s): {violations}"


class TestCollectSourcesDependencyInjection:
    def test_injected_db_is_used_and_not_closed(self, tmp_path, monkeypatch):
        """collect_sources(db=injected) uses the caller's db and must not close it."""
        _setup_env(tmp_path, monkeypatch)
        from claude_bridge.db import BridgeDB
        from claude_bridge.wiki import collect_sources

        db = BridgeDB()
        try:
            # Inject; expect [] because no agents
            assert collect_sources(db=db) == []
            # The caller's db must still be usable afterwards
            assert db.list_agents() == []
        finally:
            db.close()

    def test_default_db_is_created_when_none(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        from claude_bridge.wiki import collect_sources

        # No db injected — collector creates its own
        records = collect_sources()
        assert len(records) == 1
        assert records[0]["agent"] == "backend"


class TestCollectSourcesOrdering:
    def test_records_preserve_list_agents_order(self, tmp_path, monkeypatch):
        _setup_env(tmp_path, monkeypatch)
        _register_agent("alpha", "/projects/a")
        _register_agent("beta", "/projects/b")
        _register_agent("gamma", "/projects/c")

        from claude_bridge.db import BridgeDB
        from claude_bridge.wiki import collect_sources

        db = BridgeDB()
        try:
            expected = [row["name"] for row in db.list_agents()]
        finally:
            db.close()

        records = collect_sources()
        assert [r["agent"] for r in records] == expected
