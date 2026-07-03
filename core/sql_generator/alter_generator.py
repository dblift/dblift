"""Neutral ALTER generator wrapper."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from core.sql_generator.alter.alter_generator_factory import AlterGeneratorFactory
from core.sql_model.base import SqlConstraint

if TYPE_CHECKING:
    from core.sql_model.base import SqlColumn
    from core.sql_model.table import Table
    from core.sql_model.view import View


class AlterGenerator:
    """Backward-compatible wrapper around registered ALTER generators."""

    def __init__(self, dialect: str = "postgresql"):  # lint: allow-dialect-string
        """Initialize the wrapper for a registered dialect ALTER generator."""
        self.dialect = dialect.lower()
        self._generator = AlterGeneratorFactory.create_generator(dialect)

    def generate_alter_table_statements(
        self,
        table: "Table",
        add_constraints: Optional[List[SqlConstraint]] = None,
        drop_constraints: Optional[List[str]] = None,
        add_columns: Optional[List["SqlColumn"]] = None,
        drop_columns: Optional[List[str]] = None,
        modify_columns: Optional[List["SqlColumn"]] = None,
    ) -> List[str]:
        """Generate ALTER TABLE statements via the registered generator."""
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
        view: "View",
        new_query: Optional[str] = None,
    ) -> Optional[str]:
        """Generate an ALTER VIEW statement via the registered generator."""
        return self._generator.generate_alter_view_statement(view, new_query)

    def _format_schema_prefix(self, schema: Optional[str]) -> str:
        return self._generator._format_schema_prefix(schema)

    def _format_identifier(self, identifier: str) -> str:
        return self._generator._format_identifier(identifier)

    def _format_column_definition(self, column: "SqlColumn") -> str:
        return self._generator._format_column_definition(column)

    def _format_constraint_definition(self, constraint: SqlConstraint) -> Optional[str]:
        return self._generator._format_constraint_definition(constraint)


__all__ = ["AlterGenerator"]
