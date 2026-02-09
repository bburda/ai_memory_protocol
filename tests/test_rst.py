"""Tests for RST directive generation and in-place editing."""

from __future__ import annotations

from pathlib import Path

from ai_memory_protocol.config import TYPE_PREFIXES
from ai_memory_protocol.rst import (
    add_tags_in_rst,
    append_to_rst,
    deprecate_in_rst,
    generate_id,
    generate_rst_directive,
    remove_tags_in_rst,
    update_field_in_rst,
)


class TestGenerateId:
    def test_basic_id(self) -> None:
        result = generate_id("mem", "Gateway timeout issue")
        assert result.startswith("MEM_")
        assert "gateway" in result.lower()

    def test_special_chars_removed(self) -> None:
        result = generate_id("dec", "Use C++ HTTP library (cpp-httplib)")
        assert "(" not in result
        assert ")" not in result
        assert "++" not in result

    def test_different_types(self) -> None:
        for typ, prefix in TYPE_PREFIXES.items():
            result = generate_id(typ, "test title")
            assert result.startswith(f"{prefix}_"), f"ID for type '{typ}' should start with '{prefix}_'"

    def test_max_length(self) -> None:
        long_title = "a " * 100
        result = generate_id("mem", long_title)
        # slugify limits to 50 chars + prefix
        assert len(result) <= 60

    def test_empty_title(self) -> None:
        result = generate_id("mem", "")
        assert result.startswith("MEM_")


class TestGenerateRstDirective:
    def test_minimal_directive(self) -> None:
        rst = generate_rst_directive("mem", "Test memory", tags=["topic:test"])
        assert ".. mem::" in rst
        assert "Test memory" in rst
        assert ":tags: topic:test" in rst

    def test_with_body(self) -> None:
        rst = generate_rst_directive(
            "dec", "Test decision", tags=["topic:api"], body="Detailed rationale."
        )
        assert "Detailed rationale." in rst

    def test_with_all_fields(self) -> None:
        rst = generate_rst_directive(
            "fact",
            "Complete fact",
            need_id="FACT_custom_id",
            tags=["topic:test", "tier:core"],
            source="manual test",
            confidence="high",
            scope="global",
            body="Full body text.",
            relates=["MEM_related"],
            supersedes=["FACT_old"],
        )
        assert ":id: FACT_custom_id" in rst
        assert ":confidence: high" in rst
        assert ":source: manual test" in rst
        assert ":relates: MEM_related" in rst
        assert ":supersedes: FACT_old" in rst

    def test_includes_created_at(self) -> None:
        rst = generate_rst_directive("mem", "Test", tags=["topic:test"])
        assert ":created_at:" in rst

    def test_includes_review_after(self) -> None:
        rst = generate_rst_directive("mem", "Test", tags=["topic:test"])
        assert ":review_after:" in rst

    def test_default_status_by_type(self) -> None:
        rst_mem = generate_rst_directive("mem", "Observation", tags=["topic:test"])
        rst_fact = generate_rst_directive("fact", "Verified fact", tags=["topic:test"])
        assert ":status: draft" in rst_mem
        assert ":status: promoted" in rst_fact

    def test_custom_review_days(self) -> None:
        rst1 = generate_rst_directive("mem", "Short", tags=["t:x"], review_days=7)
        rst2 = generate_rst_directive("mem", "Long", tags=["t:x"], review_days=365)
        # Both should have review_after but different dates
        assert ":review_after:" in rst1
        assert ":review_after:" in rst2

    def test_empty_body_placeholder(self) -> None:
        rst = generate_rst_directive("mem", "No body", tags=["topic:test"])
        assert "TODO: Add description." in rst

    def test_no_tags(self) -> None:
        rst = generate_rst_directive("mem", "Tagless", tags=[])
        assert ":tags:" not in rst


