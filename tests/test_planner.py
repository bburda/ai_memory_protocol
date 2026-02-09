"""Tests for the planner module — detection algorithms and plan formatting."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from ai_memory_protocol.planner import (
    Action,
    detect_conflicts,
    detect_duplicates,
    detect_missing_tags,
    detect_split_files,
    detect_stale,
    detect_tag_normalization,
    format_plan,
    run_plan,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def needs_with_duplicates() -> dict:
    """Two near-duplicate active needs."""
    return {
        "MEM_gateway_timeout": {
            "id": "MEM_gateway_timeout",
            "type": "mem",
            "title": "Gateway timeout is 30 seconds",
            "description": "Default timeout.",
            "status": "active",
            "tags": ["topic:gateway", "repo:ros2_medkit"],
            "confidence": "medium",
            "created_at": "2026-01-10",
        },
        "MEM_gateway_timeout_issue": {
            "id": "MEM_gateway_timeout_issue",
            "type": "mem",
            "title": "Gateway timeout is 30 seconds by default",
            "description": "Same info.",
            "status": "active",
            "tags": ["topic:gateway", "repo:ros2_medkit"],
            "confidence": "high",
            "created_at": "2026-01-15",
        },
    }


@pytest.fixture
def needs_with_missing_tags() -> dict:
    """Needs missing topic: or repo: tags."""
    return {
        "MEM_no_topic": {
            "id": "MEM_no_topic",
            "type": "mem",
            "title": "An observation",
            "status": "active",
            "tags": ["repo:ros2_medkit"],
            "confidence": "medium",
        },
        "MEM_no_repo": {
            "id": "MEM_no_repo",
            "type": "mem",
            "title": "Another observation",
            "status": "active",
            "tags": ["topic:gateway"],
            "confidence": "medium",
        },
        "MEM_no_tags_at_all": {
            "id": "MEM_no_tags_at_all",
            "type": "mem",
            "title": "Missing all tags",
            "status": "active",
            "tags": [],
            "confidence": "low",
        },
        "MEM_complete": {
            "id": "MEM_complete",
            "type": "mem",
            "title": "Complete one",
            "status": "active",
            "tags": ["topic:api", "repo:ros2_medkit"],
            "confidence": "high",
        },
    }


@pytest.fixture
def needs_with_stale() -> dict:
    """Needs with expired/review-overdue dates."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    return {
        "MEM_expired": {
            "id": "MEM_expired",
            "type": "mem",
            "title": "Old memory",
            "status": "active",
            "tags": ["topic:test"],
            "expires_at": yesterday,
            "review_after": "",
        },
        "MEM_review_due": {
            "id": "MEM_review_due",
            "type": "mem",
            "title": "Review needed",
            "status": "active",
            "tags": ["topic:test"],
            "expires_at": "",
            "review_after": yesterday,
        },
        "MEM_still_fresh": {
            "id": "MEM_still_fresh",
            "type": "mem",
            "title": "Still fresh",
            "status": "active",
            "tags": ["topic:test"],
            "expires_at": "",
            "review_after": tomorrow,
        },
    }


@pytest.fixture
def needs_with_tag_issues() -> dict:
    """Needs with case-inconsistent tags."""
    return {
        "MEM_one": {
            "id": "MEM_one",
            "type": "mem",
            "title": "First",
            "status": "active",
            "tags": ["topic:Gateway", "repo:ros2_medkit"],
        },
        "MEM_two": {
            "id": "MEM_two",
            "type": "mem",
            "title": "Second",
            "status": "active",
            "tags": ["topic:gateway", "repo:ros2_medkit"],
        },
        "MEM_three": {
            "id": "MEM_three",
            "type": "mem",
            "title": "Third",
            "status": "active",
            "tags": ["topic:gateway", "repo:ros2_medkit"],
        },
    }


@pytest.fixture
def needs_with_conflicts() -> dict:
    """Two decisions on the same topic with no link."""
    return {
        "DEC_use_rest": {
            "id": "DEC_use_rest",
            "type": "dec",
            "title": "Use REST for API",
            "status": "active",
            "tags": ["topic:api"],
        },
        "DEC_use_grpc": {
            "id": "DEC_use_grpc",
            "type": "dec",
            "title": "Use gRPC for API",
            "status": "active",
            "tags": ["topic:api"],
        },
    }


