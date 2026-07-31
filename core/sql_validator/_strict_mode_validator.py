"""Strict-mode rule validation extracted from :class:`MigrationValidator`.

The original ``_validate_strict_mode_rules`` enforces two strict-mode
invariants:
1. No applied migration may exist without a corresponding script file
   (excluding ``BASELINE`` and ``UNDO_SQL``).
2. No pending versioned script may have a version lower than the
   highest applied version (out-of-order detection).

Pulled out as a single standalone function taking the validator
instance as its first parameter (``mv``). ``MigrationValidator`` keeps
a thin wrapper so existing tests calling
``v._validate_strict_mode_rules(...)`` continue to work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from core.migration import is_versioned
from core.migration.migration import Migration, MigrationType
from core.migration.version_utils import is_migration_success

if TYPE_CHECKING:
    from core.sql_validator.migration_validator import (
        MigrationValidator,
        ValidationResult,
    )


def validate_strict_mode_rules(
    mv: "MigrationValidator",
    scripts: List[Migration],
    applied_migrations: List[Migration],
    result: "ValidationResult",
    issues: List[str],
) -> bool:
    """Enforce strict-mode invariants on *scripts* + *applied_migrations*."""
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
        result.error_message = error_message
        return False

    # Role, not format: MigrationType.SQL means "versioned", and a versioned
    # .py script carries MigrationType.PYTHON instead.
    pending_versioned = [
        s
        for s in scripts
        if is_versioned(s.type)
        and s.script_name
        not in [
            getattr(a, "script_name", None)
            for a in applied_migrations
            if is_migration_success(getattr(a, "success", None))
        ]
    ]

    if not pending_versioned:
        return True

    applied_versions = [
        getattr(a, "version", None)
        for a in applied_migrations
        if is_versioned(getattr(a, "type", None))
        and is_migration_success(getattr(a, "success", None))
    ]

    if not applied_versions:
        return True

    sorted_versions = applied_versions.copy()
    sorted_versions.sort(
        key=lambda v: (
            sum(
                1
                for other_v in applied_versions
                if mv.script_manager.compare_versions(v, other_v) > 0
            ),
            v,
        )
    )
    highest_applied_version = sorted_versions[-1] if sorted_versions else None

    if highest_applied_version:
        out_of_order_migrations = []
        for script in pending_versioned:
            comparison_result = mv.script_manager.compare_versions(
                script.version, highest_applied_version
            )
            if comparison_result < 0:
                out_of_order_migrations.append(script)

        if out_of_order_migrations:
            mv.log.debug(
                f"Strict mode: {len(out_of_order_migrations)} out-of-order migration(s) detected"
            )
            result.success = False
            script_list = ", ".join(
                [f"{s.script_name} (version: {s.version})" for s in out_of_order_migrations]
            )
            error_message = (
                f"Strict mode validation failed. Found {len(out_of_order_migrations)} "
                "pending migration(s) with version(s) lower than the highest applied "
                f"version ({highest_applied_version}): {script_list}. ."
            )
            issues.append(error_message)
            result.error_message = error_message
            return False

    return True
