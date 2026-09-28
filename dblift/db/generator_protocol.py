"""Structural types for dialect DDL and ALTER generators.

A plugin's quirks advertise its generators through
``ddl_generator_class()`` / ``alter_generator_class()``. The provider layer
types those hooks against the Protocols below, so it describes what a
generator is without importing a concrete generator package. The method
signatures are copied from ``BaseSqlGenerator`` and ``BaseAlterGenerator``;
``tests/unit/db/test_generator_protocol.py`` keeps them in step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from dblift.core.sql_model.base import SqlColumn, SqlConstraint, SqlObject
    from dblift.core.sql_model.table import Table
    from dblift.core.sql_model.view import View


@runtime_checkable
class SqlGeneratorProtocol(Protocol):
    """A generator that renders CREATE and DROP DDL for SQL model objects."""

    def generate_ddl(
        self,
        objects: List[SqlObject],
        target_dialect: Optional[str] = None,
        include_comments: bool = True,
        format_sql: bool = True,
        order_by_dependencies: Optional[bool] = None,
    ) -> str:
        """Return the CREATE DDL for ``objects``."""
        ...

    def generate_create_statement(self, obj: SqlObject) -> str:
        """Return the CREATE statement for one object."""
        ...

    def generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """Return the DROP statement for one object."""
        ...

    def generate_drop_statements(
        self,
        objects: List[SqlObject],
        target_dialect: Optional[str] = None,
        format_sql: bool = True,
        order_by_dependencies: Optional[bool] = None,
    ) -> str:
        """Return the DROP statements for ``objects``."""
        ...

    def generate_schema_script(
        self,
        schema: Dict[str, List[SqlObject]],
        target_dialect: Optional[str] = None,
        options: Optional[Any] = None,
    ) -> Dict[str, str]:
        """Return the organized schema script, keyed by file name.

        ``options`` is a ``ScriptOptions``; it is typed ``Any`` here because
        that class lives in the generator package this module must not import.
        """
        ...


@runtime_checkable
class AlterGeneratorProtocol(Protocol):
    """A generator that renders ALTER statements for tables and views."""

    def generate_alter_table_statements(
        self,
        table: Table,
        add_constraints: Optional[List[SqlConstraint]] = None,
        drop_constraints: Optional[List[str]] = None,
        add_columns: Optional[List[SqlColumn]] = None,
        drop_columns: Optional[List[str]] = None,
        modify_columns: Optional[List[SqlColumn]] = None,
    ) -> List[str]:
        """Return the ALTER TABLE statements for the requested changes."""
        ...

    def generate_alter_view_statement(
        self,
        view: View,
        new_query: Optional[str] = None,
    ) -> Optional[str]:
        """Return the ALTER VIEW (or CREATE OR REPLACE VIEW) statement."""
        ...
