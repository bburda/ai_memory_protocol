"""Plan analysis — detect problems and generate maintenance actions.

The planner is **read-only**: it loads needs.json + RST files, runs
detection algorithms, and returns a list of ``Action`` dicts describing
what *should* be done.  The executor (``executor.py``) is responsible
for actually applying actions.

Usage:
    from ai_memory_protocol.planner import run_plan
    actions = run_plan(workspace, checks=["duplicates", "missing_tags"])
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from .config import TYPE_FILES
from .engine import load_needs
from .rst import MAX_ENTRIES_PER_FILE, _count_entries, _find_all_rst_files

# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

ActionKind = Literal["RETAG", "SUPERSEDE", "DEPRECATE", "UPDATE", "PRUNE", "SPLIT_FILE"]

ALL_CHECKS: list[str] = [
    "duplicates",
    "missing_tags",
    "stale",
    "conflicts",
    "tag_normalize",
    "split_files",
]


@dataclass
class Action:
    """A planned maintenance action."""

    kind: ActionKind
    reason: str
    # Fields used by individual action kinds
    id: str = ""
    add_tags: list[str] = field(default_factory=list)
    remove_tags: list[str] = field(default_factory=list)
    field_changes: dict[str, str] = field(default_factory=dict)
    # SUPERSEDE-specific
    old_id: str = ""
    new_type: str = ""
    new_title: str = ""
    new_body: str = ""
    new_tags: list[str] = field(default_factory=list)
    new_links: list[str] = field(default_factory=list)
    # DEPRECATE-specific
    by_id: str = ""
    # SPLIT_FILE-specific
    rst_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict, omitting empty fields."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v}


# ---------------------------------------------------------------------------
# Detection algorithms
# ---------------------------------------------------------------------------


def _active_needs(needs: dict[str, Any]) -> dict[str, Any]:
    """Filter to non-deprecated needs only."""
    return {k: v for k, v in needs.items() if v.get("status") != "deprecated"}


def detect_duplicates(
    needs: dict[str, Any],
    title_threshold: float = 0.8,
    tag_overlap_threshold: float = 0.5,
) -> list[Action]:
    """Find near-duplicate memories by title similarity + tag overlap.

    Complexity: O(n²) — acceptable for n < 500.
    """
    active = _active_needs(needs)
    items = list(active.items())
    actions: list[Action] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, (id1, n1) in enumerate(items):
        for id2, n2 in items[i + 1 :]:
            pair = tuple(sorted((id1, id2)))
            if pair in seen_pairs:
                continue

            title_sim = SequenceMatcher(
                None, n1.get("title", "").lower(), n2.get("title", "").lower()
            ).ratio()
            if title_sim < title_threshold:
                continue

            tags1 = set(n1.get("tags", []))
            tags2 = set(n2.get("tags", []))
            union = tags1 | tags2
            if not union:
                continue
            tag_overlap = len(tags1 & tags2) / len(union)
            if tag_overlap < tag_overlap_threshold:
                continue

            seen_pairs.add(pair)

            # Prefer newer + higher-confidence as canonical
            conf_rank = {"high": 2, "medium": 1, "low": 0}
            score1 = (
                conf_rank.get(n1.get("confidence", "medium"), 1),
                n1.get("created_at", ""),
            )
            score2 = (
                conf_rank.get(n2.get("confidence", "medium"), 1),
                n2.get("created_at", ""),
            )

            if score2 > score1:
                old_id, new_id = id1, id2
            else:
                old_id, new_id = id2, id1

            actions.append(
                Action(
                    kind="SUPERSEDE",
                    reason=(
                        f"Near-duplicate: title similarity {title_sim:.0%}, "
                        f"tag overlap {tag_overlap:.0%}. "
                        f"Keep {new_id} (higher score), deprecate {old_id}."
                    ),
                    old_id=old_id,
                    by_id=new_id,
                )
            )

    return actions


def detect_missing_tags(needs: dict[str, Any]) -> list[Action]:
    """Find memories without required tag prefixes (topic: or repo:).

    O(n) — checks every active need once.
    """
    active = _active_needs(needs)
    actions: list[Action] = []

    for nid, need in active.items():
        tags = need.get("tags", [])
        has_topic = any(t.startswith("topic:") for t in tags)
        has_repo = any(t.startswith("repo:") for t in tags)
        missing: list[str] = []
        if not has_topic:
            missing.append("topic:")
        if not has_repo:
            missing.append("repo:")
        if missing:
            actions.append(
                Action(
                    kind="RETAG",
                    reason=f"Missing required tag prefix(es): {', '.join(missing)}",
                    id=nid,
                )
            )

    return actions


def detect_stale(needs: dict[str, Any]) -> list[Action]:
    """Find expired or review-overdue memories.

    O(n) — mirrors the logic in ``cmd_stale`` but returns actions.
    """
    active = _active_needs(needs)
    today = date.today().isoformat()
    actions: list[Action] = []

    for nid, need in active.items():
        expires = need.get("expires_at", "")
        review = need.get("review_after", "")

        if expires and expires <= today:
            actions.append(
                Action(
                    kind="UPDATE",
                    reason=f"Expired on {expires} — needs review or deprecation.",
                    id=nid,
                    field_changes={"status": "review"},
                )
            )
        elif review and review <= today:
            actions.append(
                Action(
                    kind="UPDATE",
                    reason=f"Review overdue since {review}.",
                    id=nid,
                    field_changes={"status": "review"},
                )
            )

    return actions


def detect_conflicts(needs: dict[str, Any]) -> list[Action]:
    """Find active needs with same topic but no contradicts link.

    Heuristic: two decisions on the same topic:* tag with no explicit
    relationship may indicate an unrecorded contradiction.

    O(n²) per topic group — practical for small graphs.
    """
    active = _active_needs(needs)
    # Group decisions by topic tag
    by_topic: dict[str, list[str]] = defaultdict(list)
    for nid, need in active.items():
        if need.get("type") not in ("dec", "pref"):
            continue
        for tag in need.get("tags", []):
            if tag.startswith("topic:"):
                by_topic[tag].append(nid)

    actions: list[Action] = []
    seen: set[tuple[str, str]] = set()

    for _topic, ids in by_topic.items():
        if len(ids) < 2:
            continue
        for i, id1 in enumerate(ids):
            for id2 in ids[i + 1 :]:
                pair = tuple(sorted((id1, id2)))
                if pair in seen:
                    continue
                seen.add(pair)

                n1, n2 = active[id1], active[id2]
                # Check if they already have a relationship
                links1 = set()
                links2 = set()
                for lt in ("relates", "supports", "depends", "contradicts", "supersedes"):
                    links1.update(n1.get(lt, []))
                    links2.update(n2.get(lt, []))

                if id2 not in links1 and id1 not in links2:
                    actions.append(
                        Action(
                            kind="UPDATE",
                            reason=(
                                f"Potential conflict: {id1} and {id2} are both "
                                f"active {n1.get('type')}/{n2.get('type')} entries on "
                                f"the same topic with no explicit relationship link."
                            ),
                            id=id1,
                            field_changes={},
                        )
                    )

    return actions


def detect_tag_normalization(needs: dict[str, Any]) -> list[Action]:
    """Find case-insensitive tag duplicates and normalize to most common form.

    O(n) scan + O(types per lowered tag).
    """
    active = _active_needs(needs)
    # Collect all tag forms with usage counts
    tag_usage: dict[str, int] = defaultdict(int)  # exact form -> count
    for need in active.values():
        for tag in need.get("tags", []):
            tag_usage[tag] += 1

    # Group by lowercased form
    lower_groups: dict[str, set[str]] = defaultdict(set)
    for tag in tag_usage:
        lower_groups[tag.lower()].add(tag)

    actions: list[Action] = []
    for forms in lower_groups.values():
        if len(forms) <= 1:
            continue
        # Pick the most common form as canonical
        canonical = max(forms, key=lambda t: tag_usage[t])
        non_canonical = forms - {canonical}
        for form in non_canonical:
            for nid, need in active.items():
                if form in need.get("tags", []):
                    actions.append(
                        Action(
                            kind="RETAG",
                            reason=f"Tag normalization: '{form}' → '{canonical}'",
                            id=nid,
                            remove_tags=[form],
                            add_tags=[canonical],
                        )
                    )

    return actions


def detect_split_files(workspace: Path) -> list[Action]:
    """Find RST files that exceed MAX_ENTRIES_PER_FILE.

    O(files) — scans each RST file once.
    """
    actions: list[Action] = []

    for mem_type in TYPE_FILES:
        for rst_path in _find_all_rst_files(workspace, mem_type):
            count = _count_entries(rst_path)
            if count > MAX_ENTRIES_PER_FILE:
                actions.append(
                    Action(
                        kind="SPLIT_FILE",
                        reason=(
                            f"{rst_path.name} has {count} entries "
                            f"(limit: {MAX_ENTRIES_PER_FILE})."
                        ),
                        rst_path=str(rst_path),
                    )
                )

    return actions


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

# Map check names to detector functions
_DETECTORS: dict[str, Any] = {
    "duplicates": lambda needs, ws: detect_duplicates(needs),
    "missing_tags": lambda needs, ws: detect_missing_tags(needs),
    "stale": lambda needs, ws: detect_stale(needs),
    "conflicts": lambda needs, ws: detect_conflicts(needs),
    "tag_normalize": lambda needs, ws: detect_tag_normalization(needs),
    "split_files": lambda needs, ws: detect_split_files(ws),
}


def run_plan(
    workspace: Path,
    checks: list[str] | None = None,
    needs: dict[str, Any] | None = None,
) -> list[Action]:
    """Run selected (or all) checks and return a unified list of actions.

    Parameters
    ----------
    workspace
        Path to the memory workspace (containing conf.py, memory/, etc.).
    checks
        Which checks to run.  Defaults to all checks.
    needs
        Pre-loaded needs dict.  If ``None``, loads from workspace.

    Returns
    -------
    list[Action]
        Ordered list of planned actions — not yet executed.
    """
    if needs is None:
        needs = load_needs(workspace)

    selected = checks or ALL_CHECKS
    all_actions: list[Action] = []

    for check in selected:
        detector = _DETECTORS.get(check)
        if detector is None:
            continue
        # split_files only needs workspace, others need needs dict
        actions = detector(needs, workspace)
        all_actions.extend(actions)

    return all_actions


def format_plan(actions: list[Action], fmt: str = "human") -> str:
    """Render a plan as human-readable text or JSON.

    Parameters
    ----------
    fmt
        ``"human"`` for readable text, ``"json"`` for machine-readable.
    """
    if not actions:
        return "No issues found — memory graph looks healthy."

    if fmt == "json":
        import json

        return json.dumps([a.to_dict() for a in actions], indent=2, ensure_ascii=False)

    lines: list[str] = [f"## Memory Maintenance Plan — {len(actions)} action(s)\n"]

    # Group by kind
    by_kind: dict[str, list[Action]] = defaultdict(list)
    for a in actions:
        by_kind[a.kind].append(a)

    for kind in ("SUPERSEDE", "DEPRECATE", "RETAG", "UPDATE", "PRUNE", "SPLIT_FILE"):
        group = by_kind.get(kind, [])
        if not group:
            continue
        lines.append(f"### {kind} ({len(group)})\n")
        for a in group:
            target = a.id or a.old_id or a.rst_path
            lines.append(f"  - **{target}**: {a.reason}")
            if a.add_tags:
                lines.append(f"    + add tags: {', '.join(a.add_tags)}")
            if a.remove_tags:
                lines.append(f"    - remove tags: {', '.join(a.remove_tags)}")
            if a.field_changes:
                for k, v in a.field_changes.items():
                    lines.append(f"    ~ {k} → {v}")
            if a.by_id:
                lines.append(f"    → superseded by: {a.by_id}")
        lines.append("")

    return "\n".join(lines)
