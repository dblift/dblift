"""Validation of ``--target-version`` / ``target_version`` against the scripts on disk."""

from functools import cmp_to_key
from pathlib import Path
from typing import Dict, List, Optional

from dblift.core.exceptions import InvalidTargetVersionError
from dblift.core.logger import Log
from dblift.core.migration.scripting.filename_parser import parse_migration_filename
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.version_utils import compare_versions


def available_versions(
    log: Log,
    scripts_dir: Path,
    recursive: bool = True,
    additional_dirs: Optional[List[Path]] = None,
    dir_recursive_map: Optional[Dict[Path, bool]] = None,
) -> List[str]:
    """Return the distinct versions of the migration scripts on disk, lowest first."""
    names = MigrationScriptManager(log).get_all_scripts(
        scripts_dir,
        recursive=recursive,
        additional_dirs=additional_dirs,
        dir_recursive_map=dir_recursive_map,
    )
    versions: List[str] = []
    for name in names:
        version = parse_migration_filename(Path(name).name).version
        if version and not any(compare_versions(version, seen) == 0 for seen in versions):
            versions.append(version)
    return sorted(versions, key=cmp_to_key(compare_versions))


def validate_target_version(
    target_version: Optional[str],
    versions: List[str],
    *,
    allow_zero: bool = False,
) -> None:
    """Raise :class:`InvalidTargetVersionError` unless *target_version* names a script version.

    ``None`` means no target and passes. Otherwise the value must equal, under
    the version comparison the migrator uses (``1`` equals ``1.0.0``, ``1_2``
    equals ``1.2``), the version of a script on disk. A leading ``V`` is not part
    of a version. ``allow_zero`` additionally accepts ``0`` ("before the first
    migration"), which ``undo`` documents.
    """
    if target_version is None:
        return
    value = str(target_version).strip()
    if allow_zero and value and compare_versions(value, "0") == 0 and value[0].isdigit():
        return
    if value and value[0].isdigit():
        if any(compare_versions(value, known) == 0 for known in versions):
            return
    raise InvalidTargetVersionError(str(target_version), versions)
