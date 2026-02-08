"""Output formatting — brief, compact, full, context-pack, JSON."""

from __future__ import annotations

from typing import Any

from .config import CONTEXT_PACK_LABELS, CONTEXT_PACK_ORDER, LINK_FIELDS, METADATA_FIELDS


def format_brief(need: dict[str, Any]) -> str:
    """Ultra-compact single line — minimal tokens for context window.

    Format: [ID] Title (confidence) {key-tags}
    """
    nid = need.get("id", "?")
    title = need.get("title", "")
    conf = need.get("confidence", "?")
    tags = need.get("tags", [])
    # Only show topic/repo tags (most useful for context)
    key_tags = [t for t in tags if t.startswith(("topic:", "repo:"))]
    tag_str = f" {{{','.join(key_tags)}}}" if key_tags else ""
    return f"[{nid}] {title} ({conf}){tag_str}"


def format_compact(need: dict[str, Any], show_body: bool = False) -> str:
    """One-liner (optionally two) per memory — for quick scanning."""
    parts = [
        f"[{need.get('id', '?')}]",
        need.get("title", ""),
        f"status={need.get('status', '?')}",
        f"confidence={need.get('confidence', '?')}",
    ]

    tags = need.get("tags", [])
    if tags:
        parts.append(f"tags=[{','.join(tags)}]")

    links = []
    for lt in LINK_FIELDS:
        targets = need.get(lt, [])
        if targets:
            links.append(f"{lt}:{','.join(targets)}")
        back = need.get(f"{lt}_back", [])
        if back:
            links.append(f"{lt}_back:{','.join(back)}")
    if links:
        parts.append(f"links=[{'; '.join(links)}]")

    line = " | ".join(parts)

    if show_body:
        desc = (need.get("description", "") or need.get("content", "")).strip()
        if desc:
            snippet = desc[:500] + ("..." if len(desc) > 500 else "")
            line += f"\n  > {snippet}"

    return line


def format_full(need: dict[str, Any]) -> str:
    """Full metadata — for deep inspection of a single memory."""
    lines = [
        f"# {need.get('id', '?')}: {need.get('title', '')}",
        f"type: {need.get('type', '?')}",
        f"status: {need.get('status', '?')}",
        f"confidence: {need.get('confidence', '?')}",
        f"scope: {need.get('scope', '?')}",
    ]

    tags = need.get("tags", [])
    if tags:
        lines.append(f"tags: {', '.join(tags)}")

    for field in METADATA_FIELDS:
        val = need.get(field, "")
        if val and field not in ("confidence", "scope"):  # Already shown above
            lines.append(f"{field}: {val}")

    for lt in LINK_FIELDS:
        targets = need.get(lt, [])
        if targets:
            lines.append(f"{lt}: {', '.join(targets)}")
        back = need.get(f"{lt}_back", [])
        if back:
            lines.append(f"{lt}_back: {', '.join(back)}")

    desc = (need.get("description", "") or need.get("content", "")).strip()
    if desc:
        lines.append(f"\n{desc}")

    return "\n".join(lines)


def format_context_pack(needs: dict[str, Any], show_body: bool = False) -> str:
    """Structured prompt section for AI context windows.

    Groups by type, ordered by trust level (facts first).
    Body text is hidden by default to save tokens — use ``memory get <ID>`` for details.
    """
    if not needs:
        return "No relevant memories found."

    count = len(needs)
    lines = [f"## Recalled Memories ({count} results)\n"]

    by_type: dict[str, list[dict[str, Any]]] = {}
    for need in needs.values():
        by_type.setdefault(need.get("type", "?"), []).append(need)

    for t in CONTEXT_PACK_ORDER:
        entries = by_type.get(t, [])
        if not entries:
            continue
        label = CONTEXT_PACK_LABELS.get(t, t)
        lines.append(f"### {label}")
        for e in sorted(entries, key=lambda x: x.get("confidence", ""), reverse=True):
            lines.append(format_compact(e, show_body=show_body))
        lines.append("")

    if not show_body:
        lines.append("_Use `memory get <ID>` to see full body text._")

    return "\n".join(lines)
