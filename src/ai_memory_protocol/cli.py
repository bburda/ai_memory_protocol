"""AI Memory Protocol — CLI entry point.

Installed as ``memory`` command via pyproject.toml entry point.

Commands:
    memory init <dir>                   Initialize a new memory workspace
    memory add <type> "<title>"         Add a new memory
    memory recall <query>               Search memories (free text or tags)
    memory get <id>                     View a specific memory (full details)
    memory related <id>                 Explore related memories (graph walk)
    memory list                         List all memories
    memory update <id> --field value    Update metadata on a memory
    memory deprecate <id>               Mark a memory as deprecated
    memory review                       Show memories due for review
    memory tags                         List all tags in use with counts
    memory stale                        Show expired or review-overdue memories
    memory rebuild                      Rebuild needs.json from RST sources
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from datetime import date
from pathlib import Path

from . import __version__
from .capture import capture_from_ci, capture_from_discussion, capture_from_git, format_candidates
from .config import TYPE_FILES
from .engine import (
    expand_graph,
    find_workspace,
    load_needs,
    resolve_id,
    run_rebuild,
    tag_match,
    text_match,
)
from .executor import actions_from_json, execute_plan
from .formatter import format_brief, format_compact, format_context_pack, format_full
from .planner import format_plan, run_plan
from .rst import (
    add_tags_in_rst,
    append_to_rst,
    deprecate_in_rst,
    generate_id,
    generate_rst_directive,
    remove_tags_in_rst,
    update_field_in_rst,
)
from .scaffold import init_workspace

# ---------------------------------------------------------------------------
# Doctor checks
# ---------------------------------------------------------------------------


def _check_cli() -> tuple[bool, str]:
    """Verify CLI entry point works."""
    from . import __version__

    return True, f"v{__version__}"


def _check_workspace(workspace_dir: str | None) -> tuple[bool, str]:
    """Verify workspace exists and is valid."""
    try:
        ws = find_workspace(workspace_dir)
        return True, str(ws)
    except SystemExit as e:
        return False, f"{e} — Run: memory init <path>"


def _check_sphinx_build(workspace_dir: str | None) -> tuple[bool, str]:
    """Verify sphinx-build is discoverable."""
    from .engine import find_sphinx_build

    try:
        ws = find_workspace(workspace_dir)
    except SystemExit:
        return False, "Workspace not found (skipped)"
    try:
        sb = find_sphinx_build(ws)
        return True, sb
    except FileNotFoundError as e:
        return False, f"Not found — {e}"


def _check_needs_json(workspace_dir: str | None) -> tuple[bool, str]:
    """Verify needs.json is loadable."""
    from .engine import find_needs_json

    try:
        ws = find_workspace(workspace_dir)
    except SystemExit:
        return False, "Workspace not found (skipped)"
    path = find_needs_json(ws)
    if not path.exists():
        return False, f"Not found at {path} — Run: memory rebuild"
    try:
        needs = load_needs(ws)
        return True, f"{len(needs)} memories loaded"
    except (SystemExit, Exception) as e:
        return False, f"Failed to load: {e}"


def _check_mcp_importable() -> tuple[bool, str]:
    """Verify MCP SDK is installed."""
    try:
        import mcp  # noqa: F401

        return True, f"v{getattr(mcp, '__version__', '?')}"
    except ImportError:
        return False, "Not installed — Run: pipx inject ai-memory-protocol mcp"


def _check_mcp_server() -> tuple[bool, str]:
    """Verify MCP server can be created."""
    try:
        from .mcp_server import create_mcp_server

        create_mcp_server()
        return True, "Server created successfully"
    except ImportError as e:
        return False, f"MCP SDK missing: {e}"
    except Exception as e:
        return False, f"Failed: {e}"


def _check_rst_files(workspace_dir: str | None) -> tuple[bool, str]:
    """Verify RST files exist and are parseable."""
    try:
        ws = find_workspace(workspace_dir)
    except SystemExit:
        return False, "Workspace not found (skipped)"
    memory_dir = ws / "memory"
    if not memory_dir.exists():
        return False, f"No memory/ directory in {ws}"
    rst_files = list(memory_dir.glob("*.rst"))
    if not rst_files:
        return False, "No RST files found in memory/"
    errors = []
    for f in rst_files:
        try:
            f.read_text()
        except Exception as e:
            errors.append(f"{f.name}: {e}")
    if errors:
        return False, f"{len(errors)} unreadable files: {'; '.join(errors)}"
    return True, f"{len(rst_files)} RST files OK"


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize a new memory workspace."""
    directory = Path(args.directory).resolve()
    init_workspace(
        directory=directory,
        project_name=args.name,
        author=args.author,
        install_deps=args.install,
    )