# ---------------------------------------------------------------------------
# Tests: detect_duplicates
# ---------------------------------------------------------------------------


class TestDetectDuplicates:
    def test_finds_near_duplicates(self, needs_with_duplicates):
        actions = detect_duplicates(needs_with_duplicates)
        assert len(actions) == 1
        assert actions[0].kind == "SUPERSEDE"

    def test_prefers_higher_confidence(self, needs_with_duplicates):
        actions = detect_duplicates(needs_with_duplicates)
        # The higher-confidence one should be kept
        action = actions[0]
        assert action.by_id == "MEM_gateway_timeout_issue"  # high confidence
        assert action.old_id == "MEM_gateway_timeout"  # medium confidence

    def test_no_duplicates_for_different_titles(self, sample_needs):
        actions = detect_duplicates(sample_needs)
        assert len(actions) == 0

    def test_skips_deprecated(self, sample_needs):
        """Deprecated needs should not be flagged as duplicates."""
        actions = detect_duplicates(sample_needs)
        assert all(a.old_id != "FACT_deprecated" for a in actions)

    def test_threshold_respected(self, needs_with_duplicates):
        # With very high threshold, should find nothing
        actions = detect_duplicates(needs_with_duplicates, title_threshold=0.99)
        assert len(actions) == 0

    def test_tag_overlap_threshold(self, needs_with_duplicates):
        # With very high tag overlap requirement, should still match (100% overlap)
        actions = detect_duplicates(
            needs_with_duplicates, title_threshold=0.8, tag_overlap_threshold=0.9
        )
        assert len(actions) == 1


# ---------------------------------------------------------------------------
# Tests: detect_missing_tags
# ---------------------------------------------------------------------------


class TestDetectMissingTags:
    def test_finds_missing_topic(self, needs_with_missing_tags):
        actions = detect_missing_tags(needs_with_missing_tags)
        ids_with_actions = {a.id for a in actions}
        assert "MEM_no_topic" in ids_with_actions

    def test_finds_missing_repo(self, needs_with_missing_tags):
        actions = detect_missing_tags(needs_with_missing_tags)
        ids_with_actions = {a.id for a in actions}
        assert "MEM_no_repo" in ids_with_actions

    def test_finds_missing_both(self, needs_with_missing_tags):
        actions = detect_missing_tags(needs_with_missing_tags)
        ids_with_actions = {a.id for a in actions}
        assert "MEM_no_tags_at_all" in ids_with_actions

    def test_skips_complete(self, needs_with_missing_tags):
        actions = detect_missing_tags(needs_with_missing_tags)
        ids_with_actions = {a.id for a in actions}
        assert "MEM_complete" not in ids_with_actions

    def test_action_type_is_retag(self, needs_with_missing_tags):
        actions = detect_missing_tags(needs_with_missing_tags)
        assert all(a.kind == "RETAG" for a in actions)


# ---------------------------------------------------------------------------
# Tests: detect_stale
# ---------------------------------------------------------------------------


class TestDetectStale:
    def test_finds_expired(self, needs_with_stale):
        actions = detect_stale(needs_with_stale)
        ids = {a.id for a in actions}
        assert "MEM_expired" in ids

    def test_finds_review_overdue(self, needs_with_stale):
        actions = detect_stale(needs_with_stale)
        ids = {a.id for a in actions}
        assert "MEM_review_due" in ids

    def test_skips_fresh(self, needs_with_stale):
        actions = detect_stale(needs_with_stale)
        ids = {a.id for a in actions}
        assert "MEM_still_fresh" not in ids

    def test_action_type_is_update(self, needs_with_stale):
        actions = detect_stale(needs_with_stale)
        assert all(a.kind == "UPDATE" for a in actions)
        for a in actions:
            assert a.field_changes.get("status") == "review"


# ---------------------------------------------------------------------------
# Tests: detect_conflicts
# ---------------------------------------------------------------------------


