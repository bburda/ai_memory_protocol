"""Shared test fixtures for AI Memory Protocol tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_memory_protocol.config import TYPE_FILES


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a minimal memory workspace in a temp directory."""
    ws = tmp_path / ".memories"
    ws.mkdir()

    # Minimal conf.py
    (ws / "conf.py").write_text(
        'project = "Test"\n'
        'extensions = ["sphinx_needs"]\n'
        "needs_types = [\n"
        '    {"directive": "mem", "title": "Observation", "prefix": "MEM_", '
        '"color": "#BDD7EE", "style": "node"},\n'
        '    {"directive": "dec", "title": "Decision", "prefix": "DEC_", '
        '"color": "#B6D7A8", "style": "node"},\n'
        '    {"directive": "fact", "title": "Fact", "prefix": "FACT_", '
        '"color": "#FFE599", "style": "node"},\n'
        '    {"directive": "pref", "title": "Preference", "prefix": "PREF_", '
        '"color": "#D5A6BD", "style": "node"},\n'
        '    {"directive": "risk", "title": "Risk", "prefix": "RISK_", '
        '"color": "#EA9999", "style": "node"},\n'
        '    {"directive": "goal", "title": "Goal", "prefix": "GOAL_", '
        '"color": "#A4C2F4", "style": "node"},\n'
        '    {"directive": "q", "title": "Open Question", "prefix": "Q_", '
        '"color": "#D9D2E9", "style": "node"},\n'
        "]\n"
        "needs_extra_options = {\n"
        '    "source": {}, "owner": {}, "confidence": {}, "scope": {},\n'
        '    "created_at": {}, "updated_at": {}, "expires_at": {}, "review_after": {},\n'
        "}\n"
        "needs_build_json = True\n"
    )

    # Minimal index.rst with toctree
    (ws / "index.rst").write_text(
        "Test Memory\n===========\n\n"
        ".. toctree::\n   :glob:\n\n   memory/*\n"
    )

    # Memory subdirectory
    mem_dir = ws / "memory"
    mem_dir.mkdir()

    # Create RST files matching TYPE_FILES
    seen_files: set[str] = set()
    for _mem_type, rel_path in TYPE_FILES.items():
        filename = rel_path.split("/")[-1]
        if filename in seen_files:
            continue
        seen_files.add(filename)
        header = filename.replace(".rst", "").title()
        (mem_dir / filename).write_text(
            f"{'=' * len(header)}\n{header}\n{'=' * len(header)}\n\n"
        )

    return ws


@pytest.fixture
def sample_needs() -> dict[str, dict]:
    """Return a dict of sample needs for testing search/filter/format."""
    return {
        "MEM_test_observation": {
            "id": "MEM_test_observation",
            "type": "mem",
            "title": "Test observation about gateway",
            "description": "The gateway uses port 8080 by default.",
            "status": "active",
            "tags": ["topic:gateway", "repo:ros2_medkit"],
            "confidence": "high",
            "created_at": "2026-01-15",
            "review_after": "2026-07-15",
            "expires_at": "",
            "source": "manual",
            "scope": "repo:ros2_medkit",
        },
        "DEC_use_httplib": {
            "id": "DEC_use_httplib",
            "type": "dec",
            "title": "Use cpp-httplib for REST server",
            "description": "Header-only, simple, sufficient for SOVD API.",
            "status": "active",
            "tags": ["topic:gateway", "topic:http"],
            "confidence": "high",
            "created_at": "2026-01-10",
            "review_after": "",
            "expires_at": "",
            "source": "architecture review",
            "scope": "repo:ros2_medkit",
            "relates": ["MEM_test_observation"],
        },
        "FACT_deprecated": {
            "id": "FACT_deprecated",
            "type": "fact",
            "title": "Old fact",
            "description": "Deprecated.",
            "status": "deprecated",
            "tags": ["topic:old"],
            "confidence": "low",
            "created_at": "2025-01-01",
            "review_after": "",
            "expires_at": "",
        },
    }


@pytest.fixture
def needs_json_file(tmp_workspace: Path, sample_needs: dict) -> Path:
    """Create a needs.json file in the workspace build directory."""
    build_dir = tmp_workspace / "_build" / "html"
    build_dir.mkdir(parents=True)
    needs_data = {"current_version": "", "versions": {"": {"needs": sample_needs}}}
    (build_dir / "needs.json").write_text(json.dumps(needs_data, indent=2))
    return tmp_workspace
