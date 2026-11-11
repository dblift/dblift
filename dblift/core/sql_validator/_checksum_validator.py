"""Checksum-drift validation using resolved scripts and indexed applied history."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Sequence, Set, cast

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import (  # noqa: F401
    _last_successful_non_delete_record,
    _successful_non_delete_records,
)
from dblift.core.migration.state.checksum_drift import ChecksumDrift
from dblift.core.migration.state.missing_scripts import is_delete_marker
from dblift.core.migration.state.repeatable_status import (
    RepeatableRun,
    RepeatableStatus,
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
    *,
    drift: Sequence[ChecksumDrift],
    missing: Sequence[Migration],
) -> None:
    """Validate checksums of executed migrations.

    Compares each applied migration's stored checksum against the current
    file's checksum, flagging drift either as an error (versioned scripts)
    or a recorded reapply (repeatable scripts).

    ``scripts`` may be scoped by ``--tags``/``--versions`` filters; an applied
    migration that is absent from them is skipped as out of scope unless it is
    in ``missing``.

    ``drift`` and ``missing`` are the state layer's answers for these
    ``scripts`` and ``applied_migrations``: the scripts whose checksum changed
    and the applied scripts that are gone from the migration directory.
    """
    index = _index_inputs(scripts, applied_migrations, drift, missing)
    checksum_mismatches: List[Dict[str, object]] = []
    reported_missing = set()
    for applied in applied_migrations:
        script_name = getattr(applied, "script_name", None)
        migration_type = getattr(applied, "type", None)

        if _exempt_from_drift(migration_type):
            continue

        result.add_checked_script(script_name)

        missing_row = index.missing_by_name.get(script_name)
        if missing_row is not None:
            if script_name not in reported_missing:
                reported_missing.add(script_name)
                _report_missing(mv, script_name, missing_row, index, result, issues, strict_mode)
            continue
        if _skips_drift_check(mv, script_name, migration_type, index):
            continue
        _check_drift(mv, script_name, migration_type, index, result, issues, checksum_mismatches)

    # Only add validation failure for versioned scripts with checksum mismatches
    versioned_mismatches = [
        mismatch
        for mismatch in checksum_mismatches
        if mismatch["script"] in index.non_repeatable_scripts
    ]
    if versioned_mismatches:
        issues.append("Validation failed. Detected modified migration scripts.")


@dataclass
class _Index:
    """The lookups ``validate_checksums`` reads, built once from its inputs."""

    # Scripts with a version, by ``str(version)``, in the order supplied.
    scripts_by_version: Dict[str, List[Migration]]
    # The script names of ``scripts``.
    script_names: Set[str]
    drift_by_name: Dict[str, ChecksumDrift]
    missing_by_name: Dict[Optional[str], Migration]
    # Script names with a successful row that is neither a delete marker nor an undo.
    has_successful_row: Set[Optional[str]]
    # Script names with a delete marker row.
    deleted_scripts: Set[Optional[str]]
    # Script names with a row whose type is not repeatable.
    non_repeatable_scripts: Set[Optional[str]]


def _index_inputs(
    scripts: List[Migration],
    applied_migrations: List[Migration],
    drift: Sequence[ChecksumDrift],
    missing: Sequence[Migration],
) -> _Index:
    """Return the lookups over the inputs, reading ``scripts``, ``drift`` and ``missing`` once
    each and ``applied_migrations`` twice."""
    scripts_by_name: dict[str, Migration] = {}
    scripts_by_version: dict[str, list[Migration]] = {}
    for script in scripts:
        # Existing lookup selects the first script when basenames are ambiguous.
        scripts_by_name.setdefault(script.script_name, script)
        if getattr(script, "version", None) is not None:
            scripts_by_version.setdefault(str(script.version), []).append(script)
    script_names = set(scripts_by_name)
    drift_by_name = {d.script_name: d for d in drift}
    missing_by_name = {getattr(row, "script_name", None): row for row in missing}
    has_successful_row = {
        getattr(row, "script_name", None)
        for row in _successful_non_delete_records(applied_migrations)
    }
    deleted_scripts = set()
    non_repeatable_scripts = set()
    for row in applied_migrations:
        if is_delete_marker(row):
            deleted_scripts.add(getattr(row, "script_name", None))
        if getattr(row, "type", None) not in (MigrationType.REPEATABLE, "REPEATABLE"):
            non_repeatable_scripts.add(getattr(row, "script_name", None))
    return _Index(
        scripts_by_version,
        script_names,
        drift_by_name,
        missing_by_name,
        has_successful_row,
        deleted_scripts,
        non_repeatable_scripts,
    )


def _exempt_from_drift(migration_type: object) -> bool:
    """Return True for a history row type with no script checksum to compare, else False.

    Exempt are the UNKNOWN, DELETE, UNDO_SQL and BASELINE members and the string ``"UNDO_SQL"``;
    other string spellings are not exempt.
    """
    # Skip types that have no stored checksum or are exempt from drift detection.
    # Inverted guard: only skip UNKNOWN, DELETE, and BASELINE (no script to compare).
    # PYTHON is intentionally included — it has a checksum stored at apply time.
    if migration_type in (
        MigrationType.UNKNOWN,
        MigrationType.DELETE,
        MigrationType.UNDO_SQL,
        MigrationType.BASELINE,
    ):
        return True
    if migration_type == "UNDO_SQL":
        return True
    if migration_type == MigrationType.BASELINE:
        return True
    return False


def _report_missing(
    mv: "MigrationValidator",
    script_name: Optional[str],
    missing_row: Migration,
    index: _Index,
    result: "ValidationResult",
    issues: List[str],
    strict_mode: bool,
) -> None:
    """Report an applied migration missing from the migration directory.

    Returns None. The message names any other script with the same version. In strict mode it
    is appended to *issues* and the script recorded as failed; otherwise it is logged as a
    warning.
    """
    # Check for a different script with the same version
    same_version = [
        s
        for s in index.scripts_by_version.get(str(getattr(missing_row, "version", "")), [])
        if getattr(s, "script_name", None) != script_name
    ]
    if same_version:
        alt_names = ", ".join(getattr(s, "script_name", str(s)) for s in same_version)
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


def _skips_drift_check(
    mv: "MigrationValidator",
    script_name: Optional[str],
    migration_type: object,
    index: _Index,
) -> bool:
    """Return True, after logging why at debug level when there is a reason to give, for an
    applied migration whose checksum is not compared: its script is not among the scripts (marked
    deleted, or out of scope for the run's filters), it is a baseline, or it has no successful
    row (no reason logged). Return False when its checksum is compared."""
    if script_name not in index.script_names and (
        not script_name or Path(script_name).name not in index.script_names
    ):
        if script_name in index.deleted_scripts:
            # Script is missing but marked as deleted - this is OK
            mv.log.debug(
                f"Migration '{script_name}' is missing from filesystem but "
                "marked as deleted - OK"
            )
        else:
            # Present on disk but filtered out of scope by --tags/--versions - not missing.
            mv.log.debug(
                f"Migration '{script_name}' is out of scope for this run's filters - skipping"
            )
        return True
    if migration_type == MigrationType.BASELINE:
        mv.log.debug(f"Skipping checksum verification for {script_name} (baseline)")
        return True
    if script_name not in index.has_successful_row:
        # Failed history is reported separately; there is no successful checksum.
        return True
    return False


def _check_drift(
    mv: "MigrationValidator",
    script_name: Optional[str],
    migration_type: object,
    index: _Index,
    result: "ValidationResult",
    issues: List[str],
    checksum_mismatches: List[Dict[str, object]],
) -> None:
    """Compare one applied migration's checksum with its script's.

    Returns None. Without drift, logs that verification passed. With drift, appends the
    mismatch to *checksum_mismatches*; a non-repeatable migration then gets an issue (unless one
    already says the script has been modified) and is recorded as failed, while a repeatable
    one is only logged at debug level as to be reapplied.
    """
    found = index.drift_by_name.get(cast(str, script_name))
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
                cast(str, script_name) in issue and "has been modified" in issue for issue in issues
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


def _stored_text(run: RepeatableRun) -> str:
    return "" if run.stored_checksum is None else str(run.stored_checksum)


def check_repeatable_migrations(
    mv: "MigrationValidator",
    scripts: List[Migration],
    applied_migrations: List[Migration],
    result: "ValidationResult",
    command: str = "migrate",
    *,
    runs: Mapping[str, RepeatableRun],
) -> None:
    """Report repeatable migrations that will be reapplied, or are stuck on a failed run.

    The state layer decides each script's status (``runs``); this only turns
    it into validation output. A failed run whose file has not changed is an error; a new, changed
    or fixed-after-failure script is recorded as to be applied.
    """
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
