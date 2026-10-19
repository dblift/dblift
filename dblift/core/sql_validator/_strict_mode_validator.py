"""Strict-mode rule validation extracted from :class:`MigrationValidator`.

``validate_strict_mode_rules`` enforces two strict-mode invariants:
1. No applied migration may exist without a corresponding script file
   (excluding baseline, undo and audit rows, and scripts marked as deleted).
   The state manager decides this; the validator only reports its answer.
2. No pending versioned script may have a version at or below the
   schema's current version (out-of-order detection). The state manager
   decides this too.

Pulled out as a single standalone function taking the validator
instance as its first parameter (``mv``). ``MigrationValidator._validate_strict_mode_rules``
delegates to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Sequence

from dblift.core.migration.migration import Migration
from dblift.core.migration.state.ordering import OutOfOrder

if TYPE_CHECKING:
    from dblift.core.sql_validator.migration_validator import (
        MigrationValidator,
        ValidationResult,
    )


def validate_strict_mode_rules(
    mv: "MigrationValidator",
    result: "ValidationResult",
    issues: List[str],
    snapshot_missing_applied: Sequence[Migration],
    snapshot_out_of_order: Sequence[OutOfOrder],
) -> bool:
    """Enforce strict-mode invariants on the state manager's answers.

    *snapshot_missing_applied* lists the applied migrations whose script is
    gone and *snapshot_out_of_order* the pending scripts below the current
    version; this function only reports them.
    """
    if snapshot_missing_applied:
        result.success = False
        script_list = ", ".join(
            [
                f"{getattr(m, 'script_name', None)} "
                f"(version: {getattr(m, 'version', 'unknown')})"
                for m in snapshot_missing_applied
            ]
        )
        error_message = (
            f"Strict mode validation failed. Found {len(snapshot_missing_applied)} applied "
            f"migration(s) without corresponding script files: {script_list}. ."
        )
        issues.append(error_message)
        for missing in snapshot_missing_applied:
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
