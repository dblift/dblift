"""
Table rendering and display utilities.

This module handles the formatting and display of migration data in table format,
query results, and other structured display formats.
"""

import sys
from typing import Any, Dict, List, cast

from rich import box
from rich.console import Console
from rich.measure import Measurement
from rich.table import Table

from core.logger import Log, NullLog
from core.logger.console import ColumnJustify, render_table_to_str, state_text


class TableRenderer:
    """Handles table rendering and display formatting."""

    def __init__(self, log: Log):
        """Initialize the table renderer.

        Args:
            log: Logger instance
        """
        self.log = log if log is not None else NullLog()

    def display_query_results(self, results: List[Dict[str, Any]]) -> None:
        """Display query results in a formatted table.

        Args:
            results: List of dictionaries representing query results
        """
        if not results:
            self.log.info("No results found.")
            return

        all_columns: set[str] = set()
        for result in results:
            if isinstance(result, dict):
                all_columns.update(result.keys())

        if not all_columns:
            self.log.info("No columns found in results.")
            return

        columns = sorted(list(all_columns))

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
        for col in columns:
            table.add_column(str(col))

        for result in results:
            if isinstance(result, dict):
                table.add_row(*[str(result.get(col, "")) for col in columns])

        self.log.info(render_table_to_str(table))
        self.log.info(f"Total rows: {len(results)}")

    def _build_rich_table(self, migrations_data: List[Dict[str, Any]]) -> Table:
        """Build a Rich Table with colored State column."""
        # (header, key, justify, min_width, max_width, no_wrap)
        columns = [
            ("Category", "category", "left", 10, 12, True),
            ("Version", "version", "left", 5, 12, True),
            ("Description", "description", "left", 10, 28, False),
            ("Type", "type", "left", 3, 4, True),
            ("Installed On", "installed_on", "left", 19, 19, True),
            ("Installed By", "installed_by", "left", 8, 15, True),
            ("State", "state", "left", 7, 9, True),
            ("Exec Time", "execution_time", "right", 6, 10, True),
            ("Undoable", "undoable", "center", 5, 8, True),
        ]

        table = Table(box=box.ROUNDED, show_header=True, header_style="bold")
        for header, _, justify, min_w, max_w, no_wrap in columns:
            table.add_column(
                header,
                justify=cast(ColumnJustify, justify),
                min_width=min_w,
                max_width=max_w,
                no_wrap=no_wrap,
            )

        for migration in migrations_data:
            row: List[Any] = []
            for _, key, _, _, _, _ in columns:
                if key == "state":
                    row.append(state_text(str(migration.get(key, ""))))
                elif key == "description":
                    desc = str(migration.get(key, ""))
                    row.append(desc[:26] + "…" if len(desc) > 27 else desc)
                elif key == "installed_on":
                    val = str(migration.get(key, ""))
                    row.append(val[:19] if val else "")
                elif key == "execution_time":
                    val = migration.get(key, "")
                    row.append(f"{val}ms" if val else "")
                elif key == "category":
                    _CAT_LABEL = {
                        "versioned": "Versioned",
                        "repeatable": "Repeatable",
                        "undo": "Undo",
                        "baseline": "Baseline",
                    }
                    raw = str(migration.get(key, ""))
                    row.append(_CAT_LABEL.get(raw.lower(), raw.capitalize()))
                elif key == "undoable":
                    row.append("Yes" if migration.get(key) else "No")
                else:
                    row.append(str(migration.get(key, "")))
            table.add_row(*row)

        return table

    def format_migration_table(self, migrations_data: List[Dict[str, Any]]) -> str:
        """Format migration data as a plain-text table string (for file logs / stdout).

        Args:
            migrations_data: List of migration data dictionaries

        Returns:
            str: Formatted table string
        """
        if not migrations_data:
            return "No migrations found."
        return (
            render_table_to_str(self._build_rich_table(migrations_data))
            + f"\nTotal migrations: {len(migrations_data)}"
        )

    def print_migration_table(self, migrations_data: List[Dict[str, Any]]) -> None:
        """Print colored migration table to stdout (tty-aware — no ANSI when piped)."""
        if not migrations_data:
            self.log.info("No migrations found.")
            return
        table = self._build_rich_table(migrations_data)
        con = Console(file=sys.stdout, highlight=False, markup=False, soft_wrap=True)
        # Description is the only wrappable column; the other eight are no_wrap.
        # When the detected terminal is narrower than the table, Rich shrinks the
        # sole flexible column to zero, blanking Description. Floor the render
        # width to the table's natural width so every column stays visible
        # (narrow terminals soft-wrap a complete table instead). Measure with an
        # unconstrained console so the natural width isn't clamped to con.width.
        measure_con = Console(width=10_000)
        natural_width = Measurement.get(measure_con, measure_con.options, table).maximum
        if con.width < natural_width:
            con = Console(
                file=sys.stdout,
                width=natural_width,
                highlight=False,
                markup=False,
                soft_wrap=True,
            )
        con.print()
        con.print(table)
        con.print(f"Total migrations: {len(migrations_data)}")

    def display_migration_status(self, migration: Any) -> None:
        """Display the status of a single migration.

        Args:
            migration: Migration object to display
        """
        self.log.info(f"Migration: {migration.script_name}")
        self.log.info(f"  Version: {getattr(migration, 'version', 'N/A')}")
        self.log.info(f"  Description: {getattr(migration, 'description', 'N/A')}")
        self.log.info(f"  Type: {getattr(migration, 'type', 'N/A')}")
        self.log.info(f"  State: {getattr(migration, 'state', 'N/A')}")

        installed_on = getattr(migration, "installed_on", None)
        if installed_on:
            self.log.info(f"  Installed On: {installed_on}")

        execution_time = getattr(migration, "execution_time", None)
        if execution_time is not None:
            self.log.info(f"  Execution Time: {execution_time}ms")

    def display_migration_details(self, migration: Any) -> None:
        """Display detailed information about a migration.

        Args:
            migration: Migration object to display details for
        """
        self.log.info(f"=== Migration Details: {migration.script_name} ===")

        # Basic information
        self.log.info(f"Script Name: {migration.script_name}")
        self.log.info(f"Version: {getattr(migration, 'version', 'N/A')}")
        self.log.info(f"Description: {getattr(migration, 'description', 'N/A')}")
        self.log.info(f"Type: {getattr(migration, 'type', 'N/A')}")

        # File information
        filepath = getattr(migration, "filepath", None)
        if filepath:
            self.log.info(f"File Path: {filepath}")

        # Execution information
        installed_on = getattr(migration, "installed_on", None)
        if installed_on:
            self.log.info(f"Installed On: {installed_on}")

        execution_time = getattr(migration, "execution_time", None)
        if execution_time is not None:
            self.log.info(f"Execution Time: {execution_time}ms")

        installed_rank = getattr(migration, "installed_rank", None)
        if installed_rank is not None:
            self.log.info(f"Installed Rank: {installed_rank}")

        # Success status
        success = getattr(migration, "success", None)
        if success is not None:
            status = "Success" if success else "Failed"
            self.log.info(f"Status: {status}")

        # Checksum information
        checksum = getattr(migration, "checksum", None)
        if checksum:
            self.log.info(f"Checksum: {checksum}")

        self.log.info("=" * 50)

    def format_summary_stats(self, stats: Dict[str, Any]) -> str:
        """Format summary statistics as a readable string.

        Args:
            stats: Dictionary of statistics

        Returns:
            str: Formatted statistics string
        """
        lines = ["=== Migration Summary ==="]

        for key, value in stats.items():
            formatted_key = key.replace("_", " ").title()
            lines.append(f"{formatted_key}: {value}")

        lines.append("=" * 25)
        return "\n".join(lines)
