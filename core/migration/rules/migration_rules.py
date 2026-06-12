"""Migration rules — status enums and ordering/validation helpers shared across migration logic."""

from enum import Enum
from typing import Any, List, Tuple

from core.logger import Log
from core.migration._type_match import is_migration_type
from core.migration.migration import Migration, MigrationType
from core.migration.version_utils import (
    is_migration_success,
)

# MigrationStatus is defined in this file (CoreMigrationStatus)
# No need to import it


class CoreMigrationStatus(Enum):
    """Core migration statuses for business logic."""

    SUCCESS = "SUCCESS"  # Migration was applied successfully
    FAILED = "FAILED"  # Migration failed during execution
    PENDING = "PENDING"  # Migration hasn't been applied yet
    BASELINE = "BASELINE"  # Migration established a baseline


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

        # Find all successful undo operations for this version
        successful_undo_count = 0
        successful_versioned_count = 0
        latest_undo_rank = 0
        latest_versioned_rank = 0

        for m in applied_migrations:
            m_type = getattr(m, "type", None)
            m_version = getattr(m, "version", None)
            if m_type is not None:
                from core.migration._type_match import migration_type_name

                m_type = migration_type_name(m_type)

            # Convert the success value to boolean
            m_success = getattr(m, "success", False)
            is_success = is_migration_success(m_success)

            if m_version == version:
                m_rank = getattr(m, "installed_rank", 0)

                if m_type == MigrationType.UNDO_SQL.name and is_success:
                    successful_undo_count += 1
                    if m_rank > latest_undo_rank:
                        latest_undo_rank = m_rank

                if m_type == MigrationType.SQL.name and is_success:
                    successful_versioned_count += 1
                    if m_rank > latest_versioned_rank:
                        latest_versioned_rank = m_rank

        # Skip if this version was already undone and not reapplied
        if successful_undo_count > 0 and latest_undo_rank > latest_versioned_rank:
            self.logger.warning(
                f"Version {version} has already been undone - cannot undo multiple times without reapplying"
            )

            # Find the next version to undo instead
            next_version_to_undo = None
            versioned_migrations = [
                m for m in applied_migrations if getattr(m, "type", None) == MigrationType.SQL.name
            ]
            # Sort by version in reverse order (newest first) for undo operations
            versioned_migrations.sort(key=lambda m: getattr(m, "version", "") or "", reverse=True)

            for v in versioned_migrations:
                v_version = getattr(v, "version", None)
                if v_version != version:
                    # Check if this version has been undone
                    is_undone = False
                    for m in applied_migrations:
                        m_type = getattr(m, "type", None)
                        m_version = getattr(m, "version", None)
                        if (
                            is_migration_type(m_type, MigrationType.UNDO_SQL)
                            and m_version == v_version
                        ):
                            is_undone = True
                            break

                    if not is_undone:
                        next_version_to_undo = v_version
                        self.logger.info(f"Found next version to undo: {next_version_to_undo}")
                        break

            if next_version_to_undo:
                return (
                    False,
                    f"Version {version} has already been undone. Please specify version {next_version_to_undo} to undo it.",
                )
            else:
                return (
                    False,
                    f"Version {version} has already been undone and no other versions are available to undo.",
                )

        return True, ""
