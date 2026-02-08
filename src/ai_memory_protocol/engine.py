"""Core engine — workspace discovery, needs.json loading, search, graph traversal."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import LINK_FIELDS

# ---------------------------------------------------------------------------
# Workspace discovery
# ---------------------------------------------------------------------------


def find_workspace(explicit: str | None = None) -> Path:
    """Locate the memory workspace directory.

    Resolution order:
      1. Explicit ``--dir`` argument
      2. ``MEMORY_DIR`` environment variable
      3. Walk up from CWD looking for ``conf.py`` containing ``needs_types``
    """
    if explicit:
        p = Path(explicit).resolve()
        if _is_workspace(p):
            return p
        # Maybe they pointed at a parent that has the workspace
        raise SystemExit(f"Not a memory workspace: {p}\nRun 'memory init {p}' to create one.")

    env = os.environ.get("MEMORY_DIR")
    if env:
        p = Path(env).resolve()
        if _is_workspace(p):
            return p
        raise SystemExit(f"MEMORY_DIR={env} is not a valid memory workspace.")

    # Walk up from CWD
    cwd = Path.cwd().resolve()
    for d in [cwd, *cwd.parents]:
        if _is_workspace(d):
            return d

    raise SystemExit(
        "No memory workspace found.\nRun 'memory init <dir>' to create one, or set MEMORY_DIR."
    )


def _is_workspace(directory: Path) -> bool:
    """Check if a directory looks like a memory workspace."""
    conf = directory / "conf.py"
    if not conf.exists():
        return False
    try:
        content = conf.read_text()
        return "needs_types" in content
    except OSError:
        return False


# ---------------------------------------------------------------------------
# needs.json loading
# ---------------------------------------------------------------------------


def find_needs_json(workspace: Path) -> Path:
    """Find needs.json trying common Sphinx output locations."""
    candidates = [
        workspace / "_build" / "html" / "needs.json",
        workspace / "_build" / "needs" / "needs.json",
        workspace / "needs.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # Default for error messages


def load_needs(workspace: Path) -> dict[str, Any]:
    """Load all needs from needs.json.

    Returns a flat dict of ``{need_id: need_data}``.
    """
    path = find_needs_json(workspace)
    if not path.exists():
        print(f"needs.json not found at {path}", file=sys.stderr)
        print("Run: memory rebuild", file=sys.stderr)
        sys.exit(1)

    data = json.loads(path.read_text())
    version = data.get("current_version", "")
    versions = data.get("versions", {})
    if version in versions:
        return versions[version].get("needs", {})
    if versions:
        return next(iter(versions.values())).get("needs", {})
    return {}


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def text_match(need: dict[str, Any], query: str) -> bool:
    """Check if a need matches a free-text query (OR logic — any word matches)."""
    searchable = " ".join(
        [
            need.get("id", ""),
            need.get("title", ""),
            need.get("description", ""),
            " ".join(need.get("tags", [])),
            need.get("scope", ""),
            need.get("source", ""),
        ]
    ).lower()
    return any(word in searchable for word in query.lower().split())


def tag_match(need: dict[str, Any], tags: list[str]) -> bool:
    """Check if a need has all specified tags (AND logic)."""
    need_tags = need.get("tags", [])
    return all(t in need_tags for t in tags)


def resolve_id(needs: dict[str, Any], raw_id: str) -> str | None:
    """Resolve a need ID with case-insensitive fallback."""
    if raw_id in needs:
        return raw_id
    for k in needs:
        if k.lower() == raw_id.lower():
            return k
    return None


# ---------------------------------------------------------------------------
# Graph traversal
# ---------------------------------------------------------------------------


def expand_graph(
    needs: dict[str, Any],
    seed_ids: set[str],
    hops: int = 1,
) -> dict[str, Any]:
    """Walk the link graph from seeds up to N hops.

    Follows all link types (outgoing and incoming ``_back`` links).
    """
    collected = set(seed_ids)
    frontier = set(seed_ids)

    for _ in range(hops):
        next_frontier: set[str] = set()
        for nid in frontier:
            need = needs.get(nid, {})
            for lt in LINK_FIELDS:
                for target in need.get(lt, []):
                    if target not in collected:
                        next_frontier.add(target)
                for source in need.get(f"{lt}_back", []):
                    if source not in collected:
                        next_frontier.add(source)
        collected.update(next_frontier)
        frontier = next_frontier

    return {nid: needs[nid] for nid in collected if nid in needs}


# ---------------------------------------------------------------------------
# Sphinx-build discovery and rebuild
# ---------------------------------------------------------------------------


def find_sphinx_build(workspace: Path) -> str:
    """Locate the sphinx-build executable.

    Search order:
      1. Same directory as the running Python interpreter (covers pipx / venv installs)
      2. ``workspace/.venv/bin/sphinx-build``
      3. Walk parent directories for ``.venv/bin/sphinx-build``
      4. ``shutil.which("sphinx-build")`` (system PATH)

    Returns the path string, or raises ``FileNotFoundError``.
    """
    # 1. Running Python's own environment (pipx, venv, conda, etc.)
    #    Use parent of sys.executable WITHOUT resolving symlinks, so that
    #    pipx/venv wrapper scripts point to the correct bin directory.
    own_bin = Path(sys.executable).parent / "sphinx-build"
    if own_bin.exists():
        return str(own_bin)

    # 2. Workspace venv
    candidate = workspace / ".venv" / "bin" / "sphinx-build"
    if candidate.exists():
        return str(candidate)

    # 3. Walk parent directories
    for parent in workspace.parents:
        candidate = parent / ".venv" / "bin" / "sphinx-build"
        if candidate.exists():
            return str(candidate)
        # Also check sibling directories (e.g., ../ros2_medkit/.venv/)
        if parent.is_dir():
            for sibling in parent.iterdir():
                if sibling.is_dir() and sibling != workspace:
                    candidate = sibling / ".venv" / "bin" / "sphinx-build"
                    if candidate.exists():
                        return str(candidate)
            break  # Only check immediate parent's siblings

    # 4. System PATH
    system = shutil.which("sphinx-build")
    if system:
        return system

    raise FileNotFoundError(
        "sphinx-build not found. Install it with: pip install sphinx sphinx-needs\n"
        "Or create a venv in your memory workspace: memory init --install <dir>"
    )


def run_rebuild(workspace: Path) -> tuple[bool, str]:
    """Run Sphinx build to regenerate needs.json.

    Returns ``(success, message)`` — never raises on build failure.
    """
    try:
        sphinx_cmd = find_sphinx_build(workspace)
    except FileNotFoundError as e:
        return False, f"Rebuild skipped: {e}"

    cmd = [sphinx_cmd, "-b", "html", "-q", str(workspace), str(workspace / "_build" / "html")]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as e:
        return False, f"Rebuild failed: {e}"

    if result.returncode != 0:
        return False, f"Rebuild failed:\n{result.stderr}"

    needs = load_needs(workspace)
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for n in needs.values():
        by_type[n.get("type", "?")] = by_type.get(n.get("type", "?"), 0) + 1
        by_status[n.get("status", "?")] = by_status.get(n.get("status", "?"), 0) + 1

    lines = [
        f"needs.json updated at {find_needs_json(workspace)}",
        f"Total: {len(needs)} memories",
        f"  Types:    {', '.join(f'{k}={v}' for k, v in sorted(by_type.items()))}",
        f"  Statuses: {', '.join(f'{k}={v}' for k, v in sorted(by_status.items()))}",
    ]
    return True, "\n".join(lines)
