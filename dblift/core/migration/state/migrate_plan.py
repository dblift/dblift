"""Select what ``migrate`` would run, and check it against the strict-ordering rule."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple

from dblift.core.migration.migration import Migration
from dblift.core.migration.state.migration_state import MigrationReadSnapshot, MigrationState
from dblift.core.migration.state.ordering import out_of_order

if TYPE_CHECKING:
    from dblift.core.migration.state.migration_state_manager import MigrationStateManager


class StrictModeError(ValueError):
    """Raised by migrate when ``strict_mode=True`` and an out-of-order
    executable pending migration is selected. Subclasses :class:`ValueError` so
    callers that haven't migrated to the narrower type still catch it,
    but lets ``MigrateCommand`` distinguish strict-mode violations from
    arbitrary :class:`ValueError` instances raised elsewhere in the
    migrate flow (PR #241 Bugbot).

    ``current_version`` is the schema version the violation was measured against."""

    def __init__(self, message: str, current_version: Optional[str] = None) -> None:
        """Keep the bare message and remember the current schema version."""
        super().__init__(message)
        self.current_version = current_version


@dataclass(frozen=True)
class MigratePlan:
    """What ``migrate`` would run: the state it was read from and the selected migrations."""

    state: MigrationState
    current_version: Optional[str]
    pending: Tuple[Migration, ...]


def plan_migrate(
    state_manager: MigrationStateManager,
    scripts_dir: Optional[Path],
    *,
    recursive: bool,
    additional_dirs: Optional[Sequence[Path]],
    dir_recursive_map: Optional[Dict[Path, bool]],
    target_version: Optional[str],
    tags: Optional[Sequence[str]],
    exclude_tags: Optional[Sequence[str]],
    versions: Optional[Sequence[str]],
    exclude_versions: Optional[Sequence[str]],
    strict_mode: bool,
    read_snapshot: Optional[MigrationReadSnapshot] = None,
) -> MigratePlan:
    """Read the state through ``read_snapshot`` and select what migrate would run.

    The catalog is unfiltered; migrate selects the executable pending objects,
    then applies the tag and version filters. ``target_version`` is label
    context only. Out-of-order selections raise :class:`StrictModeError` in
    strict mode and log a warning otherwise.
    """
    state = state_manager.build_state(
        scripts_dir,
        recursive=recursive,
        additional_dirs=additional_dirs,
        dir_recursive_map=dir_recursive_map,
        target_version=target_version,
        read_snapshot=read_snapshot,
    )
    current = state_manager.get_current_version(state.applied_objects)
    selected = state_manager.apply_filters_to_migrations(
        state.executable_pending_objects(),
        tags=tags,
        exclude_tags=exclude_tags,
        versions=versions,
        exclude_versions=exclude_versions,
    )
    _enforce_strict_ordering(state_manager, selected, current, strict_mode)
    return MigratePlan(state=state, current_version=current, pending=tuple(selected))


def _enforce_strict_ordering(
    state_manager: MigrationStateManager,
    migrations: Sequence[Migration],
    current_version: Optional[str],
    strict_mode: bool,
) -> None:
    """Raise or warn when executable pending is out of version order."""
    for entry in out_of_order(migrations, current_version):
        migration = entry.migration
        version = migration.version
        script_name = getattr(migration, "script_name", "")
        if strict_mode:
            raise StrictModeError(
                f"Strict mode: out-of-order migration {script_name} "
                f"(version {version} <= current version {current_version}). "
                f"Renumber the script above {current_version} or run "
                f"without --strict to apply it anyway.",
                current_version,
            )
        state_manager.logger.warning(
            f"Out-of-order migration {script_name} "
            f"(version {version} <= current version {current_version}). "
            f"Applying anyway; use --strict to enforce strict ordering."
        )
