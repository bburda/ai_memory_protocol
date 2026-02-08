"""MCP server — exposes AI Memory Protocol as MCP tools for LLM agents.

Thin wrappers over the existing engine, formatter, and rst modules.
Supports both stdio and SSE transports via the ``mcp`` Python SDK.

Usage:
    # stdio (Claude Desktop, VS Code Copilot, etc.)
    memory-mcp-stdio

    # With custom workspace directory
    MEMORY_DIR=/path/to/.memories memory-mcp-stdio
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from .engine import (
    expand_graph,
    find_workspace,
    load_needs,
    resolve_id,
    run_rebuild,
    tag_match,
    text_match,
)
from .formatter import format_brief, format_compact, format_context_pack, format_full
from .rst import (
    add_tags_in_rst,
    append_to_rst,
    deprecate_in_rst,
    generate_id,
    generate_rst_directive,
    remove_tags_in_rst,
    update_field_in_rst,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------


def create_mcp_server(name: str = "ai-memory-protocol") -> Server:
    """Create and configure the MCP server with all memory tools."""
    server = Server(name)
    _register_tools(server)
    _register_handlers(server)
    return server


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS: list[Tool] = [
    Tool(
        name="memory_recall",
        description=(
            "Search memories by free text query and/or tags. "
            "Returns matching memories formatted for context windows. "
            "Use this FIRST to check existing knowledge before starting work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Free-text search query (OR logic across words). Optional if tag is provided.",
                },
                "tag": {
                    "type": "string",
                    "description": "Comma-separated tag filters (AND logic). E.g. 'topic:gateway,repo:ros2_medkit'.",
                },
                "type": {
                    "type": "string",
                    "description": "Filter by memory type: mem, dec, fact, pref, risk, goal, q.",
                    "enum": ["mem", "dec", "fact", "pref", "risk", "goal", "q"],
                },
                "format": {
                    "type": "string",
                    "description": "Output format: brief (minimal tokens), compact (one-liner), context (grouped by type, default), json.",
                    "enum": ["brief", "compact", "context", "json"],
                    "default": "context",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return. 0 = unlimited.",
                    "default": 0,
                },
                "body": {
                    "type": "boolean",
                    "description": "Include body text in output. Default false to save tokens.",
                    "default": False,
                },
                "sort": {
                    "type": "string",
                    "description": "Sort order for results.",
                    "enum": ["newest", "oldest", "confidence", "updated"],
                },
                "expand": {
                    "type": "integer",
                    "description": "Graph expansion hops from matched memories. 0 = exact matches only. Default 1.",
                    "default": 1,
                },
                "stale": {
                    "type": "boolean",
                    "description": "If true, show only expired or review-overdue memories.",
                    "default": False,
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="memory_get",
        description=(
            "Get full details of a specific memory by ID. "
            "Always shows body text. Use after recall to drill into a specific memory."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Memory ID, e.g. DEC_rest_framework or FACT_gateway_port.",
                },
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="memory_add",
        description=(
            "Record a new memory. Use when you discover, decide, or observe something important. "
            "Always include tags for discoverability. Always include body with enough context "
            "that a future agent can act on it without re-reading source files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Memory type.",
                    "enum": ["mem", "dec", "fact", "pref", "risk", "goal", "q"],
                },
                "title": {
                    "type": "string",
                    "description": "Short title for the memory.",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags in prefix:value format. E.g. 'topic:api,repo:backend'.",
                },
                "body": {
                    "type": "string",
                    "description": "Detailed description text.",
                },
                "confidence": {
                    "type": "string",
                    "description": "Trust level.",
                    "enum": ["low", "medium", "high"],
                    "default": "medium",
                },
                "source": {
                    "type": "string",
                    "description": "Provenance — URL, commit, ticket, or description of origin.",
                },
                "scope": {
                    "type": "string",
                    "description": "Applicability scope. E.g. 'global', 'repo:ros2_medkit'.",
                    "default": "global",
                },
                "relates": {
                    "type": "string",
                    "description": "Comma-separated IDs of related memories.",
                },
                "supersedes": {
                    "type": "string",
                    "description": "Comma-separated IDs that this memory supersedes.",
                },
                "id": {
                    "type": "string",
                    "description": "Custom memory ID. Auto-generated from type + title if omitted.",
                },
                "rebuild": {
                    "type": "boolean",
                    "description": "Auto-rebuild needs.json after adding. Default true.",
                    "default": True,
                },
            },
            "required": ["type", "title", "tags"],
        },
    ),
    Tool(
        name="memory_update",
        description=(
            "Update metadata on an existing memory. "
            "Can change status, confidence, scope, tags, review date, etc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Memory ID to update.",
                },
                "status": {
                    "type": "string",
                    "description": "New status.",
                    "enum": ["draft", "active", "promoted", "deprecated", "review"],
                },
                "confidence": {
                    "type": "string",
                    "description": "New confidence level.",
                    "enum": ["low", "medium", "high"],
                },
                "scope": {
                    "type": "string",
                    "description": "New scope.",
                },
                "review_after": {
                    "type": "string",
                    "description": "New review date (ISO-8601, e.g. 2026-06-01).",
                },
                "source": {
                    "type": "string",
                    "description": "New source/provenance.",
                },
                "add_tags": {
                    "type": "string",
                    "description": "Tags to add, comma-separated.",
                },
                "remove_tags": {
                    "type": "string",
                    "description": "Tags to remove, comma-separated.",
                },
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="memory_deprecate",
        description=(
            "Mark a memory as deprecated. Optionally specify the superseding memory. "
            "Use this instead of editing — supersede, don't silently edit."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Memory ID to deprecate.",
                },
                "by": {
                    "type": "string",
                    "description": "ID of the superseding memory.",
                },
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="memory_tags",
        description=(
            "List all tags in use with counts, grouped by prefix. "
            "Use before filtering to discover available tag prefixes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Filter by tag prefix, e.g. 'topic' to see only topic:* tags.",
                },
            },
            "required": [],
        },
    ),
    Tool(
        name="memory_stale",
        description="Show expired or review-overdue memories. Use periodically to keep the memory graph fresh.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="memory_rebuild",
        description=(
            "Rebuild needs.json from RST sources by running Sphinx build. "
            "Required after adding or modifying memories to make changes searchable."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
]


def _register_tools(server: Server) -> None:
    """Register tool listing handler."""

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


def _get_workspace() -> Path:
    """Get workspace, using MEMORY_DIR or auto-detection."""
    return find_workspace(None)


def _sort_needs(needs: dict[str, Any], sort: str | None) -> list[tuple[str, dict[str, Any]]]:
    """Sort needs by the given key."""
    items = list(needs.items())
    if sort == "newest":
        items.sort(key=lambda x: x[1].get("created_at", ""), reverse=True)
    elif sort == "oldest":
        items.sort(key=lambda x: x[1].get("created_at", ""))
    elif sort == "confidence":
        items.sort(
            key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(
                x[1].get("confidence", "medium"), 1
            )
        )
    elif sort == "updated":
        items.sort(
            key=lambda x: x[1].get("updated_at", "") or x[1].get("created_at", ""),
            reverse=True,
        )
    return items


def _format_output(
    needs: dict[str, Any],
    fmt: str = "context",
    limit: int = 0,
    show_body: bool = False,
    sort: str | None = None,
) -> str:
    """Format needs dict into a string using the specified format."""
    sorted_items = _sort_needs(needs, sort) if sort else list(needs.items())

    if limit and len(sorted_items) > limit:
        if not sort:
            sorted_items.sort(
                key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(
                    x[1].get("confidence", "medium"), 1
                )
            )
        sorted_items = sorted_items[:limit]
        omitted = len(needs) - limit
    else:
        omitted = 0

    trimmed = dict(sorted_items)
    lines: list[str] = []

    if fmt == "json":
        return json.dumps(trimmed, indent=2, ensure_ascii=False)
    elif fmt == "brief":
        for _, need in sorted_items:
            lines.append(format_brief(need))
    elif fmt == "compact":
        for _, need in sorted_items:
            lines.append(format_compact(need, show_body=show_body))
    else:  # context (default)
        lines.append(format_context_pack(trimmed, show_body=show_body))

    if omitted:
        lines.append(f"\n({omitted} more results omitted — use limit parameter to see more)")

    return "\n".join(lines)


def _do_rebuild(workspace: Path) -> str:
    """Run Sphinx build to regenerate needs.json."""
    success, message = run_rebuild(workspace)
    return message


def _text_response(text: str) -> list[TextContent]:
    """Wrap a string as MCP TextContent."""
    return [TextContent(type="text", text=text)]


def _register_handlers(server: Server) -> None:
    """Register all tool call handlers."""

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "memory_recall":
                return _handle_recall(arguments)
            elif name == "memory_get":
                return _handle_get(arguments)
            elif name == "memory_add":
                return _handle_add(arguments)
            elif name == "memory_update":
                return _handle_update(arguments)
            elif name == "memory_deprecate":
                return _handle_deprecate(arguments)
            elif name == "memory_tags":
                return _handle_tags(arguments)
            elif name == "memory_stale":
                return _handle_stale(arguments)
            elif name == "memory_rebuild":
                return _handle_rebuild(arguments)
            else:
                return _text_response(f"Unknown tool: {name}")
        except SystemExit as e:
            return _text_response(f"Error: {e}")
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return _text_response(f"Error in {name}: {e}")


# ---------------------------------------------------------------------------
# Individual tool handlers
# ---------------------------------------------------------------------------


def _handle_recall(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    needs = load_needs(workspace)
    query = args.get("query", "")
    tag_filters = (
        [t.strip() for t in args["tag"].split(",") if t.strip()] if args.get("tag") else []
    )
    type_filter = args.get("type")
    today = date.today().isoformat()
    stale_only = args.get("stale", False)

    matched: dict[str, Any] = {}
    for nid, need in needs.items():
        if need.get("status") == "deprecated":
            continue
        expires = need.get("expires_at", "")
        if expires and expires <= today and not stale_only:
            continue
        if type_filter and need.get("type") != type_filter:
            continue
        if tag_filters and not tag_match(need, tag_filters):
            continue
        if query and not text_match(need, query):
            continue
        matched[nid] = need

    if stale_only:
        stale: dict[str, Any] = {}
        for nid, need in matched.items():
            exp = need.get("expires_at", "")
            rev = need.get("review_after", "")
            if (exp and exp <= today) or (rev and rev <= today):
                stale[nid] = need
        matched = stale

    if not matched:
        return _text_response("No memories found.")

    expand = args.get("expand", 1)
    if expand:
        matched = expand_graph(needs, set(matched.keys()), hops=expand)
        matched = {k: v for k, v in matched.items() if v.get("status") != "deprecated"}

    output = _format_output(
        matched,
        fmt=args.get("format", "context"),
        limit=args.get("limit", 0),
        show_body=args.get("body", False),
        sort=args.get("sort"),
    )
    return _text_response(output)


def _handle_get(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    needs = load_needs(workspace)
    need_id = resolve_id(needs, args["id"])
    if not need_id:
        return _text_response(f"Memory '{args['id']}' not found.")
    return _text_response(format_full(needs[need_id]))


def _handle_add(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    tags = [t.strip() for t in args["tags"].split(",") if t.strip()] if args.get("tags") else []
    relates = (
        [t.strip() for t in args["relates"].split(",") if t.strip()]
        if args.get("relates")
        else None
    )
    supersedes = (
        [t.strip() for t in args["supersedes"].split(",") if t.strip()]
        if args.get("supersedes")
        else None
    )

    directive = generate_rst_directive(
        mem_type=args["type"],
        title=args["title"],
        need_id=args.get("id"),
        tags=tags,
        source=args.get("source", ""),
        confidence=args.get("confidence", "medium"),
        scope=args.get("scope", "global"),
        body=args.get("body", ""),
        relates=relates,
        supersedes=supersedes,
    )

    target = append_to_rst(workspace, args["type"], directive)
    nid = args.get("id") or generate_id(args["type"], args["title"])
    result_lines = [f"Added {nid} → {target.name}"]

    if args.get("rebuild", True):
        success, rebuild_msg = run_rebuild(workspace)
        if success:
            result_lines.append(rebuild_msg)
        else:
            result_lines.append(f"Warning: Memory was added but rebuild failed: {rebuild_msg}")
            result_lines.append("Run memory_rebuild manually when sphinx-build is available.")

    return _text_response("\n".join(result_lines))


def _handle_update(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    need_id = args["id"]
    messages: list[str] = []
    any_change = False

    for field in ("status", "confidence", "scope", "review_after", "source"):
        value = args.get(field)
        if value is not None:
            ok, msg = update_field_in_rst(workspace, need_id, field, value)
            messages.append(msg)
            any_change = any_change or ok

    if args.get("add_tags"):
        new_tags = [t.strip() for t in args["add_tags"].split(",")]
        ok, msg = add_tags_in_rst(workspace, need_id, new_tags)
        messages.append(msg)
        any_change = any_change or ok

    if args.get("remove_tags"):
        rm_tags = [t.strip() for t in args["remove_tags"].split(",")]
        ok, msg = remove_tags_in_rst(workspace, need_id, rm_tags)
        messages.append(msg)
        any_change = any_change or ok

    if not any_change:
        return _text_response("No changes made. Specify at least one field to update.")

    messages.append("Run memory_rebuild to update needs.json.")
    return _text_response("\n".join(messages))


def _handle_deprecate(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    ok, msg = deprecate_in_rst(workspace, args["id"], args.get("by"))
    if ok:
        msg += "\nRun memory_rebuild to update needs.json."
    return _text_response(msg)


def _handle_tags(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    needs = load_needs(workspace)
    tag_counts: dict[str, int] = {}
    for need in needs.values():
        if need.get("status") == "deprecated":
            continue
        for tag in need.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    if not tag_counts:
        return _text_response("No tags found.")

    by_prefix: dict[str, list[tuple[str, int]]] = {}
    for tag, count in sorted(tag_counts.items()):
        prefix = tag.split(":")[0] if ":" in tag else "_untagged"
        by_prefix.setdefault(prefix, []).append((tag, count))

    prefix_filter = args.get("prefix")
    lines: list[str] = []
    total = 0
    for prefix in sorted(by_prefix.keys()):
        if prefix_filter and prefix != prefix_filter:
            continue
        entries = by_prefix[prefix]
        lines.append(f"\n{prefix}:")
        for tag, count in sorted(entries, key=lambda x: -x[1]):
            lines.append(f"  {tag}  ({count})")
            total += count

    lines.append(f"\n{len(tag_counts)} unique tags, {total} total usages")
    return _text_response("\n".join(lines))


def _handle_stale(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    needs = load_needs(workspace)
    today = date.today().isoformat()

    expired: list[dict[str, Any]] = []
    review_due: list[dict[str, Any]] = []
    for need in needs.values():
        if need.get("status") == "deprecated":
            continue
        ea = need.get("expires_at", "")
        if ea and ea <= today:
            expired.append(need)
        ra = need.get("review_after", "")
        if ra and ra <= today and not ea:
            review_due.append(need)

    if not expired and not review_due:
        return _text_response("No stale memories found.")

    lines: list[str] = []
    if expired:
        lines.append(f"## {len(expired)} EXPIRED memories\n")
        for need in sorted(expired, key=lambda n: n.get("expires_at", "")):
            exp = need.get("expires_at", "")
            lines.append(f"  [EXPIRED {exp}] {format_compact(need)}")
        lines.append("")

    if review_due:
        lines.append(f"## {len(review_due)} memories overdue for review\n")
        for need in sorted(review_due, key=lambda n: n.get("review_after", "")):
            ra = need.get("review_after", "")
            lines.append(f"  [REVIEW {ra}] {format_compact(need)}")

    return _text_response("\n".join(lines))


def _handle_rebuild(args: dict[str, Any]) -> list[TextContent]:
    workspace = _get_workspace()
    result = _do_rebuild(workspace)
    return _text_response(result)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def main_stdio() -> None:
    """Run the MCP server over stdio transport."""
    import asyncio

    from mcp.server.stdio import stdio_server

    server = create_mcp_server()

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


if __name__ == "__main__":
    main_stdio()
