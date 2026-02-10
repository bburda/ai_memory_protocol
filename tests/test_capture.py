"""Tests for the capture module — git commit analysis and candidate generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ai_memory_protocol.capture import (
    MemoryCandidate,
    _classify_commit,
    _classify_statement,
    _extract_scope,
    _file_overlap,
    _GitCommit,
    _group_commits,
    _infer_tags,
    _is_duplicate,
    _parse_ci_log,
    capture_from_ci,
    capture_from_discussion,
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
            hash="222",
            subject="fix(gateway): another fix",
            body="",
            author="",
            date="",
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


# ===========================================================================
# Tests: CI Log Capture
# ===========================================================================


class TestParseCILog:
    def test_test_failure(self):
        log = "FAILED: test_gateway_health\nSome other output"
        matches = _parse_ci_log(log)
        assert len(matches) >= 1
        assert matches[0].mem_type == "mem"
        assert "gateway_health" in matches[0].title

    def test_pytest_failure(self):
        log = "FAILED tests/test_api.py::TestHealth::test_endpoint"
        matches = _parse_ci_log(log)
        assert len(matches) >= 1
        assert "test_api" in matches[0].title or "TestHealth" in matches[0].title

    def test_compiler_error(self):
        log = "src/server.cpp:42:10: error: use of undeclared identifier 'foo'"
        matches = _parse_ci_log(log)
        assert len(matches) >= 1
        assert matches[0].confidence == "high"
        assert "server.cpp" in matches[0].title

    def test_deprecation_warning(self):
        log = "DeprecationWarning: pkg_resources is deprecated"
        matches = _parse_ci_log(log)
        assert len(matches) >= 1
        assert matches[0].mem_type == "risk"

    def test_timeout_error(self):
        log = "TimeoutError: connection timed out after 30 seconds"
        matches = _parse_ci_log(log)
        assert len(matches) >= 1
        assert "timeout" in matches[0].title.lower()

    def test_cmake_error(self):
        log = "CMake Error at CMakeLists.txt:15: Could not find dependency XYZ"
        matches = _parse_ci_log(log)
        assert len(matches) >= 1
        assert "cmake" in matches[0].title.lower() or "CMake" in matches[0].detail

    def test_generic_error(self):
        log = "Error: file not found: config.yaml"
        matches = _parse_ci_log(log)
        assert len(matches) >= 1

    def test_empty_log(self):
        matches = _parse_ci_log("")
        assert matches == []

    def test_clean_log_no_matches(self):
        log = "Building project...\nCompilation successful.\nAll tests passed."
        matches = _parse_ci_log(log)
        assert matches == []

    def test_dedup_within_log(self):
        log = "FAILED: test_foo\nFAILED: test_foo\nFAILED: test_bar"
        matches = _parse_ci_log(log)
        titles = [m.title for m in matches]
        # Should not have duplicate titles
        assert len(titles) == len(set(titles))


class TestCaptureFromCI:
    def test_basic_capture(self, tmp_workspace):
        log = "FAILED: test_health_check\nError: connection refused"
        with patch("ai_memory_protocol.capture.load_needs", return_value={}):
            candidates = capture_from_ci(
                workspace=tmp_workspace,
                log_text=log,
                source="ci:test-run-123",
            )
            assert len(candidates) >= 1
            assert all("topic:ci" in c.tags for c in candidates)
            assert candidates[0].source == "ci:test-run-123"

    def test_extra_tags(self, tmp_workspace):
        log = "FAILED: test_api"
        with patch("ai_memory_protocol.capture.load_needs", return_value={}):
            candidates = capture_from_ci(
                workspace=tmp_workspace,
                log_text=log,
                tags=["repo:backend", "topic:api"],
            )
            assert len(candidates) >= 1
            assert "repo:backend" in candidates[0].tags
            assert "topic:ci" in candidates[0].tags

    def test_empty_log_returns_empty(self, tmp_workspace):
        candidates = capture_from_ci(
            workspace=tmp_workspace,
            log_text="All tests passed. Build successful.",
        )
        assert candidates == []

    def test_dedup_against_existing(self, tmp_workspace):
        log = "FAILED: test_health_check"
        existing = {
            "MEM_x": {
                "title": "CI test failure: test_health_check",
                "status": "active",
                "source": "",
            },
        }
        with patch("ai_memory_protocol.capture.load_needs", return_value=existing):
            candidates = capture_from_ci(
                workspace=tmp_workspace,
                log_text=log,
                deduplicate=True,
            )
            assert len(candidates) == 0


# ===========================================================================
# Tests: Discussion Capture
# ===========================================================================


class TestClassifyStatement:
    def test_decision(self):
        result = _classify_statement("We decided to use FastAPI for the backend")
        assert result is not None
        mem_type, title, confidence = result
        assert mem_type == "dec"
        assert "FastAPI" in title

    def test_lets_go_with(self):
        result = _classify_statement("Let's go with PostgreSQL for storage")
        assert result is not None
        assert result[0] == "dec"

    def test_preference(self):
        result = _classify_statement("I prefer TypeScript over JavaScript")
        assert result is not None
        assert result[0] == "pref"

    def test_convention(self):
        result = _classify_statement("Convention: all API responses use camelCase")
        assert result is not None
        assert result[0] == "pref"

    def test_goal(self):
        result = _classify_statement("The goal is to have 80% test coverage")
        assert result is not None
        assert result[0] == "goal"

    def test_we_need_to(self):
        result = _classify_statement("We need to optimize the database queries")
        assert result is not None
        assert result[0] == "goal"

    def test_todo(self):
        result = _classify_statement("TODO: add retry logic for failed requests")
        assert result is not None
        assert result[0] == "goal"

    def test_fact_turns_out(self):
        result = _classify_statement("It turns out the API uses OAuth2 internally")
        assert result is not None
        assert result[0] == "fact"

    def test_fact_til(self):
        result = _classify_statement("TIL: Sphinx-Needs supports needextend directives")
        assert result is not None
        assert result[0] == "fact"

    def test_risk(self):
        result = _classify_statement("Warning: this might break backward compatibility")
        assert result is not None
        assert result[0] == "risk"

    def test_could_break(self):
        result = _classify_statement("This could break the CI pipeline if merged")
        assert result is not None
        assert result[0] == "risk"

    def test_question(self):
        result = _classify_statement("Should we use Redis for caching?")
        assert result is not None
        assert result[0] == "q"

    def test_open_question(self):
        result = _classify_statement("Open question: how do we handle rate limiting?")
        assert result is not None
        assert result[0] == "q"

    def test_no_match(self):
        result = _classify_statement("The weather is nice today")
        assert result is None

    def test_too_short(self):
        result = _classify_statement("Decided ok")
        assert result is None  # Title too short after extraction


class TestCaptureFromDiscussion:
    def test_basic_capture(self, tmp_workspace):
        transcript = """
        We decided to use ROS 2 Jazzy for the gateway.
        I prefer async/await over callbacks for all new code.
        The goal is to have all endpoints documented by March.
        Should we support gRPC in addition to REST?
        """
        with patch("ai_memory_protocol.capture.load_needs", return_value={}):
            candidates = capture_from_discussion(
                workspace=tmp_workspace,
                transcript=transcript,
                source="meeting:standup",
            )
            assert len(candidates) >= 3
            types = {c.type for c in candidates}
            assert "dec" in types
            assert "pref" in types or "goal" in types

    def test_tags_applied(self, tmp_workspace):
        transcript = "We decided to deploy on Kubernetes for production"
        with patch("ai_memory_protocol.capture.load_needs", return_value={}):
            candidates = capture_from_discussion(
                workspace=tmp_workspace,
                transcript=transcript,
                tags=["repo:infra"],
            )
            assert len(candidates) >= 1
            assert "topic:discussion" in candidates[0].tags
            assert "repo:infra" in candidates[0].tags

    def test_source_label(self, tmp_workspace):
        transcript = "The goal is to launch by Q3 2026"
        with patch("ai_memory_protocol.capture.load_needs", return_value={}):
            candidates = capture_from_discussion(
                workspace=tmp_workspace,
                transcript=transcript,
                source="slack:2026-02-10",
            )
            assert len(candidates) >= 1
            assert candidates[0].source == "slack:2026-02-10"

    def test_empty_transcript(self, tmp_workspace):
        candidates = capture_from_discussion(
            workspace=tmp_workspace,
            transcript="",
        )
        assert candidates == []

    def test_irrelevant_transcript(self, tmp_workspace):
        transcript = """
        Good morning everyone.
        How was your weekend?
        Fine thanks.
        """
        candidates = capture_from_discussion(
            workspace=tmp_workspace,
            transcript=transcript,
        )
        assert candidates == []

    def test_dedup_within_transcript(self, tmp_workspace):
        transcript = """
        We decided to use PostgreSQL for storage.
        As I said, we decided to use PostgreSQL for storage.
        """
        with patch("ai_memory_protocol.capture.load_needs", return_value={}):
            candidates = capture_from_discussion(
                workspace=tmp_workspace,
                transcript=transcript,
            )
            # Should deduplicate within the same transcript
            titles = [c.title.lower() for c in candidates]
            assert len(titles) == len(set(titles))

    def test_strips_prefixes(self, tmp_workspace):
        transcript = """
        > We decided to adopt trunk-based development
        - TODO: set up branch protection rules
        12:30 I prefer small PRs over large ones
        """
        with patch("ai_memory_protocol.capture.load_needs", return_value={}):
            candidates = capture_from_discussion(
                workspace=tmp_workspace,
                transcript=transcript,
            )
            assert len(candidates) >= 2

    def test_dedup_against_existing(self, tmp_workspace):
        transcript = "We decided to use FastAPI for the backend"
        existing = {
            "DEC_x": {
                "title": "use FastAPI for the backend",
                "status": "active",
                "source": "",
            },
        }
        with patch("ai_memory_protocol.capture.load_needs", return_value=existing):
            candidates = capture_from_discussion(
                workspace=tmp_workspace,
                transcript=transcript,
                deduplicate=True,
            )
            assert len(candidates) == 0