class TestAppendToRst:
    def test_append_creates_entry(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive("mem", "New memory", tags=["topic:test"])
        target = append_to_rst(tmp_workspace, "mem", directive)
        assert target.exists()
        content = target.read_text()
        assert "New memory" in content

    def test_append_to_correct_file(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive("dec", "New decision", tags=["topic:test"])
        target = append_to_rst(tmp_workspace, "dec", directive)
        assert "decision" in target.name.lower()

    def test_multiple_appends(self, tmp_workspace: Path) -> None:
        for i in range(3):
            directive = generate_rst_directive("mem", f"Memory {i}", tags=["topic:test"])
            append_to_rst(tmp_workspace, "mem", directive)
        # Read the file and check all three are there
        from ai_memory_protocol.config import TYPE_FILES

        target = tmp_workspace / TYPE_FILES["mem"]
        content = target.read_text()
        for i in range(3):
            assert f"Memory {i}" in content


class TestUpdateFieldInRst:
    def test_update_existing_field(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive(
            "mem",
            "Updatable memory",
            need_id="MEM_updatable",
            tags=["topic:test"],
            confidence="low",
        )
        append_to_rst(tmp_workspace, "mem", directive)
        ok, msg = update_field_in_rst(tmp_workspace, "MEM_updatable", "confidence", "high")
        assert ok, msg
        # Verify the change
        from ai_memory_protocol.config import TYPE_FILES

        content = (tmp_workspace / TYPE_FILES["mem"]).read_text()
        assert ":confidence: high" in content

    def test_update_nonexistent_field_inserts(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive(
            "mem", "Field insert test", need_id="MEM_field_insert", tags=["topic:test"]
        )
        append_to_rst(tmp_workspace, "mem", directive)
        ok, msg = update_field_in_rst(tmp_workspace, "MEM_field_insert", "expires_at", "2099-12-31")
        assert ok, msg

    def test_update_nonexistent_id(self, tmp_workspace: Path) -> None:
        ok, msg = update_field_in_rst(tmp_workspace, "MEM_nonexistent", "status", "active")
        assert not ok
        assert "not found" in msg.lower()


class TestTagOperations:
    def test_add_tags(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive(
            "mem", "Tag test", need_id="MEM_tag_test", tags=["topic:original"]
        )
        append_to_rst(tmp_workspace, "mem", directive)
        ok, msg = add_tags_in_rst(tmp_workspace, "MEM_tag_test", ["topic:new"])
        assert ok, msg
        from ai_memory_protocol.config import TYPE_FILES

        content = (tmp_workspace / TYPE_FILES["mem"]).read_text()
        assert "topic:original" in content
        assert "topic:new" in content

    def test_add_duplicate_tag(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive(
            "mem", "Dedup test", need_id="MEM_dedup", tags=["topic:existing"]
        )
        append_to_rst(tmp_workspace, "mem", directive)
        ok, msg = add_tags_in_rst(tmp_workspace, "MEM_dedup", ["topic:existing"])
        assert ok
        # Should not double-add
        from ai_memory_protocol.config import TYPE_FILES

        content = (tmp_workspace / TYPE_FILES["mem"]).read_text()
        assert content.count("topic:existing") == 1

    def test_remove_tags(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive(
            "mem",
            "Tag remove test",
            need_id="MEM_tag_remove",
            tags=["topic:keep", "topic:remove"],
        )
        append_to_rst(tmp_workspace, "mem", directive)
        ok, msg = remove_tags_in_rst(tmp_workspace, "MEM_tag_remove", ["topic:remove"])
        assert ok, msg
        from ai_memory_protocol.config import TYPE_FILES

        content = (tmp_workspace / TYPE_FILES["mem"]).read_text()
        assert "topic:keep" in content
        assert "topic:remove" not in content

    def test_remove_nonexistent_id(self, tmp_workspace: Path) -> None:
        ok, msg = remove_tags_in_rst(tmp_workspace, "MEM_nonexistent", ["topic:x"])
        assert not ok


class TestDeprecate:
    def test_deprecate_sets_status(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive(
            "mem", "Deprecatable", need_id="MEM_deprecatable", tags=["topic:test"]
        )
        append_to_rst(tmp_workspace, "mem", directive)
        ok, msg = deprecate_in_rst(tmp_workspace, "MEM_deprecatable")
        assert ok, msg
        from ai_memory_protocol.config import TYPE_FILES

        content = (tmp_workspace / TYPE_FILES["mem"]).read_text()
        assert ":status: deprecated" in content

    def test_deprecate_with_superseded_by(self, tmp_workspace: Path) -> None:
        directive = generate_rst_directive(
            "mem", "Old memory", need_id="MEM_old", tags=["topic:test"]
        )
        append_to_rst(tmp_workspace, "mem", directive)
        ok, msg = deprecate_in_rst(tmp_workspace, "MEM_old", "MEM_new")
        assert ok
        assert "MEM_new" in msg

    def test_deprecate_nonexistent(self, tmp_workspace: Path) -> None:
        ok, msg = deprecate_in_rst(tmp_workspace, "MEM_nonexistent")
        assert not ok
