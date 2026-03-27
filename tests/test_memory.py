"""Tests for Auto Memory reader."""

import os

import pytest

from claude_bridge.memory import find_memory_dir, read_memory, format_memory_report


class TestFindMemoryDir:
    def test_finds_encoded_path(self, tmp_path, monkeypatch):
        # Simulate Claude Code's path encoding: /Users/me/projects/api → -Users-me-projects-api
        encoded = "-Users-me-projects-api"
        memory_dir = tmp_path / ".claude" / "projects" / encoded / "memory"
        memory_dir.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path))

        result = find_memory_dir("/Users/me/projects/api")
        assert result is not None
        assert "memory" in result

    def test_fallback_by_basename(self, tmp_path, monkeypatch):
        # If exact encoding doesn't match, search by basename
        encoded = "some-other-encoding-api"
        memory_dir = tmp_path / ".claude" / "projects" / encoded / "memory"
        memory_dir.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path))

        result = find_memory_dir("/some/path/api")
        assert result is not None

    def test_returns_none_if_not_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".claude" / "projects").mkdir(parents=True)

        result = find_memory_dir("/nonexistent/project")
        assert result is None

    def test_returns_none_if_no_projects_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))

        result = find_memory_dir("/some/project")
        assert result is None


class TestReadMemory:
    def test_reads_main_memory(self, tmp_path, monkeypatch):
        encoded = "-projects-api"
        memory_dir = tmp_path / ".claude" / "projects" / encoded / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text("# Learned stuff\n- Use Zod\n")
        monkeypatch.setenv("HOME", str(tmp_path))

        result = read_memory("/projects/api")
        assert result["found"] is True
        assert "Zod" in result["main"]

    def test_reads_topic_files(self, tmp_path, monkeypatch):
        encoded = "-projects-api"
        memory_dir = tmp_path / ".claude" / "projects" / encoded / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text("# Main\n")
        (memory_dir / "testing.md").write_text("# Testing\nUse pytest\n")
        (memory_dir / "api_patterns.md").write_text("# API\nREST conventions\n")
        monkeypatch.setenv("HOME", str(tmp_path))

        result = read_memory("/projects/api")
        assert result["found"] is True
        assert len(result["topics"]) == 2
        topic_names = [t["name"] for t in result["topics"]]
        assert "testing.md" in topic_names
        assert "api_patterns.md" in topic_names

    def test_no_memory_found(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".claude" / "projects").mkdir(parents=True)

        result = read_memory("/nonexistent/project")
        assert result["found"] is False
        assert result["main"] == ""
        assert result["topics"] == []


class TestFormatMemoryReport:
    def test_no_memory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".claude" / "projects").mkdir(parents=True)

        report = format_memory_report("backend", "/nonexistent/project")
        assert "No Auto Memory" in report

    def test_with_memory(self, tmp_path, monkeypatch):
        encoded = "-projects-api"
        memory_dir = tmp_path / ".claude" / "projects" / encoded / "memory"
        memory_dir.mkdir(parents=True)
        (memory_dir / "MEMORY.md").write_text("# Learned\n- Use Zod\n")
        (memory_dir / "testing.md").write_text("# Tests\n")
        monkeypatch.setenv("HOME", str(tmp_path))

        report = format_memory_report("backend", "/projects/api")
        assert "backend" in report
        assert "Zod" in report
        assert "testing.md" in report
