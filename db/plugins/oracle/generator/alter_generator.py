"""Oracle ALTER Statement Generator.

This module provides Oracle-specific ALTER statement generation functionality.
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


class OracleAlterGenerator(BaseAlterGenerator):
    """Oracle-specific ALTER statement generator."""

    def __init__(self, dialect: str = "oracle"):
        """Initialize Oracle ALTER generator."""
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
        """Generate Oracle ALTER TABLE statements."""
        statements = []

        schema_prefix = self._format_schema_prefix(table.schema)
        table_name = self._format_identifier(table.name)

        # Add columns
        if add_columns:
            for column in add_columns:
                col_def = self._format_column_definition(column)
                stmt = f"ALTER TABLE {schema_prefix}{table_name} ADD COLUMN {col_def}"
                statements.append(stmt)

        # Drop columns
        if drop_columns:
            for col_name in drop_columns:
                col_name_formatted = self._format_identifier(col_name)
                stmt = f"ALTER TABLE {schema_prefix}{table_name} DROP COLUMN {col_name_formatted}"
                statements.append(stmt)

        # Modify columns (Oracle uses MODIFY)
        if modify_columns:
            for column in modify_columns:
                col_def = self._format_column_definition(column)
                stmt = f"ALTER TABLE {schema_prefix}{table_name} MODIFY {col_def}"
                statements.append(stmt)

        # Add constraints
        if add_constraints:
            for constraint in add_constraints:
                constraint_def = self._format_constraint_definition(constraint)
                if constraint_def:
                    stmt = f"ALTER TABLE {schema_prefix}{table_name} ADD {constraint_def}"
                    statements.append(stmt)

        # Drop constraints
        if drop_constraints:
            for constraint_name in drop_constraints:
                constraint_name_formatted = self._format_identifier(constraint_name)
                stmt = f"ALTER TABLE {schema_prefix}{table_name} DROP CONSTRAINT {constraint_name_formatted}"
                statements.append(stmt)

        return statements

    def generate_alter_view_statement(
        self,
        view: "View",
        new_query: Optional[str] = None,
    ) -> Optional[str]:
        """Generate Oracle ALTER VIEW statement.

        Oracle uses CREATE OR REPLACE for regular views only.
        Materialized views do NOT support OR REPLACE in Oracle.
        """
        if not new_query:
            return None

        schema_prefix = self._format_schema_prefix(view.schema)
        view_name = self._format_identifier(view.name)
        view_type = "MATERIALIZED VIEW" if view.materialized else "VIEW"

        if view.materialized:
            # For materialized views, we need to drop and recreate
            # Note: This should ideally be handled by the caller with DROP + CREATE
            stmt = f"CREATE {view_type} {schema_prefix}{view_name} AS\n{new_query}"
        else:
            # Regular views use CREATE OR REPLACE
            stmt = f"CREATE OR REPLACE {view_type} {schema_prefix}{view_name} AS\n{new_query}"

        return stmt

    def _format_identifier(self, identifier: str) -> str:
        """Format identifier with Oracle double quotes, preserving case."""
        return f'"{identifier}"'

    def _format_column_definition(self, column: "SqlColumn") -> str:
        """Format column definition for Oracle ALTER statements.

        Oracle requires explicit NULL specification.
        """
        col_name = self._format_identifier(column.name)
        data_type = column.data_type or "VARCHAR2(255)"

        definition = f"{col_name} {data_type}"

        # Only add NOT NULL when explicitly False; nullable=None (unknown) must not
        # be treated as NOT NULL.
        if column.nullable is False:
            definition += " NOT NULL"
        else:
            # Oracle requires explicit NULL (nullable=True or nullable=None)
            definition += " NULL"

        if column.default_value:
            definition += f" DEFAULT {column.default_value}"

        return definition