def cmd_doctor(args: argparse.Namespace) -> None:
    """Run installation health checks."""
    ws_dir = getattr(args, "dir", None)
    checks = [
        ("CLI entry point", _check_cli),
        ("Workspace exists", lambda: _check_workspace(ws_dir)),
        ("Sphinx-build available", lambda: _check_sphinx_build(ws_dir)),
        ("needs.json loadable", lambda: _check_needs_json(ws_dir)),
        ("MCP SDK installed", _check_mcp_importable),
        ("MCP server creatable", _check_mcp_server),
        ("RST files parseable", lambda: _check_rst_files(ws_dir)),
    ]
    all_ok = True
    print("AI Memory Protocol — Health Check\n")
    for name, check_fn in checks:
        try:
            ok, detail = check_fn()
            status = "\u2713" if ok else "\u2717"
            print(f"  {status} {name}: {detail}")
            if not ok:
                all_ok = False
        except Exception as e:
            print(f"  \u2717 {name}: CRASH — {e}")
            all_ok = False
    print()
    if all_ok:
        print("All checks passed.")
    else:
        print("Some checks failed. See details above.")
        sys.exit(1)


def cmd_add(args: argparse.Namespace) -> None:
    """Add a new memory entry."""
    workspace = find_workspace(args.dir)
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    relates = [t.strip() for t in args.relates.split(",")] if args.relates else None
    supersedes = [t.strip() for t in args.supersedes.split(",")] if args.supersedes else None

    directive = generate_rst_directive(
        mem_type=args.type,
        title=args.title,
        need_id=args.id,
        tags=tags,
        source=args.source,
        confidence=args.confidence,
        scope=args.scope,
        owner=args.owner,
        body=args.body,
        relates=relates,
        supersedes=supersedes,
        review_days=args.review_days,
    )

    if args.dry_run:
        print(directive)
        return

    target = append_to_rst(workspace, args.type, directive)
    nid = args.id or generate_id(args.type, args.title)
    print(f"Added {nid} → {target}")

    if args.rebuild:
        cmd_rebuild(args)
    else:
        print("Run 'memory rebuild' to update needs.json")


def cmd_recall(args: argparse.Namespace) -> None:
    """Search memories by free text or tag."""
    workspace = find_workspace(args.dir)
    needs = load_needs(workspace)
    query = " ".join(args.query) if args.query else ""
    tag_filters = [t.strip() for t in args.tag.split(",")] if args.tag else []
    type_filter = args.type
    today = date.today().isoformat()

    matched = {}
    for nid, need in needs.items():
        if need.get("status") == "deprecated":
            continue
        # Skip expired memories unless --stale is set
        expires = need.get("expires_at", "")
        if expires and expires <= today and not getattr(args, "stale", False):
            continue
        if type_filter and need.get("type") != type_filter:
            continue
        if tag_filters and not tag_match(need, tag_filters):
            continue
        if query and not text_match(need, query):
            continue
        matched[nid] = need

    # If --stale, show ONLY expired/overdue memories
    if getattr(args, "stale", False):
        stale = {}
        for nid, need in matched.items():
            expires = need.get("expires_at", "")
            review = need.get("review_after", "")
            if (expires and expires <= today) or (review and review <= today):
                stale[nid] = need
        matched = stale

    if not matched:
        print("No memories found.")
        return

    # Graph expansion
    if args.expand:
        matched = expand_graph(needs, set(matched.keys()), hops=args.expand)
        matched = {k: v for k, v in matched.items() if v.get("status") != "deprecated"}

    sort_key = getattr(args, "sort", None)
    _output(matched, args.format, limit=args.limit, show_body=args.body, sort=sort_key)


def cmd_get(args: argparse.Namespace) -> None:
    """Get a specific memory by ID with full details."""
    workspace = find_workspace(args.dir)
    needs = load_needs(workspace)
    need_id = resolve_id(needs, args.id)
    if not need_id:
        print(f"Memory '{args.id}' not found.")
        return
    print(format_full(needs[need_id]))


