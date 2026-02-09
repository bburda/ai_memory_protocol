"""Tests for the executor module — action execution and rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_memory_protocol.executor import (
    ExecutionResult,
    actions_from_json,
    execute_plan,
    validate_actions,
)
from ai_memory_protocol.planner import Action
from ai_memory_protocol.rst import append_to_rst, generate_rst_directive


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_with_memories(tmp_workspace: Path) -> Path:
    """Workspace with a few memories already added."""
    for i, (mid, title, tags) in enumerate(
        [
            ("MEM_alpha", "Alpha observation", ["topic:test", "repo:demo"]),
            ("MEM_beta", "Beta observation", ["topic:test", "repo:demo"]),
            ("DEC_choice_a", "Choose option A", ["topic:api"]),
        ]
    ):
        mem_type = mid.split("_")[0].lower()
        directive = generate_rst_directive(
            mem_type=mem_type,
            title=title,
            need_id=mid,
            tags=tags,
            confidence="medium",
        )
        append_to_rst(tmp_workspace, mem_type, directive)
    return tmp_workspace


# ---------------------------------------------------------------------------
# Tests: validate_actions
# ---------------------------------------------------------------------------


class TestValidateActions:
    def test_valid_retag(self):
        actions = [Action(kind="RETAG", reason="fix tags", id="MEM_test")]
        valid, skipped = validate_actions(actions)
        assert len(valid) == 1
        assert len(skipped) == 0

    def test_retag_missing_id(self):
        actions = [Action(kind="RETAG", reason="fix tags")]
        valid, skipped = validate_actions(actions)
        assert len(valid) == 0
        assert len(skipped) == 1

    def test_supersede_missing_old_id(self):
        actions = [Action(kind="SUPERSEDE", reason="dup")]
        valid, skipped = validate_actions(actions)
        assert len(valid) == 0
        assert len(skipped) == 1

    def test_circular_supersede_detected(self):
        actions = [
            Action(kind="SUPERSEDE", reason="dup", old_id="A", by_id="B"),
            Action(kind="SUPERSEDE", reason="dup", old_id="B", by_id="A"),
        ]
        valid, skipped = validate_actions(actions)
        # At least one should be skipped for circular reference
        assert len(skipped) >= 1

    def test_update_missing_id(self):
        actions = [Action(kind="UPDATE", reason="stale", field_changes={"status": "review"})]
        valid, skipped = validate_actions(actions)
        assert len(valid) == 0
        assert len(skipped) == 1

    def test_split_file_missing_path(self):
        actions = [Action(kind="SPLIT_FILE", reason="too big")]
        valid, skipped = validate_actions(actions)
        assert len(valid) == 0
        assert len(skipped) == 1

    def test_mixed_valid_and_invalid(self):
        actions = [
            Action(kind="RETAG", reason="good", id="MEM_x"),
            Action(kind="RETAG", reason="bad"),  # missing id
            Action(kind="UPDATE", reason="ok", id="MEM_y", field_changes={"status": "review"}),
        ]
        valid, skipped = validate_actions(actions)
        assert len(valid) == 2
        assert len(skipped) == 1


# ---------------------------------------------------------------------------
# Tests: execute_plan
# ---------------------------------------------------------------------------


class TestExecutePlan:
    def test_empty_actions(self, workspace_with_memories):
        result = execute_plan(workspace_with_memories, [])
        assert result.success

    def test_retag_action(self, workspace_with_memories):
        actions = [
            Action(
                kind="RETAG",
                reason="add missing tag",
                id="MEM_alpha",
                add_tags=["tier:core"],
            )
        ]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 1

    def test_update_action(self, workspace_with_memories):
        actions = [
            Action(
                kind="UPDATE",
                reason="mark for review",
                id="MEM_alpha",
                field_changes={"status": "review"},
            )
        ]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 1

    def test_deprecate_action(self, workspace_with_memories):
        actions = [
            Action(kind="DEPRECATE", reason="outdated", id="MEM_beta")
        ]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 1

    def test_supersede_action(self, workspace_with_memories):
        actions = [
            Action(
                kind="SUPERSEDE",
                reason="duplicate",
                old_id="MEM_beta",
                by_id="MEM_alpha",
            )
        ]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 1

    def test_invalid_action_skipped(self, workspace_with_memories):
        actions = [
            Action(kind="RETAG", reason="no id"),  # Missing id
            Action(kind="RETAG", reason="valid", id="MEM_alpha", add_tags=["topic:new"]),
        ]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 1
        assert len(result.skipped) == 1

    def test_split_file_informational(self, workspace_with_memories):
        actions = [
            Action(kind="SPLIT_FILE", reason="too large", rst_path="/some/path.rst"),
        ]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 1

    def test_prune_action(self, workspace_with_memories):
        actions = [Action(kind="PRUNE", reason="irrelevant", id="MEM_alpha")]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 1

    def test_unknown_action_kind(self, workspace_with_memories):
        actions = [Action(kind="RETAG", reason="valid", id="MEM_alpha")]
        # Patch the kind after creation to test unknown handling
        actions[0].kind = "NONEXISTENT"  # type: ignore[assignment]
        valid, _ = validate_actions(actions)
        result = execute_plan(workspace_with_memories, valid, rebuild=False)
        assert len(result.failed) == 1

    def test_multiple_actions_sequential(self, workspace_with_memories):
        actions = [
            Action(kind="RETAG", reason="add tag", id="MEM_alpha", add_tags=["tier:core"]),
            Action(
                kind="UPDATE",
                reason="update status",
                id="MEM_beta",
                field_changes={"confidence": "high"},
            ),
        ]
        result = execute_plan(workspace_with_memories, actions, rebuild=False)
        assert result.success
        assert len(result.applied) == 2


# ---------------------------------------------------------------------------
# Tests: ExecutionResult
# ---------------------------------------------------------------------------


class TestExecutionResult:
    def test_to_dict(self):
        result = ExecutionResult(
            success=True,
            applied=[{"action": {"kind": "RETAG"}, "message": "done"}],
            message="OK",
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["applied_count"] == 1
        assert d["failed_count"] == 0

    def test_summary(self):
        result = ExecutionResult(
            success=True,
            applied=[{}],
            failed=[{}],
            skipped=[{}],
            message="test",
        )
        s = result.summary()
        assert "Applied: 1" in s
        assert "Failed: 1" in s
        assert "Skipped: 1" in s


# ---------------------------------------------------------------------------
# Tests: actions_from_json
# ---------------------------------------------------------------------------


class TestActionsFromJson:
    def test_basic_deserialization(self):
        data = [
            {"kind": "RETAG", "reason": "fix tags", "id": "MEM_x", "add_tags": ["topic:new"]},
            {
                "kind": "UPDATE", "reason": "stale",
                "id": "MEM_y", "field_changes": {"status": "review"},
            },
        ]
        actions = actions_from_json(data)
        assert len(actions) == 2
        assert actions[0].kind == "RETAG"
        assert actions[0].add_tags == ["topic:new"]
        assert actions[1].field_changes == {"status": "review"}

    def test_empty_list(self):
        assert actions_from_json([]) == []

    def test_defaults_for_missing_fields(self):
        data = [{"kind": "DEPRECATE", "reason": "old", "id": "MEM_z"}]
        actions = actions_from_json(data)
        assert actions[0].add_tags == []
        assert actions[0].field_changes == {}
        assert actions[0].by_id == ""

    def test_roundtrip(self):
        """Action → to_dict → actions_from_json → same action."""
        original = Action(
            kind="SUPERSEDE",
            reason="duplicate",
            old_id="MEM_old",
            by_id="MEM_new",
            new_tags=["topic:x"],
        )
        d = original.to_dict()
        restored = actions_from_json([d])[0]
        assert restored.kind == original.kind
        assert restored.old_id == original.old_id
        assert restored.by_id == original.by_id
        assert restored.new_tags == original.new_tags
