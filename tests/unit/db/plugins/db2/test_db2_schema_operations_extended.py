"""Extended unit tests for :class:`db.plugins.db2.db2.schema_operations.Db2SchemaOperations`.

Targets fallback/exception branches and drop helpers not covered by the existing
``test_db2_plugin.py`` test file.
"""

from unittest.mock import MagicMock

from core.migration.clean_summary import CleanExecutionSummary
from db.plugins.db2.db2.schema_operations import Db2SchemaOperations


def _make_qe():
    qe = MagicMock()
    qe.execute_query.return_value = []
    qe.execute_statement.return_value = 0
    qe.get_quoted_schema_name.side_effect = lambda s: f'"{s}"'
    qe.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
    qe.table_exists.return_value = False
    return qe


def _make_ops(qe=None):
    if qe is None:
        qe = _make_qe()
    log = MagicMock()
    return Db2SchemaOperations(qe, log), qe, log


def _make_connection(auto_commit=False):
    conn = MagicMock()
    conn.getAutoCommit.return_value = auto_commit
    return conn


class TestCreateSchemaIfNotExistsExtended:
    def test_commit_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = []
        conn.commit.side_effect = RuntimeError("commit failed")

        ops.create_schema_if_not_exists(conn, "newschema")

        warning_calls = [str(c) for c in log.warning.call_args_list]
        assert any("Could not commit schema creation" in c for c in warning_calls)

    def test_rollback_also_fails_logs_debug(self):
        ops, qe, log = _make_ops()
        conn = _make_connection()
        qe.execute_query.return_value = []
        qe.execute_statement.side_effect = RuntimeError("create failed")
        conn.rollback.side_effect = RuntimeError("rollback failed")

        try:
            ops.create_schema_if_not_exists(conn, "badschema")
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not rollback DB2 schema creation transaction" in c for c in debug_calls)


class TestGetDatabaseVersionExtended:
    def test_both_queries_empty_returns_unknown(self):
        ops, qe, log = _make_ops()
        conn = _make_connection()
        qe.execute_query.side_effect = [[], []]

        result = ops.get_database_version(conn)

        assert result == "DB2 Unknown Version"


class TestCleanSchemaExtended:
    def test_initial_autocommit_check_failure_logs_debug(self):
        ops, qe, log = _make_ops()
        conn = _make_connection()
        conn.getAutoCommit.side_effect = RuntimeError("autocommit check failed")
        qe.execute_query.return_value = []

        ops.clean_schema(conn, "myschema")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Error checking/rolling back transaction" in c for c in debug_calls)

    def test_final_commit_failure_then_rollback_succeeds(self):
        ops, qe, log = _make_ops()
        conn = _make_connection(auto_commit=False)
        qe.execute_query.return_value = []
        conn.commit.side_effect = RuntimeError("commit failed")

        summary = ops.clean_schema(conn, "myschema")

        assert summary is not None
        warning_calls = [str(c) for c in log.warning.call_args_list]
        assert any("Failed to commit cleanup transaction" in c for c in warning_calls)
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any(
            "Rolled back DB2 cleanup transaction after commit failure" in c for c in debug_calls
        )

    def test_final_commit_failure_then_rollback_also_fails(self):
        ops, qe, log = _make_ops()
        conn = _make_connection(auto_commit=False)
        qe.execute_query.return_value = []
        conn.commit.side_effect = RuntimeError("commit failed")
        conn.rollback.side_effect = RuntimeError("rollback failed")

        summary = ops.clean_schema(conn, "myschema")

        assert summary is not None
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not rollback DB2 cleanup transaction:" in c for c in debug_calls)

    def test_drop_phase_failure_rolls_back_and_raises(self):
        ops, qe, log = _make_ops()
        conn = _make_connection(auto_commit=False)
        qe.execute_query.side_effect = RuntimeError("triggers query failed")

        try:
            ops.clean_schema(conn, "myschema")
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

        conn.rollback.assert_called()
        error_calls = [str(c) for c in log.error.call_args_list]
        assert any("Error cleaning schema" in c for c in error_calls)

    def test_drop_phase_failure_and_rollback_also_fails(self):
        ops, qe, log = _make_ops()
        conn = _make_connection(auto_commit=False)
        qe.execute_query.side_effect = RuntimeError("triggers query failed")
        conn.rollback.side_effect = RuntimeError("rollback failed")

        try:
            ops.clean_schema(conn, "myschema")
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not rollback DB2 transaction after clean error" in c for c in debug_calls)


