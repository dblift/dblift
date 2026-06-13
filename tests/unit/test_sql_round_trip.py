"""Round-trip property tests: introspect(SQL) → generate() ≈ SQL.

The bug class these tests prevent (root cause of B10-BUG-23):
the introspector populates the model with one attribute name (e.g.
``Index.condition``), and the generator gates emission on a *different*
attribute (e.g. ``where_clause``). Both compile, both pass their own
unit tests, and the predicate silently disappears from the round-trip.

A handful of small property tests catch that drift without needing a
live database:

  * SQLite partial-index WHERE round-trips through the introspector
    (parsing ``sqlite_master.sql``) into the generator and back into a
    SQL string that still contains the predicate.

  * PostgreSQL filtered-index WHERE round-trips through the same
    ``Index.condition`` attribute.

  * SQL Server filtered-index WHERE likewise.

If anyone renames ``Index.condition`` again, *every* dialect with a
filtered-index path fails here, not just one introspector unit test.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class TestIndexConditionRoundTrip(unittest.TestCase):
    """``Index.condition`` survives introspect → generate."""

    def test_sqlite_partial_index_predicate_round_trips(self) -> None:
        from core.sql_model.index import Index
        from db.plugins.sqlite.generator.ddl_generator import SQLiteSqlGenerator
        from db.plugins.sqlite.introspection.sqlite_introspector import (
            SQLiteIntrospector,
        )

        original_sql = "CREATE INDEX idx_active ON users(email) WHERE active = 1"

        intro = SQLiteIntrospector.__new__(SQLiteIntrospector)
        intro.log = MagicMock()
        predicate = intro._parse_index_where_clause(original_sql)
        self.assertEqual(predicate, "active = 1")

        index = Index(
            name="idx_active",
            table_name="users",
            columns=["email"],
            unique=False,
            condition=predicate,
            dialect="sqlite",
        )

        generator = SQLiteSqlGenerator.__new__(SQLiteSqlGenerator)
        regenerated = generator._generate_index_create_statement(index)
        self.assertIn("WHERE active = 1", regenerated)

    def test_postgresql_filtered_index_predicate_emits_where(self) -> None:
        from core.sql_model.index import Index
        from db.plugins.postgresql.generator.ddl_generator import PostgreSQLSqlGenerator

        index = Index(
            name="idx_pg_active",
            table_name="users",
            columns=["email"],
            unique=False,
            condition="active IS TRUE",
            dialect="postgresql",
        )
        generator = PostgreSQLSqlGenerator.__new__(PostgreSQLSqlGenerator)
        sql = generator._generate_index_create_statement(index)
        self.assertIn("WHERE active IS TRUE", sql)

    def test_sqlserver_filtered_index_predicate_emits_where(self) -> None:
        from core.sql_model.index import Index
        from db.plugins.sqlserver.generator.ddl_generator import SQLServerSqlGenerator

        index = Index(
            name="idx_mssql_active",
            table_name="users",
            columns=["email"],
            unique=False,
            condition="active = 1",
            dialect="sqlserver",
        )
        generator = SQLServerSqlGenerator.__new__(SQLServerSqlGenerator)
        sql = generator._generate_index_create_statement(index)
        self.assertIn("WHERE active = 1", sql)

    def test_index_condition_attribute_is_canonical(self) -> None:
        """Regression guard: the canonical attribute is ``condition``.

        If anyone renames it (e.g. back to ``where_clause``), introspectors
        that set the new name will still appear to work in isolation while
        every dialect-specific generator that gates on ``condition``
        silently drops the predicate. Pin the name here so the rename is
        surfaced as a test failure rather than discovered in production.
        """
        from core.sql_model.index import Index

        index = Index(
            name="idx",
            table_name="t",
            columns=["c"],
            condition="x = 1",
            dialect="sqlite",
        )
        self.assertEqual(index.condition, "x = 1")
        self.assertFalse(hasattr(index, "where_clause"))


if __name__ == "__main__":
    unittest.main()
