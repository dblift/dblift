"""Tests for the ``MigrationType`` matching helpers.

Enumerates every input shape the three-branch defensive pattern used to
handle (enum, string, ``None``, missing, duck-typed), plus the edge
cases the PR 160 Bugbot threads surfaced (``str(enum)`` dead branch,
``.name`` vs ``.value`` confusion, case sensitivity of string names).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dblift.core.migration._type_match import (
    is_migration_type,
    is_versioned,
    migration_type_name,
)
from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, MigrationType

# --- migration_type_name ----------------------------------------------------


class TestMigrationTypeName:
    @pytest.mark.parametrize(
        "member, expected",
        [(m, m.value) for m in MigrationType],
    )
    def test_enum_members_return_their_value(self, member, expected):
        assert migration_type_name(member) == expected

    @pytest.mark.parametrize(
        "raw", ["SQL", "PYTHON", "REPEATABLE", "UNDO_SQL", "BASELINE", "CALLBACK"]
    )
    def test_plain_strings_are_returned_unchanged(self, raw):
        assert migration_type_name(raw) == raw

    def test_unknown_string_is_not_silently_normalised(self):
        # We preserve exact-match semantics; callers may receive arbitrary
        # strings from persisted history tables and the helper must not
        # fabricate a different name.
        assert migration_type_name("something_weird") == "something_weird"

    def test_none_maps_to_unknown(self):
        assert migration_type_name(None) == "UNKNOWN"

    def test_none_matches_unknown_enum_member(self):
        # If None is canonically "UNKNOWN", then MigrationType.UNKNOWN
        # should round-trip through the same predicate.
        assert migration_type_name(None) == migration_type_name(MigrationType.UNKNOWN)

    def test_duck_typed_with_value_attribute(self):
        # An object that quacks like an enum (has .value: str) is honored.
        assert migration_type_name(SimpleNamespace(value="SQL")) == "SQL"

    def test_duck_typed_with_name_attribute(self):
        # Fallback path when .value is not a string.
        assert migration_type_name(SimpleNamespace(name="SQL", value=object())) == "SQL"

    def test_non_string_non_enum_non_duck_falls_back_to_str(self):
        # Last-resort fallback — just ensures no exception and returns a
        # deterministic string that will not coincidentally match any
        # MigrationType value.
        name = migration_type_name(42)
        assert name == "42"


# --- is_versioned -----------------------------------------------------------


class TestIsVersioned:
    @pytest.mark.parametrize("member", [MigrationType.SQL, MigrationType.PYTHON])
    def test_true_for_versioned_enum_members(self, member):
        assert is_versioned(member) is True

    @pytest.mark.parametrize(
        "member",
        [
            MigrationType.REPEATABLE,
            MigrationType.UNDO_SQL,
            MigrationType.BASELINE,
            MigrationType.CALLBACK,
            MigrationType.DELETE,
            MigrationType.UNKNOWN,
        ],
    )
    def test_false_for_non_versioned_enum_members(self, member):
        assert is_versioned(member) is False

    @pytest.mark.parametrize("raw", ["SQL", "PYTHON"])
    def test_true_for_versioned_strings(self, raw):
        assert is_versioned(raw) is True

    @pytest.mark.parametrize("raw", ["REPEATABLE", "UNDO_SQL", "BASELINE"])
    def test_false_for_non_versioned_strings(self, raw):
        assert is_versioned(raw) is False

    def test_none_is_not_versioned(self):
        assert is_versioned(None) is False

    def test_str_enum_bug_pattern_does_not_leak_through(self):
        # The exact regression that started this refactor:
        # `str(MigrationType.SQL)` yields "MigrationType.SQL", which must
        # not be treated as versioned. The helper receives the enum
        # directly; the question is whether callers who pass the BROKEN
        # "MigrationType.SQL" string into the predicate get a sane answer.
        assert is_versioned("MigrationType.SQL") is False

    def test_versioned_set_content_is_the_contract(self):
        # Guards against someone silently changing the set. If a new
        # versioned type is added to MigrationType, it has to be added to
        # VERSIONED_SCRIPT_TYPES intentionally — at which point this test
        # will fail and the contributor is forced to look here.
        assert VERSIONED_SCRIPT_TYPES == frozenset({"SQL", "PYTHON"})


# --- is_migration_type ------------------------------------------------------


class TestIsMigrationType:
    def test_enum_vs_enum(self):
        assert is_migration_type(MigrationType.SQL, MigrationType.SQL) is True
        assert is_migration_type(MigrationType.SQL, MigrationType.UNDO_SQL) is False

    def test_enum_vs_string(self):
        assert is_migration_type(MigrationType.SQL, "SQL") is True
        assert is_migration_type(MigrationType.UNDO_SQL, "UNDO_SQL") is True

    def test_string_vs_enum(self):
        # Symmetric — either side can be enum or string.
        assert is_migration_type("SQL", MigrationType.SQL) is True

    def test_string_vs_string(self):
        assert is_migration_type("SQL", "SQL") is True
        assert is_migration_type("SQL", "PYTHON") is False

    def test_none_vs_unknown(self):
        assert is_migration_type(None, MigrationType.UNKNOWN) is True
        assert is_migration_type(None, "UNKNOWN") is True

    def test_none_vs_sql_is_false(self):
        assert is_migration_type(None, MigrationType.SQL) is False

    @pytest.mark.parametrize(
        "value, target, expected",
        [
            (MigrationType.UNDO_SQL, "UNDO_SQL", True),
            ("UNDO_SQL", "UNDO_SQL", True),
            (MigrationType.UNDO_SQL, MigrationType.SQL, False),
            ("undo_sql", "UNDO_SQL", False),  # case-sensitive by design
        ],
    )
    def test_canonical_match(self, value, target, expected):
        assert is_migration_type(value, target) is expected
