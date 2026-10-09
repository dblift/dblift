"""How a repair is recorded on its result: one list per kind, counters as their lengths."""

from typing import Any, Dict

from dblift.core.logger.results import MigrationInfo, RepairResult

from .info_command import normalize_migration_info_status


def record_repair(
    result: RepairResult,
    kind: str,
    repair: Dict[str, Any],
    migration_state: Any = None,
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


def repair_info(repair: Dict[str, Any], migration_state: Any) -> MigrationInfo:
    """Describe the history row a repair targets, as it was before the repair."""
    script = str(repair.get("script", ""))
    entry = None
    # The latest history row for the script, a failed row taking precedence.
    for rows in (
        getattr(migration_state, "applied", None),
        getattr(migration_state, "failed", None),
    ):
        for candidate in rows if isinstance(rows, list) else []:
            if getattr(candidate, "script", None) == script:
                entry = candidate
    original_type = repair.get("original_type")
    # An enum names its member; a plain string is kept as it is.
    fallback_type = getattr(original_type, "name", None) or (
        original_type if isinstance(original_type, str) else ""
    )
    return MigrationInfo(
        script=script,
        version=getattr(entry, "version", None) or repair.get("version"),
        description=getattr(entry, "description", None) or repair.get("description") or "",
        type=getattr(entry, "type", None) or fallback_type or "SQL",
        status=normalize_migration_info_status(getattr(entry, "status", None)),
    )
