"""Canonical matching helpers for ``MigrationType``.

The project has historically carried ~30 copies of a three-branch
defensive comparison:

    migration_type == "SQL"
    or str(migration_type) == "SQL"           # <-- dead for enum members
    or (
        migration_type is not None
        and hasattr(migration_type, "name")
        and migration_type.name == "SQL"
    )

The middle branch is dead code — ``str(MigrationType.SQL)`` is
``"MigrationType.SQL"``, which never matches a bare type name. Bugbot
flagged this pattern on PR 160 (get_reapplied_versions,
determine_pending_migration_status, get_category_and_display_type,
VERSIONED_SCRIPT_TYPES lookups); the lint rule
``enum-str-conversion`` now catches new occurrences.

This module centralises the canonical comparison so call sites become
one-liners:

    from dblift.core.migration._type_match import is_versioned, is_migration_type

    is_versioned(migration.type)
    is_migration_type(migration.type, "UNDO_SQL")
    is_migration_type(migration.type, MigrationType.SQL)

See ``docs/adr/0006-migration-type-match-helpers.md`` for the design
rationale.
"""

from __future__ import annotations

from typing import Any, Union

from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, MigrationType

# Public symbols.
__all__ = [
    "migration_type_name",
    "is_versioned",
    "is_migration_type",
]


def migration_type_name(value: Any) -> str:
    """Return the canonical string name of a migration type.

    Accepts any of:
      * a ``MigrationType`` enum member → returns its ``.value`` (e.g. ``"SQL"``)
      * a bare string → returned unchanged (no uppercasing; callers rely on
        exact-match semantics against ``VERSIONED_SCRIPT_TYPES`` and enum values)
      * ``None`` → returns ``"UNKNOWN"`` (matches ``MigrationType.UNKNOWN.value``)
      * any duck-typed object with a string ``.value`` or ``.name`` attribute
      * anything else → last-resort ``str(value)``, which is intentionally
        allow-listed in this file and only this file

    The function never raises on bad input: unknown migration types are
    caller-visible as a non-matching string, the same contract the
    three-branch defensive code used to provide.
    """
    if value is None:
        return "UNKNOWN"
    if isinstance(value, MigrationType):
        return value.value
    if isinstance(value, str):
        return value
    if hasattr(value, "value") and isinstance(value.value, str):
        return value.value
    if hasattr(value, "name") and isinstance(value.name, str):
        return value.name
    # Last-resort fallback. The linter's enum-str-conversion rule flags
    # str(x.type) / str(*_type) patterns; the argument here is plainly
    # named ``value`` and is a non-enum, non-string, non-duck object, so
    # the fallback is semantically justified.
    return str(value)


def is_versioned(value: Any) -> bool:
    """``True`` iff the value represents a versioned, run-once migration.

    Versioned types participate in Flyway-style V*__description.*
    ordering and are subject to baseline / pending / above-target
    accounting. Non-versioned types (repeatable, callback, undo,
    baseline, delete) are filtered out of those flows.

    This predicate replaces the scattered three-branch defensive
    comparisons. ``value`` may be a ``MigrationType`` member, a string,
    or ``None`` — see :func:`migration_type_name` for the exhaustive
    input contract.
    """
    return migration_type_name(value) in VERSIONED_SCRIPT_TYPES


def is_migration_type(value: Any, target: Union[MigrationType, str]) -> bool:
    """``True`` iff ``value`` represents the same migration type as ``target``.

    Both arguments are normalised via :func:`migration_type_name` before
    comparison, so any combination of enum member, string, and ``None``
    is handled symmetrically.

    >>> is_migration_type(MigrationType.SQL, "SQL")
    True
    >>> is_migration_type("SQL", MigrationType.SQL)
    True
    >>> is_migration_type(None, MigrationType.SQL)
    False
    """
    return migration_type_name(value) == migration_type_name(target)
