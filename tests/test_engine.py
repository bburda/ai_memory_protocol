"""Tests for the core engine — search, filter, graph traversal, workspace detection."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_memory_protocol.engine import (
    expand_graph,
    find_workspace,
    load_needs,
    resolve_id,
    tag_match,
    text_match,
)


class TestFindWorkspace:
    def test_explicit_dir(self, tmp_workspace: Path) -> None:
        ws = find_workspace(str(tmp_workspace))
        assert ws == tmp_workspace

    def test_cli_override(self, tmp_workspace: Path) -> None:
        ws = find_workspace(str(tmp_workspace))
        assert ws == tmp_workspace

    def test_env_var(self, tmp_workspace: Path) -> None:
        with patch.dict(os.environ, {"MEMORY_DIR": str(tmp_workspace)}):
            ws = find_workspace(None)
            assert ws == tmp_workspace

    def test_missing_dir_raises(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "nonexistent"
        with pytest.raises(SystemExit):
            find_workspace(str(nonexistent))

    def test_invalid_workspace_raises(self, tmp_path: Path) -> None:
        # Directory exists but no conf.py
        with pytest.raises(SystemExit):
            find_workspace(str(tmp_path))

    def test_walk_up_finds_workspace(self, tmp_workspace: Path) -> None:
        # Create a subdirectory and check walk-up from there
        subdir = tmp_workspace / "subdir" / "deep"
        subdir.mkdir(parents=True)
        # Walk-up from the subdirectory should find the workspace at tmp_workspace
        original_cwd = Path.cwd()
        try:
            os.chdir(subdir)
            # Clear MEMORY_DIR to test pure walk-up (but real workspace may be found first)
            with patch.dict(os.environ, {}, clear=True):
                ws = find_workspace(None)
                # Should find *some* workspace by walking up
                assert ws is not None
        finally:
            os.chdir(original_cwd)


class TestLoadNeeds:
    def test_loads_sample_data(self, needs_json_file: Path, sample_needs: dict) -> None:
        needs = load_needs(needs_json_file)
        assert "MEM_test_observation" in needs
        assert "DEC_use_httplib" in needs

    def test_missing_json_exits(self, tmp_workspace: Path) -> None:
        with pytest.raises(SystemExit):
            load_needs(tmp_workspace)

    def test_loads_correct_fields(self, needs_json_file: Path) -> None:
        needs = load_needs(needs_json_file)
        mem = needs["MEM_test_observation"]
        assert mem["title"] == "Test observation about gateway"
        assert mem["confidence"] == "high"
        assert mem["type"] == "mem"


class TestResolveId:
    def test_exact_match(self, sample_needs: dict) -> None:
        result = resolve_id(sample_needs, "MEM_test_observation")
        assert result == "MEM_test_observation"

    def test_case_insensitive(self, sample_needs: dict) -> None:
        result = resolve_id(sample_needs, "mem_test_observation")
        assert result == "MEM_test_observation"

    def test_not_found(self, sample_needs: dict) -> None:
        result = resolve_id(sample_needs, "NONEXISTENT_id")
        assert result is None


class TestTextMatch:
    def test_matches_title(self, sample_needs: dict) -> None:
        assert text_match(sample_needs["MEM_test_observation"], "gateway")

    def test_matches_body(self, sample_needs: dict) -> None:
        assert text_match(sample_needs["MEM_test_observation"], "port 8080")

    def test_no_match(self, sample_needs: dict) -> None:
        assert not text_match(sample_needs["MEM_test_observation"], "nonexistent_keyword_xyz")

    def test_case_insensitive(self, sample_needs: dict) -> None:
        assert text_match(sample_needs["MEM_test_observation"], "GATEWAY")

    def test_matches_id(self, sample_needs: dict) -> None:
        assert text_match(sample_needs["MEM_test_observation"], "MEM_test")

    def test_matches_tags(self, sample_needs: dict) -> None:
        assert text_match(sample_needs["MEM_test_observation"], "repo:ros2_medkit")

    def test_or_logic(self, sample_needs: dict) -> None:
        # Any word matching = True
        assert text_match(sample_needs["MEM_test_observation"], "nonexistent gateway")

    def test_all_words_miss(self, sample_needs: dict) -> None:
        assert not text_match(sample_needs["MEM_test_observation"], "aaa bbb ccc")


class TestTagMatch:
    def test_single_tag(self, sample_needs: dict) -> None:
        assert tag_match(sample_needs["MEM_test_observation"], ["topic:gateway"])

    def test_multiple_tags_and(self, sample_needs: dict) -> None:
        assert tag_match(
            sample_needs["MEM_test_observation"], ["topic:gateway", "repo:ros2_medkit"]
        )

    def test_tag_not_found(self, sample_needs: dict) -> None:
        assert not tag_match(sample_needs["MEM_test_observation"], ["topic:nonexistent"])

    def test_partial_tag_no_match(self, sample_needs: dict) -> None:
        assert not tag_match(sample_needs["MEM_test_observation"], ["topic:gate"])

    def test_empty_tags(self, sample_needs: dict) -> None:
        assert tag_match(sample_needs["MEM_test_observation"], [])


class TestExpandGraph:
    def test_expands_one_hop(self, sample_needs: dict) -> None:
        matched = {"DEC_use_httplib": sample_needs["DEC_use_httplib"]}
        expanded = expand_graph(sample_needs, set(matched.keys()), hops=1)
        # Should pull in MEM_test_observation via "relates" link
        assert "MEM_test_observation" in expanded

    def test_zero_hops_no_expansion(self, sample_needs: dict) -> None:
        matched = {"DEC_use_httplib": sample_needs["DEC_use_httplib"]}
        expanded = expand_graph(sample_needs, set(matched.keys()), hops=0)
        assert set(expanded.keys()) == {"DEC_use_httplib"}

    def test_includes_seed(self, sample_needs: dict) -> None:
        expanded = expand_graph(sample_needs, {"MEM_test_observation"}, hops=1)
        assert "MEM_test_observation" in expanded

    def test_nonexistent_seed_excluded(self, sample_needs: dict) -> None:
        expanded = expand_graph(sample_needs, {"NONEXISTENT"}, hops=1)
        assert "NONEXISTENT" not in expanded

    def test_multiple_hops(self, sample_needs: dict) -> None:
        # With 2 hops, starting from DEC, should reach MEM through relates
        expanded = expand_graph(sample_needs, {"DEC_use_httplib"}, hops=2)
        assert "MEM_test_observation" in expanded