class TestDetectConflicts:
    def test_finds_unlinked_decisions(self, needs_with_conflicts):
        actions = detect_conflicts(needs_with_conflicts)
        assert len(actions) >= 1

    def test_skips_linked_decisions(self):
        needs = {
            "DEC_a": {
                "type": "dec",
                "title": "A",
                "status": "active",
                "tags": ["topic:api"],
                "relates": ["DEC_b"],
            },
            "DEC_b": {
                "type": "dec",
                "title": "B",
                "status": "active",
                "tags": ["topic:api"],
            },
        }
        actions = detect_conflicts(needs)
        assert len(actions) == 0


# ---------------------------------------------------------------------------
# Tests: detect_tag_normalization
# ---------------------------------------------------------------------------


class TestDetectTagNormalization:
    def test_finds_inconsistent_case(self, needs_with_tag_issues):
        actions = detect_tag_normalization(needs_with_tag_issues)
        assert len(actions) >= 1

    def test_normalizes_to_most_common(self, needs_with_tag_issues):
        actions = detect_tag_normalization(needs_with_tag_issues)
        # "topic:gateway" appears twice, "topic:Gateway" once → normalize to lowercase
        for a in actions:
            if "Gateway" in str(a.remove_tags):
                assert "topic:gateway" in a.add_tags

    def test_action_type_is_retag(self, needs_with_tag_issues):
        actions = detect_tag_normalization(needs_with_tag_issues)
        assert all(a.kind == "RETAG" for a in actions)


# ---------------------------------------------------------------------------
# Tests: detect_split_files
# ---------------------------------------------------------------------------


class TestDetectSplitFiles:
    def test_no_split_needed(self, tmp_workspace):
        actions = detect_split_files(tmp_workspace)
        assert len(actions) == 0

    def test_detects_oversized(self, tmp_workspace):
        # Write many directives to a file
        rst_path = tmp_workspace / "memory" / "observations.rst"
        content = rst_path.read_text()
        for i in range(55):
            content += f"\n.. mem:: Entry {i}\n   :id: MEM_entry_{i}\n\n   Body text.\n"
        rst_path.write_text(content)

        actions = detect_split_files(tmp_workspace)
        assert len(actions) >= 1
        assert actions[0].kind == "SPLIT_FILE"


# ---------------------------------------------------------------------------
# Tests: run_plan
# ---------------------------------------------------------------------------


class TestRunPlan:
    def test_runs_all_checks(self, needs_json_file, sample_needs):
        actions = run_plan(needs_json_file, needs=sample_needs)
        # sample_needs has missing repo tags on DEC_use_httplib
        assert isinstance(actions, list)

    def test_runs_specific_checks(self, needs_json_file, sample_needs):
        actions = run_plan(needs_json_file, checks=["missing_tags"], needs=sample_needs)
        # Only RETAG actions from missing_tags check
        assert all(a.kind == "RETAG" for a in actions)

    def test_empty_needs_returns_empty(self, needs_json_file):
        actions = run_plan(needs_json_file, needs={})
        assert actions == []


# ---------------------------------------------------------------------------
# Tests: format_plan
# ---------------------------------------------------------------------------


class TestFormatPlan:
    def test_empty_plan(self):
        result = format_plan([])
        assert "healthy" in result.lower()

    def test_human_format(self):
        actions = [
            Action(kind="RETAG", reason="Missing topic tag", id="MEM_test"),
        ]
        result = format_plan(actions, fmt="human")
        assert "RETAG" in result
        assert "MEM_test" in result

    def test_json_format(self):
        actions = [
            Action(kind="UPDATE", reason="Stale", id="MEM_old", field_changes={"status": "review"}),
        ]
        result = format_plan(actions, fmt="json")
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["kind"] == "UPDATE"


# ---------------------------------------------------------------------------
# Tests: Action dataclass
# ---------------------------------------------------------------------------


class TestAction:
    def test_to_dict_omits_empty(self):
        a = Action(kind="RETAG", reason="test", id="MEM_x", add_tags=["topic:new"])
        d = a.to_dict()
        assert "remove_tags" not in d
        assert "field_changes" not in d
        assert d["kind"] == "RETAG"
        assert d["id"] == "MEM_x"

    def test_supersede_action(self):
        a = Action(
            kind="SUPERSEDE",
            reason="duplicate",
            old_id="MEM_old",
            by_id="MEM_new",
        )
        d = a.to_dict()
        assert d["old_id"] == "MEM_old"
        assert d["by_id"] == "MEM_new"
