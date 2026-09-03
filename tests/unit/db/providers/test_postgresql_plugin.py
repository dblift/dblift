"""Unit tests for PostgreSQL plugin components.

Covers:
- PostgreSqlSchemaOperations (schema_operations.py)
- PostgreSqlQueryExecutor (query_executor.py)
- PostgreSqlConnectionManager (connection_manager.py) — pure-Python paths only

Provider mock pattern: conn = MagicMock(), conn.isClosed.return_value = False,
stmt = MagicMock(), rs = MagicMock(), conn.prepareStatement.return_value = stmt.
"""

import unittest
from unittest.mock import MagicMock


def _make_connection(auto_commit=False, is_closed=False):
    conn = MagicMock()
    conn.isClosed.return_value = is_closed
    conn.getAutoCommit.return_value = auto_commit
    stmt = MagicMock()
    stmt.executeUpdate.return_value = 0
    rs = MagicMock()
    rs.next.return_value = False
    rs.getMetaData.return_value = MagicMock(getColumnCount=MagicMock(return_value=0))
    stmt.executeQuery.return_value = rs
    conn.prepareStatement.return_value = stmt
    conn.createStatement.return_value = stmt
    return conn, stmt, rs


# ---------------------------------------------------------------------------
# PostgreSqlSchemaOperations
# ---------------------------------------------------------------------------


