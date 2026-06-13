"""OBS-02 regression: SQLite get_tables_query excludes FTS5 shadow tables.

Before this fix the query returned every table in sqlite_master including
FTS5 internal shadow tables (*_content, *_data, *_idx, *_docsize, *_config,
*_segdir, *_segments, *_stat), making them appear as user tables in snapshots.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


def _query_tables(db_path: str) -> list[str]:
    from db.plugins.sqlite.introspection.sqlite_queries import SQLiteMetadataQueries

    queries = SQLiteMetadataQueries()
    sql, params = queries.get_tables_query("main")

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [row[0] for row in rows]


@pytest.mark.unit
class TestSqliteFts5Filter:
    def test_fts5_shadow_tables_excluded(self, tmp_path):
        db = str(tmp_path / "test.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute(
                "CREATE VIRTUAL TABLE orders_fts USING fts5(name, content='orders', content_rowid='id')"
            )

        tables = _query_tables(db)
        assert "orders" in tables
        assert "orders_fts" in tables
        # FTS5 shadow tables must be absent
        fts_shadows = [t for t in tables if t.startswith("orders_fts_")]
        assert fts_shadows == [], f"FTS5 shadow tables leaked into results: {fts_shadows}"

    def test_regular_tables_still_returned(self, tmp_path):
        db = str(tmp_path / "test.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY)")

        tables = _query_tables(db)
        assert "products" in tables
        assert "orders" in tables

    def test_sqlite_system_tables_excluded(self, tmp_path):
        db = str(tmp_path / "test.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

        tables = _query_tables(db)
        system = [t for t in tables if t.startswith("sqlite_")]
        assert system == []

    def test_table_with_fts_suffix_in_name_not_erroneously_excluded(self, tmp_path):
        """A real user table named 'my_config' should NOT be excluded."""
        db = str(tmp_path / "test.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE my_config (key TEXT, value TEXT)")

        tables = _query_tables(db)
        assert "my_config" in tables

    def test_sqlite_introspector_keeps_virtual_table_and_excludes_shadows(self, tmp_path):
        from core.sql_model.base import SqlObjectType
        from db.plugins.sqlite.introspection.sqlite_introspector import SQLiteIntrospector

        class Provider:
            def __init__(self, connection):
                self.connection = connection

            def _ensure_connection(self):
                return None

            def execute_query(self, query, params=None):
                cursor = self.connection.execute(query, params or [])
                columns = [desc[0] for desc in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]

        db = str(tmp_path / "test.db")
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute(
                "CREATE VIRTUAL TABLE orders_fts USING fts5(name, content='orders', content_rowid='id')"
            )

        conn = sqlite3.connect(db)
        try:
            introspector = SQLiteIntrospector(Provider(conn))
            tables = introspector.get_tables("main")
        finally:
            conn.close()

        names = {table.name for table in tables}
        assert "orders" in names
        assert "orders_fts" in names
        assert not any(name.startswith("orders_fts_") for name in names)

        virtual_table = next(table for table in tables if table.name == "orders_fts")
        assert virtual_table.object_type == SqlObjectType.VIRTUAL_TABLE
        assert virtual_table.raw_ddl is not None
        assert "CREATE VIRTUAL TABLE" in virtual_table.raw_ddl.upper()
        assert "USING fts5" in virtual_table.raw_ddl
