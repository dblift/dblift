"""How a repair is recorded on its result: one list per kind, counters as their lengths."""

from typing import Any, Dict

from dblift.core.logger.results import MigrationInfo, RepairResult
from dblift.core.migration.state.migration_state import MigrationState

from .info_command import normalize_migration_info_status


def record_repair(
    result: RepairResult,
    kind: str,
    repair: Dict[str, Any],
    migration_state: MigrationState,
) -> None:
    """Add one repair to the result list for its kind and recount the counters.

    ``CHECKSUM_MISMATCH`` goes to ``aligned_migrations``, ``FAILED_MIGRATION``
    to ``removed_migrations`` and ``MISSING_SCRIPT`` to ``repaired_migrations``.
    The counters are the lengths of those lists, set here only.
    """
    targets = {
        "CHECKSUM_MISMATCH": result.add_aligned_migration,
        "FAILED_MIGRATION": result.add_removed_migration,
        "MISSING_SCRIPT": result.add_repaired_migration,
    }
    targets[kind](repair_info(repair, migration_state))
    result.checksums_fixed = len(result.aligned_migrations)
    result.failed_migrations_removed = len(result.removed_migrations)
    result.deleted_migrations_marked = len(result.repaired_migrations)


def repair_info(repair: Dict[str, Any], migration_state: MigrationState) -> MigrationInfo:
    """Describe the history row a repair targets, as it was before the repair."""
    script = str(repair.get("script", ""))
    entry = None
    # The latest history row for the script, a failed row taking precedence.
    for rows in (migration_state.applied, migration_state.failed):
        for candidate in rows:
            if candidate.script == script:
                entry = candidate
    # Only a MISSING_SCRIPT repair carries the type of the row it marks deleted.
    original_type = repair.get("original_type")
    fallback_type = original_type.name if original_type is not None else ""
    return MigrationInfo(
        script=script,
        version=getattr(entry, "version", None) or repair.get("version"),
        description=getattr(entry, "description", None) or repair.get("description") or "",
        type=getattr(entry, "type", None) or fallback_type or "SQL",
        status=normalize_migration_info_status(getattr(entry, "status", None)),
    )
