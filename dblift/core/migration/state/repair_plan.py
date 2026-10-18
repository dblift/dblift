"""Decide what ``repair`` would fix: checksum drift, missing scripts and failed rows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Set, Tuple, cast

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.migration_state import MigrationReadSnapshot, MigrationState

if TYPE_CHECKING:
    from dblift.core.migration.state.migration_state_manager import MigrationStateManager


class RepairSafetyError(Exception):
    """Raised when a repair operation would make a dangerous bulk change.

    Specifically: when the scripts directory is empty (or unreadable) but
    the history table has applied migrations that would all be converted
    to DELETE entries. Almost always a misconfigured ``--scripts`` or an
    operator pointing at the wrong repo — silently marking every applied
    migration as deleted is not a recoverable mistake, so the command
    refuses and asks the operator to confirm the directory.
    """


@dataclass(frozen=True)
class RepairAction:
    """One history fix ``repair`` would make.

    ``kind`` is ``CHECKSUM_MISMATCH``, ``MISSING_SCRIPT`` or ``FAILED_MIGRATION``,
    after failed-row routing: a checksum repair on a failed row is a
    ``FAILED_MIGRATION``. ``details`` is the detected repair as found, so its
    ``type`` is the detected kind, before routing.
    """

    kind: str
    script: str
    details: Mapping[str, Any]


@dataclass(frozen=True)
class RepairPlan:
    """What ``repair`` would fix: the state it was read from and the ordered actions."""

    state: MigrationState
    actions: Tuple[RepairAction, ...]


def _count_candidate_missing(applied_migrations: Any, deleted_scripts: Set[str]) -> int:
    """Count applied migrations that would be flagged MISSING_SCRIPT.

    Mirrors the filter the main loop applies: skip DELETE-type entries and
    scripts already recorded as deleted. Used by the empty-filesystem
    safety gate so the error message reports the number of rows the user
    is being protected from.
    """
    count = 0
    for applied in applied_migrations:
        script_name = applied.script_name
        if not script_name:
            continue
        # type read defensively: history rows may carry an enum or a legacy string.
        migration_type = getattr(applied, "type", None)
        if (
            migration_type
            and hasattr(migration_type, "name")
            and migration_type.name
            in (
                "DELETE",
                "BASELINE",
            )
        ):
            continue
        if isinstance(migration_type, str) and migration_type.upper() in ("DELETE", "BASELINE"):
            continue
        if script_name in deleted_scripts:
            continue
        count += 1
    return count


def plan_repairs(
    state_manager: MigrationStateManager,
    scripts_dir: Path,
    *,
    recursive: bool,
    additional_dirs: Optional[List[Path]],
    dir_recursive_map: Optional[Dict[Path, bool]],
    read_snapshot: Optional[MigrationReadSnapshot] = None,
) -> RepairPlan:
    """Read the state and decide every repair, routing failed rows.

    A checksum repair on a failed row becomes a ``FAILED_MIGRATION``, and a
    failed row is removed once. Raises ``RepairSafetyError`` when the scripts
    directory holds no scripts but the history has migrations that would all be
    marked missing, and propagates whatever error reading the history or the
    scripts raises.
    """
    state = state_manager.build_state(
        scripts_dir,
        recursive=recursive,
        additional_dirs=additional_dirs,
        dir_recursive_map=dir_recursive_map,
        read_snapshot=read_snapshot,
    )

    repairs: List[Dict[str, Any]] = []
    repairs.extend(_detect_checksum_changes(state))
    repairs.extend(_detect_missing_migrations(state, scripts_dir))
    repairs.extend(_detect_checksum_drift(state, repairs))

    actions: List[RepairAction] = []
    removed: Set[str] = set()
    for repair in repairs:
        script = str(repair.get("script", ""))
        kind = repair["type"]
        # A checksum repair on a failed row deletes the row instead of realigning it.
        if kind == "CHECKSUM_MISMATCH" and _is_failed_migration(script, state):
            kind = "FAILED_MIGRATION"
        if kind == "FAILED_MIGRATION":
            if script in removed:
                continue
            removed.add(script)
        actions.append(RepairAction(kind=kind, script=script, details=repair))
    return RepairPlan(state=state, actions=tuple(actions))


def _detect_checksum_changes(migration_state: MigrationState) -> List[Dict[str, Any]]:
    """Build repair entries for checksum changes reported by the state manager.

    Args:
        migration_state: Current migration state

    Returns:
        List of CHECKSUM_MISMATCH repair dicts from state manager
    """
    repairs: List[Dict[str, Any]] = []
    for change in migration_state.checksum_changes:
        repairs.append(
            {
                "type": "CHECKSUM_MISMATCH",
                "script": change.script_name,
                "old_checksum": change.previous_checksum,
                "new_checksum": change.current_checksum,
            }
        )
    return repairs


def _detect_missing_migrations(
    migration_state: MigrationState, scripts_dir: Path
) -> List[Dict[str, Any]]:
    """Detect missing migrations (applied but script file no longer exists) and failed migrations.

    Args:
        migration_state: Current migration state, built with a scripts directory
        scripts_dir: Directory containing migration scripts (named in the safety error)

    Returns:
        List of MISSING_SCRIPT and FAILED_MIGRATION repair dicts
    """
    repairs: List[Dict[str, Any]] = []

    applied_migrations = migration_state.applied_objects
    deleted_scripts: Set[str] = set(migration_state.deleted_scripts)

    # Reuse the catalog the state was built with. A load failure (permission
    # denied, missing directory not caught by the CLI layer, malformed script)
    # already propagated from ``build_state`` — silently falling back to an
    # empty set turned this into a mass-mark-missing footgun. The CLI has
    # already verified that the directory exists for every command except
    # ``baseline``; anything that raises is the operator's to fix before
    # repair can proceed safely.
    # plan_repairs always builds the state with a scripts directory, so the catalog is set.
    filesystem_migrations = cast(
        Dict[MigrationType, List[Migration]], migration_state.grouped_objects
    )
    filesystem_scripts: Set[str] = set()
    for migration_group in filesystem_migrations.values():
        for migration in migration_group:
            filesystem_scripts.add(migration.script_name)

    # Safety gate: if the filesystem produced zero scripts but the
    # history has applied migrations that would all be marked MISSING,
    # refuse — this is almost always a misconfigured ``--scripts`` or
    # empty default ``./migrations`` directory. Without this
    # guard, a single ``repair`` invocation without ``--dry-run`` would
    # convert every applied migration into a DELETE entry.
    if not filesystem_scripts:
        candidate_missing_count = _count_candidate_missing(applied_migrations, deleted_scripts)
        if candidate_missing_count > 0:
            raise RepairSafetyError(
                f"Refusing to mark {candidate_missing_count} applied migration(s) "
                f"as missing: no migration scripts found in {scripts_dir}. "
                "Pass --scripts <dir> pointing to your migration files, or "
                "verify that the configured directory contains at least one "
                "matching file before retrying."
            )

    # Find migrations in history but not in filesystem
    for applied in applied_migrations:
        script_name = applied.script_name
        if not script_name:
            continue

        # type read defensively: history rows may carry an enum or a legacy string.
        migration_type = getattr(applied, "type", None)

        # Skip DELETE and BASELINE type migrations. BASELINE rows (e.g. the
        # synthetic ``B2__.sql`` marker written by ``baseline``) never have
        # a matching filesystem script by design — flagging them as missing
        # produces noisy false positives and, worse, a subsequent repair
        # would rewrite history to delete them.
        if (
            migration_type
            and hasattr(migration_type, "name")
            and migration_type.name in ("DELETE", "BASELINE")
        ):
            continue
        if isinstance(migration_type, str) and migration_type.upper() in (
            "DELETE",
            "BASELINE",
        ):
            continue

        # Skip if already marked as deleted (has DELETE entry)
        if script_name in deleted_scripts:
            continue

        # If the script is not in filesystem, add to repairs. A row recorded
        # with a directory prefix still matches its script by basename, as
        # ``validate`` matches it.
        if script_name not in filesystem_scripts and Path(script_name).name not in (
            filesystem_scripts
        ):
            repairs.append(
                {
                    "type": "MISSING_SCRIPT",
                    "script": script_name,
                    "version": applied.version,
                    "description": applied.description,
                    "original_type": migration_type,  # Preserve original type
                }
            )

    # Check for failed migrations that need to be cleaned up
    for failed_migration in migration_state.failed_objects:
        script_name = failed_migration.script_name
        if script_name:
            repairs.append(
                {
                    "type": "FAILED_MIGRATION",
                    "script": script_name,
                    "version": failed_migration.version,
                    "description": failed_migration.description,
                }
            )

    return repairs


def _detect_checksum_drift(
    migration_state: MigrationState, existing_repairs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Detect checksum drift for applied versioned migrations not already in repairs.

    MigrationState currently only tracks repeatable checksum changes; the
    versioned drift in every script format is read from
    ``migration_state.checksum_drift``, the same answer ``validate`` reports.

    Args:
        migration_state: Current migration state, built with a scripts directory
        existing_repairs: Already-collected repair dicts (to avoid duplicates)

    Returns:
        List of additional CHECKSUM_MISMATCH repair dicts
    """
    repairs: List[Dict[str, Any]] = []

    already_recorded_scripts = {entry["script"] for entry in existing_repairs if "script" in entry}

    # The same drift ``validate`` reports, computed over every applied row
    # (undone ones included). Repeatable drift is handled by the repeatable
    # checksum-change scan, not here.
    for drift in migration_state.checksum_drift:
        if (
            drift.repeatable
            or drift.current_checksum is None
            or drift.script_name in already_recorded_scripts
        ):
            continue
        repairs.append(
            {
                "type": "CHECKSUM_MISMATCH",
                "script": drift.script_name,
                "old_checksum": drift.applied_checksum,
                "new_checksum": drift.current_checksum,
            }
        )
        already_recorded_scripts.add(drift.script_name)

    return repairs


def _is_failed_migration(script: str, migration_state: Any) -> bool:
    """Return True if `script` is in the failed_objects set of `migration_state`."""
    if not script or migration_state is None:
        return False
    for failed in migration_state.failed_objects:
        if failed.script_name == script:
            return True
    return False
