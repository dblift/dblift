"""OBS-04: clean drops ``dblift_migration_lock`` (no more preservation).

Plan: clean must produce an empty slate so the next migrate starts from
zero; lock manager auto-recreates the lock table on next ``acquire``.
Verifies the three dialects that previously preserved the lock table:
PostgreSQL, MySQL, SQLite. (SQL Server and Oracle never had preservation.)
"""

import sqlite3
import unittest
from unittest.mock import MagicMock


class TestPostgresqlCleanDropsLock(unittest.TestCase):
    def test_lock_table_is_dropped(self):
        from dblift.db.plugins.postgresql.postgresql.schema_operations import (
            PostgreSqlSchemaOperations,
        )

        qx = MagicMock()
        # extensions query → empty; views handled by _drop_views (mocked)
        # tables query returns the lock table among results
        qx.execute_query.side_effect = [
            [],  # extensions
            [{"table_name": "dblift_migration_lock"}, {"table_name": "users"}],  # tables
            [],  # functions/procedures
            [],  # user-defined types
        ]
        qx.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())
        ops._drop_views = MagicMock()
        ops._drop_sequences = MagicMock()
        # Other internal drops not asserted here; we only care about table loop.

        ops.clean_schema(MagicMock(), "public")

        drop_calls = [str(c) for c in qx.execute_statement.call_args_list]
        joined = " ".join(drop_calls)
        self.assertIn("dblift_migration_lock", joined)
        self.assertIn("DROP TABLE", joined.upper())


class TestMysqlCleanDropsLock(unittest.TestCase):
    def test_drop_tables_passes_no_skip_names(self):
        import inspect

        from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations

        # Source-level guard: the previous code preserved
        # ``DBLIFT_MIGRATION_LOCKS`` via ``skip_names={...}``. After OBS-04 fix
        # that argument must be gone.
        src = inspect.getsource(MySqlSchemaOperations._drop_tables)
        self.assertNotIn("DBLIFT_MIGRATION_LOCKS", src)
        self.assertNotIn("skip_names=", src)


class TestSqliteCleanDropsLock(unittest.TestCase):
    def test_lock_table_enumerated_as_candidate(self):
        from dblift.db.plugins.sqlite.sqlite.schema_operations import SQLiteSchemaOperations

        # Build an in-memory sqlite DB with lock + a user table.
        conn = sqlite3.connect(":memory:")
        conn.execute('CREATE TABLE "dblift_migration_lock" (id INTEGER PRIMARY KEY, name TEXT)')
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")

        qx = MagicMock()

        def _exec_query(connection, query, params=None):
            cursor = connection.execute(query)
            cols = [c[0] for c in cursor.description] if cursor.description else []
            return [dict(zip(cols, row)) for row in cursor.fetchall()]

        qx.execute_query.side_effect = _exec_query
        ops = SQLiteSchemaOperations(query_executor=qx, log=MagicMock())

        candidates = ops.enumerate_clean_candidates(conn, "main")
        names = {name for _, name, _ in candidates}
        self.assertIn("dblift_migration_lock", names)
        self.assertIn("users", names)


if __name__ == "__main__":
    unittest.main()
