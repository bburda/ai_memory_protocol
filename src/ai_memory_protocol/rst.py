"""RST directive generation and in-place editing."""

from __future__ import annotations

import re
import textwrap
from datetime import date, timedelta
from pathlib import Path

from .config import DEFAULT_STATUS, TYPE_FILES, TYPE_PREFIXES

# Maximum number of memory entries per RST file before splitting
MAX_ENTRIES_PER_FILE = 50


def slugify(text: str, max_length: int = 50) -> str:
    """Convert title to a safe ID slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    slug = re.sub(r"\s+", "_", slug.strip())
    return slug[:max_length]


def generate_id(mem_type: str, title: str) -> str:
    """Generate a need ID from type prefix + slugified title."""
    prefix = TYPE_PREFIXES.get(mem_type, "MEM")
    return f"{prefix}_{slugify(title)}"


def generate_rst_directive(
    mem_type: str,
    title: str,
    need_id: str | None = None,
    tags: list[str] | None = None,
    source: str = "",
    confidence: str = "medium",
    scope: str = "global",
    owner: str = "",
    body: str = "",
    relates: list[str] | None = None,
    supports: list[str] | None = None,
    depends: list[str] | None = None,
    supersedes: list[str] | None = None,
    review_days: int = 90,
) -> str:
    """Generate a Sphinx-Needs RST directive string."""
    nid = need_id or generate_id(mem_type, title)
    status = DEFAULT_STATUS.get(mem_type, "draft")
    today = date.today().isoformat()
    review = (date.today() + timedelta(days=review_days)).isoformat()

    lines = [
        f".. {mem_type}:: {title}",
        f"   :id: {nid}",
        f"   :status: {status}",
    ]
    if tags:
        lines.append(f"   :tags: {', '.join(tags)}")
    if source:
        lines.append(f"   :source: {source}")
    if confidence:
        lines.append(f"   :confidence: {confidence}")
    if scope:
        lines.append(f"   :scope: {scope}")
    if owner:
        lines.append(f"   :owner: {owner}")
    lines.append(f"   :created_at: {today}")
    lines.append(f"   :review_after: {review}")
    if relates:
        lines.append(f"   :relates: {', '.join(relates)}")
    if supports:
        lines.append(f"   :supports: {', '.join(supports)}")
    if depends:
        lines.append(f"   :depends: {', '.join(depends)}")
    if supersedes:
        lines.append(f"   :supersedes: {', '.join(supersedes)}")
    lines.append("")
    if body:
        for line in textwrap.fill(body, width=72).split("\n"):
            lines.append(f"   {line}")
    else:
        lines.append("   TODO: Add description.")
    lines.append("")
    return "\n".join(lines)


def _count_entries(path: Path) -> int:
    """Count the number of memory directives in an RST file."""
    if not path.exists():
        return 0
    content = path.read_text()
    # Each directive starts with ".. <type>::" where type is a needs type
    return len(re.findall(r"^\.\. \w+::", content, re.MULTILINE))


def _find_all_rst_files(workspace: Path, mem_type: str) -> list[Path]:
    """Find all RST files for a memory type, including split files.

    For 'memory/facts.rst', also finds 'memory/facts_002.rst', 'memory/facts_003.rst', etc.
    """
    base_path = workspace / TYPE_FILES[mem_type]
    if not base_path.parent.exists():
        return []

    stem = base_path.stem  # e.g., "facts"
    suffix = base_path.suffix  # ".rst"
    parent = base_path.parent

    files = [base_path] if base_path.exists() else []
    # Find numbered splits: facts_002.rst, facts_003.rst, ...
    for p in sorted(parent.glob(f"{stem}_[0-9][0-9][0-9]{suffix}")):
        files.append(p)
    return files


def _create_split_file(workspace: Path, mem_type: str) -> Path:
    """Create the next numbered split file for a memory type."""
    base_path = workspace / TYPE_FILES[mem_type]
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent

    existing = _find_all_rst_files(workspace, mem_type)
    next_num = len(existing) + 1
    new_path = parent / f"{stem}_{next_num:03d}{suffix}"

    header = f"{stem.title()} (Part {next_num})"
    new_path.write_text(f"{'=' * len(header)}\n{header}\n{'=' * len(header)}\n\n")
    return new_path


def append_to_rst(workspace: Path, mem_type: str, content: str) -> Path:
    """Append a directive to the appropriate RST file in the workspace.

    Automatically splits into numbered files when a file exceeds
    MAX_ENTRIES_PER_FILE entries.
    """
    target = workspace / TYPE_FILES[mem_type]
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        header = TYPE_FILES[mem_type].split("/")[-1].replace(".rst", "").title()
        target.write_text(f"{'=' * len(header)}\n{header}\n{'=' * len(header)}\n\n")

    # Check if current file (or latest split) is too large
    all_files = _find_all_rst_files(workspace, mem_type)
    latest = all_files[-1] if all_files else target

    if _count_entries(latest) >= MAX_ENTRIES_PER_FILE:
        latest = _create_split_file(workspace, mem_type)

    existing = latest.read_text()
    if not existing.endswith("\n\n"):
        existing = existing.rstrip("\n") + "\n\n"
    latest.write_text(existing + content)
    return latest


def update_field_in_rst(
    workspace: Path,
    need_id: str,
    field: str,
    new_value: str,
) -> tuple[bool, str]:
    """Update a metadata field on a need in its RST source file.

    Searches across all RST files including split files.
    Returns ``(success, message)``.
    """
    for mem_type, _rst_rel in TYPE_FILES.items():
        for rst_path in _find_all_rst_files(workspace, mem_type):
            if not rst_path.exists():
                continue
            content = rst_path.read_text()
            if f":id: {need_id}" not in content:
                continue

            lines = content.split("\n")
            id_line_idx = None
            for i, line in enumerate(lines):
                if f":id: {need_id}" in line:
                    id_line_idx = i
                    break
            if id_line_idx is None:
                return False, f"Found file but could not locate :id: {need_id}"

            # Search nearby lines for the field
            field_pattern = f":{field}:"
            for j in range(max(0, id_line_idx - 2), min(len(lines), id_line_idx + 20)):
                if field_pattern in lines[j]:
                    lines[j] = re.sub(
                        rf":{field}:\s*.*",
                        f":{field}: {new_value}",
                        lines[j],
                    )
                    rst_path.write_text("\n".join(lines))
                    return True, f"Updated {field} on {need_id} in {rst_path.name}"

            # Field not found — insert it after :id: line
            indent = "   "
            insert_line = f"{indent}:{field}: {new_value}"
            # Find the last metadata line (lines starting with :something:)
            insert_idx = id_line_idx + 1
            while insert_idx < len(lines) and re.match(r"\s+:\w", lines[insert_idx]):
                insert_idx += 1
            lines.insert(insert_idx, insert_line)
            rst_path.write_text("\n".join(lines))
            return True, f"Added {field}={new_value} to {need_id} in {rst_path.name}"

    return False, f"Memory '{need_id}' not found in any RST file."


def deprecate_in_rst(
    workspace: Path,
    need_id: str,
    superseded_by: str | None = None,
) -> tuple[bool, str]:
    """Mark a memory as deprecated in its RST source file."""
    success, msg = update_field_in_rst(workspace, need_id, "status", "deprecated")
    if success and superseded_by:
        msg += f"\nSuperseded by: {superseded_by}"
        msg += f"\nRemember to add ':supersedes: {need_id}' to {superseded_by}"
    return success, msg


def prune_deprecated_from_rst(workspace: Path) -> tuple[int, list[str]]:
    """Remove all deprecated directive blocks from RST files.

    Returns (count_removed, list of removed IDs).
    Git preserves history so no data is truly lost.
    """
    removed_ids: list[str] = []

    for mem_type in TYPE_FILES:
        for rst_path in _find_all_rst_files(workspace, mem_type):
            if not rst_path.exists():
                continue
            content = rst_path.read_text()
            if ":status: deprecated" not in content:
                continue

            lines = content.split("\n")
            new_lines: list[str] = []
            i = 0
            while i < len(lines):
                # Detect start of a directive block: ".. type:: Title"
                directive_match = re.match(r"^\.\. (\w+):: ", lines[i])
                if not directive_match:
                    new_lines.append(lines[i])
                    i += 1
                    continue

                # Collect the full directive block (directive line + indented body)
                block_lines = [lines[i]]
                i += 1
                while i < len(lines) and (lines[i].startswith("   ") or lines[i].strip() == ""):
                    # Stop at empty line followed by non-indented content
                    if lines[i].strip() == "" and (
                        i + 1 >= len(lines)
                        or (lines[i + 1].strip() != "" and not lines[i + 1].startswith("   "))
                    ):
                        block_lines.append(lines[i])
                        i += 1
                        break
                    block_lines.append(lines[i])
                    i += 1

                # Check if this block is deprecated
                block_text = "\n".join(block_lines)
                if ":status: deprecated" in block_text:
                    # Extract ID for reporting
                    id_match = re.search(r":id:\s*(\S+)", block_text)
                    if id_match:
                        removed_ids.append(id_match.group(1))
                    # Skip this block (don't add to new_lines)
                    # Also skip trailing blank lines
                    while i < len(lines) and lines[i].strip() == "":
                        i += 1
                else:
                    new_lines.extend(block_lines)

            # Write back cleaned content
            cleaned = "\n".join(new_lines)
            # Normalize trailing newlines
            cleaned = cleaned.rstrip("\n") + "\n"
            rst_path.write_text(cleaned)

    return len(removed_ids), removed_ids


def update_body_in_rst(
    workspace: Path,
    need_id: str,
    new_body: str,
) -> tuple[bool, str]:
    """Replace the body text of a need in its RST source file."""
    for mem_type in TYPE_FILES:
        for rst_path in _find_all_rst_files(workspace, mem_type):
            if not rst_path.exists():
                continue
            content = rst_path.read_text()
            if f":id: {need_id}" not in content:
                continue

            lines = content.split("\n")
            id_line_idx = None
            for i, line in enumerate(lines):
                if f":id: {need_id}" in line:
                    id_line_idx = i
                    break
            if id_line_idx is None:
                return False, f"Found file but could not locate :id: {need_id}"

            # Find end of metadata (last line starting with whitespace + colon)
            body_start = id_line_idx + 1
            while body_start < len(lines) and re.match(r"\s+:\w", lines[body_start]):
                body_start += 1

            # Skip blank line between metadata and body
            if body_start < len(lines) and lines[body_start].strip() == "":
                body_start += 1

            # Find end of body (next blank line or next directive or EOF)
            body_end = body_start
            while body_end < len(lines):
                line = lines[body_end]
                if line.strip() == "" and body_end > body_start:
                    break
                if re.match(r"\.\. \w+::", line):
                    break
                body_end += 1

            # Build new body lines
            new_body_lines = []
            for bline in textwrap.fill(new_body, width=72).split("\n"):
                new_body_lines.append(f"   {bline}")

            # Replace
            lines[body_start:body_end] = new_body_lines
            rst_path.write_text("\n".join(lines))

            # Update the updated_at field
            update_field_in_rst(workspace, need_id, "updated_at", date.today().isoformat())

            return True, f"Updated body on {need_id} in {rst_path.name}"

    return False, f"Memory '{need_id}' not found in any RST file."


def update_title_in_rst(
    workspace: Path,
    need_id: str,
    new_title: str,
) -> tuple[bool, str]:
    """Replace the title of a need in its RST source file."""
    new_title = new_title.replace("\n", " ").replace("\r", " ").strip()
    if not new_title:
        return False, "Title cannot be empty."
    for mem_type in TYPE_FILES:
        for rst_path in _find_all_rst_files(workspace, mem_type):
            if not rst_path.exists():
                continue
            content = rst_path.read_text()
            if f":id: {need_id}" not in content:
                continue

            lines = content.split("\n")
            for i, line in enumerate(lines):
                if f":id: {need_id}" in line:
                    # Directive line is 1-2 lines above :id:
                    for j in range(max(0, i - 3), i):
                        if re.match(r"\.\. \w+::", lines[j]):
                            directive_type = lines[j].split("::")[0].strip()
                            lines[j] = f"{directive_type}:: {new_title}"
                            rst_path.write_text("\n".join(lines))
                            update_field_in_rst(
                                workspace, need_id, "updated_at", date.today().isoformat()
                            )
                            return True, (
                                f"Updated title on {need_id} to '{new_title}' in {rst_path.name}"
                            )
                    return False, f"Could not find directive line for {need_id}"

    return False, f"Memory '{need_id}' not found in any RST file."


def add_tags_in_rst(
    workspace: Path,
    need_id: str,
    new_tags: list[str],
) -> tuple[bool, str]:
    """Add tags to a need (preserving existing ones). Searches split files."""
    for mem_type in TYPE_FILES:
        for rst_path in _find_all_rst_files(workspace, mem_type):
            if not rst_path.exists():
                continue
            content = rst_path.read_text()
            if f":id: {need_id}" not in content:
                continue

            lines = content.split("\n")
            id_line_idx = None
            for i, line in enumerate(lines):
                if f":id: {need_id}" in line:
                    id_line_idx = i
                    break
            if id_line_idx is None:
                return False, f"Could not locate :id: {need_id}"

            for j in range(max(0, id_line_idx - 2), min(len(lines), id_line_idx + 20)):
                if ":tags:" in lines[j]:
                    existing = lines[j].split(":tags:")[1].strip()
                    existing_tags = [t.strip() for t in existing.split(",") if t.strip()]
                    merged = list(dict.fromkeys(existing_tags + new_tags))  # preserve order, dedup
                    lines[j] = re.sub(
                        r":tags:\s*.*",
                        f":tags: {', '.join(merged)}",
                        lines[j],
                    )
                    rst_path.write_text("\n".join(lines))
                    return True, f"Tags updated on {need_id}: {', '.join(merged)}"

            # No :tags: line found — insert one
            indent = "   "
            insert_idx = id_line_idx + 1
            while insert_idx < len(lines) and re.match(r"\s+:\w", lines[insert_idx]):
                insert_idx += 1
            lines.insert(insert_idx, f"{indent}:tags: {', '.join(new_tags)}")
            rst_path.write_text("\n".join(lines))
            return True, f"Added tags to {need_id}: {', '.join(new_tags)}"

    return False, f"Memory '{need_id}' not found in any RST file."


def remove_tags_in_rst(
    workspace: Path,
    need_id: str,
    tags_to_remove: list[str],
) -> tuple[bool, str]:
    """Remove specific tags from a need. Searches split files."""
    for mem_type in TYPE_FILES:
        for rst_path in _find_all_rst_files(workspace, mem_type):
            if not rst_path.exists():
                continue
            content = rst_path.read_text()
            if f":id: {need_id}" not in content:
                continue

            lines = content.split("\n")
            for i, line in enumerate(lines):
                if f":id: {need_id}" in line:
                    for j in range(max(0, i - 2), min(len(lines), i + 20)):
                        if ":tags:" in lines[j]:
                            existing = lines[j].split(":tags:")[1].strip()
                            existing_tags = [t.strip() for t in existing.split(",") if t.strip()]
                            remaining = [t for t in existing_tags if t not in tags_to_remove]
                            if remaining:
                                lines[j] = re.sub(
                                    r":tags:\s*.*",
                                    f":tags: {', '.join(remaining)}",
                                    lines[j],
                                )
                            else:
                                lines.pop(j)
                            rst_path.write_text("\n".join(lines))
                            removed = set(existing_tags) - set(remaining)
                            return True, f"Removed tags from {need_id}: {', '.join(removed)}"
                    return False, f"No :tags: field on {need_id}"

    return False, f"Memory '{need_id}' not found in any RST file."
