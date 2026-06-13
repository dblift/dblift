"""
Main migration UI orchestrator.

This is the primary entry point for migration UI operations, now refactored
to use specialized components for better separation of concerns.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.logger import Log, NullLog
from core.migration.migration import Migration
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.state.migration_state import MigrationState

from .data_collector import MigrationDataCollector
from .display_formatters import DisplayFormatters
from .migration_analyzer import MigrationAnalyzer
from .table_renderer import TableRenderer


class MigrationUI:
    """Main UI class that orchestrates migration display operations."""

    def __init__(self, log: Log):
        """Initialize the migration UI.

        Args:
            log: Logger instance for display output
        """
        self.log = log if log is not None else NullLog()
        self.script_manager: Optional[MigrationScriptManager] = None
        self._target_version: Optional[str] = None

        # Initialize specialized components
        self.data_collector = MigrationDataCollector(log)
        self.display_formatters = DisplayFormatters(log)
        self.migration_analyzer = MigrationAnalyzer(log)
        self.table_renderer = TableRenderer(log)

    def get_migration_data(
        self,
        applied_migrations: Union[List[Migration], None] = None,
        pending_migrations: Optional[List[Migration]] = None,
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
        migration_state: Optional[MigrationState] = None,
        all_applied_migrations: Optional[List[Migration]] = None,
    ) -> List[Dict[str, Any]]:
        """Get structured migration data suitable for any formatter (console, HTML, JSON).

        Args:
            applied_migrations: List of applied migrations (legacy parameter, use migration_state instead)
            pending_migrations: List of pending migrations (optional, legacy parameter)
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude
            migration_state: MigrationState object (preferred, contains all state info)
            all_applied_migrations: All migrations from history in chronological order (required with migration_state)

        Returns:
            List of migration data dictionaries
        """
        # Set up script manager for data collector if needed
        if self.script_manager:
            self.data_collector.script_manager = self.script_manager

        # Use new signature if migration_state is provided
        if migration_state is not None and all_applied_migrations is not None:
            return self.data_collector.get_migration_data(
                migration_state=migration_state,
                all_applied_migrations=all_applied_migrations,
                scripts_dir=scripts_dir,
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )

        # Legacy signature for backward compatibility
        if applied_migrations is None:
            applied_migrations = []
        return self.data_collector.get_migration_data(
            applied_migrations=applied_migrations,
            pending_migrations=pending_migrations,
            scripts_dir=scripts_dir,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
        )

    def display_combined_migrations(
        self,
        applied_migrations: List[Migration],
        pending_migrations: Optional[List[Migration]] = None,
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
    ) -> None:
        """Display both applied and pending migrations in a single table.

        Args:
            applied_migrations: List of applied migrations
            pending_migrations: List of pending migrations (optional)
            scripts_dir: Directory containing migration scripts
            target_version: Optional target version to consider
            tags: Optional list of tags to filter migrations by (inclusion)
            exclude_tags: Optional list of tags to exclude from migrations
            versions: Optional list of versions to include
            exclude_versions: Optional list of versions to exclude
        """
        # Initialize script manager if needed
        if self.script_manager is None:
            logger = self.log
            self.script_manager = MigrationScriptManager(logger, "utf-8")  # Default encoding
            self.data_collector.script_manager = self.script_manager

        # Prepare empty list for pending migrations if None
        if pending_migrations is None:
            pending_migrations = []

        # Store target version for use in other methods
        self._target_version = target_version

        # Get structured migration data
        migrations_data = self.get_migration_data(
            applied_migrations=applied_migrations,
            pending_migrations=pending_migrations,
            scripts_dir=scripts_dir,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
        )

        self.table_renderer.print_migration_table(migrations_data)
        self.log.file_only_info(self.table_renderer.format_migration_table(migrations_data))

        # Store the structured data in the logger for formatters to use
        for log in getattr(self.log, "logs", [self.log]):
            setattr(log, "migration_data", migrations_data)

    def display_query_results(self, results: List[Dict[str, Any]]) -> None:
        """Display query results in a formatted table.

        Args:
            results: List of dictionaries representing query results
        """
        self.table_renderer.display_query_results(results)

    def display_migration_status(self, migration: Migration) -> None:
        """Display the status of a single migration.

        Args:
            migration: Migration object to display
        """
        self.table_renderer.display_migration_status(migration)

    def display_migration_details(self, migration: Migration) -> None:
        """Display detailed information about a migration.

        Args:
            migration: Migration object to display details for
        """
        self.table_renderer.display_migration_details(migration)

    def display_migration_info(
        self,
        applied_migrations: Union[List[Migration], None] = None,
        pending_migrations: Optional[List[Migration]] = None,
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
        migration_state: Optional[MigrationState] = None,
        all_applied_migrations: Optional[List[Migration]] = None,
    ) -> None:
        """Display comprehensive migration information.

        This is a higher-level method that combines data collection and display.

        Args:
            applied_migrations: List of applied migrations (legacy parameter, use migration_state instead)
            pending_migrations: List of pending migrations (optional, legacy parameter)
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude
            migration_state: MigrationState object (preferred, contains all state info)
            all_applied_migrations: All migrations from history in chronological order (required with migration_state)
        """
        # Get migration data
        migrations_data = self.get_migration_data(
            applied_migrations=applied_migrations,
            pending_migrations=pending_migrations,
            scripts_dir=scripts_dir,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            migration_state=migration_state,
            all_applied_migrations=all_applied_migrations,
        )

        # Display summary statistics
        # Handle both old uppercase and new capitalized formats
        total_applied = len(
            [
                m
                for m in migrations_data
                if m.get("state", "").upper() in ("SUCCESS", "APPLIED", "BASELINE")
            ]
        )
        total_pending = len([m for m in migrations_data if m.get("state", "").upper() == "PENDING"])
        total_failed = len([m for m in migrations_data if m.get("state", "").upper() == "FAILED"])

        stats = {
            "total_migrations": len(migrations_data),
            "applied_migrations": total_applied,
            "pending_migrations": total_pending,
            "failed_migrations": total_failed,
        }

        summary = self.table_renderer.format_summary_stats(stats)
        # Single emit through DbliftLogger covers both console and file sinks,
        # replacing the previous ``print(summary) + file_only_info(summary)`` pair.
        self.log.info(summary)

        # Display the migration table
        # For new signature, we need to get the data again for display_combined_migrations
        # which still uses the old signature
        if migration_state is not None and all_applied_migrations is not None:
            # Use the new data collector method directly
            migrations_data = self.data_collector.get_migration_data(
                migration_state=migration_state,
                all_applied_migrations=all_applied_migrations,
                scripts_dir=scripts_dir,
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )
            self.table_renderer.print_migration_table(migrations_data)
            self.log.file_only_info(self.table_renderer.format_migration_table(migrations_data))
            # Store the structured data in the logger for formatters to use
            for log in getattr(self.log, "logs", [self.log]):
                setattr(log, "migration_data", migrations_data)
        else:
            # Legacy path
            if applied_migrations is None:
                applied_migrations = []
            self.display_combined_migrations(
                applied_migrations=applied_migrations,
                pending_migrations=pending_migrations,
                scripts_dir=scripts_dir,
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )

    # Delegate formatting methods to display_formatters
    def _format_state(self, state: str) -> str:
        """Format migration state for display."""
        return self.display_formatters.format_state(state)

    def _format_category(self, category: str) -> str:
        """Format migration category for display."""
        return self.display_formatters.format_category(category)

    def _format_version(self, version: Optional[str]) -> str:
        """Format version string for display."""
        return self.display_formatters.format_version(version)

    def _get_category_and_display_type(self, m_type: str) -> Tuple[str, str]:
        """Get the category and display type for a migration type."""
        return self.display_formatters.get_category_and_display_type(m_type)

    def _determine_pending_migration_status(
        self,
        migration: Any,
        target_version: Optional[str] = None,
        current_version: Optional[str] = None,
        baseline_version: Optional[str] = None,
    ) -> str:
        """Determine the status of a pending migration."""
        return self.display_formatters.determine_pending_migration_status(
            migration, target_version, current_version, baseline_version
        )

    # Delegate analysis methods to migration_analyzer
    def _get_undone_versions(self, applied_migrations: List[Migration]) -> Set[str]:
        """Get versions that have been undone."""
        return self.migration_analyzer.get_undone_versions(applied_migrations)

    def _get_reapplied_versions(self, applied_migrations: List[Migration]) -> Set[str]:
        """Get versions that have been reapplied."""
        return self.migration_analyzer.get_reapplied_versions(applied_migrations)

    def _detect_out_of_order_migrations(
        self, versioned_migrations: List[Dict[str, Any]]
    ) -> Set[str]:
        """Detect migrations that were applied out of order."""
        return self.migration_analyzer.detect_out_of_order_migrations(versioned_migrations)

    def _build_repeatable_checksums(self, applied_migrations: List[Migration]) -> Dict[str, str]:
        """Build a mapping of repeatable migration script names to their latest checksums."""
        return self.migration_analyzer.build_repeatable_checksums(applied_migrations)

    def _sort_applied_migrations(self, applied_migrations: List[Migration]) -> List[Migration]:
        """Sort applied migrations by installed_rank."""
        return self.migration_analyzer.sort_applied_migrations(applied_migrations)

    def _mark_reapplied_duplicates(
        self, sorted_applied_migrations: List[Migration], reapplied_versions: Set[str]
    ) -> Set[Migration]:
        """Mark duplicate migrations that should be kept for reapplication display."""
        return self.migration_analyzer.mark_reapplied_duplicates(
            sorted_applied_migrations, reapplied_versions
        )

    # Helper methods that may be used by data collector
    def _find_undo_versions(self, scripts_dir: Optional[Path]) -> Set[str]:
        """Find versions that have undo scripts available."""
        return self.data_collector._find_undo_versions(scripts_dir)

    def _find_current_and_baseline_version(
        self, applied_migrations: List[Migration]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Find the current version and baseline version."""
        return self.data_collector._find_current_and_baseline_version(applied_migrations)

    def _collect_versioned_migrations(
        self, applied_migrations: List[Migration]
    ) -> List[Dict[str, Any]]:
        """Collect versioned migrations for analysis."""
        return self.data_collector._collect_versioned_migrations(applied_migrations)

    def _compare_versions(self, version1: Optional[str], version2: Optional[str]) -> int:
        """Compare two version strings."""
        return self.migration_analyzer._compare_versions(version1 or "", version2 or "")
