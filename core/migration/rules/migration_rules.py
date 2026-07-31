"""Migration rules — ordering/validation helpers shared across migration logic."""

from typing import Any, List, Tuple

from core.logger import Log
from core.migration._type_match import is_migration_type, is_versioned
from core.migration.migration import Migration, MigrationType
from core.migration.version_utils import (
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

    @staticmethod
    def _latest_ranks(version: Any, applied_migrations: List[Migration]) -> Tuple[int, int]:
        """Highest successful undo rank and versioned rank recorded for *version*.

        Every versioned type counts towards the versioned rank, not just
        ``SQL``: a document store has no SQL DDL, so all of its migrations are
        ``V*__*.py`` and are recorded as ``PYTHON``. Counting only ``SQL``
        leaves the versioned rank at 0, which makes the undo row look
        permanently newer than any later re-apply.
        """
        latest_undo_rank = 0
        latest_versioned_rank = 0

        for m in applied_migrations:
            if getattr(m, "version", None) != version:
                continue
            if not is_migration_success(getattr(m, "success", False)):
                continue

            m_type = getattr(m, "type", None)
            m_rank = getattr(m, "installed_rank", 0) or 0

            if is_migration_type(m_type, MigrationType.UNDO_SQL):
                latest_undo_rank = max(latest_undo_rank, m_rank)
            elif is_versioned(m_type):
                latest_versioned_rank = max(latest_versioned_rank, m_rank)

        return latest_undo_rank, latest_versioned_rank

    def _is_undone(self, version: Any, applied_migrations: List[Migration]) -> bool:
        """True when *version* was undone and has not been re-applied since.

        A re-apply supersedes the undo by recording the versioned migration
        again with a higher ``installed_rank`` — relational vendors insert a
        fresh history row, document stores rewrite the document with a new
        rank. Either way the ranks, not the mere presence of an undo row,
        decide whether the version is currently undone.
        """
        latest_undo_rank, latest_versioned_rank = self._latest_ranks(version, applied_migrations)
        return latest_undo_rank > 0 and latest_undo_rank > latest_versioned_rank

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

        if not self._is_undone(version, applied_migrations):
            return True, ""

        self.logger.warning(
            f"Version {version} has already been undone - cannot undo multiple times without reapplying"
        )

        # Find the next version to undo instead
        next_version_to_undo = None
        versioned_migrations = [
            m for m in applied_migrations if is_versioned(getattr(m, "type", None))
        ]
        # Sort by version in reverse order (newest first) for undo operations
        versioned_migrations.sort(key=lambda m: getattr(m, "version", "") or "", reverse=True)

        for v in versioned_migrations:
            v_version = getattr(v, "version", None)
            if v_version != version and not self._is_undone(v_version, applied_migrations):
                next_version_to_undo = v_version
                self.logger.info(f"Found next version to undo: {next_version_to_undo}")
                break

        if next_version_to_undo:
            return (
                False,
                f"Version {version} has already been undone. Please specify version {next_version_to_undo} to undo it.",
            )
        return (
            False,
            f"Version {version} has already been undone and no other versions are available to undo.",
        )
