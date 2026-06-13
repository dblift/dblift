"""ALTER Statement Generator for SQL Objects.

This module provides functionality for generating ALTER statements to modify
existing database objects. This is now a thin wrapper around the database-specific
ALTER generators for backward compatibility.
"""

import logging
from typing import TYPE_CHECKING, List, Optional

from core.sql_generator.alter.alter_generator_factory import AlterGeneratorFactory
from core.sql_model.base import SqlConstraint

if TYPE_CHECKING:
    from core.sql_model.base import SqlColumn
    from core.sql_model.table import Table
    from core.sql_model.view import View

logger = logging.getLogger(__name__)


class AlterGenerator:
    """Generates ALTER statements for modifying SQL objects.

    This is a backward-compatible wrapper around the database-specific
    ALTER generators. New code should use AlterGeneratorFactory directly.
    """

    def __init__(self, dialect: str = "postgresql"):  # lint: allow-dialect-string: dialect dispatch
        """Initialize ALTER generator.

        Args:
            dialect: SQL dialect for generation
        """
        self.dialect = dialect.lower()
        self._generator = AlterGeneratorFactory.create_generator(dialect)

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
        return self._generator.generate_alter_table_statements(
            table=table,
            add_constraints=add_constraints,
            drop_constraints=drop_constraints,
            add_columns=add_columns,
            drop_columns=drop_columns,
            modify_columns=modify_columns,
        )

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
        return self._generator.generate_alter_view_statement(view, new_query)

    # Expose internal methods for backward compatibility
    def _format_schema_prefix(self, schema: Optional[str]) -> str:
        """Format schema prefix for identifier."""
        return self._generator._format_schema_prefix(schema)

    def _format_identifier(self, identifier: str) -> str:
        """Format identifier based on dialect."""
        return self._generator._format_identifier(identifier)

    def _format_column_definition(self, column: "SqlColumn") -> str:  # type: ignore
        """Format column definition for ALTER statements."""
        return self._generator._format_column_definition(column)

    def _format_constraint_definition(self, constraint: SqlConstraint) -> Optional[str]:
        """Format constraint definition for ALTER statements."""
        return self._generator._format_constraint_definition(constraint)