class TestPostgreSqlSchemaOperations(unittest.TestCase):

    def _make_qe(self):
        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 0
        qe.get_quoted_schema_name.side_effect = lambda s: f'"{s}"'
        qe.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
        return qe

    def _make_ops(self, qe=None):
        from dblift.db.plugins.postgresql.postgresql.schema_operations import (
            PostgreSqlSchemaOperations,
        )

        if qe is None:
            qe = self._make_qe()
        log = MagicMock()
        return PostgreSqlSchemaOperations(qe, log), qe, log

    # --- create_schema_if_not_exists ---

    def test_create_schema_executes_create_schema_sql(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        ops.create_schema_if_not_exists(conn, "myschema")
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("CREATE SCHEMA" in c for c in calls))

    def test_create_schema_uses_if_not_exists(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        ops.create_schema_if_not_exists(conn, "myschema")
        sql = qe.execute_statement.call_args[0][1]
        self.assertIn("IF NOT EXISTS", sql.upper())

    def test_create_schema_swallows_already_exists_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("schema already exists")
        # Should not raise
        ops.create_schema_if_not_exists(conn, "myschema")

    def test_create_schema_raises_on_non_exists_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("permission denied")
        with self.assertRaises(RuntimeError):
            ops.create_schema_if_not_exists(conn, "myschema")

    # --- set_current_schema ---

    def test_set_current_schema_uses_search_path(self):
        # Now uses createStatement().execute() directly — not execute_statement()
        ops, qe, log = self._make_ops()
        conn, stmt, _ = _make_connection()
        conn.createStatement.return_value = stmt
        ops.set_current_schema(conn, "myschema")
        sql = stmt.execute.call_args[0][0]
        self.assertIn("search_path", sql.lower())

    def test_set_current_schema_includes_public(self):
        ops, qe, log = self._make_ops()
        conn, stmt, _ = _make_connection()
        conn.createStatement.return_value = stmt
        ops.set_current_schema(conn, "myschema")
        sql = stmt.execute.call_args[0][0]
        self.assertIn("public", sql.lower())

    def test_set_current_schema_uses_create_statement_not_prepare(self):
        """SET search_path must use createStatement (simple query protocol), not prepareStatement."""
        ops, qe, log = self._make_ops()
        conn, stmt, _ = _make_connection()
        conn.createStatement.return_value = stmt
        ops.set_current_schema(conn, "myschema")
        conn.createStatement.assert_called()
        conn.prepareStatement.assert_not_called()

    def test_set_current_schema_closes_statement(self):
        ops, qe, log = self._make_ops()
        conn, stmt, _ = _make_connection()
        conn.createStatement.return_value = stmt
        ops.set_current_schema(conn, "myschema")
        stmt.close.assert_called()

    def test_set_current_schema_raises_on_error(self):
        ops, qe, log = self._make_ops()
        conn, stmt, _ = _make_connection()
        stmt.execute.side_effect = RuntimeError("SQL error")
        conn.createStatement.return_value = stmt
        with self.assertRaises(RuntimeError):
            ops.set_current_schema(conn, "myschema")

    # --- get_database_version ---

    def test_get_database_version_returns_version_string(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"version": "PostgreSQL 14.3 on x86_64-linux"}]
        result = ops.get_database_version(conn)
        self.assertIn("PostgreSQL", result)
        # Should strip the " on ..." portion
        self.assertNotIn(" on ", result)

    def test_get_database_version_returns_unknown_on_empty(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []
        result = ops.get_database_version(conn)
        self.assertIn("Unknown", result)

    def test_get_database_version_returns_unknown_on_exception(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("query failed")
        result = ops.get_database_version(conn)
        self.assertIn("Unknown", result)

    # --- get_tables ---

    def test_get_tables_returns_list_of_table_names(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"table_name": "orders"}, {"table_name": "users"}]
        result = ops.get_tables(conn, "public")
        self.assertEqual(["orders", "users"], result)

    def test_get_tables_returns_empty_on_exception(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("query failed")
        result = ops.get_tables(conn, "public")
        self.assertEqual([], result)

    # --- get_schemas ---

    def test_get_schemas_returns_list(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"schema_name": "public"}, {"schema_name": "app"}]
        result = ops.get_schemas(conn)
        self.assertIn("public", result)
        self.assertIn("app", result)

    def test_get_schemas_returns_empty_on_exception(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("query failed")
        result = ops.get_schemas(conn)
        self.assertEqual([], result)

    # --- get_columns_query ---

    def test_get_columns_query_returns_tuple(self):
        ops, qe, log = self._make_ops()
        sql, params = ops.get_columns_query("public", "orders")
        self.assertIn("information_schema.columns", sql.lower())
        self.assertEqual(["public", "orders"], params)

    # --- get_add_column_sql ---

    def test_get_add_column_sql_generates_alter_table(self):
        ops, qe, log = self._make_ops()
        sql = ops.get_add_column_sql("public", "orders", "status", "VARCHAR(50)")
        self.assertIn("ALTER TABLE", sql)
        self.assertIn("ADD COLUMN", sql)
        self.assertIn('"status"', sql)

    # --- get_parameter_placeholders ---

    def test_get_parameter_placeholders(self):
        ops, qe, log = self._make_ops()
        result = ops.get_parameter_placeholders(3)
        self.assertEqual("?, ?, ?", result)

    # --- clean_schema ---

    def test_clean_schema_drops_tables(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "pg_tables" in sql:
                return [{"table_name": "orders"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP TABLE" in c for c in calls))

    def test_clean_schema_drops_migration_lock_table(self):
        """OBS-04: ``clean_schema`` drops every table including
        ``dblift_migration_lock``; the locking manager re-creates the lock
        table on the next ``acquire_migration_lock`` call, so wiping it
        here is intentional and not a regression. Previously this test
        asserted the opposite (lock table skipped) but the implementation
        was changed in OBS-04 to drop it."""
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "pg_tables" in sql:
                return [{"table_name": "dblift_migration_lock"}, {"table_name": "orders"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        # Lock table IS dropped (re-created on next acquire — see locking_manager).
        self.assertTrue(
            any("dblift_migration_lock" in c and "DROP" in c for c in calls),
            f"Expected dblift_migration_lock to be dropped; calls: {calls}",
        )
        # orders SHOULD be dropped too.
        self.assertTrue(any("DROP TABLE" in c and "orders" in c for c in calls))

    def test_clean_schema_drops_views(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "pg_views" in sql:
                return [{"view_name": "my_view"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP VIEW" in c for c in calls))

    def test_clean_schema_drops_sequences(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "information_schema.sequences" in sql:
                return [{"sequence_name": "my_seq"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP SEQUENCE" in c for c in calls))

    def test_clean_schema_drops_functions(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "information_schema.routines" in sql:
                return [{"routine_name": "my_func", "routine_type": "FUNCTION"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP FUNCTION" in c for c in calls))

    def test_clean_schema_drops_procedures(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "information_schema.routines" in sql:
                return [{"routine_name": "my_proc", "routine_type": "PROCEDURE"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP PROCEDURE" in c for c in calls))

    def test_clean_schema_returns_summary(self):
        from dblift.core.migration.clean_summary import CleanExecutionSummary

        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []
        summary = ops.clean_schema(conn, "public")
        self.assertIsInstance(summary, CleanExecutionSummary)

    def test_clean_schema_raises_on_critical_type_drop_failure(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "pg_type" in sql:
                return [{"type_name": "my_type", "typtype": "c"}]
            return []

        def stmt_side_effect(c, sql):
            if "DROP TYPE" in sql:
                raise RuntimeError("cannot drop type my_type because requires it")
            return 0

        qe.execute_query.side_effect = query_side_effect
        qe.execute_statement.side_effect = stmt_side_effect

        with self.assertRaises(Exception):
            ops.clean_schema(conn, "public")

    def test_clean_schema_drops_composite_types(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "pg_type" in sql:
                return [{"type_name": "my_composite", "typtype": "c"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP TYPE" in c for c in calls))

    def test_clean_schema_drops_domain_types(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "pg_type" in sql:
                return [{"type_name": "my_domain", "typtype": "d"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "public")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP DOMAIN" in c for c in calls))

    def test_drop_views_uses_template_method(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        from dblift.core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        qe.execute_query.return_value = [{"view_name": "v1"}, {"view_name": "v2"}]

        ops._drop_views(conn, "public", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        drop_calls = [c for c in calls if "DROP VIEW" in c]
        self.assertEqual(2, len(drop_calls))

    def test_drop_sequences_uses_template_method(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        from dblift.core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        qe.execute_query.return_value = [{"sequence_name": "s1"}]

        ops._drop_sequences(conn, "public", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP SEQUENCE" in c for c in calls))


# ---------------------------------------------------------------------------
# PostgreSqlHistoryManager
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
