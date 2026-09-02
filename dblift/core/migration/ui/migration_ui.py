"""
Main migration UI orchestrator.

This is the primary entry point for migration UI operations, now refactored
to use specialized components for better separation of concerns.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from dblift.core.logger import Log, NullLog
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.state.migration_state import MigrationState

from .data_collector import MigrationDataCollector
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

        # Initialize specialized components
        self.data_collector = MigrationDataCollector(log)
        self.table_renderer = TableRenderer(log)

    def get_migration_data(
        self,
        migration_state: MigrationState,
        all_applied_migrations: List[Migration],
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get structured migration data suitable for any formatter (console, HTML, JSON).

        Args:
            migration_state: MigrationState object (contains all state info)
            all_applied_migrations: All migrations from history in chronological order
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude

        Returns:
            List of migration data dictionaries
        """
        # Set up script manager for data collector if needed
        if self.script_manager:
            self.data_collector.script_manager = self.script_manager

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

    def display_migration_info(
        self,
        migration_state: MigrationState,
        all_applied_migrations: List[Migration],
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
    ) -> None:
        """Display comprehensive migration information.

        This is a higher-level method that combines data collection and display.

        Args:
            migration_state: MigrationState object (contains all state info)
            all_applied_migrations: All migrations from history in chronological order
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude
        """
        # Get migration data
        migrations_data = self.get_migration_data(
            migration_state=migration_state,
            all_applied_migrations=all_applied_migrations,
            scripts_dir=scripts_dir,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
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
        self.table_renderer.print_migration_table(migrations_data)
        self.log.file_only_info(self.table_renderer.format_migration_table(migrations_data))
        # Store the structured data in the logger for formatters to use
        for log in getattr(self.log, "logs", [self.log]):
            setattr(log, "migration_data", migrations_data)
