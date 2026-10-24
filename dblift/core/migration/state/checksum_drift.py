"""Checksum drift between migration scripts on disk and the applied history.

``validate`` reports drift and ``repair`` fixes it. Both ask this module, so
``repair`` realigns exactly the scripts ``validate`` flags.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from dblift.core.migration._type_match import is_migration_type
from dblift.core.migration.migration import (
    Migration,
    MigrationType,
    normalize_migration_checksum,
)
from dblift.core.migration.scripting.migration_script_manager import (
    _successful_non_delete_records,
)

# Rows that carry no script content to compare.
_NO_CHECKSUM_TYPES = (
    MigrationType.UNKNOWN,
    MigrationType.DELETE,
    MigrationType.UNDO_SQL,
    MigrationType.BASELINE,
)


@dataclass(frozen=True)
class ChecksumDrift:
    """A script whose current checksum differs from the one recorded when it was applied."""

    script_name: str  # as recorded in history
    applied_checksum: Optional[int]  # normalised
    current_checksum: Optional[int]  # normalised
    repeatable: bool


def find_checksum_drift(
    scripts: Sequence[Migration], applied: Sequence[Migration]
) -> List[ChecksumDrift]:
    """Return the applied scripts whose checksum no longer matches the script on disk.

    The latest successful non-audit history row of each script is compared
    with the script, both checksums normalised. A missing checksum on either
    side counts as drift. A history row matches a script by its recorded name
    or, for rows written with a directory prefix, by its basename. History
    scripts that are missing or out of scope are not reported here. The result
    has one entry per script, in history order.
    """
    scripts_by_name: Dict[str, Migration] = {}
    for candidate in scripts:
        # When basenames are ambiguous the first script wins.
        scripts_by_name.setdefault(candidate.script_name, candidate)
    # One pass over the supplied history; the lookups below reuse this snapshot.
    rows = list(applied)
    latest_successful = {
        getattr(row, "script_name", None): row for row in _successful_non_delete_records(rows)
    }

    drift: List[ChecksumDrift] = []
    seen = set()
    for row in rows:
        script_name = getattr(row, "script_name", None)
        if not script_name or script_name in seen:
            continue
        if any(is_migration_type(getattr(row, "type", None), t) for t in _NO_CHECKSUM_TYPES):
            continue
        script = scripts_by_name.get(script_name)
        if script is None:
            script = scripts_by_name.get(Path(script_name).name)
        applied_record = latest_successful.get(script_name)
        if script is None or applied_record is None:
            continue
        seen.add(script_name)
        applied_checksum = normalize_migration_checksum(getattr(applied_record, "checksum", None))
        current_checksum = normalize_migration_checksum(getattr(script, "checksum", None))
        if (
            applied_checksum is None
            or current_checksum is None
            or applied_checksum != current_checksum
        ):
            drift.append(
                ChecksumDrift(
                    script_name=script_name,
                    applied_checksum=applied_checksum,
                    current_checksum=current_checksum,
                    repeatable=is_migration_type(
                        getattr(applied_record, "type", None), MigrationType.REPEATABLE
                    ),
                )
            )
    return drift
