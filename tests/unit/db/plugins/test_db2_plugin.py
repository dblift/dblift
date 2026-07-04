"""Unit tests for DB2 plugin: schema_operations, query_executor, history_manager."""

import unittest
from unittest.mock import MagicMock, call, patch


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
        from db.plugins.db2.db2.schema_operations import Db2SchemaOperations

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

    # --- private drop helpers ---

    def test_drop_triggers_drops_each_trigger(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        from core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        qe.execute_query.return_value = [{"TRIGNAME": "TR1"}, {"TRIGNAME": "TR2"}]

        ops._drop_triggers(conn, "myschema", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        drop_calls = [c for c in calls if "DROP TRIGGER" in c]
        self.assertEqual(2, len(drop_calls))

    def test_drop_views_drops_each_view(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        from core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        qe.execute_query.return_value = [{"TABNAME": "V1"}]

        ops._drop_views(conn, "myschema", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP VIEW" in c for c in calls))

    def test_drop_sequences_drops_each_sequence(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        from core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        qe.execute_query.return_value = [{"SEQNAME": "SEQ1"}]

        ops._drop_sequences(conn, "myschema", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("DROP SEQUENCE" in c for c in calls))

    def test_drop_tables_skips_none_name(self):
        ops, qe, log = self._make_ops()
        conn = _make_connection()
        from core.migration.clean_summary import CleanExecutionSummary

        summary = CleanExecutionSummary()

        # Row with None TABNAME should be skipped
        qe.execute_query.return_value = [{"TABNAME": None}, {"TABNAME": "T1"}]

        ops._drop_tables(conn, "myschema", summary)

        calls = [str(c) for c in qe.execute_statement.call_args_list]
        drop_calls = [c for c in calls if "DROP TABLE" in c]
        self.assertEqual(1, len(drop_calls))

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


class TestDb2HistoryManager(unittest.TestCase):

    def _make_manager(self):
        from db.plugins.db2.db2.history_manager import Db2HistoryManager

        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 0
        qe.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
        qe.table_exists.return_value = False
        schema_ops = MagicMock()
        config = MagicMock()
        log = MagicMock()
        return Db2HistoryManager(qe, schema_ops, config, log), qe, schema_ops, log

    def _make_connection(self):
        conn = MagicMock()
        conn.isClosed.return_value = False
        conn.getAutoCommit.return_value = False
        return conn

    # --- create_migration_history_table_if_not_exists ---

    def test_create_table_when_not_exists_executes_create(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = False

        mgr.create_migration_history_table_if_not_exists(conn, "myschema")

        qe.execute_statement.assert_called_once()
        sql = qe.execute_statement.call_args[0][1]
        self.assertIn("CREATE TABLE", sql)

    def test_create_table_skips_when_already_exists(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True

        mgr.create_migration_history_table_if_not_exists(conn, "myschema")

        qe.execute_statement.assert_not_called()

    def test_create_table_creates_schema_when_flag_set(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = False

        mgr.create_migration_history_table_if_not_exists(conn, "myschema", create_schema=True)

        schema_ops.create_schema_if_not_exists.assert_called_once_with(conn, "myschema")

    def test_create_table_commits_after_creation(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = False

        mgr.create_migration_history_table_if_not_exists(conn, "myschema")

        conn.commit.assert_called()

    def test_create_table_rollback_on_error(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = False
        qe.execute_statement.side_effect = RuntimeError("create failed")

        with self.assertRaises(RuntimeError):
            mgr.create_migration_history_table_if_not_exists(conn, "myschema")

        conn.rollback.assert_called()

    # --- record_migration ---

    def test_record_migration_inserts_record(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True

        migration_info = {
            "version": "1",
            "description": "initial",
            "type": "SQL",
            "script": "V1__init.sql",
            "checksum": 12345,
            "installed_by": "testuser",
            "execution_time": 100,
            "success": True,
        }

        mgr.record_migration(conn, "myschema", migration_info)

        qe.execute_statement.assert_called_once()
        sql = qe.execute_statement.call_args[0][1]
        self.assertIn("INSERT INTO", sql)

    def test_record_migration_creates_table_if_not_exists(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        # First call: table does not exist; after create it does
        qe.table_exists.side_effect = [False, False]

        migration_info = {"script": "V1.sql", "success": True}

        mgr.record_migration(conn, "myschema", migration_info)

        # create_migration_history_table_if_not_exists should have been called
        # which calls execute_statement for CREATE TABLE
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("CREATE TABLE" in c or "INSERT INTO" in c for c in calls))

    def test_record_migration_converts_bool_to_smallint(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True

        migration_info = {"script": "V1.sql", "success": False}
        mgr.record_migration(conn, "myschema", migration_info)

        params = (
            qe.execute_statement.call_args[1].get("params") or qe.execute_statement.call_args[0][2]
        )
        # success=False should become 0
        self.assertEqual(0, params[-1])

    # --- get_applied_migrations ---

    def test_get_applied_migrations_returns_empty_when_no_table(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = False

        result = mgr.get_applied_migrations(conn, "myschema")

        self.assertEqual([], result)
        qe.execute_query.assert_not_called()

    def test_get_applied_migrations_returns_rows(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True
        qe.execute_query.return_value = [{"script": "V1.sql", "success": 1, "installed_rank": 1}]

        result = mgr.get_applied_migrations(conn, "myschema")

        self.assertEqual(1, len(result))
        # success should be converted to bool
        self.assertTrue(result[0]["success"])

    def test_get_applied_migrations_converts_success_to_bool(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True
        qe.execute_query.return_value = [
            {"script": "V1.sql", "success": 0},
            {"script": "V2.sql", "success": 1},
        ]

        result = mgr.get_applied_migrations(conn, "myschema")

        self.assertFalse(result[0]["success"])
        self.assertTrue(result[1]["success"])

    def test_get_applied_migrations_raises_on_query_error(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True
        qe.execute_query.side_effect = RuntimeError("query error")

        with self.assertRaises(RuntimeError):
            mgr.get_applied_migrations(conn, "myschema")

    # --- create_history_table (SQL generation) ---

    def test_create_history_table_generates_sql(self):
        mgr, qe, schema_ops, log = self._make_manager()
        sql = mgr.create_history_table("myschema", "DBLIFT_SCHEMA_HISTORY")
        self.assertIn("CREATE TABLE", sql)
        self.assertIn("installed_rank", sql)
        self.assertIn("SMALLINT", sql)

    # --- get_current_version ---

    def test_get_current_version_returns_none_when_no_table(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = False

        result = mgr.get_current_version(conn, "myschema")

        self.assertIsNone(result)

    def test_get_current_version_returns_latest(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True
        qe.execute_query.return_value = [{"version": "2"}]

        result = mgr.get_current_version(conn, "myschema")

        self.assertEqual("2", result)

    def test_get_current_version_returns_none_when_empty(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True
        qe.execute_query.return_value = []

        result = mgr.get_current_version(conn, "myschema")

        self.assertIsNone(result)

    # --- migration_exists ---

    def test_migration_exists_returns_true(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = True
        qe.execute_query.return_value = [{"1": 1}]

        result = mgr.migration_exists(conn, "myschema", "1.0")

        self.assertTrue(result)

    def test_migration_exists_returns_false_when_no_table(self):
        mgr, qe, schema_ops, log = self._make_manager()
        conn = self._make_connection()
        qe.table_exists.return_value = False

        result = mgr.migration_exists(conn, "myschema", "1.0")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
