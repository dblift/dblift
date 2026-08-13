"""Checksum-drift validators extracted from :class:`MigrationValidator`.

The two heavy methods ``_validate_checksums`` and
``_check_repeatable_migrations`` were the largest chunk of the
1770-line ``migration_validator.py``. They depend on three things from
the validator instance:

- ``script_manager`` (``has_script_changed`` / ``calculate_checksum`` /
  encoding settings),
- ``log`` (a :class:`Log` instance),
- the module-level ``_last_successful_non_delete_record`` helper.

Pulled into a dedicated module as standalone functions taking the
validator as their first parameter (``mv``). ``MigrationValidator``
keeps thin wrapper methods so existing tests that call
``v._validate_checksums(...)`` / ``v._check_repeatable_migrations(...)``
continue to work.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from core.migration.encoding import read_migration_text
from core.migration.migration import (
    Migration,
    MigrationType,
    calculate_migration_script_checksum,
    normalize_migration_checksum,
)
from core.migration.version_utils import is_migration_success

if TYPE_CHECKING:
    from core.sql_validator.migration_validator import (
        MigrationValidator,
        ValidationResult,
    )


def _last_successful_non_delete_record(
    applied_migrations: List[Migration], script_name: str
) -> Optional[Migration]:
    """Local copy of the helper from :mod:`core.sql_validator.migration_validator`.

    Kept here so this module is self-contained; the original re-exports
    the same name for backward compat with tests that import it directly.
    """
    from core.migration._type_match import is_migration_type

    for migration in reversed(applied_migrations):
        if getattr(migration, "script_name", None) != script_name:
            continue
        migration_type = getattr(migration, "type", None)
        if is_migration_type(migration_type, "DELETE") or is_migration_type(
            migration_type, "UNDO_SQL"
        ):
            continue
        if not is_migration_success(getattr(migration, "success", False)):
            continue
        return migration
    return None


def validate_checksums(
    mv: "MigrationValidator",
    scripts: List[Migration],
    applied_migrations: List[Migration],
    result: "ValidationResult",
    issues: List[str],
    strict_mode: bool = False,
    all_scripts: Optional[List[Migration]] = None,
) -> None:
    """Validate checksums of executed migrations.

    Compares each applied migration's stored checksum against the current
    file's checksum, flagging drift either as an error (versioned scripts)
    or a recorded reapply (repeatable scripts).

    ``scripts`` may be scoped by ``--tags``/``--versions`` filters; ``all_scripts``,
    when provided, is the full unfiltered set of on-disk scripts and is used only to
    decide whether an applied migration is genuinely missing from the migration
    directory (as opposed to merely filtered out of the current run's scope).
    """
    checksum_mismatches = []
    script_names = [s.script_name for s in scripts]
    full_script_names = (
        [s.script_name for s in all_scripts] if all_scripts is not None else script_names
    )

    for applied in applied_migrations:
        script_name = getattr(applied, "script_name", None)
        migration_type = getattr(applied, "type", None)
        version_val = getattr(applied, "version", "")

        # Skip types that have no stored checksum or are exempt from drift detection.
        # Inverted guard: only skip UNKNOWN, DELETE, and BASELINE (no script to compare).
        # PYTHON is intentionally included — it has a checksum stored at apply time.
        if migration_type in (
            MigrationType.UNKNOWN,
            MigrationType.DELETE,
            MigrationType.UNDO_SQL,
            MigrationType.BASELINE,
        ):
            continue
        if migration_type == "UNDO_SQL":
            continue
        if migration_type == MigrationType.BASELINE:
            continue

        if script_name not in full_script_names and (
            not script_name or Path(script_name).name not in full_script_names
        ):
            if migration_type != MigrationType.BASELINE and str(version_val).lower() != "baseline":
                # Check if this script has been marked as deleted
                is_deleted = any(
                    getattr(m, "script_name", None) == script_name
                    and getattr(m, "type", None) == MigrationType.DELETE
                    for m in applied_migrations
                )

                if not is_deleted:
                    # Check for a different script with the same version
                    same_version = [
                        s
                        for s in scripts
                        if getattr(s, "version", None) is not None
                        and str(getattr(s, "version", "")) == str(version_val)
                        and getattr(s, "script_name", None) != script_name
                    ]
                    if same_version:
                        alt_names = ", ".join(
                            getattr(s, "script_name", str(s)) for s in same_version
                        )
                        msg = (
                            f"Applied migration '{script_name}' is missing from the "
                            "migration directory."
                            f" A script with the same version exists under a "
                            f"different name: {alt_names}."
                            " Run 'repair' to resolve the name mismatch."
                        )
                    else:
                        msg = (
                            f"Applied migration '{script_name}' is missing from the "
                            "migration directory. Use 'repair' command to mark it as "
                            "intentionally deleted."
                        )
                    if strict_mode:
                        issues.append(msg)
                    else:
                        mv.log.warning(msg)
                else:
                    # Script is missing but marked as deleted - this is OK
                    mv.log.debug(
                        f"Migration '{script_name}' is missing from filesystem but "
                        "marked as deleted - OK"
                    )
            continue
        if script_name not in script_names and (
            not script_name or Path(script_name).name not in script_names
        ):
            # Present on disk but filtered out of scope by --tags/--versions - not missing.
            mv.log.debug(
                f"Migration '{script_name}' is out of scope for this run's filters - skipping"
            )
            continue
        if migration_type == MigrationType.BASELINE:
            mv.log.debug(f"Skipping checksum verification for {script_name} (baseline)")
            continue
        # Find the Migration object in scripts with the matching script_name
        script_obj = next(
            (s for s in scripts if getattr(s, "script_name", None) == script_name), None
        )
        if script_obj is None and script_name:
            script_basename = Path(script_name).name
            script_obj = next(
                (s for s in scripts if getattr(s, "script_name", None) == script_basename), None
            )
        script_path = script_obj.path if script_obj is not None else None
        script_changed = mv.script_manager.has_script_changed(
            script_name=script_name,
            applied_migrations=applied_migrations,
            script_path=script_path,
        )
        if script_changed:
            # Align with has_script_changed: latest successful row + CRC32 from raw file bytes
            applied_record = _last_successful_non_delete_record(applied_migrations, script_name)
            if applied_record is None:
                # Migration was never successfully applied (e.g. it failed).
                # No checksum to compare against — skip, the "failed migration" error
                # above covers it.
                continue
            last_applied_raw = (
                getattr(applied_record, "checksum", None) if applied_record is not None else None
            )
            last_applied_checksum = normalize_migration_checksum(last_applied_raw)
            current_checksum: Optional[int] = None
            if script_path and script_path.exists():
                enc = getattr(mv.script_manager, "script_encoding", "utf-8")
                detect_encoding = getattr(mv.script_manager, "detect_encoding", False)
                raw_text = read_migration_text(
                    script_path,
                    configured_encoding=enc,
                    detect_encoding=detect_encoding,
                )
                current_checksum = normalize_migration_checksum(
                    mv.script_manager.calculate_checksum(raw_text)
                )
                if current_checksum is None:
                    current_checksum = calculate_migration_script_checksum(raw_text)
            # Authoritative compare: driver quirks or mixed-type comparisons in
            # has_script_changed can yield false positives; only flag real drift.
            if (
                last_applied_checksum is not None
                and current_checksum is not None
                and last_applied_checksum == current_checksum
            ):
                mv.log.debug(
                    f"Checksum re-verification matched for {script_name} "
                    f"({current_checksum}); ignoring false positive from change detection"
                )
            else:
                checksum_mismatches.append(
                    {
                        "script": script_name,
                        "current_checksum": current_checksum,
                        "applied_checksum": last_applied_checksum,
                    }
                )
                # Only consider modified scripts as errors if they are not repeatable
                if migration_type != MigrationType.REPEATABLE and migration_type != "REPEATABLE":
                    error_message = (
                        f"Migration script {script_name} has been modified since it was "
                        f"applied. Database checksum: {last_applied_checksum}, "
                        f"Filesystem checksum: {current_checksum}"
                    )
                    if not any(
                        script_name in issue and "has been modified" in issue for issue in issues
                    ):
                        issues.append(error_message)
                else:
                    # For repeatable migrations, just log at debug level
                    mv.log.debug(
                        f"Repeatable migration {script_name} has been modified and "
                        f"will be reapplied. Database checksum: {last_applied_checksum}, "
                        f"Filesystem checksum: {current_checksum}"
                    )
        else:
            mv.log.debug(f"Checksum verification passed for {script_name}")

    # Only add validation failure for versioned scripts with checksum mismatches
    versioned_mismatches = [
        m
        for m in checksum_mismatches
        if next(
            (
                a
                for a in applied_migrations
                if getattr(a, "script_name", None) == m["script"]
                and getattr(a, "type", None) != MigrationType.REPEATABLE
                and getattr(a, "type", None) != "REPEATABLE"
            ),
            None,
        )
    ]
    if versioned_mismatches:
        issues.append("Validation failed. Detected modified migration scripts.")


def check_repeatable_migrations(
    mv: "MigrationValidator",
    scripts: List[Migration],
    applied_migrations: List[Migration],
    result: "ValidationResult",
    command: str = "migrate",
) -> None:
    """Identify repeatable migrations that need to be reapplied.

    A repeatable migration is reapplied when its filesystem checksum
    differs from the last applied checksum or when the previous run
    failed (in which case we either re-record or surface the failure).
    """
    for script in scripts:
        if script.type != MigrationType.REPEATABLE:
            continue
        matching = [
            a for a in applied_migrations if getattr(a, "script_name", None) == script.script_name
        ]
        # Coerce None → 0 explicitly: ``getattr(..., default)`` only
        # returns the default when the attribute is missing, not when
        # the attribute exists and is None (e.g. corrupted history
        # row). Without ``or 0`` the lambda yields None and ``max``
        # raises ``TypeError`` comparing None to int.
        applied_script = max(
            matching,
            key=lambda a: getattr(a, "installed_rank", 0) or 0,
            default=None,
        )
        if applied_script:
            # Use migration rules to determine if migration was successful
            success_value = getattr(applied_script, "success", False)
            is_success = is_migration_success(success_value)

            if not is_success and getattr(applied_script, "execution_time", 0) > 0:
                if getattr(applied_script, "checksum", None) == script.checksum:
                    mv.log.debug(
                        f"[DEBUG] _check_repeatable_migrations: setting success=False "
                        f"for failed repeatable {script.script_name}"
                    )
                    result.success = False
                    error_msg = (
                        f"Repeatable migration {script.script_name} previously failed "
                        "and has not changed. Please fix the script before retrying."
                    )
                    if not result.error_message:
                        result.error_message = error_msg
                    else:
                        result.error_message += f"\n{error_msg}"
                    continue
                else:
                    mv.log.debug(
                        f"Repeatable migration {script.script_name} previously failed "
                        "but has changed; will be reapplied"
                    )
                    result.add_modified_repeatable(
                        script.script_name,
                        str(getattr(applied_script, "checksum", "")),
                        script.checksum if script.checksum is not None else 0,
                    )
                    continue
            script_changed = mv.script_manager.has_script_changed(
                script_name=script.script_name,
                applied_migrations=applied_migrations,
                script_path=script.path,
            )
            if script_changed:
                mv.log.debug(
                    f"Repeatable migration {script.script_name} was modified and will "
                    "be reapplied"
                )
                result.add_modified_repeatable(
                    script.script_name,
                    str(getattr(applied_script, "checksum", "")),
                    script.checksum if script.checksum is not None else 0,
                )
        else:
            mv.log.debug(f"Repeatable migration {script.script_name} has not been applied yet")
            result.add_modified_repeatable(
                script.script_name, "", script.checksum if script.checksum is not None else 0
            )
    if result.repeatable_migrations_to_reapply:
        first_time = [
            rep
            for rep in result.repeatable_migrations_to_reapply
            if not rep["database_checksum"]
        ]
        to_reapply = [
            rep
            for rep in result.repeatable_migrations_to_reapply
            if rep["database_checksum"]
        ]
        # Only show these messages for commands where they make sense (migrate and info)
        if command in ["migrate", "info"]:
            if first_time:
                mv.log.info(
                    f"Found {len(first_time)} pending repeatable migration(s)"
                )
            if to_reapply:
                mv.log.info(
                    f"Found {len(to_reapply)} repeatable migration(s) that need to be reapplied"
                )
        for rep in result.repeatable_migrations_to_reapply:
            if rep["database_checksum"]:
                mv.log.debug(
                    f"Repeatable migration {rep['script']} was modified: "
                    f"database checksum {rep['database_checksum']}, "
                    f"filesystem checksum {rep['filesystem_checksum']}"
                )
            else:
                mv.log.debug(
                    f"Repeatable migration {rep['script']} will be applied for the first time"
                )
