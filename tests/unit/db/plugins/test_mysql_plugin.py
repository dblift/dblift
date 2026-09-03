"""Unit tests for MySQL plugin: schema_operations, query_executor, history_manager."""

import unittest
from unittest.mock import MagicMock


def _make_connection(auto_commit=True, is_closed=False):
    conn = MagicMock()
    conn.isClosed.return_value = is_closed
    conn.getAutoCommit.return_value = auto_commit
    stmt = MagicMock()
    stmt.executeUpdate.return_value = 0
    rs = MagicMock()
    rs.next.side_effect = [False]
    rs.getMetaData.return_value = MagicMock(getColumnCount=MagicMock(return_value=0))
    stmt.executeQuery.return_value = rs
    conn.createStatement.return_value = stmt
    conn.prepareStatement.return_value = stmt
    return conn, stmt, rs


# ---------------------------------------------------------------------------
# MySqlSchemaOperations
# ---------------------------------------------------------------------------


class TestMySqlSchemaOperations(unittest.TestCase):

    def _make_qe(self):
        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 0
        qe.get_quoted_schema_name.side_effect = lambda s: f"`{s}`"
        qe.get_schema_qualified_name.side_effect = lambda s, n: f"`{s}`.`{n}`"
        return qe

    def _make_ops(self, qe=None):
        from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations

        if qe is None:
            qe = self._make_qe()
        log = MagicMock()
        return MySqlSchemaOperations(qe, log), qe, log

    # --- create_schema_if_not_exists ---

    def test_create_schema_when_not_exists(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []  # DB does not exist

        ops.create_schema_if_not_exists(conn, "mydb")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("CREATE DATABASE" in c for c in calls))

    def test_create_schema_when_already_exists_skips_create(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"SCHEMA_NAME": "mydb"}]

        ops.create_schema_if_not_exists(conn, "mydb")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertFalse(any("CREATE DATABASE" in c for c in calls))

    def test_create_schema_always_calls_set_current_schema(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        ops.create_schema_if_not_exists(conn, "mydb")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("USE" in c for c in calls))

    # --- set_current_schema ---

    def test_set_current_schema_executes_use(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        ops.set_current_schema(conn, "mydb")

        qe.execute_statement.assert_called_once()
        sql = qe.execute_statement.call_args[0][1]
        self.assertIn("USE", sql)

    def test_set_current_schema_raises_on_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("unknown database")

        with self.assertRaises(RuntimeError):
            ops.set_current_schema(conn, "baddb")

    # --- get_database_version ---

    def test_get_database_version_returns_mysql_prefix(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"version": "8.0.27"}]

        result = ops.get_database_version(conn)

        self.assertIn("MySQL", result)
        self.assertIn("8.0.27", result)

    def test_get_database_version_on_error_returns_unknown(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("version query failed")

        result = ops.get_database_version(conn)

        self.assertIn("Unknown", result)

    # --- get_tables ---

    def test_get_tables_returns_list(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"table_name": "orders"}, {"table_name": "users"}]

        tables = ops.get_tables(conn, "mydb")

        self.assertEqual(["orders", "users"], tables)

    def test_get_tables_returns_empty_on_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("query failed")

        tables = ops.get_tables(conn, "mydb")

        self.assertEqual([], tables)

    # --- get_schemas ---

    def test_get_schemas_returns_list(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"schema_name": "mydb"}]

        schemas = ops.get_schemas(conn)

        self.assertIn("mydb", schemas)

    # --- get_columns_query ---

    def test_get_columns_query_contains_schema_and_table(self):
        ops, qe, log = self._make_ops()
        sql = ops.get_columns_query("mydb", "orders")
        self.assertIn("mydb", sql)
        self.assertIn("orders", sql)
        self.assertIn("COLUMN_NAME", sql)

    def test_get_columns_query_includes_column_type(self):
        """BUG-01: COLUMN_TYPE must be included to get full ENUM member list."""
        ops, qe, log = self._make_ops()
        sql = ops.get_columns_query("mydb", "orders")
        self.assertIn("COLUMN_TYPE", sql.upper())

    # --- get_add_column_sql ---

    def test_get_add_column_sql_uses_backtick(self):
        ops, qe, log = self._make_ops()
        sql = ops.get_add_column_sql("mydb", "orders", "status", "VARCHAR(50)")
        self.assertIn("ALTER TABLE", sql)
        self.assertIn("ADD COLUMN", sql)
        self.assertIn("`status`", sql)

    # --- get_parameter_placeholders ---

    def test_get_parameter_placeholders(self):
        ops, qe, log = self._make_ops()
        result = ops.get_parameter_placeholders(3)
        self.assertEqual("?, ?, ?", result)

    # --- clean_schema ---

    def test_clean_schema_disables_fk_checks(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        summary = ops.clean_schema(conn, "mydb")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("FOREIGN_KEY_CHECKS" in c for c in calls))

    def test_clean_schema_re_enables_fk_checks(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        summary = ops.clean_schema(conn, "mydb")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        fk_calls = [c for c in calls if "FOREIGN_KEY_CHECKS" in c]
        # Should have both SET FOREIGN_KEY_CHECKS = 0 and = 1
        self.assertGreaterEqual(len(fk_calls), 2)

    def test_clean_schema_drops_views(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "information_schema.VIEWS" in sql:
                return [{"TABLE_NAME": "myview"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "mydb")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP VIEW" in c for c in calls))

    def test_clean_schema_drops_tables(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "information_schema.TABLES" in sql and "BASE TABLE" in sql:
                return [{"TABLE_NAME": "orders"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "mydb")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP TABLE" in c for c in calls))

    def test_clean_schema_records_drops_from_lowercase_metadata_keys(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "information_schema.TABLES" in sql and "BASE TABLE" in sql:
                return [{"table_name": "orders"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "mydb")

        self.assertEqual(1, len(summary.objects))
        self.assertEqual("orders", summary.objects[0].name)
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP TABLE" in c for c in calls))

    def test_clean_schema_returns_summary(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        from dblift.core.migration.clean_summary import CleanExecutionSummary

        summary = ops.clean_schema(conn, "mydb")

        self.assertIsInstance(summary, CleanExecutionSummary)

    def test_clean_schema_raises_on_fatal_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        # set_current_schema will fail immediately
        qe.execute_statement.side_effect = RuntimeError("fatal")
        qe.execute_query.return_value = []

        with self.assertRaises(RuntimeError):
            ops.clean_schema(conn, "mydb")

    def test_clean_schema_commits_when_autocommit_false(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection(auto_commit=False)
        qe.execute_query.return_value = []

        summary = ops.clean_schema(conn, "mydb")

        conn.commit.assert_called()

    # --- _drop_triggers ---

    def test_drop_triggers_drops_each_trigger(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        from dblift.core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        qe.execute_query.return_value = [{"TRIGGER_NAME": "TR1"}, {"TRIGGER_NAME": "TR2"}]

        ops._drop_triggers(conn, "mydb", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        drop_calls = [c for c in calls if "DROP TRIGGER" in c]
        self.assertEqual(2, len(drop_calls))


# ---------------------------------------------------------------------------
# MySqlHistoryManager
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main()
