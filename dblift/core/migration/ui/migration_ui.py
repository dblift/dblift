"""
Main migration UI orchestrator.

This is the primary entry point for migration UI operations, now refactored
to use specialized components for better separation of concerns.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from dblift.core.logger import Log, NullLog
from dblift.core.logger.results import is_failed_migration_status

if TYPE_CHECKING:
    from .table_renderer import TableRenderer


def __getattr__(name: str) -> Any:
    if name == "TableRenderer":
        from .table_renderer import TableRenderer

        globals()[name] = TableRenderer
        return TableRenderer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class MigrationUI:
    """Main UI class that orchestrates migration display operations."""

    def __init__(self, log: Log):
        """Initialize the migration UI.

        Args:
            log: Logger instance for display output
        """
        self.log = log if log is not None else NullLog()
        self._table_renderer: Optional["TableRenderer"] = None

    @property
    def table_renderer(self) -> "TableRenderer":
        """Return this UI's renderer, creating it on first display."""
        if self._table_renderer is None:
            from .migration_ui import TableRenderer

            self._table_renderer = TableRenderer(self.log)
        return self._table_renderer

    @table_renderer.setter
    def table_renderer(self, renderer: "TableRenderer") -> None:
        """Use an injected renderer for subsequent displays."""
        self._table_renderer = renderer

    def display_migration_info(self, migrations_data: List[Dict[str, Any]]) -> None:
        """Display comprehensive migration information.

        Args:
            migrations_data: Rows from ``MigrationDataCollector.get_migration_data``
        """
        if isinstance(self.log, NullLog):
            return

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
        total_failed = len(
            [m for m in migrations_data if is_failed_migration_status(m.get("state", ""))]
        )

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
