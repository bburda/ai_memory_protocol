"""Tests for workspace initialization (scaffold module)."""

from __future__ import annotations

from pathlib import Path

from ai_memory_protocol.scaffold import init_workspace


class TestInitWorkspace:
    def test_creates_directory_structure(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test Memory")
        assert (ws / "conf.py").exists()
        assert (ws / "index.rst").exists()
        assert (ws / "memory").is_dir()

    def test_creates_rst_files(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test Memory")
        assert (ws / "memory" / "observations.rst").exists()
        assert (ws / "memory" / "decisions.rst").exists()
        assert (ws / "memory" / "facts.rst").exists()
        assert (ws / "memory" / "preferences.rst").exists()
        assert (ws / "memory" / "risks.rst").exists()
        assert (ws / "memory" / "goals.rst").exists()
        assert (ws / "memory" / "questions.rst").exists()

    def test_creates_memory_index(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test Memory")
        assert (ws / "memory" / "index.rst").exists()

    def test_creates_makefile(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test Memory")
        assert (ws / "Makefile").exists()

    def test_creates_gitignore(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test Memory")
        assert (ws / ".gitignore").exists()

    def test_conf_has_needs_types(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test Memory")
        content = (ws / "conf.py").read_text()
        assert "needs_types" in content

    def test_conf_has_project_name(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="My Custom Project")
        content = (ws / "conf.py").read_text()
        assert "My Custom Project" in content

    def test_idempotent(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test 1")
        init_workspace(ws, project_name="Test 2")  # Should not crash
        assert (ws / "conf.py").exists()
        # Original content should be preserved (skips existing files)
        content = (ws / "conf.py").read_text()
        assert "Test 1" in content  # First creation wins

    def test_custom_author(self, tmp_path: Path) -> None:
        ws = tmp_path / ".memories"
        init_workspace(ws, project_name="Test", author="testauthor")
        content = (ws / "conf.py").read_text()
        assert "testauthor" in content
