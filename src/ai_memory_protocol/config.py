"""Constants and configuration for the AI Memory Protocol."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Memory type definitions
# ---------------------------------------------------------------------------

TYPE_FILES: dict[str, str] = {
    "mem": "memory/observations.rst",
    "dec": "memory/decisions.rst",
    "fact": "memory/facts.rst",
    "pref": "memory/preferences.rst",
    "risk": "memory/risks.rst",
    "goal": "memory/goals.rst",
    "q": "memory/questions.rst",
}

TYPE_PREFIXES: dict[str, str] = {
    "mem": "MEM",
    "dec": "DEC",
    "fact": "FACT",
    "pref": "PREF",
    "risk": "RISK",
    "goal": "GOAL",
    "q": "Q",
}

TYPE_LABELS: dict[str, str] = {
    "mem": "Observation",
    "dec": "Decision",
    "fact": "Fact",
    "pref": "Preference",
    "risk": "Risk",
    "goal": "Goal",
    "q": "Open Question",
}

DEFAULT_STATUS: dict[str, str] = {
    "mem": "draft",
    "dec": "active",
    "fact": "promoted",
    "pref": "active",
    "risk": "active",
    "goal": "draft",
    "q": "active",
}

LINK_FIELDS: list[str] = [
    "relates",
    "supports",
    "depends",
    "supersedes",
    "contradicts",
    "example_of",
]

METADATA_FIELDS: list[str] = [
    "source",
    "owner",
    "confidence",
    "scope",
    "created_at",
    "updated_at",
    "review_after",
    "expires_at",
]

# ---------------------------------------------------------------------------
# Context-pack type ordering — facts first (highest trust)
# ---------------------------------------------------------------------------

CONTEXT_PACK_ORDER: list[str] = ["fact", "dec", "pref", "goal", "mem", "risk", "q"]

CONTEXT_PACK_LABELS: dict[str, str] = {
    "fact": "Facts (verified, high trust)",
    "dec": "Decisions (with rationale)",
    "pref": "Preferences (coding style, conventions)",
    "goal": "Goals (objectives)",
    "mem": "Observations (may need verification)",
    "risk": "Risks & Assumptions",
    "q": "Open Questions (unresolved)",
}
