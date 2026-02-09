"""Tests for config constants — ensure consistency of mappings."""

from ai_memory_protocol.config import (
    CONTEXT_PACK_LABELS,
    CONTEXT_PACK_ORDER,
    DEFAULT_STATUS,
    LINK_FIELDS,
    METADATA_FIELDS,
    TYPE_FILES,
    TYPE_LABELS,
    TYPE_PREFIXES,
)


def test_type_files_maps_all_types():
    """Every type in TYPE_PREFIXES should have a corresponding file."""
    for typ in TYPE_PREFIXES:
        assert typ in TYPE_FILES, f"Type '{typ}' missing from TYPE_FILES"


def test_type_prefixes_maps_all_types():
    """Every type in TYPE_FILES should have a prefix."""
    for typ in TYPE_FILES:
        assert typ in TYPE_PREFIXES, f"Type '{typ}' missing from TYPE_PREFIXES"


def test_type_prefixes_uppercase():
    """Prefixes should be uppercase."""
    for typ, prefix in TYPE_PREFIXES.items():
        assert prefix == prefix.upper(), f"Prefix for '{typ}' should be uppercase: got '{prefix}'"


def test_type_labels_all_types():
    """Every type should have a human-readable label."""
    for typ in TYPE_PREFIXES:
        assert typ in TYPE_LABELS, f"Type '{typ}' missing from TYPE_LABELS"


def test_default_status_all_types():
    """Every type should have a default status."""
    for typ in TYPE_PREFIXES:
        assert typ in DEFAULT_STATUS, f"Type '{typ}' missing from DEFAULT_STATUS"


def test_link_fields_are_strings():
    """Link fields should all be strings."""
    for field in LINK_FIELDS:
        assert isinstance(field, str)


def test_metadata_fields_are_strings():
    """Metadata fields should all be strings."""
    for field in METADATA_FIELDS:
        assert isinstance(field, str)


def test_context_pack_order_covers_types():
    """Context pack order should include all types."""
    for typ in TYPE_PREFIXES:
        assert typ in CONTEXT_PACK_ORDER, f"Type '{typ}' missing from CONTEXT_PACK_ORDER"


def test_context_pack_labels_covers_order():
    """Every type in context pack order should have a label."""
    for typ in CONTEXT_PACK_ORDER:
        assert typ in CONTEXT_PACK_LABELS, f"Type '{typ}' missing from CONTEXT_PACK_LABELS"


def test_type_files_paths_are_rst():
    """All type file paths should be .rst files."""
    for typ, path in TYPE_FILES.items():
        assert path.endswith(".rst"), f"Type '{typ}' file path should be .rst: got '{path}'"


def test_type_files_in_memory_dir():
    """All type file paths should be under memory/."""
    for typ, path in TYPE_FILES.items():
        assert path.startswith("memory/"), f"Type '{typ}' path should start with 'memory/': {path}"
