"""The missing-script rule: applied migrations whose script is gone from the catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Sequence, Set, Tuple

from dblift.core.migration._type_match import is_migration_type
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.scripting.migration_script_manager import (
    _successful_non_delete_records,
)


def is_delete_marker(row: Migration) -> bool:
    """Return True for the history row ``repair`` writes to record a script as deleted."""
    return is_migration_type(getattr(row, "type", None), MigrationType.DELETE)


def deleted_script_names(history: Sequence[Migration]) -> Set[str]:
    """Return the scripts that have a DELETE marker row."""
    return {getattr(row, "script_name", "") for row in history if is_delete_marker(row)}


def missing_applied(
    catalog: Sequence[Migration], history: Sequence[Migration]
) -> Tuple[Migration, ...]:
    """Return the applied migrations whose script is in neither the catalog nor its file names.

    ``validate``, ``migrate`` and ``repair`` all read this one rule. Each
    script is judged by its latest successful history row and listed once,
    in history order. A row recorded under a directory-qualified name matches
    the catalog by its file name, and a catalog script matches by its file
    name as well. Baseline and undo rows, audit rows, scripts that have a
    DELETE marker and scripts with no successful row are never missing.
    """
    present: Set[str] = set()
    for script in catalog:
        present.add(script.script_name)
        present.add(Path(script.script_name).name)
    deleted = deleted_script_names(history)

    # Latest successful row of each script, ordered by where that row sits in the history.
    latest: Dict[str, Migration] = {}
    for row in _successful_non_delete_records(history):
        script_name = getattr(row, "script_name", None)
        if script_name:
            latest.pop(script_name, None)
            latest[script_name] = row

    return tuple(
        row
        for script_name, row in latest.items()
        if not is_migration_type(getattr(row, "type", None), MigrationType.BASELINE)
        and str(getattr(row, "version", "")).lower() != "baseline"
        and script_name not in deleted
        and script_name not in present
        and Path(script_name).name not in present
    )
