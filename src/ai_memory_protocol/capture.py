"""Capture knowledge from external sources — git, CI, discussions.

Extract memories from:
- **Git history** — commit messages classified by conventional commit type
- **CI logs** — test failures, build errors, warnings
- **Discussions** — decisions, preferences, goals from conversation transcripts

Usage:
    from ai_memory_protocol.capture import capture_from_git, capture_from_ci, capture_from_discussion
    candidates = capture_from_git(workspace, repo_path, since="2 weeks ago")
    candidates = capture_from_ci(workspace, log_text)
    candidates = capture_from_discussion(workspace, transcript)
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


# ===========================================================================
# CI Log Capture
# ===========================================================================

# Patterns for extracting structured data from CI logs
_CI_PATTERNS: list[tuple[str, str, str, str]] = [
    # (regex, memory_type, title_template, confidence)
    # Test failures
    (
        r"(?:FAILED|FAIL|ERROR)\s*:?\s*(?:test_?)?(\S+?)(?:\s*[-—]\s*(.+))?$",
        "mem",
        "CI test failure: {name}",
        "high",
    ),
    # Python pytest failures
    (
        r"(?:FAILED)\s+([\w/]+\.py::[\w:]+)",
        "mem",
        "Test failure: {name}",
        "high",
    ),
    # Compiler errors (C/C++)
    (
        r"(\S+\.\w+):(\d+):\d+:\s*error:\s*(.+)",
        "mem",
        "Build error in {file}:{line}",
        "high",
    ),
    # Linker errors
    (
        r"(?:undefined reference to|cannot find -l)(.+)",
        "mem",
        "Linker error: {name}",
        "high",
    ),
    # Deprecation warnings
    (
        r"(?:DeprecationWarning|FutureWarning):\s*(.+)",
        "risk",
        "Deprecation warning: {name}",
        "medium",
    ),
    # Timeout errors
    (
        r"(?:TimeoutError|timed?\s*out)\s*:?\s*(.+)?",
        "mem",
        "Timeout: {name}",
        "high",
    ),
    # CMake / build configuration errors
    (
        r"CMake Error.*?:\s*(.+)",
        "mem",
        "CMake error: {name}",
        "high",
    ),
    # Generic error lines
    (
        r"^(?:Error|ERROR)\s*:?\s*(.+)",
        "mem",
        "CI error: {name}",
        "medium",
    ),
]

# Summary line patterns: "X passed, Y failed"
_CI_SUMMARY_PATTERN = re.compile(
    r"(\d+)\s+(?:passed|succeeded).*?(\d+)\s+(?:failed|errors?)",
    re.IGNORECASE,
)


@dataclass
class _CIMatch:
    """A matched CI pattern with extracted data."""

    mem_type: str
    title: str
    detail: str
    confidence: str
    line_num: int


def _parse_ci_log(text: str) -> list[_CIMatch]:
    """Parse CI log text and extract structured error/failure data."""
    matches: list[_CIMatch] = []
    seen_titles: set[str] = set()

    for line_num, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue

        for pattern, mem_type, title_tpl, confidence in _CI_PATTERNS:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                groups = m.groups()
                # Build title from template and captured groups
                name = (groups[0] or "").strip() if groups else ""
                file_val = ""
                line_val = ""
                if len(groups) >= 3:
                    file_val = (groups[0] or "").strip()
                    line_val = (groups[1] or "").strip()
                    name = (groups[2] or "").strip()

                title = title_tpl.format(
                    name=name[:80] if name else "unknown",
                    file=file_val,
                    line=line_val,
                )[:120]

                # Dedup within same log
                if title in seen_titles:
                    break
                seen_titles.add(title)

                detail = line[:200]
                matches.append(
                    _CIMatch(
                        mem_type=mem_type,
                        title=title,
                        detail=detail,
                        confidence=confidence,
                        line_num=line_num,
                    )
                )
                break  # One match per line

    return matches


def capture_from_ci(
    workspace: Path,
    log_text: str,
    source: str = "ci-log",
    tags: list[str] | None = None,
    deduplicate: bool = True,
) -> list[MemoryCandidate]:
    """Extract memory candidates from CI log output.

    Parameters
    ----------
    workspace
        Path to the memory workspace (for dedup against existing).
    log_text
        Raw CI log text (stdout/stderr from build or test run).
    source
        Source label for provenance (e.g. ``"ci:github-actions:run-123"``).
    tags
        Additional tags to apply to all candidates. Auto-infers ``topic:ci``.
    deduplicate
        If True, filter out candidates that match existing memories.

    Returns
    -------
    list[MemoryCandidate]
        Candidate memories ready for review and optional insertion.
    """
    base_tags = ["topic:ci"]
    if tags:
        base_tags.extend(t for t in tags if t not in base_tags)

    matches = _parse_ci_log(log_text)
    if not matches:
        return []

    # Load existing for dedup
    existing: dict[str, Any] = {}
    if deduplicate:
        try:
            existing = load_needs(workspace)
        except (SystemExit, Exception):
            existing = {}

    candidates: list[MemoryCandidate] = []
    for match in matches:
        candidate = MemoryCandidate(
            type=match.mem_type,
            title=match.title,
            body=f"Line {match.line_num}: {match.detail}",
            tags=list(base_tags),
            source=source,
            confidence=match.confidence,
        )
        candidates.append(candidate)

    # Dedup against existing
    if deduplicate and existing:
        candidates = [c for c in candidates if not _is_duplicate(c, existing)]

    return candidates


# ===========================================================================
# Discussion / Transcript Capture
# ===========================================================================

# Patterns for classifying discussion statements
_DISCUSSION_PATTERNS: list[tuple[str, str, str]] = [
    # Decisions
    (r"(?:we\s+)?decided\s+(?:to\s+)?(.+)", "dec", "high"),
    (r"(?:the\s+)?decision\s+is\s+(?:to\s+)?(.+)", "dec", "high"),
    (
        r"(?:let'?s|we\s+should|we\s+will|we'?ll)\s+(?:go\s+with\s+|use\s+|adopt\s+)(.+)",
        "dec",
        "medium",
    ),
    (r"(?:I'?m\s+going\s+with|going\s+with|choosing)\s+(.+)", "dec", "medium"),
    # Preferences
    (r"I\s+prefer\s+(.+)", "pref", "high"),
    (r"(?:let'?s|we\s+should)\s+(?:always|prefer|stick\s+with|keep)\s+(.+)", "pref", "medium"),
    (r"(?:convention|standard|style):\s*(.+)", "pref", "medium"),
    (r"(?:use|prefer)\s+(\S+)\s+(?:over|instead\s+of)\s+(\S+)", "pref", "medium"),
    # Goals
    (r"(?:the\s+)?goal\s+(?:is\s+)?(?:to\s+)?(.+)", "goal", "high"),
    (r"we\s+(?:need|want|aim|plan)\s+to\s+(.+)", "goal", "medium"),
    (r"(?:TODO|FIXME|HACK):\s*(.+)", "goal", "medium"),
    (r"next\s+(?:step|priority|milestone):\s*(.+)", "goal", "medium"),
    # Facts
    (r"(?:it\s+)?turns?\s+out\s+(?:that\s+)?(.+)", "fact", "medium"),
    (r"(?:TIL|FYI|note|important):\s*(.+)", "fact", "medium"),
    (
        r"(?:the\s+)?(?:API|endpoint|service|server)\s+(?:is|uses|runs|supports)\s+(.+)",
        "fact",
        "medium",
    ),
    # Risks
    (r"(?:risk|warning|careful|watch\s+out|danger):\s*(.+)", "risk", "high"),
    (r"(?:this\s+)?(?:might|could|may)\s+(?:break|fail|cause)\s+(.+)", "risk", "medium"),
    # Questions
    (r"(?:should\s+we|do\s+we\s+need\s+to|how\s+(?:do|should)\s+we)\s+(.+)\??", "q", "medium"),
    (r"(?:open\s+question|TBD|to\s+be\s+decided):\s*(.+)", "q", "medium"),
]


# Confidence ranking for tie-breaking
_CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}


def _classify_statement(text: str) -> tuple[str, str, str] | None:
    """Classify a statement into a memory type.

    Evaluates all matching patterns and returns the highest-confidence
    classification.  Returns (type, extracted_title, confidence) or None
    if no match.
    """
    text_stripped = text.strip()
    best: tuple[str, str, str] | None = None
    best_rank = -1
    for pattern, mem_type, confidence in _DISCUSSION_PATTERNS:
        m = re.search(pattern, text_stripped, re.IGNORECASE)
        if m:
            title = m.group(1).strip()
            # Handle special case for "use X over Y" → "Prefer X over Y"
            if mem_type == "pref" and len(m.groups()) >= 2:
                title = f"{m.group(1)} over {m.group(2)}"
            # Clean title
            title = re.sub(r"\s+", " ", title)
            title = title.rstrip(".")
            if len(title) < 5:
                continue
            rank = _CONFIDENCE_RANK.get(confidence, 0)
            if rank > best_rank:
                best = (mem_type, title[:120], confidence)
                best_rank = rank
    return best


def capture_from_discussion(
    workspace: Path,
    transcript: str,
    source: str = "discussion",
    tags: list[str] | None = None,
    deduplicate: bool = True,
) -> list[MemoryCandidate]:
    """Extract memory candidates from a discussion transcript.

    Parses free-text conversation and identifies decisions, preferences,
    goals, facts, risks, and open questions based on linguistic patterns.

    Parameters
    ----------
    workspace
        Path to the memory workspace (for dedup against existing).
    transcript
        Raw text of the discussion/conversation.
    source
        Source label for provenance (e.g. ``"slack:2026-02-10"``).
    tags
        Additional tags to apply to all candidates.
    deduplicate
        If True, filter out candidates that match existing memories.

    Returns
    -------
    list[MemoryCandidate]
        Candidate memories ready for review and optional insertion.
    """
    base_tags = ["topic:discussion"]
    if tags:
        base_tags.extend(t for t in tags if t not in base_tags)

    # Load existing for dedup
    existing: dict[str, Any] = {}
    if deduplicate:
        try:
            existing = load_needs(workspace)
        except (SystemExit, Exception):
            existing = {}

    candidates: list[MemoryCandidate] = []
    seen_titles: set[str] = set()

    # Process line by line and also try multi-line sentences
    lines = transcript.splitlines()
    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue

        # Strip common prefixes: "> quote", "- list", "* list", "User:", timestamps
        cleaned = re.sub(r"^(?:[>*\-]\s*|\d{1,2}:\d{2}\s*|[\w]+:\s*)", "", line).strip()
        if not cleaned or len(cleaned) < 10:
            continue

        result = _classify_statement(cleaned)
        if result is None:
            continue

        mem_type, title, confidence = result

        # Dedup within same transcript
        title_lower = title.lower()
        if title_lower in seen_titles:
            continue
        seen_titles.add(title_lower)

        candidate = MemoryCandidate(
            type=mem_type,
            title=title,
            body=cleaned[:500],
            tags=list(base_tags),
            source=source,
            confidence=confidence,
        )
        candidates.append(candidate)

    # Dedup against existing
    if deduplicate and existing:
        candidates = [c for c in candidates if not _is_duplicate(c, existing)]

    return candidates
