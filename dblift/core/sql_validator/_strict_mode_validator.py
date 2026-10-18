"""Strict-mode rule validation extracted from :class:`MigrationValidator`.

The original ``_validate_strict_mode_rules`` enforces two strict-mode
invariants:
1. No applied migration may exist without a corresponding script file
   (excluding ``BASELINE`` and ``UNDO_SQL``).
2. No pending versioned script may have a version at or below the
   schema's current version (out-of-order detection). The state manager
   decides this; the validator only reports its answer.

Pulled out as a single standalone function taking the validator
instance as its first parameter (``mv``). ``MigrationValidator`` keeps
a thin wrapper so existing tests calling
``v._validate_strict_mode_rules(...)`` continue to work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Sequence

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.ordering import OutOfOrder
from dblift.core.migration.version_utils import is_migration_success

if TYPE_CHECKING:
    from dblift.core.sql_validator.migration_validator import (
        MigrationValidator,
        ValidationResult,
    )


def validate_strict_mode_rules(
    mv: "MigrationValidator",
    scripts: List[Migration],
    applied_migrations: List[Migration],
    result: "ValidationResult",
    issues: List[str],
    snapshot_out_of_order: Sequence[OutOfOrder],
) -> bool:
    """Enforce strict-mode invariants on *scripts* + *applied_migrations*.

    *snapshot_out_of_order* is the state manager's answer for the pending
    scripts below the current version; this function only reports it.
    """
    script_names = [s.script_name for s in scripts]

    missing_migrations = []
    for applied in applied_migrations:
        version_val = getattr(applied, "version", "")
        if (
            getattr(applied, "type", None) == MigrationType.BASELINE
            or str(version_val).lower() == "baseline"
        ):
            continue
        if getattr(applied, "type", None) == MigrationType.UNDO_SQL:
            continue
        script_name = getattr(applied, "script_name", None)
        if script_name not in script_names and is_migration_success(
            getattr(applied, "success", None)
        ):
            missing_migrations.append(applied)
    if missing_migrations:
        result.success = False
        script_list = ", ".join(
            [
                f"{getattr(m, 'script_name', None)} "
                f"(version: {getattr(m, 'version', 'unknown')})"
                for m in missing_migrations
            ]
        )
        error_message = (
            f"Strict mode validation failed. Found {len(missing_migrations)} applied "
            f"migration(s) without corresponding script files: {script_list}. ."
        )
        issues.append(error_message)
        for missing in missing_migrations:
            result.add_failed_script(getattr(missing, "script_name", None))
        result.error_message = error_message
        return False

    if snapshot_out_of_order:
        mv.log.debug(
            f"Strict mode: {len(snapshot_out_of_order)} out-of-order migration(s) detected"
        )
        result.success = False
        script_list = ", ".join(
            [
                f"{entry.migration.script_name} (version: {entry.migration.version})"
                for entry in snapshot_out_of_order
            ]
        )
        current_version = snapshot_out_of_order[0].current_version
        error_message = (
            f"Strict mode validation failed. Found {len(snapshot_out_of_order)} "
            "pending migration(s) with version(s) lower than the highest applied "
            f"version ({current_version}): {script_list}. ."
        )
        issues.append(error_message)
        for entry in snapshot_out_of_order:
            result.add_failed_script(getattr(entry.migration, "script_name", None))
        result.error_message = error_message
        return False

    return True