def cmd_related(args: argparse.Namespace) -> None:
    """Get memories related to a given ID (graph walk)."""
    workspace = find_workspace(args.dir)
    needs = load_needs(workspace)
    need_id = resolve_id(needs, args.id)
    if not need_id:
        print(f"Memory '{args.id}' not found.")
        return

    related = expand_graph(needs, {need_id}, hops=args.hops)
    seed = related.pop(need_id, None)
    if seed:
        print(f"## Related to: {need_id} — {seed.get('title', '')}\n")
    if not related:
        print("No related memories found.")
        return
    for need in related.values():
        print(format_compact(need, show_body=True))
        print()


def cmd_list(args: argparse.Namespace) -> None:
    """List all memories, optionally filtered."""
    workspace = find_workspace(args.dir)
    needs = load_needs(workspace)
    for _nid, need in sorted(needs.items()):
        if args.type and need.get("type") != args.type:
            continue
        if args.status and need.get("status") != args.status:
            continue
        if need.get("status") == "deprecated" and not args.all:
            continue
        print(format_compact(need))


def cmd_update(args: argparse.Namespace) -> None:
    """Update metadata on an existing memory."""
    workspace = find_workspace(args.dir)

    need_id = args.id
    any_change = False

    # Update simple fields
    for field in ("status", "confidence", "scope", "review_after", "source", "owner"):
        value = getattr(args, field.replace("-", "_"), None)
        if value is not None:
            ok, msg = update_field_in_rst(workspace, need_id, field, value)
            print(msg)
            any_change = any_change or ok

    # Tag operations
    if args.add_tags:
        new_tags = [t.strip() for t in args.add_tags.split(",")]
        ok, msg = add_tags_in_rst(workspace, need_id, new_tags)
        print(msg)
        any_change = any_change or ok

    if args.remove_tags:
        rm_tags = [t.strip() for t in args.remove_tags.split(",")]
        ok, msg = remove_tags_in_rst(workspace, need_id, rm_tags)
        print(msg)
        any_change = any_change or ok

    if not any_change:
        print("No changes made. Specify at least one field to update.")
        print("  --status, --confidence, --scope, --review-after, --add-tags, --remove-tags")
        return

    print("Run 'memory rebuild' to update needs.json")


def cmd_deprecate(args: argparse.Namespace) -> None:
    """Mark a memory as deprecated."""
    workspace = find_workspace(args.dir)
    ok, msg = deprecate_in_rst(workspace, args.id, args.by)
    print(msg)
    if ok:
        print("Run 'memory rebuild' to update needs.json")


def cmd_review(args: argparse.Namespace) -> None:
    """Show memories needing review."""
    workspace = find_workspace(args.dir)
    needs = load_needs(workspace)
    today = date.today().isoformat()
    due = []
    for _nid, need in needs.items():
        if need.get("status") == "deprecated":
            continue
        ra = need.get("review_after", "")
        if ra and ra <= today:
            due.append(need)
    if not due:
        print("No memories due for review.")
        return
    print(f"## {len(due)} memories due for review\n")
    for need in sorted(due, key=lambda n: n.get("review_after", "")):
        print(f"  {format_compact(need)}")


