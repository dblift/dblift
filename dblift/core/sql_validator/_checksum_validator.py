"""Checksum-drift validation using resolved scripts and indexed applied history."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Mapping, Optional, Sequence, cast

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import (  # noqa: F401
    _last_successful_non_delete_record,
    _successful_non_delete_records,
)
from dblift.core.migration.state.checksum_drift import ChecksumDrift, find_checksum_drift
from dblift.core.migration.state.repeatable_status import (
    RepeatableRun,
    RepeatableStatus,
    repeatable_runs,
)

if TYPE_CHECKING:
    from dblift.core.sql_validator.migration_validator import (
        MigrationValidator,
        ValidationResult,
    )


def validate_checksums(
    mv: "MigrationValidator",
    scripts: List[Migration],
    applied_migrations: List[Migration],
    result: "ValidationResult",
    issues: List[str],
    strict_mode: bool = False,
    all_scripts: Optional[List[Migration]] = None,
    drift: Optional[Sequence[ChecksumDrift]] = None,
) -> None:
    """Validate checksums of executed migrations.

    Compares each applied migration's stored checksum against the current
    file's checksum, flagging drift either as an error (versioned scripts)
    or a recorded reapply (repeatable scripts).

    ``scripts`` may be scoped by ``--tags``/``--versions`` filters; ``all_scripts``,
    when provided, is the full unfiltered set of on-disk scripts and is used only to
    decide whether an applied migration is genuinely missing from the migration
    directory (as opposed to merely filtered out of the current run's scope).

    ``drift`` is the state layer's answer for these ``scripts`` and
    ``applied_migrations``. When not given it is derived with the same
    ``find_checksum_drift`` rule.
    """
    checksum_mismatches = []
    scripts_by_name: dict[str, Migration] = {}
    scripts_by_version: dict[str, list[Migration]] = {}
    for script in scripts:
        # Existing lookup selects the first script when basenames are ambiguous.
        scripts_by_name.setdefault(script.script_name, script)
        if getattr(script, "version", None) is not None:
            scripts_by_version.setdefault(str(script.version), []).append(script)
    script_names = set(scripts_by_name)
    full_script_names = (
        {s.script_name for s in all_scripts} if all_scripts is not None else script_names
    )
    if drift is None:
        drift = find_checksum_drift(scripts, applied_migrations)
    drift_by_name = {d.script_name: d for d in drift}
    has_successful_row = {
        getattr(row, "script_name", None)
        for row in _successful_non_delete_records(applied_migrations)
    }
    deleted_scripts = set()
    non_repeatable_scripts = set()
    for row in applied_migrations:
        if getattr(row, "type", None) == MigrationType.DELETE:
            deleted_scripts.add(getattr(row, "script_name", None))
        if getattr(row, "type", None) not in (MigrationType.REPEATABLE, "REPEATABLE"):
            non_repeatable_scripts.add(getattr(row, "script_name", None))

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

        result.add_checked_script(script_name)

        if script_name not in full_script_names and (
            not script_name or Path(script_name).name not in full_script_names
        ):
            if migration_type != MigrationType.BASELINE and str(version_val).lower() != "baseline":
                # Check if this script has been marked as deleted
                is_deleted = script_name in deleted_scripts

                if not is_deleted:
                    # Check for a different script with the same version
                    same_version = [
                        s
                        for s in scripts_by_version.get(str(version_val), [])
                        if getattr(s, "script_name", None) != script_name
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
                        result.add_failed_script(script_name)
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
        if script_name not in has_successful_row:
            # Failed history is reported separately; there is no successful checksum.
            continue
        found = drift_by_name.get(script_name)
        if found is not None:
            current_checksum = found.current_checksum
            last_applied_checksum = found.applied_checksum
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
                    cast(str, script_name) in issue and "has been modified" in issue
                    for issue in issues
                ):
                    issues.append(error_message)
                result.add_failed_script(script_name)
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
        mismatch for mismatch in checksum_mismatches if mismatch["script"] in non_repeatable_scripts
    ]
    if versioned_mismatches:
        issues.append("Validation failed. Detected modified migration scripts.")


def _stored_text(run: RepeatableRun) -> str:
    return "" if run.stored_checksum is None else str(run.stored_checksum)


def check_repeatable_migrations(
    mv: "MigrationValidator",
    scripts: List[Migration],
    applied_migrations: List[Migration],
    result: "ValidationResult",
    command: str = "migrate",
    runs: Optional[Mapping[str, RepeatableRun]] = None,
) -> None:
    """Report repeatable migrations that will be reapplied, or are stuck on a failed run.

    The state layer decides each script's status (``runs``, or derived from
    ``applied_migrations`` when not given); this only turns it into validation
    output. A failed run whose file has not changed is an error; a new, changed
    or fixed-after-failure script is recorded as to be applied.
    """
    if runs is None:
        runs = repeatable_runs(scripts, applied_migrations)
    for script in scripts:
        if script.type != MigrationType.REPEATABLE:
            continue
        run = runs.get(script.script_name)
        if run is None:
            continue
        current = run.current_checksum if run.current_checksum is not None else 0
        if run.status is RepeatableStatus.FAILED_UNCHANGED:
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
        elif run.status is RepeatableStatus.NEW:
            mv.log.debug(f"Repeatable migration {script.script_name} has not been applied yet")
            result.add_modified_repeatable(script.script_name, "", current)
        elif run.status is RepeatableStatus.FAILED_CHANGED:
            mv.log.debug(
                f"Repeatable migration {script.script_name} previously failed "
                "but has changed; will be reapplied"
            )
            result.add_modified_repeatable(script.script_name, _stored_text(run), current)
        elif run.status is RepeatableStatus.CHANGED:
            mv.log.debug(
                f"Repeatable migration {script.script_name} was modified and will be reapplied"
            )
            result.add_modified_repeatable(script.script_name, _stored_text(run), current)
    if result.repeatable_migrations_to_reapply:
        first_time = [
            rep for rep in result.repeatable_migrations_to_reapply if not rep["database_checksum"]
        ]
        to_reapply = [
            rep for rep in result.repeatable_migrations_to_reapply if rep["database_checksum"]
        ]
        # Only show these messages for commands where they make sense (migrate and info)
        if command in ["migrate", "info"]:
            if first_time:
                mv.log.info(f"Found {len(first_time)} pending repeatable migration(s)")
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
