"""Unit tests for DB2 plugin: schema_operations, query_executor, history_manager."""

import unittest
from unittest.mock import MagicMock


def _make_connection(auto_commit=False, is_closed=False):
    """Return a mock native connection."""
    conn = MagicMock()
    conn.isClosed.return_value = is_closed
    conn.getAutoCommit.return_value = auto_commit
    stmt = MagicMock()
    stmt.executeUpdate.return_value = 0
    stmt.executeQuery.return_value = MagicMock()
    conn.createStatement.return_value = stmt
    conn.prepareStatement.return_value = stmt
    return conn


# ---------------------------------------------------------------------------
# Db2SchemaOperations
# ---------------------------------------------------------------------------


class TestDb2SchemaOperations(unittest.TestCase):

    def _make_qe(self):
        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 0
        qe.get_quoted_schema_name.side_effect = lambda s: f'"{s}"'
        qe.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
        qe.table_exists.return_value = False
        return qe

    def _make_ops(self, qe=None):
        from dblift.db.plugins.db2.db2.schema_operations import Db2SchemaOperations

        if qe is None:
            qe = self._make_qe()
        log = MagicMock()
        return Db2SchemaOperations(qe, log), qe, log

    # --- create_schema_if_not_exists ---

    def test_create_schema_when_not_exists(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = []  # schema does not exist

        ops.create_schema_if_not_exists(conn, "myschema")

        qe.execute_statement.assert_called_once()
        sql_arg = qe.execute_statement.call_args[0][1]
        self.assertIn("CREATE SCHEMA", sql_arg)

    def test_create_schema_already_exists_skips(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = [{"SCHEMANAME": "myschema"}]

        ops.create_schema_if_not_exists(conn, "myschema")

        qe.execute_statement.assert_not_called()

    def test_create_schema_commits_on_success(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = []

        ops.create_schema_if_not_exists(conn, "newschema")

        conn.commit.assert_called()

    def test_create_schema_rollback_on_execute_error(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = []
        qe.execute_statement.side_effect = RuntimeError("create failed")

        with self.assertRaises(RuntimeError):
            ops.create_schema_if_not_exists(conn, "badschema")

        conn.rollback.assert_called()

    # --- set_current_schema ---

    def test_set_current_schema_calls_execute_statement(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()

        ops.set_current_schema(conn, "myschema")

        qe.execute_statement.assert_called_once()
        sql = qe.execute_statement.call_args[0][1]
        self.assertIn("SET SCHEMA", sql)

    def test_set_current_schema_raises_on_error(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("set schema failed")

        with self.assertRaises(RuntimeError):
            ops.set_current_schema(conn, "myschema")

    # --- get_database_version ---

    def test_get_database_version_reads_driver_connection_dbms_ver(self):
        # No SQL query at all — reads the version the driver already got
        # from the CLI handshake at connect time (avoids the fenced
        # SYSIBMADM.ENV_INST_INFO route entirely; see BUG OBS-01).
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        conn.connection.dbms_ver = "11.05.0900"
        qe.execute_query.side_effect = AssertionError("should not query SYSIBMADM.ENV_INST_INFO")

        result = ops.get_database_version(conn)

        self.assertEqual("DB2 11.05.0900", result)

    def test_get_database_version_fallback_when_dbms_ver_missing(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        conn.connection = None
        qe.execute_query.return_value = [{"DB_NAME": "MYDB"}]

        result = ops.get_database_version(conn)

        self.assertIn("DB2", result)

    def test_get_database_version_on_exception_returns_unknown(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        conn.connection = None
        qe.execute_query.side_effect = RuntimeError("driver error")

        result = ops.get_database_version(conn)

        self.assertEqual("DB2 Unknown Version", result)

    # --- get_tables ---

    def test_get_tables_returns_list(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = [{"table_name": "ORDERS"}, {"table_name": "USERS"}]

        tables = ops.get_tables(conn, "myschema")

        self.assertEqual(["ORDERS", "USERS"], tables)

    def test_get_tables_returns_empty_on_exception(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_query.side_effect = RuntimeError("query failed")

        tables = ops.get_tables(conn, "myschema")

        self.assertEqual([], tables)

    # --- get_schemas ---

    def test_get_schemas_returns_list(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = [{"schema_name": "HR"}, {"schema_name": "SALES"}]

        schemas = ops.get_schemas(conn)

        self.assertIn("HR", schemas)
        self.assertIn("SALES", schemas)

    # --- get_columns_query ---

    def test_get_columns_query_returns_tuple(self):
        ops, qe, log = self._make_ops()
        sql, params = ops.get_columns_query("myschema", "mytable")
        self.assertIn("syscat.columns", sql.lower())
        self.assertEqual(["myschema", "mytable"], params)

    # --- get_add_column_sql ---

    def test_get_add_column_sql_format(self):
        ops, qe, log = self._make_ops()
        sql = ops.get_add_column_sql("myschema", "mytable", "mycolumn", "VARCHAR(100)")
        self.assertIn("ALTER TABLE", sql)
        self.assertIn("ADD COLUMN", sql)
        self.assertIn("mycolumn", sql)

    # --- get_parameter_placeholders ---

    def test_get_parameter_placeholders(self):
        ops, qe, log = self._make_ops()
        result = ops.get_parameter_placeholders(3)
        self.assertEqual("?, ?, ?", result)

    # --- clean_schema ---

    def test_clean_schema_calls_drop_methods(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        # make getAutoCommit return False so the rollback path is tried
        conn.getAutoCommit.return_value = False
        # All query calls return empty lists (nothing to drop)
        qe.execute_query.return_value = []

        summary = ops.clean_schema(conn, "myschema")

        # Verify no crash and summary is returned
        self.assertIsNotNone(summary)

    def test_clean_schema_drops_views(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        conn.getAutoCommit.return_value = True  # auto-commit on

        # Views query returns one view, all others return empty
        def query_side_effect(c, sql, params=None, **kw):
            if "TYPE = 'V'" in sql:
                return [{"TABNAME": "MY_VIEW"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "myschema")

        # execute_statement should have been called for SET SCHEMA + DROP VIEW + commits
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP VIEW" in c for c in calls))

    def test_clean_schema_drops_tables(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        conn.getAutoCommit.return_value = True

        def query_side_effect(c, sql, params=None, **kw):
            if "TYPE = 'T'" in sql and "SYSCAT.TABLES" in sql:
                return [{"TABNAME": "ORDERS"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "myschema")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP TABLE" in c for c in calls))

    def test_clean_schema_rollback_on_error(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()

        # set_current_schema will call execute_statement → raise immediately
        qe.execute_statement.side_effect = RuntimeError("fatal error")
        qe.execute_query.return_value = []

        with self.assertRaises(RuntimeError):
            ops.clean_schema(conn, "myschema")

        conn.rollback.assert_called()

    def test_commit_if_needed_commits_when_auto_commit_false(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection(auto_commit=False)

        ops._commit_if_needed(conn, "test op")

        conn.commit.assert_called_once()

    def test_commit_if_needed_skips_when_auto_commit_true(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection(auto_commit=True)

        ops._commit_if_needed(conn, "test op")

        conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Db2HistoryManager
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
