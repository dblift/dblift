"""
Migration formatting utilities.

This module provides utilities for formatting migration data into various
output formats including tables, JSON, and HTML.
"""

from typing import Any, Dict, List

from rich import box
from rich.table import Table

from core.logger import Log
from core.logger.console import render_table_to_str
from core.migration.version_utils import compare_versions as _compare_versions_shared


class MigrationFormatter:
    """Formats migration data for various output types."""

    def __init__(self, logger: Log):
        """Initialize the migration formatter.

        Args:
            logger: Logger instance for debugging
        """
        self.logger = logger

    def format_as_table(self, migration_data: List[Dict[str, Any]]) -> str:
        """Format migration data as a table string.

        Args:
            migration_data: List of migration data dictionaries

        Returns:
            str: Formatted table string
        """
        if not migration_data:
            return "No migrations found."

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
        table.add_column("Category")
        table.add_column("Version")
        table.add_column("Description")
        table.add_column("Type")
        table.add_column("Installed On")
        table.add_column("State")
        table.add_column("Execution Time", justify="right")

        for migration in migration_data:
            exec_time = migration.get("execution_time")
            if isinstance(exec_time, (int, float)) and exec_time > 0:
                exec_time_str = f"{exec_time}ms"
            else:
                exec_time_str = ""

            installed_on = migration.get("installed_on")
            installed_on_str = str(installed_on)[:19] if installed_on else ""

            description = migration.get("description", "")
            if len(description) > 50:
                description = description[:50] + "..."

            table.add_row(
                migration.get("category", ""),
                migration.get("version", ""),
                description,
                migration.get("type", ""),
                installed_on_str,
                migration.get("state", ""),
                exec_time_str,
            )

        return render_table_to_str(table)

    def format_as_json(self, migration_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Format migration data as JSON-serializable dictionary.

        Args:
            migration_data: List of migration data dictionaries

        Returns:
            Dict: JSON-serializable dictionary with migration data and summary
        """
        # Create summary statistics
        total_migrations = len(migration_data)
        successful_migrations = len([m for m in migration_data if m.get("state") == "Success"])
        failed_migrations = len([m for m in migration_data if m.get("state") == "Failed"])
        pending_migrations = len([m for m in migration_data if m.get("state") == "Pending"])

        # Convert datetime objects to strings for JSON serialization
        json_migrations = []
        for migration in migration_data:
            json_migration = migration.copy()

            # Convert installed_on to string if it's not None
            if json_migration.get("installed_on"):
                json_migration["installed_on"] = str(json_migration["installed_on"])

            json_migrations.append(json_migration)

        return {
            "migrations": json_migrations,
            "summary": {
                "total": total_migrations,
                "successful": successful_migrations,
                "failed": failed_migrations,
                "pending": pending_migrations,
            },
        }

    def format_as_html(self, migration_data: List[Dict[str, Any]]) -> str:
        """Format migration data as HTML table.

        Args:
            migration_data: List of migration data dictionaries

        Returns:
            str: HTML table string
        """
        if not migration_data:
            return "<p>No migrations found.</p>"

        html_parts = [
            "<table class='migration-table' border='1' cellpadding='5' cellspacing='0'>",
            "<thead>",
            "<tr>",
            "<th>Category</th>",
            "<th>Version</th>",
            "<th>Description</th>",
            "<th>Type</th>",
            "<th>Installed On</th>",
            "<th>State</th>",
            "<th>Execution Time</th>",
            "</tr>",
            "</thead>",
            "<tbody>",
        ]

        for migration in migration_data:
            state = migration.get("state", "")
            state_class = f"state-{state.lower().replace(' ', '-')}"

            # Format execution time
            exec_time = migration.get("execution_time")
            if exec_time is not None and isinstance(exec_time, (int, float)) and exec_time > 0:
                exec_time_str = f"{exec_time}ms"
            else:
                exec_time_str = ""

            # Format installed on date
            installed_on = migration.get("installed_on")
            if installed_on:
                installed_on_str = str(installed_on)[:19]  # Truncate to YYYY-MM-DD HH:MM:SS
            else:
                installed_on_str = ""

            html_parts.extend(
                [
                    f"<tr class='{state_class}'>",
                    f"<td>{migration.get('category', '')}</td>",
                    f"<td>{migration.get('version', '')}</td>",
                    f"<td>{migration.get('description', '')}</td>",
                    f"<td>{migration.get('type', '')}</td>",
                    f"<td>{installed_on_str}</td>",
                    f"<td><span class='state {self._get_state_color(state)}'>{state}</span></td>",
                    f"<td>{exec_time_str}</td>",
                    "</tr>",
                ]
            )

        html_parts.extend(
            [
                "</tbody>",
                "</table>",
                f"<p class='summary'>Total migrations: {len(migration_data)}</p>",
            ]
        )

        return "\n".join(html_parts)

    def _get_state_color(self, state: str) -> str:
        """Get CSS class for migration state color.

        Args:
            state: Migration state

        Returns:
            str: CSS class name for the state
        """
        state_colors = {
            "success": "success",
            "failed": "error",
            "pending": "pending",
            "undone": "warning",
            "missing": "error",
            "ignored": "muted",
            "deleted": "muted",
            "available": "info",
            "above target": "muted",
            "baseline": "info",
            "below baseline": "muted",
            "failed missing": "error",
            "failed future": "error",
            "future": "warning",
            "out of order": "warning",
            "outdated": "warning",
            "superseded": "muted",
        }

        return state_colors.get(state.lower(), "default")

    def _compare_versions(self, version1: str, version2: str) -> int:
        """Compare two version strings. Delegates to shared compare_versions utility."""
        return _compare_versions_shared(version1, version2)
