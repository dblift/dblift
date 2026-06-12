"""
Migration analysis utilities.

This module contains utilities for analyzing migration states, detecting
patterns like undone versions, reapplied migrations, and out-of-order
executions.
"""

from typing import Any, Dict, List, Set

from core.logger import Log, NullLog
from core.migration._type_match import is_migration_type, is_versioned, migration_type_name
from core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration
from core.migration.version_utils import compare_versions as _compare_versions_shared
from core.migration.version_utils import (
    is_migration_success,
)


class MigrationAnalyzer:
    """Analyzes migration patterns and states."""

    def __init__(self, log: Log):
        """Initialize the migration analyzer.

        Args:
            log: Logger instance
        """
        self.log = log if log is not None else NullLog()

    def get_undone_versions(self, applied_migrations: List[Migration]) -> Set[str]:
        """Get versions that have been undone.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            set: Set of undone versions that have not been reapplied
        """
        undone_versions = set()

        # First, find all successful UNDO_SQL migrations
        successful_undos = {}
        for migration in applied_migrations:
            migration_type = getattr(migration, "type", None)
            success = getattr(migration, "success", None)
            version = getattr(migration, "version", None)

            is_undo_sql = is_migration_type(migration_type, "UNDO_SQL")

            if is_undo_sql and version and is_migration_success(success):
                undo_rank = getattr(migration, "installed_rank", 0)
                successful_undos[version] = undo_rank
                self.log.debug(f"Found undo operation for version: {version} (rank={undo_rank})")

        # For each undone version, check if it was reapplied after the undo
        for version, undo_rank in successful_undos.items():
            # Find the most recent successful SQL migration for this version
            most_recent_versioned_rank = 0
            for migration in applied_migrations:
                migration_type = getattr(migration, "type", None)
                success = getattr(migration, "success", None)
                migration_version = getattr(migration, "version", None)

                if (
                    is_versioned(migration_type)
                    and migration_version == version
                    and is_migration_success(success)
                ):
                    versioned_rank = getattr(migration, "installed_rank", 0)
                    if versioned_rank > most_recent_versioned_rank:
                        most_recent_versioned_rank = versioned_rank

            # Only mark as undone if the undo was more recent than the most recent versioned migration
            if undo_rank >= most_recent_versioned_rank:
                undone_versions.add(version)
                self.log.debug(
                    f"Version {version} is undone (undo_rank={undo_rank} >= versioned_rank={most_recent_versioned_rank})"
                )
            else:
                self.log.debug(
                    f"Version {version} was reapplied after undo (undo_rank={undo_rank} < versioned_rank={most_recent_versioned_rank})"
                )

        return undone_versions

    def get_reapplied_versions(self, applied_migrations: List[Migration]) -> Set[str]:
        """Get versions that have been reapplied (undone and then reapplied).

        Args:
            applied_migrations: List of applied migrations

        Returns:
            set: Set of reapplied versions
        """
        reapplied_versions = set()
        version_states: dict[str, list[str]] = {}  # Track state changes for each version

        # Sort migrations by installed_rank to process them in chronological order
        sorted_migrations = sorted(
            applied_migrations, key=lambda m: getattr(m, "installed_rank", 0) or 0
        )

        for migration in sorted_migrations:
            version = getattr(migration, "version", None)
            migration_type = getattr(migration, "type", None)
            success = getattr(migration, "success", None)

            if not version:
                continue

            # Track successful operations only
            if is_migration_success(success):
                if version not in version_states:
                    version_states[version] = []

                if migration_type is not None:
                    version_states[version].append(migration_type_name(migration_type))

        # Find versions that went through: SQL -> UNDO_SQL -> SQL
        for version, states in version_states.items():
            # Look for the pattern: applied, undone, reapplied
            versioned_count = sum(s in VERSIONED_SCRIPT_TYPES for s in states)
            undo_count = states.count("UNDO_SQL")

            # A version is reapplied if it has been applied multiple times
            # or has been undone and then applied again
            if versioned_count > 1 or (versioned_count >= 1 and undo_count >= 1):
                # Check if the sequence shows reapplication after undo
                last_versioned_index = -1
                last_undo_index = -1

                for i, state in enumerate(states):
                    if state in VERSIONED_SCRIPT_TYPES:
                        last_versioned_index = i
                    elif state == "UNDO_SQL":
                        last_undo_index = i

                # If there's a SQL after an UNDO_SQL, it's reapplied
                if last_undo_index >= 0 and last_versioned_index > last_undo_index:
                    reapplied_versions.add(version)
                    self.log.debug(f"Found reapplied version: {version}")

        return reapplied_versions

    def detect_out_of_order_migrations(
        self, versioned_migrations: List[Dict[str, Any]]
    ) -> Set[str]:
        """Detect migrations that were applied out of order.

        Args:
            versioned_migrations: List of versioned migration dictionaries
                                with 'version' and 'migration' keys

        Returns:
            set: Set of script names that were applied out of order
        """
        out_of_order_scripts: set[str] = set()

        if len(versioned_migrations) < 2:
            return out_of_order_scripts

        # Sort by the order they were applied (using installed_rank)
        migrations_by_rank = sorted(
            versioned_migrations, key=lambda m: getattr(m["migration"], "installed_rank", 0) or 0
        )

        # Check if versions are in ascending order
        for i in range(len(migrations_by_rank) - 1):
            current_version = migrations_by_rank[i]["version"]
            next_version = migrations_by_rank[i + 1]["version"]

            # Compare versions - if current > next, then next is out of order
            if _compare_versions_shared(current_version, next_version) > 0:
                out_of_order_script = migrations_by_rank[i + 1]["migration"].script_name
                out_of_order_scripts.add(out_of_order_script)
                self.log.debug(f"Detected out-of-order migration: {out_of_order_script}")

        return out_of_order_scripts

    def build_repeatable_checksums(self, applied_migrations: List[Migration]) -> Dict[str, str]:
        """Build a mapping of repeatable migration script names to their latest checksums.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            dict: Mapping of script names to their latest checksums
        """
        repeatable_checksums = {}

        # Filter for successful repeatable migrations
        repeatable_migrations = []
        for migration in applied_migrations:
            migration_type = getattr(migration, "type", None)
            success = getattr(migration, "success", None)

            if migration_type == "REPEATABLE" and is_migration_success(success):
                repeatable_migrations.append(migration)

        # Sort by installed_rank to process in chronological order
        repeatable_migrations.sort(key=lambda m: getattr(m, "installed_rank", 0) or 0, reverse=True)

        # Get the latest checksum for each repeatable script
        for migration in repeatable_migrations:
            script_name = migration.script_name
            checksum = getattr(migration, "checksum", None)

            if script_name and checksum and script_name not in repeatable_checksums:
                repeatable_checksums[script_name] = checksum

        return repeatable_checksums

    def sort_applied_migrations(self, applied_migrations: List[Migration]) -> List[Migration]:
        """Sort applied migrations by installed_rank.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            list: Sorted list of migrations
        """
        return sorted(applied_migrations, key=lambda m: getattr(m, "installed_rank", 0) or 0)

    def mark_reapplied_duplicates(
        self, sorted_applied_migrations: List[Migration], reapplied_versions: Set[str]
    ) -> Set[Migration]:
        """Mark duplicate migrations that should be kept for reapplication display.

        Args:
            sorted_applied_migrations: Migrations sorted by installed_rank
            reapplied_versions: Set of versions that have been reapplied

        Returns:
            set: Set of migration objects to keep as duplicates
        """
        keep_duplicates = set()
        script_occurrence_count = {}

        for migration in sorted_applied_migrations:
            script_name = migration.script_name
            version = getattr(migration, "version", None)

            if version and version in reapplied_versions:
                # Count occurrences of this script
                if script_name not in script_occurrence_count:
                    script_occurrence_count[script_name] = 0

                script_occurrence_count[script_name] += 1

                # Keep duplicates after the first occurrence
                if script_occurrence_count[script_name] > 1:
                    keep_duplicates.add(migration)

        return keep_duplicates
