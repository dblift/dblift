"""Base ALTER Statement Generator for SQL Objects.

This module provides the abstract base class for database-specific ALTER statement generators.
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from core.sql_generator.basic_table_ddl_generator import _build_fk_body_sql
from core.sql_model.base import SqlConstraint, get_constraint_type_name

if TYPE_CHECKING:
    from core.sql_model.base import SqlColumn
    from core.sql_model.table import Table
    from core.sql_model.view import View

logger = logging.getLogger(__name__)


class BaseAlterGenerator(ABC):
    """Abstract base class for generating ALTER statements for modifying SQL objects."""

    def __init__(self, dialect: str):
        """Initialize ALTER generator.

        Args:
            dialect: SQL dialect for generation
        """
        self.dialect = dialect.lower()

    @abstractmethod
    def generate_alter_table_statements(
        self,
        table: "Table",  # type: ignore
        add_constraints: Optional[List[SqlConstraint]] = None,
        drop_constraints: Optional[List[str]] = None,
        add_columns: Optional[List["SqlColumn"]] = None,  # type: ignore
        drop_columns: Optional[List[str]] = None,
        modify_columns: Optional[List["SqlColumn"]] = None,  # type: ignore
    ) -> List[str]:
        """Generate ALTER TABLE statements.

        Args:
            table: Table object to alter
            add_constraints: List of constraints to add
            drop_constraints: List of constraint names to drop
            add_columns: List of columns to add
            drop_columns: List of column names to drop
            modify_columns: List of columns to modify

        Returns:
            List of ALTER TABLE statements
        """

    @abstractmethod
    def generate_alter_view_statement(
        self,
        view: "View",  # type: ignore
        new_query: Optional[str] = None,
    ) -> Optional[str]:
        """Generate ALTER VIEW statement.

        Note: Some databases use CREATE OR REPLACE VIEW instead of ALTER VIEW.

        Args:
            view: View object to alter
            new_query: New view query

        Returns:
            ALTER VIEW or CREATE OR REPLACE VIEW statement
        """

    @abstractmethod
    def _format_identifier(self, identifier: str) -> str:
        """Format identifier based on dialect.

        Args:
            identifier: The identifier to format

        Returns:
            Formatted identifier with appropriate quoting
        """

    def _format_schema_prefix(self, schema: Optional[str]) -> str:
        """Format schema prefix for identifier."""
        if schema:
            return f"{self._format_identifier(schema)}."
        return ""

    def _format_column_definition(self, column: "SqlColumn") -> str:  # type: ignore
        """Format column definition for ALTER statements.

        This base implementation provides common logic that can be overridden
        by database-specific implementations.
        """
        col_name = self._format_identifier(column.name)
        data_type = column.data_type or "VARCHAR(255)"

        definition = f"{col_name} {data_type}"

        # Only add NOT NULL when explicitly False; nullable=None (unknown) must not
        # be treated as NOT NULL.
        if column.nullable is False:
            definition += " NOT NULL"

        if column.default_value:
            definition += f" DEFAULT {column.default_value}"

        return definition

    def _format_constraint_definition(self, constraint: SqlConstraint) -> Optional[str]:
        """Format constraint definition for ALTER statements.

        This base implementation provides common logic that can be overridden
        by database-specific implementations.
        """
        constraint_type = get_constraint_type_name(constraint)

        if constraint_type == "PRIMARY KEY":
            cols = ", ".join(self._format_identifier(col) for col in constraint.columns)
            return f"PRIMARY KEY ({cols})"

        elif constraint_type == "FOREIGN KEY":
            if not constraint.reference_table:
                return None
            local_cols = list(constraint.columns)
            ref_cols = list(constraint.reference_columns or [])
            fk_body = _build_fk_body_sql(
                local_cols=local_cols,
                ref_cols=ref_cols,
                ref_table=constraint.reference_table,
                ref_schema=constraint.reference_schema,
                format_identifier=self._format_identifier,
                on_delete=None,
                on_update=None,
            )
            constraint_def = fk_body
            if constraint.name:
                constraint_def = f"CONSTRAINT {self._format_identifier(constraint.name)} {fk_body}"
            return constraint_def

        elif constraint_type == "UNIQUE":
            cols = ", ".join(self._format_identifier(col) for col in constraint.columns)
            constraint_def = f"UNIQUE ({cols})"

            if constraint.name:
                constraint_def = (
                    f"CONSTRAINT {self._format_identifier(constraint.name)} {constraint_def}"
                )

            return constraint_def

        elif constraint_type == "CHECK":
            if constraint.columns:
                check_expr = " ".join(constraint.columns)
            else:
                check_expr = "1=1"

            constraint_def = f"CHECK ({check_expr})"

            if constraint.name:
                constraint_def = (
                    f"CONSTRAINT {self._format_identifier(constraint.name)} {constraint_def}"
                )

            return constraint_def

        return None
