"""Unit tests for Oracle plugin: schema_operations, query_executor."""

import unittest
from unittest.mock import MagicMock, patch


def _make_connection(is_closed=False):
    conn = MagicMock()
    conn.isClosed.return_value = is_closed
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
# OracleSchemaOperations
# ---------------------------------------------------------------------------


class TestOracleSchemaOperations(unittest.TestCase):

    def _make_qe(self):
        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 0
        qe.get_quoted_schema_name.side_effect = lambda s: f'"{s}"'
        qe.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
        return qe

    def _make_ops(self, qe=None):
        from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations

        if qe is None:
            qe = self._make_qe()
        log = MagicMock()
        return OracleSchemaOperations(qe, log), qe, log

    # --- _to_int ---

    def test_to_int_with_plain_int(self):
        from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations

        self.assertEqual(5, OracleSchemaOperations._to_int(5))

    def test_to_int_with_float(self):
        from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations

        self.assertEqual(3, OracleSchemaOperations._to_int(3.9))

    def test_to_int_with_none(self):
        from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations

        self.assertEqual(0, OracleSchemaOperations._to_int(None))

    def test_to_int_with_string(self):
        from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations

        self.assertEqual(7, OracleSchemaOperations._to_int("7"))

    def test_to_int_with_decimal_string(self):
        from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations

        self.assertEqual(2, OracleSchemaOperations._to_int("2.0"))

    def test_to_int_with_non_numeric_returns_zero(self):
        from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations

        self.assertEqual(0, OracleSchemaOperations._to_int("nope"))

    # --- create_schema_if_not_exists ---

    def test_create_schema_skips_when_user_exists(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"user_count": 1}]

        ops.create_schema_if_not_exists(conn, "TESTUSER")

        qe.execute_statement.assert_not_called()

    def test_create_schema_attempts_create_when_not_exists(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"user_count": 0}]

        ops.create_schema_if_not_exists(conn, "NEWUSER")

        # Should attempt to execute CREATE USER
        self.assertTrue(qe.execute_statement.called)

    def test_create_schema_does_not_raise_on_privilege_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"user_count": 0}]
        qe.execute_statement.side_effect = RuntimeError("insufficient privileges")

        # Should NOT raise — privilege errors are swallowed
        try:
            ops.create_schema_if_not_exists(conn, "NEWUSER")
        except RuntimeError:
            self.fail("create_schema_if_not_exists should not propagate privilege errors")

    # --- set_current_schema ---

    def test_set_current_schema_executes_alter_session(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        ops.set_current_schema(conn, "MYSCHEMA")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("ALTER SESSION" in c for c in calls))

    def test_set_current_schema_raises_on_invalid_identifier(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        with self.assertRaises((ValueError, Exception)):
            ops.set_current_schema(conn, "123invalid!")

    def test_set_current_schema_raises_on_executor_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("alter session failed")

        with self.assertRaises(RuntimeError):
            ops.set_current_schema(conn, "MYSCHEMA")

    # --- get_database_version ---

    def test_get_database_version_returns_banner(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"banner": "Oracle Database 19c"}]

        result = ops.get_database_version(conn)

        self.assertIn("Oracle Database 19c", result)

    def test_get_database_version_returns_unknown_on_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("no v$version")

        result = ops.get_database_version(conn)

        self.assertIn("Unknown", result)

    def test_get_database_version_returns_unknown_when_empty(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        result = ops.get_database_version(conn)

        self.assertIn("Unknown", result)

    # --- get_tables ---

    def test_get_tables_returns_list(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"table_name": "ORDERS"}, {"table_name": "USERS"}]

        tables = ops.get_tables(conn, "MYSCHEMA")

        self.assertEqual(["ORDERS", "USERS"], tables)

    def test_get_tables_returns_empty_on_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("query failed")

        tables = ops.get_tables(conn, "MYSCHEMA")

        self.assertEqual([], tables)

    # --- get_schemas ---

    def test_get_schemas_returns_list(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"schema_name": "HR"}, {"schema_name": "OE"}]

        schemas = ops.get_schemas(conn)

        self.assertIn("HR", schemas)

    def test_get_schemas_excludes_ojvmsys(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        ops.get_schemas(conn)

        query = qe.execute_query.call_args[0][1]
        self.assertIn("'OJVMSYS'", query)
        self.assertNotIn("OproviderSYS", query)

    # --- get_columns_query ---

    def test_get_columns_query_format(self):
        ops, qe, log = self._make_ops()
        sql, params = ops.get_columns_query("MYSCHEMA", "MYTABLE")
        self.assertIn("all_tab_columns", sql.lower())
        self.assertEqual(["MYSCHEMA", "MYTABLE"], params)

    # --- get_add_column_sql ---

    def test_get_add_column_sql_format(self):
        ops, qe, log = self._make_ops()
        sql = ops.get_add_column_sql("MYSCHEMA", "MYTABLE", "MYCOLUMN", "VARCHAR2(100)")
        self.assertIn("ALTER TABLE", sql)
        self.assertIn("ADD", sql)
        self.assertIn("MYCOLUMN", sql)

    # --- get_parameter_placeholders ---

    def test_get_parameter_placeholders_oracle_style(self):
        ops, qe, log = self._make_ops()
        result = ops.get_parameter_placeholders(3)
        self.assertIn(":1", result)
        self.assertIn(":2", result)
        self.assertIn(":3", result)

    # --- is_system_generated_sequence ---

    def test_is_system_generated_sequence_iseq_pattern(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        # No need for connection call; name matches pattern
        self.assertTrue(ops.is_system_generated_sequence(conn, "MYSCHEMA", "ISEQ$$_12345"))

    def test_is_system_generated_sequence_user_sequence_false(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"identity_count": 0}]

        result = ops.is_system_generated_sequence(conn, "MYSCHEMA", "SEQ_ORDERS")

        self.assertFalse(result)

    def test_is_system_generated_sequence_false_for_none(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        self.assertFalse(ops.is_system_generated_sequence(conn, "MYSCHEMA", None))

    def test_is_system_generated_sequence_true_when_identity_col(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"identity_count": 1}]

        result = ops.is_system_generated_sequence(conn, "MYSCHEMA", "MY_SEQ")

        self.assertTrue(result)

    # --- clean_schema ---

    def test_clean_schema_calls_set_current_schema(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        summary = ops.clean_schema(conn, "MYSCHEMA")

        # set_current_schema calls execute_statement with ALTER SESSION
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("ALTER SESSION" in c for c in calls))

    def test_clean_schema_drops_views(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "ALL_VIEWS" in sql:
                return [{"view_name": "MY_VIEW"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "MYSCHEMA")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP VIEW" in c for c in calls))

    def test_clean_schema_drops_tables(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()

        def query_side_effect(c, sql, params=None, **kw):
            if "ALL_TABLES" in sql and "BIN$" in sql:
                return [{"table_name": "ORDERS"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        summary = ops.clean_schema(conn, "MYSCHEMA")

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP TABLE" in c for c in calls))

    def test_clean_schema_raises_on_set_current_schema_error(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("alter session failed")

        with self.assertRaises(RuntimeError):
            ops.clean_schema(conn, "MYSCHEMA")

    def test_clean_schema_returns_summary(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []

        from core.migration.clean_summary import CleanExecutionSummary

        summary = ops.clean_schema(conn, "MYSCHEMA")

        self.assertIsInstance(summary, CleanExecutionSummary)

    # --- _drop_db_links ---

    def test_drop_db_links_drops_each_link(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        from core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"db_link": "LINK1", "owner": "MYSCHEMA"}]

        ops._drop_db_links(conn, "MYSCHEMA", "MYSCHEMA", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP DATABASE LINK" in c for c in calls))

    # --- _drop_sequences ---

    def test_drop_sequences_skips_system_generated(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        from core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        qe.execute_query.return_value = [{"sequence_name": "ISEQ$$_99999"}]

        ops._drop_sequences(conn, "MYSCHEMA", "MYSCHEMA", summary)

        # DROP SEQUENCE should NOT be called for system-generated sequences
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertFalse(any("DROP SEQUENCE" in c for c in calls))

    def test_drop_sequences_drops_user_sequences(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        from core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        def query_side_effect(c, sql, params=None, **kw):
            if "ALL_TAB_IDENTITY_COLS" in sql:
                return [{"identity_count": 0}]
            return [{"sequence_name": "ORDER_SEQ"}]

        qe.execute_query.side_effect = query_side_effect

        ops._drop_sequences(conn, "MYSCHEMA", "MYSCHEMA", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP SEQUENCE" in c for c in calls))


if __name__ == "__main__":
    unittest.main()
