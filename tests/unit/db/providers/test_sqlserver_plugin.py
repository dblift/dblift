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
from unittest.mock import MagicMock, call, patch


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

    def test_set_current_schema_is_noop(self):
        ops, qe, log = self._make_ops()
        conn, _, _ = _make_connection()
        # Should not raise, no execute calls
        ops.set_current_schema(conn, "dbo")
        qe.execute_statement.assert_not_called()

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


class TestSqlServerHistoryManager(unittest.TestCase):

    def _make_qe(self):
        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 1
        qe.table_exists.return_value = True
        qe.get_schema_qualified_name.side_effect = lambda s, n: f"[{s}].[{n}]"
        return qe

    def _make_manager(self, qe=None):
        from db.plugins.sqlserver.sqlserver.history_manager import SqlServerHistoryManager

        if qe is None:
            qe = self._make_qe()
        schema_ops = MagicMock()
        config = MagicMock()
        config.history_table = "dblift_schema_history"
        log = MagicMock()
        log.is_debug_enabled.return_value = False
        return SqlServerHistoryManager(qe, schema_ops, config, log), qe, log

    def test_create_table_if_not_exists_creates_table_when_missing(self):
        manager, qe, log = self._make_manager()
        qe.table_exists.return_value = False
        conn, _, _ = _make_connection()
        manager.create_migration_history_table_if_not_exists(conn, "dbo")
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("CREATE TABLE" in c for c in calls))

    def test_create_table_if_not_exists_skips_when_exists(self):
        manager, qe, log = self._make_manager()
        qe.table_exists.return_value = True
        conn, _, _ = _make_connection()
        manager.create_migration_history_table_if_not_exists(conn, "dbo")
        qe.execute_statement.assert_not_called()

    def test_create_table_creates_schema_when_flag_set(self):
        manager, qe, log = self._make_manager()
        qe.table_exists.return_value = False
        conn, _, _ = _make_connection()
        manager.create_migration_history_table_if_not_exists(conn, "dbo", create_schema=True)
        manager.schema_operations.create_schema_if_not_exists.assert_called_once()

    def test_create_table_raises_on_error(self):
        manager, qe, log = self._make_manager()
        qe.table_exists.return_value = False
        qe.execute_statement.side_effect = RuntimeError("permission denied")
        conn, _, _ = _make_connection()
        with self.assertRaises(RuntimeError):
            manager.create_migration_history_table_if_not_exists(conn, "dbo")

    def test_record_migration_inserts_row(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        info = {
            "version": "1.0",
            "description": "initial",
            "type": "SQL",
            "script": "V1__initial.sql",
            "checksum": 12345,
            "installed_by": "user",
            "installed_on": "2024-01-01",
            "execution_time": 100,
            "success": True,
        }
        manager.record_migration(conn, "dbo", info)
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("INSERT INTO" in c for c in calls))

    def test_record_migration_creates_table_if_missing(self):
        manager, qe, log = self._make_manager()
        qe.table_exists.return_value = False
        conn, _, _ = _make_connection()
        info = {"script": "V1__init.sql", "installed_on": "2024-01-01"}
        manager.record_migration(conn, "dbo", info)
        # Should call create table
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("CREATE TABLE" in c for c in calls))

    def test_record_migration_queries_getdate_when_no_installed_on(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"current_time": "2024-01-01"}]
        info = {"script": "V1__init.sql"}
        manager.record_migration(conn, "dbo", info)
        # execute_query should have been called for GETDATE()
        qe.execute_query.assert_called()

    def test_get_applied_migrations_returns_empty_when_no_table(self):
        manager, qe, log = self._make_manager()
        qe.table_exists.return_value = False
        conn, _, _ = _make_connection()
        result = manager.get_applied_migrations(conn, "dbo")
        self.assertEqual([], result)

    def test_get_applied_migrations_returns_rows(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [
            {
                "script": "V1__init.sql",
                "success": 1,
                "version": "1.0",
                "installed_rank": 1,
                "description": "init",
                "type": "SQL",
                "checksum": 1,
                "installed_by": "user",
                "installed_on": "2024-01-01",
                "execution_time": 10,
            }
        ]
        result = manager.get_applied_migrations(conn, "dbo")
        self.assertEqual(1, len(result))
        self.assertTrue(result[0]["success"])  # bool cast

    def test_get_applied_migrations_raises_on_error(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("query failed")
        with self.assertRaises(RuntimeError):
            manager.get_applied_migrations(conn, "dbo")

    def test_repair_migration_updates_row(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_statement.return_value = 1
        result = manager.repair_migration_history(conn, "dbo", "V1__init.sql", 12345)
        self.assertTrue(result)
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        self.assertTrue(any("UPDATE" in c for c in calls))

    def test_repair_migration_returns_false_when_no_rows_affected(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_statement.return_value = 0
        result = manager.repair_migration_history(conn, "dbo", "V1__init.sql", 12345)
        self.assertFalse(result)

    def test_repair_migration_with_success_value(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_statement.return_value = 1
        result = manager.repair_migration_history(
            conn, "dbo", "V1__init.sql", 12345, success_value=True
        )
        self.assertTrue(result)
        calls = [str(c) for c in qe.execute_statement.call_args_list]
        # The update SQL should include success = ?
        self.assertTrue(any("success" in c.lower() for c in calls))

    def test_repair_migration_raises_on_error(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("SQL error")
        with self.assertRaises(RuntimeError):
            manager.repair_migration_history(conn, "dbo", "V1__init.sql", 12345)

    def test_record_undo_inserts_undo_record(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"description": "initial", "installed_rank": 1}]
        result = manager.record_undo(conn, "dbo", "1.0")
        self.assertTrue(result)

    def test_record_undo_returns_false_when_no_migration_found(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []
        result = manager.record_undo(conn, "dbo", "1.0")
        self.assertFalse(result)

    def test_record_undo_returns_false_on_error(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("SQL error")
        result = manager.record_undo(conn, "dbo", "1.0")
        self.assertFalse(result)

    def test_create_history_table_sql_contains_identity(self):
        manager, qe, log = self._make_manager()
        sql = manager.create_history_table("dbo", "dblift_schema_history")
        self.assertIn("IDENTITY", sql)
        self.assertIn("CREATE TABLE", sql)

    def test_get_first_value_returns_none_on_empty(self):
        manager, qe, log = self._make_manager()
        self.assertIsNone(manager._get_first_value([]))
        self.assertIsNone(manager._get_first_value(None))

    def test_get_first_value_returns_first(self):
        manager, qe, log = self._make_manager()
        result = manager._get_first_value([{"col": 42}])
        self.assertEqual(42, result)


# ---------------------------------------------------------------------------
# SqlServerLockingManager
# ---------------------------------------------------------------------------


class TestSqlServerLockingManager(unittest.TestCase):

    def _make_qe(self):
        qe = MagicMock()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 0
        qe.table_exists.return_value = False
        qe.get_schema_qualified_name.side_effect = lambda s, n: f"[{s}].[{n}]"
        return qe

    def _make_manager(self, qe=None):
        from db.plugins.sqlserver.sqlserver.locking_manager import SqlServerLockingManager

        if qe is None:
            qe = self._make_qe()
        log = MagicMock()
        return SqlServerLockingManager(qe, log), qe, log

    def test_create_lock_table_executes_create_sql(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        manager.create_migration_lock_table_if_not_exists(conn, "dbo")
        qe.execute_statement.assert_called_once()
        sql = qe.execute_statement.call_args[0][1]
        self.assertIn("CREATE TABLE", sql)

    def test_create_lock_table_raises_on_error(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_statement.side_effect = RuntimeError("create failed")
        with self.assertRaises(RuntimeError):
            manager.create_migration_lock_table_if_not_exists(conn, "dbo")

    def test_acquire_lock_returns_true_on_result_zero(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"lock_result": 0}]
        result = manager.acquire_migration_lock(conn, "dbo")
        self.assertTrue(result)

    def test_acquire_lock_returns_true_on_result_one(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"lock_result": 1}]
        result = manager.acquire_migration_lock(conn, "dbo")
        self.assertTrue(result)

    def test_acquire_lock_falls_back_to_table_on_negative_result(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        # Native lock returns -1 (timeout), table fallback succeeds
        qe.execute_query.return_value = [{"lock_result": -1}]
        qe.execute_statement.return_value = 1
        result = manager.acquire_migration_lock(conn, "dbo", wait_timeout_seconds=1.0)
        self.assertTrue(result)

    def test_acquire_lock_falls_back_to_table_on_empty_result(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = []
        qe.execute_statement.return_value = 1
        result = manager.acquire_migration_lock(conn, "dbo", wait_timeout_seconds=1.0)
        self.assertTrue(result)

    def test_acquire_lock_falls_back_on_execute_query_error(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.side_effect = RuntimeError("native lock error")
        qe.execute_statement.return_value = 1
        result = manager.acquire_migration_lock(conn, "dbo", wait_timeout_seconds=1.0)
        self.assertTrue(result)

    def test_acquire_table_based_lock_returns_true(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_statement.return_value = 1
        result = manager._acquire_table_based_lock(conn, "dbo", "dblift_migration_lock_dbo", 60)
        self.assertTrue(result)

    def test_acquire_table_based_lock_returns_false_on_error(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        # create_lock_table is called first; make execute_statement raise on the MERGE
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] > 1:  # After CREATE TABLE
                raise RuntimeError("merge failed")
            return 0

        qe.execute_statement.side_effect = side_effect
        result = manager._acquire_table_based_lock(conn, "dbo", "dblift_migration_lock_dbo", 60)
        self.assertFalse(result)

    def test_release_lock_returns_true_on_native_release(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"release_result": 0}]
        qe.table_exists.return_value = False
        result = manager.release_migration_lock(conn, "dbo")
        self.assertTrue(result)

    def test_release_lock_cleans_up_table_based_lock(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        # Native release fails
        qe.execute_query.return_value = [{"release_result": -999}]
        # Table exists with a lock row
        qe.table_exists.return_value = True
        qe.execute_statement.return_value = 1  # 1 row deleted
        result = manager.release_migration_lock(conn, "dbo")
        self.assertTrue(result)

    def test_release_lock_returns_false_when_nothing_released(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"release_result": -999}]
        qe.table_exists.return_value = True
        qe.execute_statement.return_value = 0  # no rows deleted
        result = manager.release_migration_lock(conn, "dbo")
        self.assertFalse(result)

    def test_release_lock_with_no_table(self):
        manager, qe, log = self._make_manager()
        conn, _, _ = _make_connection()
        qe.execute_query.return_value = [{"release_result": 0}]
        qe.table_exists.return_value = False
        result = manager.release_migration_lock(conn, "dbo")
        self.assertTrue(result)

    def test_nulllog_used_when_no_log(self):
        from core.logger import NullLog
        from db.plugins.sqlserver.sqlserver.locking_manager import SqlServerLockingManager

        qe = self._make_qe()
        manager = SqlServerLockingManager(qe)
        self.assertIsInstance(manager.log, NullLog)


if __name__ == "__main__":
    unittest.main()