def cmd_tags(args: argparse.Namespace) -> None:
    """List all tags in use, grouped by prefix, with counts."""
    workspace = find_workspace(args.dir)
    needs = load_needs(workspace)
    tag_counts: dict[str, int] = {}
    for need in needs.values():
        if need.get("status") == "deprecated":
            continue
        for tag in need.get("tags", []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    if not tag_counts:
        print("No tags found.")
        return

    # Group by prefix
    by_prefix: dict[str, list[tuple[str, int]]] = {}
    for tag, count in sorted(tag_counts.items()):
        prefix = tag.split(":")[0] if ":" in tag else "_untagged"
        by_prefix.setdefault(prefix, []).append((tag, count))

    prefix_filter = args.prefix

    total = 0
    for prefix in sorted(by_prefix.keys()):
        if prefix_filter and prefix != prefix_filter:
            continue
        entries = by_prefix[prefix]
        print(f"\n{prefix}:")
        for tag, count in sorted(entries, key=lambda x: -x[1]):
            print(f"  {tag}  ({count})")
            total += count
    print(f"\n{len(tag_counts)} unique tags, {total} total usages")


def cmd_stale(args: argparse.Namespace) -> None:
    """Show expired or review-overdue memories."""
    workspace = find_workspace(args.dir)
    needs = load_needs(workspace)
    today = date.today().isoformat()

    expired = []
    review_due = []
    for _nid, need in needs.items():
        if need.get("status") == "deprecated":
            continue
        ea = need.get("expires_at", "")
        if ea and ea <= today:
            expired.append(need)
        ra = need.get("review_after", "")
        if ra and ra <= today and not ea:  # Don't double-count
            review_due.append(need)

    if not expired and not review_due:
        print("No stale memories found.")
        return

    if expired:
        print(f"## {len(expired)} EXPIRED memories\n")
        for need in sorted(expired, key=lambda n: n.get("expires_at", "")):
            exp = need.get("expires_at", "")
            print(f"  [EXPIRED {exp}] {format_compact(need)}")
        print()

    if review_due:
        print(f"## {len(review_due)} memories overdue for review\n")
        for need in sorted(review_due, key=lambda n: n.get("review_after", "")):
            ra = need.get("review_after", "")
            print(f"  [REVIEW {ra}] {format_compact(need)}")


def cmd_rebuild(args: argparse.Namespace) -> None:
    """Rebuild needs.json by running Sphinx build."""
    workspace = find_workspace(args.dir)
    success, message = run_rebuild(workspace)
    print(message)
    if not success:
        sys.exit(1)


def cmd_plan(args: argparse.Namespace) -> None:
    """Analyze memory graph and generate a maintenance plan."""
    workspace = find_workspace(args.dir)
    checks = [c.strip() for c in args.checks.split(",")] if args.checks else None
    actions = run_plan(workspace, checks=checks)
    fmt = args.format
    print(format_plan(actions, fmt=fmt))


def cmd_apply(args: argparse.Namespace) -> None:
    """Execute a list of planned actions from a JSON file."""
    workspace = find_workspace(args.dir)

    if args.file:
        import json as json_mod

        data = json_mod.loads(Path(args.file).read_text())
        actions = actions_from_json(data)
    elif args.plan:
        # Run plan first, then apply
        checks = [c.strip() for c in args.plan.split(",")] if args.plan != "all" else None
        actions_list = run_plan(workspace, checks=checks)
        if not actions_list:
            print("No issues found — nothing to apply.")
            return
        print(format_plan(actions_list, fmt="human"))
        if not args.yes:
            answer = input(f"\nApply {len(actions_list)} action(s)? [y/N] ")
            if answer.lower() not in ("y", "yes"):
                print("Aborted.")
                return
        actions = actions_list
    else:
        print("Provide --file <actions.json> or --plan [checks] to generate and apply.")
        sys.exit(1)

    result = execute_plan(
        workspace,
        actions,
        auto_commit=args.auto_commit,
        rebuild=not args.no_rebuild,
    )
    print(result.summary())
    if not result.success:
        sys.exit(1)


def cmd_capture(args: argparse.Namespace) -> None:
    """Capture memory candidates from external sources."""
    workspace = find_workspace(args.dir)

    if args.source == "git":
        repo_path = Path(args.repo).resolve() if args.repo else Path.cwd()
        candidates = capture_from_git(
            workspace=workspace,
            repo_path=repo_path,
            since=args.since,
            until=args.until,
            repo_name=args.repo_name,
            min_confidence=args.min_confidence,
        )
        print(format_candidates(candidates, fmt=args.format))

        if args.auto_add and candidates:
            from .rst import append_to_rst, generate_rst_directive

            count = 0
            for c in candidates:
                directive = generate_rst_directive(
                    mem_type=c.type,
                    title=c.title,
                    tags=c.tags,
                    source=c.source,
                    confidence=c.confidence,
                    scope=c.scope,
                    body=c.body,
                )
                append_to_rst(workspace, c.type, directive)
                count += 1
            print(f"\nAdded {count} memories to workspace.")
            if not args.no_rebuild:
                success, message = run_rebuild(workspace)
                print(message)
    elif args.source == "ci":
        log_text = _read_capture_input(args.input)
        if log_text is None:
            print("Provide CI log via --input <file> or pipe to stdin.")
            sys.exit(1)
        extra_tags = (
            [t.strip() for t in args.extra_tags.split(",") if t.strip()]
            if args.extra_tags
            else None
        )
        candidates = capture_from_ci(
            workspace=workspace,
            log_text=log_text,
            source=args.source_label or "ci-log",
            tags=extra_tags,
        )
        print(format_candidates(candidates, fmt=args.format))
        _auto_add_candidates(workspace, candidates, args)
    elif args.source == "discussion":
        transcript = _read_capture_input(args.input)
        if transcript is None:
            print("Provide transcript via --input <file> or pipe to stdin.")
            sys.exit(1)
        extra_tags = (
            [t.strip() for t in args.extra_tags.split(",") if t.strip()]
            if args.extra_tags
            else None
        )
        candidates = capture_from_discussion(
            workspace=workspace,
            transcript=transcript,
            source=args.source_label or "discussion",
            tags=extra_tags,
        )
        print(format_candidates(candidates, fmt=args.format))
        _auto_add_candidates(workspace, candidates, args)
    else:
        print(f"Unknown capture source: {args.source}")
        print("Supported sources: git, ci, discussion")
        sys.exit(1)


def _read_capture_input(input_path: str | None) -> str | None:
    """Read capture input from file, stdin, or return None."""
    if input_path:
        path = Path(input_path)
        if path.exists():
            return path.read_text()
        print(f"File not found: {input_path}")
        return None
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return None


def _auto_add_candidates(
    workspace: Path,
    candidates: list,
    args: argparse.Namespace,
) -> None:
    """Add candidates to workspace if --auto-add flag is set."""
    if not getattr(args, "auto_add", False) or not candidates:
        return
    from .rst import append_to_rst, generate_rst_directive

    count = 0
    for c in candidates:
        directive = generate_rst_directive(
            mem_type=c.type,
            title=c.title,
            tags=c.tags,
            source=c.source,
            confidence=c.confidence,
            scope=c.scope,
            body=c.body,
        )
        append_to_rst(workspace, c.type, directive)
        count += 1
    print(f"\nAdded {count} memories to workspace.")
    if not getattr(args, "no_rebuild", False):
        success, message = run_rebuild(workspace)
        print(message)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sort_needs(needs: dict, sort: str | None) -> list[tuple[str, dict]]:
    """Sort needs by the given key. Returns list of (id, need) tuples."""
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


def _output(
    needs: dict,
    fmt: str,
    limit: int = 0,
    show_body: bool = False,
    sort: str | None = None,
) -> None:
    """Output needs in the requested format."""
    # Apply sorting
    sorted_items = _sort_needs(needs, sort) if sort else list(needs.items())

    # Apply limit
    if limit and len(sorted_items) > limit:
        # If no explicit sort, use confidence for limit trimming
        if not sort:
            sorted_items.sort(
                key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(
                    x[1].get("confidence", "medium"), 1
                )
            )
        trimmed_items = sorted_items[:limit]
        omitted = len(sorted_items) - limit
    else:
        trimmed_items = sorted_items
        omitted = 0

    trimmed = dict(trimmed_items)

    if fmt == "json":
        print(json.dumps(trimmed, indent=2, ensure_ascii=False))
    elif fmt == "brief":
        for _, need in trimmed_items:
            print(format_brief(need))
    elif fmt == "compact":
        for _, need in trimmed_items:
            print(format_compact(need, show_body=show_body))
    else:  # context (default)
        print(format_context_pack(trimmed, show_body=show_body))

    if omitted:
        print(f"\n_({omitted} more results omitted — use --limit N to see more)_")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="memory",
        description="AI Memory Protocol — versioned, graph-based memory for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              memory init ./my-memories              Create a new memory workspace
              memory add mem "API timeout is 30s"    Add an observation
              memory recall gateway --tag topic:api  Search memories
              memory get DEC_rest_framework          View full details
              memory update MEM_x --confidence high  Update metadata
              memory deprecate OLD_ID --by NEW_ID    Deprecate a memory
              memory rebuild                         Rebuild needs.json
        """),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--dir", help="Memory workspace directory (auto-detected if omitted)")

    sub = parser.add_subparsers(dest="command", required=True)

    # --- init ---
    p_init = sub.add_parser("init", help="Initialize a new memory workspace")
    p_init.add_argument("directory", help="Directory to create the workspace in")
    p_init.add_argument("--name", default="AI Memory Protocol", help="Project name")
    p_init.add_argument("--author", default="bburda", help="Author name")
    p_init.add_argument(
        "--install", action="store_true", help="Create .venv and install dependencies"
    )
    p_init.set_defaults(func=cmd_init)

    # --- add ---
    p_add = sub.add_parser("add", help="Add a new memory")
    p_add.add_argument("type", choices=TYPE_FILES.keys(), help="Memory type")
    p_add.add_argument("title", help="Title of the memory")
    p_add.add_argument("--id", help="Custom ID (auto-generated if omitted)")
    p_add.add_argument("--tags", help="Tags, comma-separated (use prefix:value format)")
    p_add.add_argument("--source", default="", help="Provenance (URL, commit, description)")
    p_add.add_argument("--confidence", default="medium", choices=["low", "medium", "high"])
    p_add.add_argument("--scope", default="global", help="Scope: global, repo:X, product:X")
    p_add.add_argument("--owner", default="", help="Owner (@username)")
    p_add.add_argument("--body", default="", help="Description text")
    p_add.add_argument("--relates", default="", help="Related memory IDs, comma-separated")
    p_add.add_argument("--supersedes", default="", help="IDs this supersedes, comma-separated")
    p_add.add_argument(
        "--review-days", type=int, default=30, help="Days until review (default: 30)"
    )
    p_add.add_argument("--dry-run", action="store_true", help="Print RST without writing")
    p_add.add_argument(
        "--rebuild", action="store_true", help="Auto-rebuild needs.json after adding"
    )
    p_add.set_defaults(func=cmd_add)

    # --- recall ---
    p_recall = sub.add_parser("recall", help="Search memories (free text or tags)")
    p_recall.add_argument("query", nargs="*", help="Free-text search query (OR logic)")
    p_recall.add_argument("--tag", "-t", help="Filter by tag(s), comma-separated")
    p_recall.add_argument("--type", help="Filter by type (mem/dec/fact/pref/risk/goal/q)")
    p_recall.add_argument(
        "--expand", "-e", type=int, default=1, help="Graph expansion hops (0=off, default: 1)"
    )
    p_recall.add_argument(
        "--format", "-f", choices=["context", "compact", "brief", "json"], default="context"
    )
    p_recall.add_argument(
        "--limit", "-l", type=int, default=0, help="Max results (0=unlimited, default: 0)"
    )
    p_recall.add_argument("--body", "-b", action="store_true", help="Include body text in output")
    p_recall.add_argument(
        "--sort",
        "-s",
        choices=["newest", "oldest", "confidence", "updated"],
        help="Sort order (newest/oldest by created_at, updated by updated_at)",
    )
    p_recall.add_argument(
        "--stale", action="store_true", help="Show only expired or review-overdue memories"
    )
    p_recall.set_defaults(func=cmd_recall)

    # --- get ---
    p_get = sub.add_parser("get", help="View a specific memory (full details)")
    p_get.add_argument("id", help="Memory ID (e.g., DEC_rest_framework)")
    p_get.set_defaults(func=cmd_get)

    # --- related ---
    p_related = sub.add_parser("related", help="Explore related memories via graph walk")
    p_related.add_argument("id", help="Memory ID to start from")
    p_related.add_argument("--hops", "-n", type=int, default=2, help="Hops to walk (default: 2)")
    p_related.set_defaults(func=cmd_related)

    # --- list ---
    p_list = sub.add_parser("list", help="List all memories")
    p_list.add_argument("--type", help="Filter by type")
    p_list.add_argument("--status", help="Filter by status")
    p_list.add_argument("--all", action="store_true", help="Include deprecated")
    p_list.set_defaults(func=cmd_list)

    # --- update ---
    p_update = sub.add_parser("update", help="Update metadata on an existing memory")
    p_update.add_argument("id", help="Memory ID to update")
    p_update.add_argument("--status", help="New status (draft/active/promoted/deprecated/review)")
    p_update.add_argument("--confidence", help="New confidence (low/medium/high)")
    p_update.add_argument("--scope", help="New scope")
    p_update.add_argument("--review-after", help="New review date (ISO-8601)")
    p_update.add_argument("--source", help="New source/provenance")
    p_update.add_argument("--owner", help="New owner")
    p_update.add_argument("--add-tags", help="Tags to add, comma-separated")
    p_update.add_argument("--remove-tags", help="Tags to remove, comma-separated")
    p_update.set_defaults(func=cmd_update)

    # --- deprecate ---
    p_dep = sub.add_parser("deprecate", help="Mark a memory as deprecated")
    p_dep.add_argument("id", help="Memory ID to deprecate")
    p_dep.add_argument("--by", help="ID of the superseding memory")
    p_dep.set_defaults(func=cmd_deprecate)

    # --- review ---
    p_review = sub.add_parser("review", help="Show memories due for review")
    p_review.set_defaults(func=cmd_review)

    # --- tags ---
    p_tags = sub.add_parser("tags", help="List all tags in use with counts")
    p_tags.add_argument("--prefix", help="Filter by tag prefix (e.g., topic, repo)")
    p_tags.set_defaults(func=cmd_tags)

    # --- stale ---
    p_stale = sub.add_parser("stale", help="Show expired or review-overdue memories")
    p_stale.set_defaults(func=cmd_stale)

    # --- rebuild ---
    p_rebuild = sub.add_parser("rebuild", help="Rebuild needs.json from RST sources")
    p_rebuild.set_defaults(func=cmd_rebuild)

    # --- doctor ---
    p_doctor = sub.add_parser("doctor", help="Run installation health checks")
    p_doctor.set_defaults(func=cmd_doctor)

    # --- plan ---
    p_plan = sub.add_parser("plan", help="Analyze memory graph and generate maintenance plan")
    p_plan.add_argument(
        "--checks",
        help=(
            "Comma-separated checks to run. "
            "Options: duplicates, missing_tags, stale, conflicts, tag_normalize, split_files. "
            "Default: all."
        ),
    )
    p_plan.add_argument(
        "--format",
        "-f",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    p_plan.set_defaults(func=cmd_plan)

    # --- apply ---
    p_apply = sub.add_parser("apply", help="Execute planned maintenance actions")
    p_apply.add_argument("--file", help="JSON file containing actions to apply")
    p_apply.add_argument(
        "--plan",
        nargs="?",
        const="all",
        help="Run plan first, then apply. Optionally specify checks (comma-separated).",
    )
    p_apply.add_argument(
        "--auto-commit",
        action="store_true",
        help="Commit changes to git after successful apply",
    )
    p_apply.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Skip Sphinx rebuild after applying",
    )
    p_apply.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt when using --plan",
    )
    p_apply.set_defaults(func=cmd_apply)

    # --- capture ---
    p_capture = sub.add_parser("capture", help="Capture memories from external sources")
    p_capture.add_argument(
        "source",
        choices=["git", "ci", "discussion"],
        help="Capture source type",
    )
    p_capture.add_argument(
        "--repo",
        help="Path to git repository (default: current directory, git only)",
    )
    p_capture.add_argument(
        "--repo-name",
        help="Repository name for repo: tags (auto-detected from path if omitted, git only)",
    )
    p_capture.add_argument(
        "--since",
        default="HEAD~20",
        help="Start of git range (commit ref or date like '2 weeks ago'). Default: HEAD~20",
    )
    p_capture.add_argument(
        "--until",
        default="HEAD",
        help="End of git range. Default: HEAD",
    )
    p_capture.add_argument(
        "--min-confidence",
        choices=["low", "medium", "high"],
        default="low",
        help="Minimum confidence to include (default: low)",
    )
    p_capture.add_argument(
        "--format",
        "-f",
        choices=["human", "json"],
        default="human",
        help="Output format (default: human)",
    )
    p_capture.add_argument(
        "--auto-add",
        action="store_true",
        help="Automatically add candidates to workspace (skip review)",
    )
    p_capture.add_argument(
        "--no-rebuild",
        action="store_true",
        help="Skip rebuild after auto-add",
    )
    p_capture.add_argument(
        "--input",
        help="Input file for ci/discussion capture (reads stdin if omitted and not a TTY)",
    )
    p_capture.add_argument(
        "--source-label",
        help="Source provenance label (e.g. 'ci:github-actions:run-123', 'slack:2026-02-10')",
    )
    p_capture.add_argument(
        "--extra-tags",
        help="Extra tags for ci/discussion candidates, comma-separated",
    )
    p_capture.set_defaults(func=cmd_capture)

    return parser


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
