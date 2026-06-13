"""SQLite ALTER statement generator.

SQLite supports only a small subset of ALTER TABLE operations. This generator
emits executable SQL for safe operations and explicit comments for operations
that require a table-rebuild migration.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator
from core.sql_model.base import SqlConstraint

if TYPE_CHECKING:
    from core.sql_model.base import SqlColumn
    from core.sql_model.table import Table
    from core.sql_model.view import View

logger = logging.getLogger(__name__)


class SQLiteAlterGenerator(BaseAlterGenerator):
    """SQLite-specific ALTER statement generator."""

    def __init__(self, dialect: str = "sqlite") -> None:
        """Initialize SQLite ALTER generator."""
        super().__init__(dialect)

    def generate_alter_table_statements(
        self,
        table: "Table",
        add_constraints: Optional[List[SqlConstraint]] = None,
        drop_constraints: Optional[List[str]] = None,
        add_columns: Optional[List["SqlColumn"]] = None,
        drop_columns: Optional[List[str]] = None,
        modify_columns: Optional[List["SqlColumn"]] = None,
    ) -> List[str]:
        """Generate SQLite ALTER TABLE statements."""
        statements: List[str] = []
        table_name = self._format_identifier(table.name)

        if add_columns:
            for column in add_columns:
                if self._can_add_column(column):
                    col_def = self._format_column_definition(column)
                    statements.append(f"ALTER TABLE {table_name} ADD COLUMN {col_def}")
                else:
                    statements.append(
                        "-- SQLite cannot add column "
                        f"{self._format_identifier(column.name)} to {table_name} with inline "
                        "PRIMARY KEY, UNIQUE, or stored generated constraints; rebuild the table"
                    )

        if drop_columns:
            for col_name in drop_columns:
                statements.append(
                    "-- SQLite column drop for "
                    f"{self._format_identifier(col_name)} on {table_name} requires rebuilding the table"
                )

        if modify_columns:
            for column in modify_columns:
                statements.append(
                    "-- SQLite column modification for "
                    f"{self._format_identifier(column.name)} on {table_name} requires rebuilding the table"
                )

        if add_constraints:
            for constraint in add_constraints:
                constraint_name = (
                    self._format_identifier(constraint.name) if constraint.name else "constraint"
                )
                statements.append(
                    f"-- SQLite cannot add constraint {constraint_name} to {table_name}; "
                    "rebuild the table with the constraint in the CREATE TABLE statement"
                )

        if drop_constraints:
            for constraint_name in drop_constraints:
                statements.append(
                    "-- SQLite constraint drop for "
                    f"{self._format_identifier(constraint_name)} on {table_name} requires rebuilding the table"
                )

        return statements

    def generate_alter_view_statement(
        self,
        view: "View",
        new_query: Optional[str] = None,
    ) -> Optional[str]:
        """Generate SQLite view replacement statements."""
        if not new_query:
            return None

        view_name = self._format_identifier(view.name)
        return f"DROP VIEW IF EXISTS {view_name};\nCREATE VIEW {view_name} AS {new_query}"

    def _format_identifier(self, identifier: str) -> str:
        """Format identifier with SQLite double quotes."""
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'

    def _can_add_column(self, column: "SqlColumn") -> bool:
        """Return whether SQLite can add this column directly."""
        return not (
            getattr(column, "is_primary_key", False)
            or getattr(column, "is_unique", False)
            or (getattr(column, "is_computed", False) and getattr(column, "computed_stored", False))
        )
