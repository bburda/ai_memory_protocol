"""Execute planned maintenance actions against the memory workspace.

The executor takes a list of ``Action`` objects (from ``planner.py``)
and applies them sequentially using existing ``rst.py`` functions.
Includes git-based rollback on build failure.

Usage:
    from ai_memory_protocol.executor import execute_plan
    result = execute_plan(workspace, actions, auto_commit=False)
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import run_rebuild
from .planner import Action
from .rst import (
    add_tags_in_rst,
    append_to_rst,
    deprecate_in_rst,
    generate_rst_directive,
    remove_tags_in_rst,
    update_field_in_rst,
)

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result of executing a plan."""

    success: bool
    applied: list[dict[str, Any]] = field(default_factory=list)
    failed: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    build_output: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "applied_count": len(self.applied),
            "failed_count": len(self.failed),
            "skipped_count": len(self.skipped),
            "applied": self.applied,
            "failed": self.failed,
            "skipped": self.skipped,
            "build_output": self.build_output,
            "message": self.message,
        }

    def summary(self) -> str:
        parts = [self.message] if self.message else []
        parts.append(
            f"Applied: {len(self.applied)}, "
            f"Failed: {len(self.failed)}, "
            f"Skipped: {len(self.skipped)}"
        )
        if self.build_output:
            parts.append(f"Build: {self.build_output[:200]}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_actions(actions: list[Action]) -> tuple[list[Action], list[dict[str, Any]]]:
    """Validate actions before execution.

    Returns (valid_actions, skipped_with_reasons).
    Checks:
      - Circular supersedes (A supersedes B, B supersedes A)
      - Missing required fields per action kind
    """
    valid: list[Action] = []
    skipped: list[dict[str, Any]] = []

    # Build supersede graph for cycle detection
    supersede_map: dict[str, str] = {}
    for a in actions:
        if a.kind == "SUPERSEDE" and a.old_id and a.by_id:
            supersede_map[a.old_id] = a.by_id

    for a in actions:
        # Check required fields
        if a.kind == "RETAG" and not a.id:
            skipped.append({"action": a.to_dict(), "reason": "RETAG requires 'id'"})
            continue
        if a.kind == "SUPERSEDE" and not a.old_id:
            skipped.append({"action": a.to_dict(), "reason": "SUPERSEDE requires 'old_id'"})
            continue
        if a.kind == "DEPRECATE" and not a.id:
            skipped.append({"action": a.to_dict(), "reason": "DEPRECATE requires 'id'"})
            continue
        if a.kind == "UPDATE" and not a.id:
            skipped.append({"action": a.to_dict(), "reason": "UPDATE requires 'id'"})
            continue
        if a.kind == "SPLIT_FILE" and not a.rst_path:
            skipped.append({"action": a.to_dict(), "reason": "SPLIT_FILE requires 'rst_path'"})
            continue

        # Check supersede cycles
        if a.kind == "SUPERSEDE" and a.old_id:
            visited: set[str] = set()
            current = a.old_id
            cycle = False
            while current in supersede_map:
                if current in visited:
                    cycle = True
                    break
                visited.add(current)
                current = supersede_map[current]
            if cycle:
                skipped.append(
                    {
                        "action": a.to_dict(),
                        "reason": f"Circular supersede chain involving {a.old_id}",
                    }
                )
                continue

        valid.append(a)

    return valid, skipped


# ---------------------------------------------------------------------------
# Individual action executors
# ---------------------------------------------------------------------------


def _execute_retag(workspace: Path, action: Action) -> tuple[bool, str]:
    """Execute a RETAG action — add/remove tags on a memory."""
    messages: list[str] = []
    ok = True

    if action.remove_tags:
        success, msg = remove_tags_in_rst(workspace, action.id, action.remove_tags)
        messages.append(msg)
        ok = ok and success

    if action.add_tags:
        success, msg = add_tags_in_rst(workspace, action.id, action.add_tags)
        messages.append(msg)
        ok = ok and success

    return ok, "; ".join(messages)


def _execute_supersede(workspace: Path, action: Action) -> tuple[bool, str]:
    """Execute a SUPERSEDE action — deprecate old, optionally create new."""
    messages: list[str] = []

    # Deprecate the old memory
    ok, msg = deprecate_in_rst(workspace, action.old_id, action.by_id)
    messages.append(msg)

    if not ok:
        return False, f"Failed to deprecate {action.old_id}: {msg}"

    # If new memory details provided, create it
    if action.new_type and action.new_title:
        directive = generate_rst_directive(
            mem_type=action.new_type,
            title=action.new_title,
            tags=action.new_tags or [],
            body=action.new_body or "",
            supersedes=[action.old_id],
        )
        target = append_to_rst(workspace, action.new_type, directive)
        messages.append(f"Created replacement in {target.name}")

    return True, "; ".join(messages)


def _execute_deprecate(workspace: Path, action: Action) -> tuple[bool, str]:
    """Execute a DEPRECATE action."""
    return deprecate_in_rst(workspace, action.id, action.by_id or None)


def _execute_update(workspace: Path, action: Action) -> tuple[bool, str]:
    """Execute an UPDATE action — change metadata fields."""
    if not action.field_changes:
        return True, f"No field changes for {action.id}"

    messages: list[str] = []
    all_ok = True

    for field_name, value in action.field_changes.items():
        ok, msg = update_field_in_rst(workspace, action.id, field_name, value)
        messages.append(msg)
        all_ok = all_ok and ok

    return all_ok, "; ".join(messages)


def _execute_prune(workspace: Path, action: Action) -> tuple[bool, str]:
    """Execute a PRUNE action — deprecate without replacement."""
    return deprecate_in_rst(workspace, action.id)


def _execute_split_file(workspace: Path, action: Action) -> tuple[bool, str]:  # noqa: ARG001
    """Execute a SPLIT_FILE action.

    This is informational — actual splitting happens automatically
    via rst.py append_to_rst when MAX_ENTRIES_PER_FILE is exceeded.
    """
    return True, (
        f"File splitting noted for {action.rst_path} — handled automatically on next append."
    )


# Dispatcher
_EXECUTORS = {
    "RETAG": _execute_retag,
    "SUPERSEDE": _execute_supersede,
    "DEPRECATE": _execute_deprecate,
    "UPDATE": _execute_update,
    "PRUNE": _execute_prune,
    "SPLIT_FILE": _execute_split_file,
}


# ---------------------------------------------------------------------------
# Git operations for rollback
# ---------------------------------------------------------------------------


def _git_stash_push(workspace: Path) -> bool:
    """Stash uncommitted changes for rollback.  Returns True if stash was created."""
    try:
        result = subprocess.run(
            ["git", "stash", "push", "-m", "memory_apply pre-backup"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        # Only treat as successful if git exited cleanly.
        if result.returncode != 0:
            return False
        # "No local changes to save" means nothing was stashed.
        # This may appear in stdout or stderr.
        output = (result.stdout or "") + (result.stderr or "")
        return "No local changes to save" not in output
    except OSError:
        return False


def _git_stash_pop(workspace: Path) -> bool:
    """Pop stashed changes to rollback."""
    try:
        result = subprocess.run(
            ["git", "stash", "pop"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except OSError:
        return False


def _git_stash_drop(workspace: Path) -> bool:
    """Drop the stash (cleanup after successful apply)."""
    try:
        result = subprocess.run(
            ["git", "stash", "drop"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except OSError:
        return False


def _git_commit(workspace: Path, message: str) -> bool:
    """Stage and commit memory changes."""
    try:
        subprocess.run(
            ["git", "add", "memory/", "*.rst"],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(workspace),
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Main execution entry point
# ---------------------------------------------------------------------------


def execute_plan(
    workspace: Path,
    actions: list[Action],
    auto_commit: bool = False,
    rebuild: bool = True,
) -> ExecutionResult:
    """Execute a list of planned actions.

    Parameters
    ----------
    workspace
        Path to the memory workspace.
    actions
        Actions to execute (from ``run_plan`` or deserialized from JSON).
    auto_commit
        If True, commit changes to git after successful execution.
    rebuild
        If True, run Sphinx rebuild after applying actions.

    Returns
    -------
    ExecutionResult
        Summary of applied/failed/skipped actions + build output.
    """
    # Validate
    valid_actions, skipped = validate_actions(actions)

    if not valid_actions:
        return ExecutionResult(
            success=True,
            skipped=skipped,
            message="No valid actions to execute.",
        )

    # Stash for rollback
    stashed = _git_stash_push(workspace)

    # Execute sequentially
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for action in valid_actions:
        executor = _EXECUTORS.get(action.kind)
        if not executor:
            failed.append(
                {
                    "action": action.to_dict(),
                    "error": f"Unknown action kind: {action.kind}",
                }
            )
            continue

        try:
            ok, msg = executor(workspace, action)
            entry = {"action": action.to_dict(), "message": msg}
            if ok:
                applied.append(entry)
            else:
                failed.append({**entry, "error": msg})
        except Exception as e:
            failed.append({"action": action.to_dict(), "error": str(e)})

    # Rebuild
    build_output = ""
    build_ok = True
    if rebuild and applied:
        build_ok, build_output = run_rebuild(workspace)

    # If build failed, always treat as unsuccessful; use git stash for rollback
    # when available.
    if not build_ok:
        if stashed:
            _git_stash_pop(workspace)
            applied_result: list[dict[str, Any]] = []
            message = "Build failed after applying actions — rolled back via git stash pop."
        else:
            # No stash available: cannot automatically roll back workspace changes.
            applied_result = applied
            message = (
                "Build failed after applying actions — no git stash available for "
                "rollback; workspace may be in an inconsistent state."
            )

        return ExecutionResult(
            success=False,
            applied=applied_result,
            failed=failed,
            skipped=skipped,
            build_output=build_output,
            message=message,
        )

    # Cleanup stash on success
    if stashed:
        _git_stash_drop(workspace)

    # Auto-commit
    if auto_commit and applied:
        kinds = set(a.get("action", {}).get("kind", "?") for a in applied)
        msg = f"memory: auto-apply {', '.join(sorted(kinds))} ({len(applied)} actions)"
        _git_commit(workspace, msg)

    all_succeeded = not failed
    return ExecutionResult(
        success=all_succeeded,
        applied=applied,
        failed=failed,
        skipped=skipped,
        build_output=build_output,
        message=(
            f"Plan executed: {len(applied)} applied, {len(failed)} failed, {len(skipped)} skipped."
        ),
    )


def actions_from_json(data: list[dict[str, Any]]) -> list[Action]:
    """Deserialize a list of action dicts (e.g. from JSON) into Action objects."""
    actions: list[Action] = []
    for d in data:
        actions.append(
            Action(
                kind=d.get("kind", "UPDATE"),
                reason=d.get("reason", ""),
                id=d.get("id", ""),
                add_tags=d.get("add_tags", []),
                remove_tags=d.get("remove_tags", []),
                field_changes=d.get("field_changes", {}),
                old_id=d.get("old_id", ""),
                new_type=d.get("new_type", ""),
                new_title=d.get("new_title", ""),
                new_body=d.get("new_body", ""),
                new_tags=d.get("new_tags", []),
                new_links=d.get("new_links", []),
                by_id=d.get("by_id", ""),
                rst_path=d.get("rst_path", ""),
            )
        )
    return actions
