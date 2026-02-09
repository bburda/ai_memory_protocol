"""Integration tests for CLI commands. Requires Sphinx/sphinx-needs."""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.integration


class TestCLIWorkflow:
    def test_version(self) -> None:
        result = subprocess.run(["memory", "--version"], capture_output=True, text=True)
        assert result.returncode == 0
        assert "0." in result.stdout

    def test_init_add_recall(self, tmp_path) -> None:
        ws = str(tmp_path / ".memories")

        # Init
        result = subprocess.run(
            ["memory", "init", ws, "--name", "CLI Test", "--install"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0

        # Add
        result = subprocess.run(
            [
                "memory",
                "--dir",
                ws,
                "add",
                "fact",
                "CLI test fact",
                "--tags",
                "topic:test",
                "--confidence",
                "high",
                "--body",
                "Test body content",
                "--rebuild",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0

        # Recall
        result = subprocess.run(
            ["memory", "--dir", ws, "recall", "test", "--format", "brief"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "FACT_" in result.stdout

    def test_doctor(self, tmp_path) -> None:
        ws = str(tmp_path / ".memories")
        subprocess.run(
            ["memory", "init", ws, "--name", "Doctor Test", "--install"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        result = subprocess.run(
            ["memory", "--dir", ws, "doctor"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # doctor should run without crash
        assert result.returncode in (0, 1)

    def test_tags_command(self, tmp_path) -> None:
        ws = str(tmp_path / ".memories")
        subprocess.run(
            ["memory", "init", ws, "--name", "Tags Test", "--install"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        subprocess.run(
            [
                "memory",
                "--dir",
                ws,
                "add",
                "mem",
                "Tagged memory",
                "--tags",
                "topic:test,repo:example",
                "--rebuild",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        result = subprocess.run(
            ["memory", "--dir", ws, "tags"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "topic:test" in result.stdout

    def test_update_and_deprecate(self, tmp_path) -> None:
        ws = str(tmp_path / ".memories")
        subprocess.run(
            ["memory", "init", ws, "--name", "Update Test", "--install"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        subprocess.run(
            [
                "memory",
                "--dir",
                ws,
                "add",
                "mem",
                "Updateable",
                "--tags",
                "topic:test",
                "--id",
                "MEM_updateable",
                "--rebuild",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Update confidence
        result = subprocess.run(
            ["memory", "--dir", ws, "update", "MEM_updateable", "--confidence", "high"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0

        # Deprecate
        result = subprocess.run(
            ["memory", "--dir", ws, "deprecate", "MEM_updateable"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
