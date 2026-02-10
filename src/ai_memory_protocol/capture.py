"""Capture knowledge from external sources — git, CI, discussions.

Primary use-case: extract memories from git history so the agent does
not lose context from past development sessions.

Usage:
    from ai_memory_protocol.capture import capture_from_git
    candidates = capture_from_git(workspace, repo_path, since="2 weeks ago")
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .engine import load_needs

# ---------------------------------------------------------------------------
# Candidate (not yet a memory — needs review before adding)
# ---------------------------------------------------------------------------


@dataclass
class MemoryCandidate:
    """A candidate memory extracted from a source (git, CI, discussion)."""

    type: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    source: str = ""
    confidence: str = "medium"
    scope: str = "global"
    # For dedup
    _source_hashes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {
            "type": self.type,
            "title": self.title,
            "body": self.body,
            "tags": self.tags,
            "source": self.source,
            "confidence": self.confidence,
            "scope": self.scope,
        }
        return {k: v for k, v in d.items() if v}


# ---------------------------------------------------------------------------
# Git commit parsing
# ---------------------------------------------------------------------------


_GIT_RECORD_SEP = "\x1e"  # ASCII Record Separator between commits
_GIT_FIELD_SEP = "\x1f"  # ASCII Unit Separator between fields
_GIT_LOG_FORMAT = (
    f"%H{_GIT_FIELD_SEP}%s{_GIT_FIELD_SEP}%b{_GIT_FIELD_SEP}%an{_GIT_FIELD_SEP}%ad{_GIT_RECORD_SEP}"
)


@dataclass
class _GitCommit:
    """Parsed git commit."""

    hash: str
    subject: str
    body: str
    author: str
    date: str
    files: list[str] = field(default_factory=list)


def _parse_git_log(repo_path: Path, since: str, until: str) -> list[_GitCommit]:
    """Run git log and parse the output."""
    # Base git log command
    cmd: list[str] = [
        "git",
        "log",
        f"--format={_GIT_LOG_FORMAT}",
        "--date=iso-strict",
    ]

    # Heuristic: if arguments contain spaces (e.g. "2 weeks ago"), treat them as
    # date expressions and use --since/--until. Otherwise treat them as refs and
    # use git's revision range syntax.
    has_since = bool(since)
    has_until = bool(until)
    since_is_date = has_since and (" " in since)
    until_is_date = has_until and (" " in until)

    if has_since and has_until:
        if since_is_date or until_is_date:
            # Date-based range
            cmd.append(f"--since={since}")
            cmd.append(f"--until={until}")
        else:
            # Ref-based range: use {since}..{until}
            cmd.append(f"{since}..{until}")
    elif has_since:
        if since_is_date:
            cmd.append(f"--since={since}")
        else:
            cmd.append(since)
    elif has_until:
        if until_is_date:
            cmd.append(f"--until={until}")
        else:
            cmd.append(until)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
    except OSError:
        return []

    commits: list[_GitCommit] = []
    # Split on record separator — safe even when %b contains newlines
    for record in result.stdout.split(_GIT_RECORD_SEP):
        record = record.strip()
        if not record:
            continue
        parts = record.split(_GIT_FIELD_SEP)
        if len(parts) < 5:
            continue
        commit = _GitCommit(
            hash=parts[0].strip(),
            subject=parts[1].strip(),
            body=parts[2].strip(),
            author=parts[3].strip(),
            date=parts[4].strip(),
        )
        commits.append(commit)

    # Get changed files per commit
    for c in commits:
        try:
            files_result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", c.hash],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
            )
            c.files = [f.strip() for f in files_result.stdout.strip().split("\n") if f.strip()]
        except OSError:
            # Best-effort: if git diff-tree fails for this commit (e.g. git not
            # available or repository in an unexpected state), leave the files
            # list unchanged for this commit and continue processing others.
            pass

    return commits


# ---------------------------------------------------------------------------
# Commit classification
# ---------------------------------------------------------------------------

# Patterns for classifying commits by conventional commit prefix
_CLASSIFY_PATTERNS: list[tuple[str, str, str]] = [
    # (regex_pattern, memory_type, confidence)
    (r"^fix[\(:]|^bugfix[\(:]|^hotfix[\(:]", "mem", "high"),
    (r"^feat[\(:]|^add[\(:]|^feature[\(:]", "fact", "medium"),
    (r"^refactor[\(:]|^perf[\(:]|^optimize[\(:]", "dec", "medium"),
    (r"^docs[\(:]|^doc[\(:]", "fact", "low"),
    (r"^test[\(:]|^tests[\(:]", "mem", "low"),
    (r"^ci[\(:]|^build[\(:]|^chore[\(:]", "mem", "low"),
    (r"BREAKING[ _]CHANGE", "risk", "high"),
    (r"^revert[\(:]", "mem", "medium"),
    (r"^style[\(:]", "pref", "low"),
]


def _classify_commit(commit: _GitCommit) -> tuple[str, str]:
    """Classify a commit into a memory type + confidence.

    Returns (type, confidence). Falls back to "mem"/"low" for unclassifiable commits.
    """
    subject = commit.subject
    body_text = f"{subject} {commit.body}"

    # Check BREAKING CHANGE first (can appear anywhere)
    if re.search(r"BREAKING[ _]CHANGE", body_text, re.IGNORECASE):
        return "risk", "high"

    for pattern, mem_type, confidence in _CLASSIFY_PATTERNS:
        if re.search(pattern, subject, re.IGNORECASE):
            return mem_type, confidence

    return "mem", "low"


def _extract_scope(subject: str) -> str:
    """Extract scope from conventional commit format.  e.g. 'fix(gateway): ...' → 'gateway'."""
    match = re.match(r"^\w+\(([^)]+)\)", subject)
    return match.group(1) if match else ""


def _infer_tags(commit: _GitCommit, repo_name: str) -> list[str]:
    """Infer tags from commit metadata."""
    tags: list[str] = [f"repo:{repo_name}"]

    # Extract scope as topic tag
    scope = _extract_scope(commit.subject)
    if scope:
        tags.append(f"topic:{scope}")

    # Infer topic from file paths
    path_topics: set[str] = set()
    for f in commit.files:
        parts = Path(f).parts
        if len(parts) >= 2:
            # Use first meaningful directory as topic
            for part in parts:
                if part not in ("src", "lib", "test", "tests", "include", ".", ".."):
                    path_topics.add(part.replace("_", "-"))
                    break

    for topic in sorted(path_topics)[:3]:  # Limit to 3 path-based topics
        tag = f"topic:{topic}"
        if tag not in tags:
            tags.append(tag)

    return tags


# ---------------------------------------------------------------------------
# Grouping related commits
# ---------------------------------------------------------------------------


def _file_overlap(files1: list[str], files2: list[str]) -> float:
    """Compute Jaccard similarity of file sets."""
    s1, s2 = set(files1), set(files2)
    union = s1 | s2
    if not union:
        return 0.0
    return len(s1 & s2) / len(union)


def _group_commits(
    commits: list[_GitCommit], file_overlap_threshold: float = 0.3
) -> list[list[_GitCommit]]:
    """Group commits by file overlap (simple greedy clustering)."""
    if not commits:
        return []

    groups: list[list[_GitCommit]] = [[commits[0]]]

    for commit in commits[1:]:
        best_group = -1
        best_overlap = 0.0
        for i, group in enumerate(groups):
            # Compare against all commits in the group
            group_files = [f for c in group for f in c.files]
            overlap = _file_overlap(commit.files, group_files)
            if overlap > best_overlap:
                best_overlap = overlap
                best_group = i

        if best_overlap >= file_overlap_threshold and best_group >= 0:
            groups[best_group].append(commit)
        else:
            groups.append([commit])

    return groups


# ---------------------------------------------------------------------------
# Deduplication against existing memories
# ---------------------------------------------------------------------------


def _is_duplicate(
    candidate: MemoryCandidate,
    existing_needs: dict[str, Any],
    title_threshold: float = 0.7,
) -> bool:
    """Check if a candidate is a near-duplicate of an existing memory."""
    for need in existing_needs.values():
        if need.get("status") == "deprecated":
            continue
        existing_title = need.get("title", "").lower()
        candidate_title = candidate.title.lower()
        sim = SequenceMatcher(None, candidate_title, existing_title).ratio()
        if sim >= title_threshold:
            return True

        # Also check by source (exact commit hash match)
        existing_source = need.get("source", "")
        if candidate.source and candidate.source in existing_source:
            return True

    return False


# ---------------------------------------------------------------------------
# Public interface: capture from git
# ---------------------------------------------------------------------------


def capture_from_git(
    workspace: Path,
    repo_path: Path,
    since: str = "HEAD~20",
    until: str = "HEAD",
    repo_name: str | None = None,
    deduplicate: bool = True,
    min_confidence: str = "low",
) -> list[MemoryCandidate]:
    """Analyze git log and generate memory candidates.

    Parameters
    ----------
    workspace
        Path to the memory workspace (for dedup against existing).
    repo_path
        Path to the git repository to analyze.
    since
        Start of the range (commit or date like ``"2 weeks ago"``).
    until
        End of the range (default: ``"HEAD"``).
    repo_name
        Repository name for ``repo:`` tags. Auto-detected from path if omitted.
    deduplicate
        If True, filter out candidates that match existing memories.
    min_confidence
        Minimum confidence to include. "low" includes all.

    Returns
    -------
    list[MemoryCandidate]
        Candidate memories ready for review and optional insertion.
    """
    if repo_name is None:
        repo_name = repo_path.name

    commits = _parse_git_log(repo_path, since, until)
    if not commits:
        return []

    # Load existing memories for dedup
    existing: dict[str, Any] = {}
    if deduplicate:
        try:
            existing = load_needs(workspace)
        except (SystemExit, Exception):
            existing = {}

    # Classify and group
    conf_rank = {"high": 2, "medium": 1, "low": 0}
    min_conf_rank = conf_rank.get(min_confidence, 0)

    candidates: list[MemoryCandidate] = []

    # Group related commits
    groups = _group_commits(commits)

    for group in groups:
        if len(group) == 1:
            # Single commit → single candidate
            commit = group[0]
            mem_type, confidence = _classify_commit(commit)

            if conf_rank.get(confidence, 0) < min_conf_rank:
                continue

            # Clean title: remove conventional commit prefix
            title = re.sub(r"^\w+(\([^)]*\))?:\s*", "", commit.subject)
            if not title:
                title = commit.subject

            body_parts = [commit.body] if commit.body else []
            if commit.files:
                body_parts.append(f"Files: {', '.join(commit.files[:10])}")

            candidate = MemoryCandidate(
                type=mem_type,
                title=title[:120],
                body="\n".join(body_parts),
                tags=_infer_tags(commit, repo_name),
                source=f"commit:{commit.hash[:8]}",
                confidence=confidence,
                scope=f"repo:{repo_name}",
                _source_hashes=[commit.hash],
            )
            candidates.append(candidate)
        else:
            # Multiple related commits → summarize
            primary = group[0]  # Use first (most recent) commit
            mem_type, confidence = _classify_commit(primary)

            # Upgrade confidence for grouped commits
            if len(group) >= 3 and confidence == "low":
                confidence = "medium"

            if conf_rank.get(confidence, 0) < min_conf_rank:
                continue

            title = re.sub(r"^\w+(\([^)]*\))?:\s*", "", primary.subject)
            if not title:
                title = primary.subject

            body_parts = [f"Group of {len(group)} related commits:"]
            for c in group[:5]:
                body_parts.append(f"  - {c.subject} ({c.hash[:8]})")
            if len(group) > 5:
                body_parts.append(f"  ... and {len(group) - 5} more")

            all_files: set[str] = set()
            all_tags: set[str] = set()
            for c in group:
                all_files.update(c.files)
                for tag in _infer_tags(c, repo_name):
                    all_tags.add(tag)

            if all_files:
                body_parts.append(f"Files: {', '.join(sorted(all_files)[:10])}")

            candidate = MemoryCandidate(
                type=mem_type,
                title=title[:120],
                body="\n".join(body_parts),
                tags=sorted(all_tags),
                source=f"commit:{primary.hash[:8]}+{len(group) - 1}",
                confidence=confidence,
                scope=f"repo:{repo_name}",
                _source_hashes=[c.hash for c in group],
            )
            candidates.append(candidate)

    # Dedup against existing
    if deduplicate and existing:
        candidates = [c for c in candidates if not _is_duplicate(c, existing)]

    return candidates


def format_candidates(candidates: list[MemoryCandidate], fmt: str = "human") -> str:
    """Format capture candidates for display."""
    if not candidates:
        return "No new memory candidates found."

    if fmt == "json":
        import json

        return json.dumps([c.to_dict() for c in candidates], indent=2, ensure_ascii=False)

    lines = [f"## {len(candidates)} memory candidate(s)\n"]
    for i, c in enumerate(candidates, 1):
        lines.append(f"  {i}. [{c.type}] {c.title}")
        lines.append(f"     Tags: {', '.join(c.tags)}")
        lines.append(f"     Confidence: {c.confidence} | Source: {c.source}")
        if c.body:
            # Show first 2 lines of body
            body_lines = c.body.split("\n")[:2]
            for bl in body_lines:
                lines.append(f"     {bl}")
        lines.append("")

    return "\n".join(lines)