class TestCommitIfNeededExtended:
    def test_getautocommit_exception_logs_debug(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        conn.getAutoCommit.side_effect = RuntimeError("boom")

        ops._commit_if_needed(conn, "test op")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not commit after test op" in c for c in debug_calls)


class TestDropTriggersExtended:
    def test_drop_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"TRIGNAME": "TR1"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")

        ops._drop_triggers(conn, "myschema", summary)

        log.warning.assert_called()
        assert not summary.statements


class TestDropForeignKeysExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [
            {"CONSTNAME": "FK1", "TABNAME": "ORDERS"},
            {"CONSTNAME": "FK2", "TABNAME": "ITEMS"},
        ]

        def stmt_side_effect(connection, sql):
            if "FK2" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_foreign_keys(conn, "myschema", summary)

        assert any("DROP CONSTRAINT" in s and "FK1" in s for s in summary.statements)
        log.warning.assert_called()


class TestDropViewsExtended:
    def test_drop_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"TABNAME": "V1"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")

        ops._drop_views(conn, "myschema", summary)

        log.warning.assert_called()


class TestDropMaterializedQueryTablesExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"TABNAME": "MQT1"}, {"TABNAME": "MQT2"}]

        def stmt_side_effect(connection, sql):
            if "MQT2" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_materialized_query_tables(conn, "myschema", summary)

        assert any("DROP TABLE" in s and "MQT1" in s for s in summary.statements)
        log.warning.assert_called()


class TestDropTablesExtended:
    def test_drop_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"TABNAME": "T1"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")

        ops._drop_tables(conn, "myschema", summary)

        log.warning.assert_called()


class TestDropMigrationLockTableExtended:
    def test_drops_lock_table_when_present(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.table_exists.return_value = True

        ops._drop_migration_lock_table(conn, "myschema", summary)

        assert any("DROP TABLE" in s for s in summary.statements)

    def test_drop_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.table_exists.return_value = True
        qe.execute_statement.side_effect = RuntimeError("drop failed")

        ops._drop_migration_lock_table(conn, "myschema", summary)

        log.warning.assert_called()


class TestDropAliasesExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"TABNAME": "A1"}, {"TABNAME": "A2"}]

        def stmt_side_effect(connection, sql):
            if "A2" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_aliases(conn, "myschema", summary)

        assert any("DROP ALIAS" in s and "A1" in s for s in summary.statements)
        log.warning.assert_called()


class TestDropSequencesExtended:
    def test_drop_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"SEQNAME": "SEQ1"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")

        ops._drop_sequences(conn, "myschema", summary)

        log.warning.assert_called()


class TestDropFunctionsExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [
            {"FUNCNAME": "F1", "SPECIFICNAME": "F1_SPEC"},
            {"FUNCNAME": "F2", "SPECIFICNAME": "F2_SPEC"},
        ]

        def stmt_side_effect(connection, sql):
            if "F2_SPEC" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_functions(conn, "myschema", summary)

        assert any("DROP SPECIFIC FUNCTION" in s and "F1_SPEC" in s for s in summary.statements)
        log.warning.assert_called()


class TestDropProceduresExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [
            {"PROCNAME": "P1", "SPECIFICNAME": "P1_SPEC"},
            {"PROCNAME": "P2", "SPECIFICNAME": "P2_SPEC"},
        ]

        def stmt_side_effect(connection, sql):
            if "P2_SPEC" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_procedures(conn, "myschema", summary)

        assert any("DROP SPECIFIC PROCEDURE" in s and "P1_SPEC" in s for s in summary.statements)
        log.warning.assert_called()


class TestDropTypesExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"TYPENAME": "TYPE1"}, {"TYPENAME": "TYPE2"}]

        def stmt_side_effect(connection, sql):
            if "TYPE2" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_types(conn, "myschema", summary)

        assert any("DROP TYPE" in s and "TYPE1" in s for s in summary.statements)
        log.warning.assert_called()


class TestDropGlobalTemporaryTablesExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"TABNAME": "GTT1"}, {"TABNAME": "GTT2"}]

        def stmt_side_effect(connection, sql):
            if "GTT2" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_global_temporary_tables(conn, "myschema", summary)

        assert any("DROP TABLE" in s and "GTT1" in s for s in summary.statements)
        log.warning.assert_called()

    def test_query_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.side_effect = RuntimeError("query failed")

        ops._drop_global_temporary_tables(conn, "myschema", summary)

        warning_calls = [str(c) for c in log.warning.call_args_list]
        assert any("Error checking for global temporary tables" in c for c in warning_calls)


class TestDropModulesExtended:
    def test_drop_success_and_failure(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"MODULENAME": "MOD1"}, {"MODULENAME": "MOD2"}]

        def stmt_side_effect(connection, sql):
            if "MOD2" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect

        ops._drop_modules(conn, "myschema", summary)

        assert any("DROP MODULE" in s and "MOD1" in s for s in summary.statements)
        log.warning.assert_called()

    def test_query_failure_logs_warning(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.side_effect = RuntimeError("query failed")

        ops._drop_modules(conn, "myschema", summary)

        warning_calls = [str(c) for c in log.warning.call_args_list]
        assert any("Error checking for modules" in c for c in warning_calls)


class TestDropIndexesExtended:
    def test_drop_success_records_details_with_table(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        summary = CleanExecutionSummary()
        qe.execute_query.return_value = [{"INDNAME": "IDX1", "TABNAME": "ORDERS"}]

        ops._drop_indexes(conn, "myschema", summary)

        assert any("DROP INDEX" in s and "IDX1" in s for s in summary.statements)


class TestGetSchemasExtended:
    def test_query_exception_returns_empty_list(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        qe.execute_query.side_effect = RuntimeError("query failed")

        result = ops.get_schemas(conn)

        assert result == []
        log.error.assert_called()
