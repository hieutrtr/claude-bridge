"""Tests for M24.T3 — `bridge-cli wiki ingest` CLI command.

Invokes main() from claude_bridge.cli with sys.argv patched; captures
stdout/stderr via pytest capsys. subprocess.run to the real `claude`
CLI is stubbed throughout.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from .test_wiki import _setup_env, _register_agent, _seed_memory


def _run_cli(argv: list[str], monkeypatch) -> int:
    """Invoke claude_bridge.cli.main with sys.argv[1:] == argv.

    Returns the exit code (sys.exit raises SystemExit which we catch).
    """
    from claude_bridge import cli

    monkeypatch.setattr(sys, "argv", ["bridge-cli"] + argv)
    try:
        cli.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1


# ---------------------------------------------------------------------------
# Parser wiring — help, subcommand registration
# ---------------------------------------------------------------------------


class TestWikiCLIParser:
    def test_wiki_subcommand_exists(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        code = _run_cli(["wiki", "--help"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "ingest" in captured.out

    def test_wiki_ingest_help_lists_flags(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        code = _run_cli(["wiki", "ingest", "--help"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "--agent" in captured.out
        assert "--dry-run" in captured.out


# ---------------------------------------------------------------------------
# No sources → exits 0 with friendly message
# ---------------------------------------------------------------------------


class TestWikiIngestNoSources:
    def test_no_agents_exits_zero_with_message(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        code = _run_cli(["wiki", "ingest"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "No sources" in captured.out or "no sources" in captured.out.lower()

    def test_no_agents_does_not_call_subprocess(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        calls: list = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        monkeypatch.setattr(subprocess, "run", fake_run)

        _run_cli(["wiki", "ingest"], monkeypatch)
        assert calls == []


# ---------------------------------------------------------------------------
# Happy path — mocked subprocess, progress output
# ---------------------------------------------------------------------------


class TestWikiIngestHappyPath:
    def test_prints_done_with_stats(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.12, "duration_ms": 2500}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "ingest"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "Done" in captured.out
        assert "0.12" in captured.out or "$0.12" in captured.out

    def test_idempotent_second_run_prints_skipped(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100}', stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        _run_cli(["wiki", "ingest"], monkeypatch)
        capsys.readouterr()  # drain
        code = _run_cli(["wiki", "ingest"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "Skipped" in captured.out or "skipped" in captured.out.lower()


# ---------------------------------------------------------------------------
# --dry-run — previews without subprocess and without DB write
# ---------------------------------------------------------------------------


class TestWikiIngestDryRun:
    def test_dry_run_does_not_call_subprocess(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        calls: list = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "ingest", "--dry-run"], monkeypatch)
        assert code == 0
        assert calls == []

    def test_dry_run_does_not_write_operations_row(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        _run_cli(["wiki", "ingest", "--dry-run"], monkeypatch)

        from claude_bridge.db import BridgeDB
        db = BridgeDB()
        try:
            rows = db.conn.execute(
                "SELECT COUNT(*) AS n FROM wiki_operations"
            ).fetchone()
        finally:
            db.close()
        assert rows["n"] == 0

    def test_dry_run_lists_agents(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _register_agent("frontend", "/projects/web")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# B\n"})
        _seed_memory(fake_home, "/projects/web", {"MEMORY.md": "# F\n"})

        _run_cli(["wiki", "ingest", "--dry-run"], monkeypatch)
        captured = capsys.readouterr()
        assert "backend" in captured.out
        assert "frontend" in captured.out


# ---------------------------------------------------------------------------
# --agent filter
# ---------------------------------------------------------------------------


class TestWikiIngestAgentFilter:
    def test_agent_filter_narrows(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _register_agent("frontend", "/projects/web")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Backend\n"})
        _seed_memory(fake_home, "/projects/web", {"MEMORY.md": "# Frontend\n"})

        captured_cmds: list = []
        def fake_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100}', stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        _run_cli(["wiki", "ingest", "--agent", "backend"], monkeypatch)
        captured = capsys.readouterr()
        assert len(captured_cmds) == 1
        # Prompt body (after -p) mentions only the backend agent's content
        dash_p_idx = captured_cmds[0].index("-p")
        prompt = captured_cmds[0][dash_p_idx + 1]
        assert "# Backend" in prompt
        assert "# Frontend" not in prompt


# ---------------------------------------------------------------------------
# .bridgewiki-ignore — project-level opt-out
# ---------------------------------------------------------------------------


class TestBridgewikiIgnore:
    def test_project_with_ignore_file_is_skipped(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)

        # Register two agents — one project gets a .bridgewiki-ignore marker
        ignored_project = tmp_path / "projects" / "api"
        kept_project = tmp_path / "projects" / "web"
        ignored_project.mkdir(parents=True)
        kept_project.mkdir(parents=True)
        (ignored_project / ".bridgewiki-ignore").write_text("")

        _register_agent("backend", str(ignored_project))
        _register_agent("frontend", str(kept_project))
        _seed_memory(fake_home, str(ignored_project), {"MEMORY.md": "# I am ignored\n"})
        _seed_memory(fake_home, str(kept_project), {"MEMORY.md": "# I am kept\n"})

        captured_cmds: list = []
        def fake_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.01, "duration_ms": 100}', stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "ingest"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        # The subprocess prompt must not contain the ignored content
        dash_p_idx = captured_cmds[0].index("-p")
        prompt = captured_cmds[0][dash_p_idx + 1]
        assert "I am ignored" not in prompt
        assert "I am kept" in prompt
        # Output mentions the skip
        assert "ignor" in captured.out.lower()

    def test_all_agents_ignored_exits_zero_no_subprocess(
        self, tmp_path, monkeypatch, capsys
    ):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        project = tmp_path / "projects" / "api"
        project.mkdir(parents=True)
        (project / ".bridgewiki-ignore").write_text("")
        _register_agent("backend", str(project))
        _seed_memory(fake_home, str(project), {"MEMORY.md": "# X\n"})

        calls: list = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "ingest"], monkeypatch)
        assert code == 0
        assert calls == []


# ---------------------------------------------------------------------------
# Failure propagation
# ---------------------------------------------------------------------------


class TestWikiIngestFailure:
    def test_non_zero_exit_propagates(self, tmp_path, monkeypatch, capsys):
        _, fake_home = _setup_env(tmp_path, monkeypatch)
        _register_agent("backend", "/projects/api")
        _seed_memory(fake_home, "/projects/api", {"MEMORY.md": "# Main\n"})

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 2, "", stderr="claude CLI exploded\n"
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "ingest"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 2
        assert "Failed" in captured.err or "failed" in captured.err.lower()
        assert "exploded" in captured.err


# ---------------------------------------------------------------------------
# M25.T3 — `bridge-cli wiki query`
# ---------------------------------------------------------------------------


def _seed_wiki_page(home, name, content):
    (home / name).write_text(content, encoding="utf-8")


class TestWikiQueryParser:
    def test_wiki_help_lists_query(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        code = _run_cli(["wiki", "--help"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "query" in captured.out

    def test_wiki_query_help_lists_flags(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        code = _run_cli(["wiki", "query", "--help"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "--top-k" in captured.out
        assert "--json" in captured.out


class TestWikiQueryEmptyWiki:
    def test_empty_wiki_exits_zero_with_message(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        from claude_bridge.wiki import wiki_home
        wiki_home()

        calls: list = []
        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "{}", "")
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "query", "what is X?"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "wiki" in captured.out.lower()
        assert calls == []


class TestWikiQueryHappyPath:
    def test_text_output_has_answer_sources_cost(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        from claude_bridge.wiki import wiki_home
        home = wiki_home()
        _seed_wiki_page(home, "api.md",
                        "# API\n\n## Rate Limiting\n\n60rpm per key.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.04, "duration_ms": 900, '
                       '"result": "Token bucket at 60rpm [Source: api.md]."}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "query", "rate limiting"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 0
        assert "Token bucket" in captured.out
        assert "Sources:" in captured.out
        assert "api.md" in captured.out
        assert "Cost:" in captured.out or "$0.04" in captured.out

    def test_json_flag_emits_machine_readable(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        from claude_bridge.wiki import wiki_home
        home = wiki_home()
        _seed_wiki_page(home, "api.md",
                        "# API\n\n## Rate Limiting\n\n60rpm per key.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 0,
                stdout='{"total_cost_usd": 0.04, "duration_ms": 900, '
                       '"result": "x [Source: api.md]"}',
                stderr="",
            )
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "query", "--json", "rate limiting"], monkeypatch)
        captured = capsys.readouterr()
        import json as _json
        payload = _json.loads(captured.out)
        assert payload["answer"]
        assert "api.md" in payload["sources_cited"]
        assert "pages_retrieved" in payload


class TestWikiQueryFailure:
    def test_non_zero_exit_propagates(self, tmp_path, monkeypatch, capsys):
        _setup_env(tmp_path, monkeypatch)
        from claude_bridge.wiki import wiki_home
        home = wiki_home()
        _seed_wiki_page(home, "api.md",
                        "# API\n\n## Rate Limiting\n\n60rpm per key.\n")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 2, "", "boom")
        monkeypatch.setattr(subprocess, "run", fake_run)

        code = _run_cli(["wiki", "query", "rate limiting"], monkeypatch)
        captured = capsys.readouterr()
        assert code == 2
        assert "boom" in captured.err or "Failed" in captured.err
