"""Migration rules — ordering/validation helpers shared across migration logic."""

from functools import cmp_to_key
from typing import Any, List, Optional, Tuple

from core.logger import Log
from core.migration._type_match import is_versioned
from core.migration.migration import Migration
from core.migration.state.rank_wins import latest_successful_ranks
from core.migration.version_utils import (
    compare_versions,
    is_migration_success,
)


class MigrationRules:
    """Migration business rules implementation - handles execution logic."""

    def __init__(self, logger: Log) -> None:
        """Initialize migration rules.

        Args:
            logger: Logger for logging events
        """
        self.logger = logger

    def is_success(self, migration: Any) -> bool:
        """Determine if a migration was successful using consistent logic.

        Args:
            migration: Migration object or any object with a 'success' attribute

        Returns:
            bool: True if the migration was successful, False otherwise
        """
        success_value = getattr(migration, "success", False)
        return is_migration_success(success_value)

    def should_undo_version(
        self, version: str, applied_migrations: List[Migration]
    ) -> Tuple[bool, str]:
        """Determine if a version should be undone.

        This checks if the version has already been undone and not reapplied,
        and provides guidance on which version to undo next if this one cannot be undone.

        Args:
            version: The version to check
            applied_migrations: List of applied migrations

        Returns:
            Tuple[bool, str]: (can_undo, message)
                - can_undo: True if the version can be undone, False otherwise
                - message: Empty string if can_undo is True, otherwise an error message
        """
        if not applied_migrations:
            return True, ""

        if not self._is_currently_undone(version, applied_migrations):
            return True, ""

        self.logger.warning(
            f"Version {version} has already been undone - cannot undo multiple times without reapplying"
        )

        next_version_to_undo = self._next_version_to_undo(version, applied_migrations)
        if next_version_to_undo:
            return (
                False,
                f"Version {version} has already been undone. Please specify version {next_version_to_undo} to undo it.",
            )
        return (
            False,
            f"Version {version} has already been undone and no other versions are available to undo.",
        )

    def _is_currently_undone(self, version: Any, applied_migrations: List[Migration]) -> bool:
        """Return True if `version` has an undo that no later re-apply supersedes.

        A version undone and then migrated again is applied, so it is undoable
        again; ranks decide which of the two happened last. Every versioned
        format counts as a re-apply — the history records versioned Python
        scripts as PYTHON, not SQL.
        """
        if version is None or version == "":
            return False
        state = latest_successful_ranks(applied_migrations).get(str(version))
        return bool(state and state.currently_undone)

    def _next_version_to_undo(
        self, version: Any, applied_migrations: List[Migration]
    ) -> Optional[Any]:
        """Return the highest still-applied version other than `version`, or None.

        Mirrors what ``undo`` without a target version would pick: successful
        versioned migrations, newest first by semantic version, skipping any
        version whose undo has not been superseded by a re-apply.
        """
        candidates: List[Any] = []
        seen = set()
        for m in applied_migrations:
            if not is_versioned(getattr(m, "type", None)):
                continue
            if not is_migration_success(getattr(m, "success", False)):
                continue
            m_version = getattr(m, "version", None)
            if m_version is None or m_version == version or str(m_version) in seen:
                continue
            seen.add(str(m_version))
            candidates.append(m_version)

        candidates.sort(
            key=cmp_to_key(lambda a, b: compare_versions(str(a), str(b))),
            reverse=True,
        )

        for candidate in candidates:
            if self._is_currently_undone(candidate, applied_migrations):
                continue
            self.logger.info(f"Found next version to undo: {candidate}")
            return candidate

        return None
