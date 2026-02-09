"""Tests for output formatters."""

from __future__ import annotations

import pytest

from ai_memory_protocol.formatter import (
    format_brief,
    format_compact,
    format_context_pack,
    format_full,
)


class TestFormatBrief:
    def test_basic_output(self, sample_needs: dict) -> None:
        result = format_brief(sample_needs["MEM_test_observation"])
        assert "MEM_test_observation" in result
        assert "Test observation" in result

    def test_includes_confidence(self, sample_needs: dict) -> None:
        result = format_brief(sample_needs["MEM_test_observation"])
        assert "high" in result

    def test_includes_key_tags(self, sample_needs: dict) -> None:
        result = format_brief(sample_needs["MEM_test_observation"])
        assert "topic:gateway" in result

    def test_deprecated_entry(self, sample_needs: dict) -> None:
        result = format_brief(sample_needs["FACT_deprecated"])
        assert "FACT_deprecated" in result

    def test_no_tags(self) -> None:
        need = {"id": "TEST_1", "title": "No tags", "confidence": "low", "tags": []}
        result = format_brief(need)
        assert "TEST_1" in result
        assert "No tags" in result


class TestFormatCompact:
    def test_basic_output(self, sample_needs: dict) -> None:
        result = format_compact(sample_needs["MEM_test_observation"])
        assert "MEM_test_observation" in result

    def test_with_body(self, sample_needs: dict) -> None:
        result = format_compact(sample_needs["MEM_test_observation"], show_body=True)
        assert "port 8080" in result

    def test_without_body(self, sample_needs: dict) -> None:
        result = format_compact(sample_needs["MEM_test_observation"], show_body=False)
        assert "port 8080" not in result

    def test_includes_status(self, sample_needs: dict) -> None:
        result = format_compact(sample_needs["MEM_test_observation"])
        assert "status=active" in result

    def test_includes_tags(self, sample_needs: dict) -> None:
        result = format_compact(sample_needs["MEM_test_observation"])
        assert "topic:gateway" in result

    def test_includes_links(self, sample_needs: dict) -> None:
        result = format_compact(sample_needs["DEC_use_httplib"])
        assert "relates" in result
        assert "MEM_test_observation" in result

    def test_long_body_truncated(self) -> None:
        need = {
            "id": "TEST_1",
            "title": "Long body",
            "description": "x" * 600,
            "status": "active",
            "confidence": "medium",
            "tags": [],
        }
        result = format_compact(need, show_body=True)
        assert "..." in result


class TestFormatFull:
    def test_includes_all_fields(self, sample_needs: dict) -> None:
        result = format_full(sample_needs["DEC_use_httplib"])
        assert "DEC_use_httplib" in result
        assert "cpp-httplib" in result
        assert "topic:gateway" in result

    def test_includes_header(self, sample_needs: dict) -> None:
        result = format_full(sample_needs["MEM_test_observation"])
        assert result.startswith("# MEM_test_observation")

    def test_includes_type(self, sample_needs: dict) -> None:
        result = format_full(sample_needs["MEM_test_observation"])
        assert "type: mem" in result

    def test_includes_scope(self, sample_needs: dict) -> None:
        result = format_full(sample_needs["MEM_test_observation"])
        assert "scope: repo:ros2_medkit" in result

    def test_includes_body(self, sample_needs: dict) -> None:
        result = format_full(sample_needs["MEM_test_observation"])
        assert "port 8080" in result

    def test_includes_links(self, sample_needs: dict) -> None:
        result = format_full(sample_needs["DEC_use_httplib"])
        assert "relates: MEM_test_observation" in result


class TestFormatContextPack:
    def test_groups_by_type(self, sample_needs: dict) -> None:
        active = {k: v for k, v in sample_needs.items() if v["status"] != "deprecated"}
        result = format_context_pack(active)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_includes_count(self, sample_needs: dict) -> None:
        active = {k: v for k, v in sample_needs.items() if v["status"] != "deprecated"}
        result = format_context_pack(active)
        assert "2 results" in result

    def test_empty_needs(self) -> None:
        result = format_context_pack({})
        assert "No relevant" in result

    def test_hide_body_by_default(self, sample_needs: dict) -> None:
        active = {k: v for k, v in sample_needs.items() if v["status"] != "deprecated"}
        result = format_context_pack(active, show_body=False)
        assert "memory get" in result.lower() or "memory_get" in result.lower()

    def test_show_body(self, sample_needs: dict) -> None:
        active = {k: v for k, v in sample_needs.items() if v["status"] != "deprecated"}
        result = format_context_pack(active, show_body=True)
        assert "port 8080" in result
