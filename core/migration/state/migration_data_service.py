"""
Migration data preparation service.

This module provides services for preparing and analyzing migration data
for display and processing purposes.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.logger import Log
from core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration
from core.migration.state.migration_state_service import MigrationStateService
from core.migration.state.rank_wins import latest_successful_ranks
from core.migration.version_utils import compare_versions as _compare_versions_shared
from core.migration.version_utils import is_migration_success


class MigrationDataService:
    """Service for preparing migration data for display and analysis."""

    def __init__(
        self, logger: Log, scripts_dir: Optional[Path] = None, target_version: Optional[str] = None
    ):
        """Initialize the migration data service.

        Args:
            logger: Logger instance
            scripts_dir: Directory containing migration scripts
            target_version: Target version for migrations
        """
        self.logger = logger
        self.scripts_dir = scripts_dir
        self.target_version = target_version
        self.state_service = MigrationStateService(logger)

    def _build_analysis_context(self, applied_migrations: List[Migration]) -> Dict[str, Any]:
        """Build context for migration state analysis.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            Dictionary containing analysis context
        """
        # Sort migrations by installed rank for analysis
        sorted_migrations = self._sort_applied_migrations(applied_migrations)

        # Build analysis data
        undone_versions = self._get_undone_versions(sorted_migrations)
        reapplied_versions = self._get_reapplied_versions(sorted_migrations)
        baseline_version = self._get_baseline_version(sorted_migrations)
        out_of_order_migrations = self._detect_out_of_order_migrations(sorted_migrations)
        current_version = self._get_current_version(sorted_migrations)

        return {
            "undone_versions": undone_versions,
            "reapplied_versions": reapplied_versions,
            "baseline_version": baseline_version,
            "out_of_order_migrations": out_of_order_migrations,
            "current_version": current_version,
            "target_version": self.target_version,
            "scripts_dir": self.scripts_dir,
        }

    def _get_undone_versions(self, migrations: List[Migration]) -> Set[str]:
        """Get set of versions that have been undone.

        Args:
            migrations: List of migrations to analyze

        Returns:
            Set of undone version strings
        """
        undone_versions = set()

        for migration in migrations:
            if self._get_migration_type(migration) == "UNDO_SQL":
                version = getattr(migration, "version", None)
                if version and self._is_migration_successful(migration):
                    undone_versions.add(str(version))

        return undone_versions

    def _get_reapplied_versions(self, migrations: List[Migration]) -> Set[str]:
        """Get set of versions that were reapplied after being undone.

        Args:
            migrations: List of migrations to analyze

        Returns:
            Set of reapplied version strings
        """
        ranks = latest_successful_ranks(migrations)
        return {version for version, state in ranks.items() if state.reapplied}

    def _is_version_reapplied(self, migrations: List[Migration], version: str) -> bool:
        """Check if a version was reapplied after being undone.

        Args:
            migrations: List of migrations
            version: Version to check

        Returns:
            bool: True if version was reapplied
        """
        state = latest_successful_ranks(migrations).get(str(version))
        return bool(state and state.reapplied)

    def _get_undo_rank(self, migrations: List[Migration], version: str) -> int:
        """Get the installed rank of the undo migration for a version.

        Args:
            migrations: List of migrations
            version: Version to find undo rank for

        Returns:
            int: Installed rank of undo migration, or -1 if not found
        """
        # A version can be undone more than once (undo, reapply, undo again),
        # so the latest undo -- not the first one found -- determines whether
        # a later reapply superseded it. Sentinel -1 matches the previous
        # helper contract when no successful undo exists.
        state = latest_successful_ranks(migrations).get(str(version))
        if state is None or state.undo <= 0:
            return -1
        return state.undo

    def _get_baseline_version(self, applied_migrations: List[Migration]) -> Optional[str]:
        """Get the baseline version from applied migrations.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            Optional[str]: Baseline version if found
        """
        for migration in applied_migrations:
            if self._get_migration_type(migration) == "BASELINE":
                return str(getattr(migration, "version", ""))
        return None

    def _detect_out_of_order_migrations(self, applied_migrations: List[Migration]) -> Set[str]:
        """Detect migrations that were applied out of order.

        Args:
            applied_migrations: List of applied migrations sorted by rank

        Returns:
            Set of version strings that were applied out of order
        """
        out_of_order = set()
        last_version: Optional[str] = None

        for migration in applied_migrations:
            if self._get_migration_type(migration) not in VERSIONED_SCRIPT_TYPES:
                continue

            version = str(getattr(migration, "version", ""))
            if not version:
                continue

            try:
                # Check if this version is lower than the previous one. Uses the
                # shared comparator: a local int-only parse scored every alpha
                # segment as 0, so a VB -> VA regression looked in-order.
                if last_version is not None and _compare_versions_shared(version, last_version) < 0:
                    out_of_order.add(version)

                last_version = version

            except Exception as e:
                self.logger.debug(f"Could not parse version for out-of-order detection: {e}")
                continue

        return out_of_order

    def _sort_applied_migrations(self, applied_migrations: List[Migration]) -> List[Migration]:
        """Sort applied migrations by installed rank.

        Args:
            applied_migrations: List of migrations to sort

        Returns:
            List of migrations sorted by installed rank
        """
        return sorted(applied_migrations, key=lambda m: getattr(m, "installed_rank", 0))

    def _get_migration_type(self, migration: Any) -> str:
        """Get the migration type as uppercase string.

        Args:
            migration: Migration object

        Returns:
            str: Migration type in uppercase
        """
        from core.migration._type_match import migration_type_name

        return migration_type_name(getattr(migration, "type", None)).upper()

    def _is_migration_successful(self, migration: Any) -> bool:
        """Check if a migration was successful.

        Args:
            migration: Migration object

        Returns:
            bool: True if migration was successful
        """
        success = getattr(migration, "success", None)
        return is_migration_success(success)

    def _get_current_version(self, applied_migrations: List[Migration]) -> Optional[str]:
        """Get the current version from successfully applied versioned migrations.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            Optional[str]: Current version if found
        """
        current_version = None

        for migration in applied_migrations:
            if self._get_migration_type(
                migration
            ) in VERSIONED_SCRIPT_TYPES and self._is_migration_successful(migration):
                version = str(getattr(migration, "version", ""))
                if version:
                    # Keep track of the highest version
                    if not current_version:
                        current_version = version
                    else:
                        try:
                            if self._compare_versions(version, current_version) > 0:
                                current_version = version
                        except Exception as e:
                            self.logger.debug(
                                f"Version comparison failed, using string fallback: {e}"
                            )
                            if version > current_version:
                                current_version = version

        return current_version

    def _compare_versions(self, version1: str, version2: str) -> int:
        """Compare two version strings. Delegates to shared compare_versions utility."""
        return _compare_versions_shared(version1, version2)
