"""Tests for MCP server tool handlers."""

from __future__ import annotations

import json

import pytest

try:
    from ai_memory_protocol.mcp_server import (
        TOOLS,
        _MCP_AVAILABLE,
        _format_output,
        _sort_needs,
        create_mcp_server,
    )

    MCP_AVAILABLE = _MCP_AVAILABLE
except ImportError:
    MCP_AVAILABLE = False

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="MCP SDK not installed")


class TestMCPAvailability:
    def test_mcp_flag_is_set(self) -> None:
        assert MCP_AVAILABLE is True

    def test_create_server(self) -> None:
        server = create_mcp_server()
        assert server is not None


class TestMCPToolDefinitions:
    def test_tool_count(self) -> None:
        assert len(TOOLS) >= 8

    def test_all_tools_have_schemas(self) -> None:
        for tool in TOOLS:
            assert tool.inputSchema is not None
            assert tool.inputSchema.get("type") == "object"

    def test_required_tools_present(self) -> None:
        names = {t.name for t in TOOLS}
        for expected in [
            "memory_recall",
            "memory_get",
            "memory_add",
            "memory_update",
            "memory_deprecate",
            "memory_tags",
            "memory_stale",
            "memory_rebuild",
            "memory_plan",
            "memory_apply",
            "memory_capture_git",
        ]:
            assert expected in names, f"Missing tool: {expected}"

    def test_tools_have_descriptions(self) -> None:
        for tool in TOOLS:
            assert tool.description, f"Tool {tool.name} has empty description"
            assert len(tool.description) > 10, f"Tool {tool.name} description too short"


class TestFormatOutput:
    def test_brief_format(self, sample_needs: dict) -> None:
        output = _format_output(sample_needs, fmt="brief")
        assert isinstance(output, str)
        assert "MEM_test_observation" in output

    def test_json_format(self, sample_needs: dict) -> None:
        output = _format_output(sample_needs, fmt="json")
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_compact_format(self, sample_needs: dict) -> None:
        output = _format_output(sample_needs, fmt="compact")
        assert isinstance(output, str)

    def test_context_format(self, sample_needs: dict) -> None:
        output = _format_output(sample_needs, fmt="context")
        assert isinstance(output, str)
        assert "Recalled Memories" in output

    def test_limit(self, sample_needs: dict) -> None:
        output = _format_output(sample_needs, fmt="brief", limit=1)
        assert "omitted" in output.lower()

    def test_with_body(self, sample_needs: dict) -> None:
        output = _format_output(sample_needs, fmt="compact", show_body=True)
        assert "port 8080" in output

    def test_without_body(self, sample_needs: dict) -> None:
        output = _format_output(sample_needs, fmt="compact", show_body=False)
        assert "port 8080" not in output


class TestSortNeeds:
    def test_sort_newest(self, sample_needs: dict) -> None:
        sorted_items = _sort_needs(sample_needs, "newest")
        dates = [item[1].get("created_at", "") for item in sorted_items]
        assert dates == sorted(dates, reverse=True)

    def test_sort_oldest(self, sample_needs: dict) -> None:
        sorted_items = _sort_needs(sample_needs, "oldest")
        dates = [item[1].get("created_at", "") for item in sorted_items]
        assert dates == sorted(dates)

    def test_sort_confidence(self, sample_needs: dict) -> None:
        sorted_items = _sort_needs(sample_needs, "confidence")
        conf_order = [item[1].get("confidence", "medium") for item in sorted_items]
        # high should come first
        assert conf_order[0] == "high"

    def test_sort_none(self, sample_needs: dict) -> None:
        sorted_items = _sort_needs(sample_needs, None)
        assert len(sorted_items) == len(sample_needs)

    def test_sort_updated(self, sample_needs: dict) -> None:
        sorted_items = _sort_needs(sample_needs, "updated")
        # Should not crash even without updated_at fields
        assert len(sorted_items) == len(sample_needs)
