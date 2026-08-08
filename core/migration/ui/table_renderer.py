"""
Table rendering and display utilities.

This module handles the formatting and display of migration data in table format
and other structured display formats.
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

    def _build_rich_table(self, migrations_data: List[Dict[str, Any]]) -> Table:
        """Build a Rich Table with colored State column."""
        # (header, key, justify, min_width, max_width, no_wrap)
        columns = [
            ("Category", "category", "left", 10, 12, True),
            ("Version", "version", "left", 5, 12, True),
            ("Description", "description", "left", 10, 28, False),
            ("Type", "type", "left", 4, None, True),
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
