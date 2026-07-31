"""Extended unit tests for :class:`db.plugins.db2.db2.schema_operations.Db2SchemaOperations`.

Targets fallback/exception branches not covered by the existing
``test_db2_plugin.py`` test file.
"""

from unittest.mock import MagicMock

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
        conn.connection = None
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

    def test_clean_schema_omits_indexes_dropped_with_tables(self):
        ops, qe, log = _make_ops()
        conn = _make_connection(auto_commit=True)
        qe.execute_query.side_effect = lambda _conn, sql, params=None: (
            [{"TABNAME": "USERS"}] if "SYSCAT.TABLES" in sql and "TYPE = 'T'" in sql else []
        )

        summary = ops.clean_schema(conn, "myschema")

        assert 'DROP TABLE "myschema"."USERS"' in summary.statements
        assert not any("DROP INDEX" in statement for statement in summary.statements)
        assert not any(obj.object_type == "index" for obj in summary.objects)

    def test_catalog_query_failure_is_logged_without_raising(self):
        ops, qe, log = _make_ops()
        conn = _make_connection(auto_commit=False)
        qe.execute_query.side_effect = RuntimeError("triggers query failed")

        summary = ops.clean_schema(conn, "myschema")

        assert not summary.statements
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not query DB2 trigger" in c for c in debug_calls)

    def test_initial_rollback_failure_is_logged_and_clean_continues(self):
        ops, qe, log = _make_ops()
        conn = _make_connection(auto_commit=False)
        conn.rollback.side_effect = RuntimeError("rollback failed")

        summary = ops.clean_schema(conn, "myschema")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Error checking/rolling back transaction" in c for c in debug_calls)
        assert summary is not None


class TestCommitIfNeededExtended:
    def test_getautocommit_exception_logs_debug(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        conn.getAutoCommit.side_effect = RuntimeError("boom")

        ops._commit_if_needed(conn, "test op")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not commit after test op" in c for c in debug_calls)


class TestGetSchemasExtended:
    def test_query_exception_returns_empty_list(self):
        ops, qe, log = _make_ops()
        conn = MagicMock()
        qe.execute_query.side_effect = RuntimeError("query failed")

        result = ops.get_schemas(conn)

        assert result == []
        log.error.assert_called()
