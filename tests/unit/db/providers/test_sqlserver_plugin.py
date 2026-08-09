"""Unit tests for SQL Server plugin components.

Covers:
- SqlServerHistoryManager (history_manager.py)
- SqlServerConnectionManager (connection_manager.py) — pure-Python paths only
- SqlServerLockingManager (locking_manager.py)
- SqlServerQueryExecutor (query_executor.py)
- SqlServerSchemaOperations (schema_operations.py)

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
    # execute() for SqlServer execute_statement: returns False (no result set)
    stmt.execute.return_value = False
    stmt.getUpdateCount.side_effect = [1, -1]  # 1 row affected, then -1 to stop loop
    stmt.getMoreResults.return_value = False
    rs = MagicMock()
    rs.next.return_value = False
    rs.getMetaData.return_value = MagicMock(getColumnCount=MagicMock(return_value=0))
    stmt.executeQuery.return_value = rs
    conn.prepareStatement.return_value = stmt
    conn.createStatement.return_value = stmt
    return conn, stmt, rs


# ---------------------------------------------------------------------------
# SqlServerSchemaOperations
# ---------------------------------------------------------------------------


class TestSqlServerSchemaOperations(unittest.TestCase):

    def _make_qe(self):
        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 0
        qe.get_quoted_schema_name.side_effect = lambda s: f"[{s}]"
        qe.get_schema_qualified_name.side_effect = lambda s, n: f"[{s}].[{n}]"
        return qe

    def _make_ops(self, qe=None):
        from db.plugins.sqlserver.sqlserver.schema_operations import SqlServerSchemaOperations

        if qe is None:
            qe = self._make_qe()
        log = MagicMock()
        return SqlServerSchemaOperations(qe, log), qe, log

    def test_create_schema_when_not_exists(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        # schema_count = 0 → create
        qe.execute_query.return_value = [{"schema_count": 0}]
        ops.create_schema_if_not_exists(conn, "myschema")
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("CREATE SCHEMA" in c for c in calls))

    def test_create_schema_skipped_when_already_exists(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"schema_count": 1}]
        ops.create_schema_if_not_exists(conn, "myschema")
        qe.execute_statement.assert_not_called()

    def test_create_schema_swallows_already_exists_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"schema_count": 0}]
        qe.execute_statement.side_effect = RuntimeError("already exists")
        # Should not raise
        ops.create_schema_if_not_exists(conn, "myschema")

    def test_create_schema_raises_on_other_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"schema_count": 0}]
        qe.execute_statement.side_effect = RuntimeError("permission denied")
        with self.assertRaises(RuntimeError):
            ops.create_schema_if_not_exists(conn, "myschema")

    def test_get_database_version_returns_first_line(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"version": "Microsoft SQL Server 2019\n(RTM)"}]
        result = ops.get_database_version(conn)
        self.assertIn("Microsoft SQL Server 2019", result)
        self.assertNotIn("\n", result)

    def test_get_database_version_returns_unknown_on_empty(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []
        result = ops.get_database_version(conn)
        self.assertIn("Unknown", result)

    def test_get_database_version_returns_unknown_on_exception(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("error")
        result = ops.get_database_version(conn)
        self.assertIn("Unknown", result)

    def test_get_tables_returns_list(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"table_name": "orders"}, {"table_name": "users"}]
        result = ops.get_tables(conn, "dbo")
        self.assertEqual(["orders", "users"], result)

    def test_get_tables_returns_empty_on_exception(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("error")
        result = ops.get_tables(conn, "dbo")
        self.assertEqual([], result)

    def test_get_schemas_returns_list(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"schema_name": "dbo"}, {"schema_name": "app"}]
        result = ops.get_schemas(conn)
        self.assertIn("dbo", result)

    def test_get_schemas_returns_empty_on_exception(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("error")
        result = ops.get_schemas(conn)
        self.assertEqual([], result)

    def test_set_current_schema_alters_connecting_user_default_schema(self):
        """Unqualified DDL must land in the configured schema (issue #806).

        SQL Server has no session-level search path; ALTER USER ... WITH
        DEFAULT_SCHEMA is the real equivalent, and it takes effect
        immediately within the current session.
        """
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"db_user": "dblift_test"}]

        ops.set_current_schema(conn, "dbo")

        qe.execute_statement.assert_called_once_with(
            conn, "ALTER USER [dblift_test] WITH DEFAULT_SCHEMA = [dbo]"
        )

    def test_set_current_schema_logs_warning_when_it_cannot_determine_user(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []  # can't resolve the connecting user

        ops.set_current_schema(conn, "dbo")

        qe.execute_statement.assert_not_called()
        log.warning.assert_called_once()

    def test_set_current_schema_alters_only_once_for_same_schema(self):
        """DEFAULT_SCHEMA is catalog-level state on the login, not
        connection-scoped like every other dialect's mechanism — repeated
        calls with the same schema must not re-issue ALTER USER.
        """
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def fake_execute_query(connection, sql, params=None):
            if "USER_NAME()" in sql:
                return [{"db_user": "dblift_test"}]
            if "sys.database_principals" in sql:
                return [{"default_schema": ops._current_schema_set}]
            return []

        qe.execute_query.side_effect = fake_execute_query

        ops.set_current_schema(conn, "dbo")
        ops.set_current_schema(conn, "dbo")
        ops.set_current_schema(conn, "dbo")

        qe.execute_statement.assert_called_once_with(
            conn, "ALTER USER [dblift_test] WITH DEFAULT_SCHEMA = [dbo]"
        )
        log.warning.assert_not_called()

    def test_set_current_schema_detects_interference_even_when_target_schema_is_unchanged(self):
        """The interference check must not be gated behind the cache-hit
        skip. ``--db-schema`` is fixed for a whole process run, so after the
        first call every later call asks for the SAME schema again -- if the
        catalog read only ran on a schema change, a concurrent process
        clobbering DEFAULT_SCHEMA between two identical calls would never be
        noticed. See issue #806 review follow-up.
        """
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        ops._current_schema_set = "sales"  # as if set earlier on this connection

        def fake_execute_query(connection, sql, params=None):
            if "sys.database_principals" in sql:
                # someone else silently overwrote it
                return [{"db_user": "dblift_test", "default_schema": "orders"}]
            return []

        qe.execute_query.side_effect = fake_execute_query

        ops.set_current_schema(conn, "sales")  # same schema as before -- a cache hit

        log.warning.assert_called_once()
        warning_msg = log.warning.call_args[0][0]
        assert "orders" in warning_msg
        assert "sales" in warning_msg
        # The write is still skipped on the cache hit -- only detection changed.
        qe.execute_statement.assert_not_called()
        assert ops._current_schema_set == "sales"

    def test_set_current_schema_warns_on_external_interference(self):
        """A concurrent process sharing this login changing DEFAULT_SCHEMA
        between our own writes must be surfaced loudly, not silently trusted.
        """
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        ops._current_schema_set = "schema_a"  # as if set earlier on this connection

        def fake_execute_query(connection, sql, params=None):
            if "sys.database_principals" in sql:
                # someone else changed it
                return [{"db_user": "dblift_test", "default_schema": "schema_hijacked"}]
            return []

        qe.execute_query.side_effect = fake_execute_query

        ops.set_current_schema(conn, "schema_b")

        log.warning.assert_called_once()
        warning_msg = log.warning.call_args[0][0]
        assert "schema_hijacked" in warning_msg
        assert "schema_a" in warning_msg
        qe.execute_statement.assert_called_once_with(
            conn, "ALTER USER [dblift_test] WITH DEFAULT_SCHEMA = [schema_b]"
        )
        assert ops._current_schema_set == "schema_b"

    def test_get_columns_query_returns_tuple(self):
        ops, qe, log = self._make_ops()
        sql, params = ops.get_columns_query("dbo", "orders")
        self.assertIn("INFORMATION_SCHEMA.COLUMNS", sql)
        self.assertEqual(["dbo", "orders"], params)

    def test_get_add_column_sql_generates_alter_table(self):
        ops, qe, log = self._make_ops()
        sql = ops.get_add_column_sql("dbo", "orders", "status", "NVARCHAR(50)")
        self.assertIn("ALTER TABLE", sql)
        self.assertIn("ADD", sql)
        self.assertIn("[status]", sql)

    def test_get_parameter_placeholders(self):
        ops, qe, log = self._make_ops()
        result = ops.get_parameter_placeholders(3)
        self.assertEqual("?, ?, ?", result)

    def test_clean_schema_drops_tables(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "INFORMATION_SCHEMA.TABLES" in sql and "BASE TABLE" in sql:
                return [{"table_name": "orders"}]
            if "sys.tables" in sql and "temporal_type" in sql:
                return []
            return []

        qe.execute_query.side_effect = query_side_effect
        summary = ops.clean_schema(conn, "dbo")
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP TABLE" in c for c in calls))

    def test_clean_schema_drops_views(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "INFORMATION_SCHEMA.VIEWS" in sql:
                return [{"view_name": "v_orders"}]
            if "sys.tables" in sql and "temporal_type" in sql:
                return []
            return []

        qe.execute_query.side_effect = query_side_effect
        ops.clean_schema(conn, "dbo")
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP VIEW" in c for c in calls))

    def test_clean_schema_handles_drop_error_gracefully(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "INFORMATION_SCHEMA.TABLES" in sql and "BASE TABLE" in sql:
                return [{"table_name": "orders"}]
            if "sys.tables" in sql and "temporal_type" in sql:
                return []
            return []

        qe.execute_query.side_effect = query_side_effect
        qe.execute_statement.side_effect = RuntimeError("FK constraint")
        # Should not raise
        ops.clean_schema(conn, "dbo")

    def test_enumerate_clean_candidates_drops_fk_first(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "sys.foreign_keys" in sql:
                return [{"constraint_name": "fk_orders", "table_name": "orders"}]
            if "sys.tables" in sql and "temporal_type" in sql:
                return []
            return []

        qe.execute_query.side_effect = query_side_effect
        candidates = ops.enumerate_clean_candidates(conn, "dbo")
        sqls = [c.sql for c in candidates]
        self.assertTrue(any("DROP CONSTRAINT" in s for s in sqls))

    def test_get_clean_preview_returns_summary(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []
        summary = ops.get_clean_preview(conn, "dbo")
        self.assertIsNotNone(summary)

    def test_temporal_metadata_handles_exception(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("not supported")
        # Should return empty dict, not raise
        result = ops._get_temporal_table_metadata(conn, "dbo")
        self.assertEqual({}, result)

    def test_clean_schema_drops_procedures(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "INFORMATION_SCHEMA.ROUTINES" in sql:
                return [{"routine_name": "sp_dowork", "routine_type": "PROCEDURE"}]
            if "sys.tables" in sql and "temporal_type" in sql:
                return []
            return []

        qe.execute_query.side_effect = query_side_effect
        ops.clean_schema(conn, "dbo")
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP PROCEDURE" in c for c in calls))


# ---------------------------------------------------------------------------
# SqlServerHistoryManager
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# SqlServerLockingManager
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
