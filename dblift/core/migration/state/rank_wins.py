"""Latest successful undo vs versioned ranks per version.

Undo, reapply, and "is this version currently applied?" decisions all reduce
to the same comparison: for each version, take the highest successful
``installed_rank`` among versioned rows and among UNDO_SQL rows. The later
rank wins. Four call sites used to copy that loop with different success
predicates and rank defaults; they now call :func:`latest_successful_ranks`.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, NamedTuple, Optional

from dblift.core.migration._type_match import (
    is_migration_type,
    is_versioned,
    migration_type_name,
)
from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration, MigrationType
from dblift.core.migration.version_utils import is_migration_success


class VersionRankState(NamedTuple):
    """Latest successful versioned and undo ranks for one version.

    Missing ranks default to ``0`` (the same default migrate and the state
    manager already used). ``reapplied`` additionally requires that an undo
    actually exists, matching the data-service / state-manager copies.
    """

    versioned: int
    undo: int

    @property
    def currently_undone(self) -> bool:
        """True when the latest successful undo outranks any later versioned row."""
        return self.undo > self.versioned

    @property
    def reapplied(self) -> bool:
        """True when a successful undo exists and a later versioned row supersedes it."""
        return self.undo > 0 and self.versioned > self.undo


def installed_rank(row: Any) -> int:
    """Return ``installed_rank`` as int, treating missing/None as 0."""
    return int(getattr(row, "installed_rank", 0) or 0)


def latest_successful_ranks(rows: Iterable[Any]) -> Dict[str, VersionRankState]:
    """Map version string to latest successful versioned and undo ranks.

    Failed rows are ignored (``is_migration_success``). Only versioned script
    types and ``UNDO_SQL`` contribute. Versions are stringified so int ``1``
    and ``"1"`` collapse to the same key — the data-service / migrate copies
    already did this; the rules copy compared versions with ``!=`` and is
    aligned to the stringified form.
    """
    versioned: Dict[str, int] = {}
    undo: Dict[str, int] = {}
    for row in rows:
        version = getattr(row, "version", None)
        if version is None or version == "":
            continue
        if not is_migration_success(getattr(row, "success", False)):
            continue
        key = str(version)
        rank = installed_rank(row)
        mtype = getattr(row, "type", None)
        if is_migration_type(mtype, MigrationType.UNDO_SQL):
            undo[key] = max(undo.get(key, 0), rank)
        elif is_versioned(mtype):
            versioned[key] = max(versioned.get(key, 0), rank)
    keys = set(versioned) | set(undo)
    return {
        key: VersionRankState(versioned=versioned.get(key, 0), undo=undo.get(key, 0))
        for key in keys
    }


def effective_current_version(
    rows: Iterable[Migration], compare_versions: Callable[[str, str], int]
) -> Optional[str]:
    """Highest active successful versioned migration or baseline."""
    history = list(rows)
    ranks = latest_successful_ranks(history)
    # A legacy undo with no usable rank still deactivates its version unless
    # a ranked successful reapply supersedes it.
    undone = {
        str(row.version)
        for row in history
        if getattr(row, "version", None)
        and migration_type_name(getattr(row, "type", None)).upper() == "UNDO_SQL"
        and is_migration_success(getattr(row, "success", None))
    }
    inactive = {
        version for version in undone if not ranks.get(version, VersionRankState(0, 0)).reapplied
    }
    current = None
    for row in history:
        version = getattr(row, "version", None)
        if not version or not is_migration_success(getattr(row, "success", None)):
            continue
        kind = migration_type_name(getattr(row, "type", None))
        if kind != "BASELINE" and (kind not in VERSIONED_SCRIPT_TYPES or str(version) in inactive):
            continue
        candidate = str(version)
        if current is None or compare_versions(candidate, current) > 0:
            current = candidate
    return current
