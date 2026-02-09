"""Tests for the capture module — git commit analysis and candidate generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ai_memory_protocol.capture import (
    MemoryCandidate,
    _classify_commit,
    _extract_scope,
    _file_overlap,
    _GitCommit,
    _group_commits,
    _infer_tags,
    _is_duplicate,
    capture_from_git,
    format_candidates,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fix_commit() -> _GitCommit:
    return _GitCommit(
        hash="abc12345",
        subject="fix(gateway): resolve timeout issue",
        body="The timeout was set too low.",
        author="dev",
        date="2026-01-15T10:00:00+00:00",
        files=["src/gateway/server.cpp", "src/gateway/config.hpp"],
    )


@pytest.fixture
def feat_commit() -> _GitCommit:
    return _GitCommit(
        hash="def67890",
        subject="feat(api): add health endpoint",
        body="",
        author="dev",
        date="2026-01-16T10:00:00+00:00",
        files=["src/api/health.cpp"],
    )


@pytest.fixture
def breaking_commit() -> _GitCommit:
    return _GitCommit(
        hash="ghi11111",
        subject="refactor(core): restructure module layout",
        body="BREAKING CHANGE: Module paths changed.",
        author="dev",
        date="2026-01-17T10:00:00+00:00",
        files=["src/core/module.cpp"],
    )


@pytest.fixture
def plain_commit() -> _GitCommit:
    return _GitCommit(
        hash="jkl22222",
        subject="Update README",
        body="",
        author="dev",
        date="2026-01-18T10:00:00+00:00",
        files=["README.md"],
    )


# ---------------------------------------------------------------------------
# Tests: _classify_commit
# ---------------------------------------------------------------------------


class TestClassifyCommit:
    def test_fix_commit(self, fix_commit):
        mem_type, confidence = _classify_commit(fix_commit)
        assert mem_type == "mem"
        assert confidence == "high"

    def test_feat_commit(self, feat_commit):
        mem_type, confidence = _classify_commit(feat_commit)
        assert mem_type == "fact"
        assert confidence == "medium"

    def test_breaking_change(self, breaking_commit):
        mem_type, confidence = _classify_commit(breaking_commit)
        assert mem_type == "risk"
        assert confidence == "high"

    def test_plain_commit(self, plain_commit):
        mem_type, confidence = _classify_commit(plain_commit)
        assert mem_type == "mem"
        assert confidence == "low"

    def test_style_commit(self):
        c = _GitCommit(hash="x", subject="style(ui): fix formatting", body="", author="", date="")
        mem_type, _ = _classify_commit(c)
        assert mem_type == "pref"

    def test_docs_commit(self):
        c = _GitCommit(hash="x", subject="docs: update API guide", body="", author="", date="")
        mem_type, _ = _classify_commit(c)
        assert mem_type == "fact"


# ---------------------------------------------------------------------------
# Tests: _extract_scope
# ---------------------------------------------------------------------------


class TestExtractScope:
    def test_with_scope(self):
        assert _extract_scope("fix(gateway): bug") == "gateway"

    def test_without_scope(self):
        assert _extract_scope("fix: general bug") == ""

    def test_with_parentheses_in_title(self):
        assert _extract_scope("feat(api): add handler (new)") == "api"


# ---------------------------------------------------------------------------
# Tests: _infer_tags
# ---------------------------------------------------------------------------


class TestInferTags:
    def test_includes_repo(self, fix_commit):
        tags = _infer_tags(fix_commit, "ros2_medkit")
        assert "repo:ros2_medkit" in tags

    def test_includes_scope_as_topic(self, fix_commit):
        tags = _infer_tags(fix_commit, "ros2_medkit")
        assert "topic:gateway" in tags

    def test_infers_from_paths(self, feat_commit):
        tags = _infer_tags(feat_commit, "ros2_medkit")
        assert "repo:ros2_medkit" in tags
        # Should infer topic from file path
        assert any("topic:" in t for t in tags)


# ---------------------------------------------------------------------------
# Tests: _file_overlap
# ---------------------------------------------------------------------------


class TestFileOverlap:
    def test_full_overlap(self):
        assert _file_overlap(["a.cpp", "b.cpp"], ["a.cpp", "b.cpp"]) == 1.0

    def test_no_overlap(self):
        assert _file_overlap(["a.cpp"], ["b.cpp"]) == 0.0

    def test_partial_overlap(self):
        overlap = _file_overlap(["a.cpp", "b.cpp"], ["b.cpp", "c.cpp"])
        assert 0.3 < overlap < 0.4  # 1/3

    def test_empty_files(self):
        assert _file_overlap([], []) == 0.0


# ---------------------------------------------------------------------------
# Tests: _group_commits
# ---------------------------------------------------------------------------


class TestGroupCommits:
    def test_groups_by_file_overlap(self, fix_commit):
        c2 = _GitCommit(
            hash="222", subject="fix(gateway): another fix", body="",
            author="", date="",
            files=["src/gateway/server.cpp"],
        )
        groups = _group_commits([fix_commit, c2])
        assert len(groups) == 1  # Should be grouped together

    def test_separate_groups_for_unrelated(self, fix_commit, feat_commit):
        groups = _group_commits([fix_commit, feat_commit])
        assert len(groups) == 2  # Different files → separate groups

    def test_empty_list(self):
        assert _group_commits([]) == []

    def test_single_commit(self, fix_commit):
        groups = _group_commits([fix_commit])
        assert len(groups) == 1
        assert len(groups[0]) == 1


# ---------------------------------------------------------------------------
# Tests: _is_duplicate
# ---------------------------------------------------------------------------


class TestIsDuplicate:
    def test_similar_title_is_duplicate(self):
        candidate = MemoryCandidate(
            type="mem",
            title="Gateway timeout is 30 seconds",
            body="test",
            source="commit:abc",
        )
        existing = {
            "MEM_x": {
                "title": "Gateway timeout is 30 seconds by default",
                "status": "active",
                "source": "",
            },
        }
        assert _is_duplicate(candidate, existing)

    def test_different_title_not_duplicate(self):
        candidate = MemoryCandidate(
            type="mem",
            title="API supports pagination",
            body="test",
            source="commit:abc",
        )
        existing = {
            "MEM_x": {
                "title": "Gateway timeout issue",
                "status": "active",
                "source": "",
            },
        }
        assert not _is_duplicate(candidate, existing)

    def test_same_source_is_duplicate(self):
        candidate = MemoryCandidate(
            type="mem",
            title="Completely different title",
            body="test",
            source="commit:abc12345",
        )
        existing = {
            "MEM_x": {
                "title": "Something else",
                "status": "active",
                "source": "commit:abc12345",
            },
        }
        assert _is_duplicate(candidate, existing)

    def test_skips_deprecated(self):
        candidate = MemoryCandidate(
            type="mem",
            title="Gateway timeout",
            body="",
            source="",
        )
        existing = {
            "MEM_x": {
                "title": "Gateway timeout",
                "status": "deprecated",
                "source": "",
            },
        }
        assert not _is_duplicate(candidate, existing)


# ---------------------------------------------------------------------------
# Tests: format_candidates
# ---------------------------------------------------------------------------


class TestFormatCandidates:
    def test_empty_candidates(self):
        result = format_candidates([])
        assert "No new" in result

    def test_human_format(self):
        candidates = [
            MemoryCandidate(
                type="mem",
                title="Test fix",
                body="Fixed a bug",
                tags=["topic:test"],
                source="commit:abc",
                confidence="high",
            ),
        ]
        result = format_candidates(candidates, fmt="human")
        assert "Test fix" in result
        assert "topic:test" in result
        assert "commit:abc" in result

    def test_json_format(self):
        candidates = [
            MemoryCandidate(type="fact", title="New feature", body="Added X", tags=["topic:api"]),
        ]
        result = format_candidates(candidates, fmt="json")
        import json
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["type"] == "fact"

    def test_multiple_candidates(self):
        candidates = [
            MemoryCandidate(type="mem", title=f"Item {i}", body="", tags=[]) for i in range(5)
        ]
        result = format_candidates(candidates, fmt="human")
        assert "5 memory candidate" in result


# ---------------------------------------------------------------------------
# Tests: capture_from_git (integration-ish, mocked subprocess)
# ---------------------------------------------------------------------------


class TestCaptureFromGit:
    def test_no_commits_returns_empty(self, tmp_workspace):
        with patch("ai_memory_protocol.capture._parse_git_log", return_value=[]):
            candidates = capture_from_git(
                workspace=tmp_workspace,
                repo_path=Path("/fake/repo"),
                since="HEAD~5",
                until="HEAD",
            )
            assert candidates == []

    def test_single_commit_creates_candidate(self, tmp_workspace):
        mock_commits = [
            _GitCommit(
                hash="abc12345",
                subject="fix(gateway): timeout bug",
                body="Set default to 30s",
                author="dev",
                date="2026-01-15",
                files=["src/server.cpp"],
            ),
        ]
        with (
            patch("ai_memory_protocol.capture._parse_git_log", return_value=mock_commits),
            patch("ai_memory_protocol.capture.load_needs", return_value={}),
        ):
            candidates = capture_from_git(
                workspace=tmp_workspace,
                repo_path=Path("/fake/repo"),
                repo_name="ros2_medkit",
            )
            assert len(candidates) == 1
            assert candidates[0].type == "mem"
            assert "timeout" in candidates[0].title.lower()
            assert "repo:ros2_medkit" in candidates[0].tags

    def test_dedup_filters_existing(self, tmp_workspace):
        mock_commits = [
            _GitCommit(
                hash="abc12345",
                subject="fix: gateway timeout issue",
                body="",
                author="dev",
                date="2026-01-15",
                files=[],
            ),
        ]
        existing_needs = {
            "MEM_x": {
                "title": "gateway timeout issue",
                "status": "active",
                "source": "",
            },
        }
        with (
            patch("ai_memory_protocol.capture._parse_git_log", return_value=mock_commits),
            patch("ai_memory_protocol.capture.load_needs", return_value=existing_needs),
        ):
            candidates = capture_from_git(
                workspace=tmp_workspace,
                repo_path=Path("/fake/repo"),
                deduplicate=True,
            )
            assert len(candidates) == 0

    def test_min_confidence_filters(self, tmp_workspace):
        mock_commits = [
            _GitCommit(
                hash="abc12345",
                subject="chore: update deps",
                body="",
                author="dev",
                date="2026-01-15",
                files=[],
            ),
        ]
        with (
            patch("ai_memory_protocol.capture._parse_git_log", return_value=mock_commits),
            patch("ai_memory_protocol.capture.load_needs", return_value={}),
        ):
            candidates = capture_from_git(
                workspace=tmp_workspace,
                repo_path=Path("/fake/repo"),
                min_confidence="medium",
            )
            assert len(candidates) == 0  # chore → low confidence, filtered out


# ---------------------------------------------------------------------------
# Tests: MemoryCandidate
# ---------------------------------------------------------------------------


class TestMemoryCandidate:
    def test_to_dict(self):
        c = MemoryCandidate(
            type="mem",
            title="Test",
            body="Body text",
            tags=["topic:test"],
            source="commit:abc",
            confidence="high",
        )
        d = c.to_dict()
        assert d["type"] == "mem"
        assert d["title"] == "Test"
        assert d["confidence"] == "high"
        assert "_source_hashes" not in d  # Private field excluded

    def test_empty_fields_omitted(self):
        c = MemoryCandidate(type="mem", title="Minimal", body="", tags=[])
        d = c.to_dict()
        assert "body" not in d
        assert "source" not in d
