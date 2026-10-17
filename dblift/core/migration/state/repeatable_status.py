"""Repeatable migration status, decided once from each script's latest recorded run.

``migrate``, ``info`` and ``validate`` all need to know whether a repeatable
script is new, changed, unchanged or stuck on a failed run. The state manager
owns that answer; callers read it and do no comparison of their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from dblift.core.migration._type_match import is_migration_type
from dblift.core.migration.migration import Migration, MigrationType, normalize_migration_checksum
from dblift.core.migration.state.rank_wins import installed_rank
from dblift.core.migration.version_utils import is_migration_success


class RepeatableStatus(str, Enum):
    """Where a repeatable script stands relative to its latest recorded run."""

    NEW = "NEW"  # never run (exact name or file name)
    CHANGED = "CHANGED"  # latest run succeeded; checksum differs
    UNCHANGED = "UNCHANGED"  # latest run succeeded; same checksum
    FAILED_CHANGED = "FAILED_CHANGED"  # latest run failed; file changed since that run
    FAILED_UNCHANGED = "FAILED_UNCHANGED"  # latest run failed; same file as that run


PENDING_REPEATABLE_STATUSES = frozenset(
    {RepeatableStatus.NEW, RepeatableStatus.CHANGED, RepeatableStatus.FAILED_CHANGED}
)


@dataclass(frozen=True)
class RepeatableRun:
    """A repeatable script's status with the checksums it was decided from."""

    status: RepeatableStatus
    stored_checksum: Optional[int]  # checksum of the latest run's row (normalised); None for NEW
    current_checksum: Optional[int]  # normalised script checksum


def _repeatable_rows_by_name(history: Sequence[Any]) -> Dict[str, list]:
    rows: Dict[str, list] = {}
    for row in history:
        row_type = getattr(row, "type", None)
        if row_type is not None and not is_migration_type(row_type, MigrationType.REPEATABLE):
            continue
        # A row with no recorded outcome (NULL) is neither a success nor a failure.
        if getattr(row, "success", None) is None:
            continue
        name = getattr(row, "script_name", None)
        if name:
            rows.setdefault(name, []).append(row)
    return rows


def repeatable_runs(
    scripts: Sequence[Migration], history: Sequence[Migration]
) -> Dict[str, RepeatableRun]:
    """Map each repeatable script's ``script_name`` to its :class:`RepeatableRun`.

    A script matches history rows by exact ``script_name``, else by file name
    (rows written before directory-qualified names were dropped). Its latest
    run is the highest ``installed_rank`` among those rows, success or failure.
    """
    by_name = _repeatable_rows_by_name(history)
    by_basename: Dict[str, list] = {}
    for name, rows in by_name.items():
        by_basename.setdefault(Path(name).name, []).extend(rows)

    runs: Dict[str, RepeatableRun] = {}
    for script in scripts:
        if not is_migration_type(getattr(script, "type", None), MigrationType.REPEATABLE):
            continue
        name = script.script_name
        rows = by_name.get(name) or by_basename.get(Path(name).name) or []
        current = normalize_migration_checksum(getattr(script, "checksum", None))
        if not rows:
            runs[name] = RepeatableRun(RepeatableStatus.NEW, None, current)
            continue
        latest = max(rows, key=installed_rank)
        stored = normalize_migration_checksum(getattr(latest, "checksum", None))
        if not is_migration_success(getattr(latest, "success", None)):
            status = (
                RepeatableStatus.FAILED_CHANGED
                if current != stored
                else RepeatableStatus.FAILED_UNCHANGED
            )
        elif stored is not None and current is not None and stored != current:
            status = RepeatableStatus.CHANGED
        else:
            status = RepeatableStatus.UNCHANGED
        runs[name] = RepeatableRun(status, stored, current)
    return runs
