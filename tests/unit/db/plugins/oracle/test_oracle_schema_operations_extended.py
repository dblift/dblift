"""Extended unit tests for :class:`db.plugins.oracle.oracle.schema_operations.OracleSchemaOperations`.

Targets fallback/exception branches not covered by the existing
``test_oracle_plugin.py`` / ``test_get_clean_preview_oracle.py`` /
``test_oracle_system_sequence_user_prefix.py`` test files.
"""

from unittest.mock import MagicMock

from core.migration.clean_summary import CleanExecutionSummary
from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations


def _make_qe():
    qe = MagicMock()
    qe.execute_query.return_value = []
    qe.execute_statement.return_value = 0
    qe.get_quoted_schema_name.side_effect = lambda s: f'"{s}"'
    qe.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
    return qe


def _make_ops(qe=None):
    if qe is None:
        qe = _make_qe()
    log = MagicMock()
    return OracleSchemaOperations(qe, log), qe, log


class TestCreateSchemaIfNotExistsFallbacks:
    def test_minimal_create_user_succeeds_grants_minimal_privileges(self):
        ops, qe, log = _make_ops()
        qe.execute_query.return_value = [{"user_count": 0}]

        def stmt_side_effect(connection, sql):
            if "QUOTA UNLIMITED ON USERS" in sql:
                raise RuntimeError("full create failed")
            return 0

        qe.execute_statement.side_effect = stmt_side_effect

        ops.create_schema_if_not_exists(MagicMock(), "NEWUSER")

        calls = [c.args[1] for c in qe.execute_statement.call_args_list]
        assert any("CREATE ANY TABLE, CREATE ANY VIEW" in c for c in calls)

    def test_existing_user_full_grant_succeeds(self):
        ops, qe, log = _make_ops()
        qe.execute_query.return_value = [{"user_count": 0}]

        def stmt_side_effect(connection, sql):
            if "CREATE USER" in sql:
                raise RuntimeError("create failed")
            return 0

        qe.execute_statement.side_effect = stmt_side_effect

        ops.create_schema_if_not_exists(MagicMock(), "EXISTINGUSER")

        calls = [c.args[1] for c in qe.execute_statement.call_args_list]
        assert any(
            "RESOURCE, CREATE TABLE, CREATE VIEW, CREATE MATERIALIZED VIEW, "
            "CREATE DATABASE LINK, UNLIMITED TABLESPACE" in c
            for c in calls
        )

    def test_existing_user_object_privilege_grant_succeeds(self):
        ops, qe, log = _make_ops()
        qe.execute_query.return_value = [{"user_count": 0}]

        def stmt_side_effect(connection, sql):
            if "CREATE USER" in sql:
                raise RuntimeError("create failed")
            if "RESOURCE, CREATE TABLE" in sql:
                raise RuntimeError("first grant failed")
            return 0

        qe.execute_statement.side_effect = stmt_side_effect

        ops.create_schema_if_not_exists(MagicMock(), "EXISTINGUSER")

        calls = [c.args[1] for c in qe.execute_statement.call_args_list]
        assert any("CREATE ANY TABLE, CREATE ANY VIEW, CREATE ANY PROCEDURE" in c for c in calls)

    def test_existing_user_unlimited_tablespace_grant_succeeds(self):
        ops, qe, log = _make_ops()
        qe.execute_query.return_value = [{"user_count": 0}]

        def stmt_side_effect(connection, sql):
            if "CREATE USER" in sql:
                raise RuntimeError("create failed")
            if "RESOURCE, CREATE TABLE" in sql or "CREATE ANY TABLE, CREATE ANY VIEW" in sql:
                raise RuntimeError("grant failed")
            return 0

        qe.execute_statement.side_effect = stmt_side_effect

        ops.create_schema_if_not_exists(MagicMock(), "EXISTINGUSER")

        calls = [c.args[1] for c in qe.execute_statement.call_args_list]
        assert any(c.strip() == 'GRANT UNLIMITED TABLESPACE TO "EXISTINGUSER"' for c in calls)

    def test_existing_user_all_grants_fail_logs_debug(self):
        ops, qe, log = _make_ops()
        qe.execute_query.return_value = [{"user_count": 0}]
        qe.execute_statement.side_effect = RuntimeError("ORA-01031: insufficient privileges")

        ops.create_schema_if_not_exists(MagicMock(), "EXISTINGUSER")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not grant privileges and quota" in c for c in debug_calls)
        assert any("Could not grant object privileges and quota" in c for c in debug_calls)
        assert any("Could not grant UNLIMITED TABLESPACE" in c for c in debug_calls)

    def test_check_user_query_failure_logs_error(self):
        ops, qe, log = _make_ops()
        qe.execute_query.side_effect = RuntimeError("connection lost")

        ops.create_schema_if_not_exists(MagicMock(), "ANYUSER")

        error_calls = [str(c) for c in log.error.call_args_list]
        assert any("Error creating schema" in c for c in error_calls)


class TestGetCleanPreviewExceptions:
    def _qe_failing_on(self, fail_substring):
        qe = _make_qe()

        def query_side_effect(connection, sql, params=None):
            if fail_substring in sql:
                raise RuntimeError("query failed")
            return []

        qe.execute_query.side_effect = query_side_effect
        return qe

    def test_db_links_query_failure_logs_debug(self):
        ops, qe, log = _make_ops(self._qe_failing_on("ALL_DB_LINKS"))

        summary = ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        assert summary is not None
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("DB links" in c for c in debug_calls)

    def test_views_query_failure_logs_debug(self):
        ops, qe, log = _make_ops(self._qe_failing_on("ALL_VIEWS"))

        ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("views" in c for c in debug_calls)

    def test_materialized_views_query_failure_logs_debug(self):
        ops, qe, log = _make_ops(self._qe_failing_on("ALL_MVIEWS"))

        ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("materialized views" in c for c in debug_calls)

    def test_tables_query_failure_logs_debug(self):
        ops, qe, log = _make_ops(self._qe_failing_on("ALL_TABLES"))

        ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("tables" in c for c in debug_calls)

    def test_sequences_query_failure_logs_debug(self):
        ops, qe, log = _make_ops(self._qe_failing_on("ALL_SEQUENCES"))

        ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("sequences" in c for c in debug_calls)

    def test_program_objects_query_failure_logs_debug(self):
        ops, qe, log = _make_ops(self._qe_failing_on("DECODE(object_type"))

        ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("program objects" in c for c in debug_calls)

    def test_program_objects_type_gets_force_suffix(self):
        qe = _make_qe()

        def query_side_effect(connection, sql, params=None):
            if "DECODE(object_type" in sql:
                return [{"object_name": "MY_TYPE", "object_type": "TYPE"}]
            return []

        qe.execute_query.side_effect = query_side_effect
        ops, qe, log = _make_ops(qe)

        summary = ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        assert any("DROP TYPE" in s and "FORCE" in s for s in summary.statements)

    def test_synonyms_query_failure_logs_debug(self):
        ops, qe, log = _make_ops(self._qe_failing_on("ALL_SYNONYMS"))

        ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("synonyms" in c for c in debug_calls)

    def test_remaining_objects_query_failure_logs_debug(self):
        qe = _make_qe()

        def query_side_effect(connection, sql, params=None):
            if "TRIGGER" in sql:
                raise RuntimeError("query failed")
            return []

        qe.execute_query.side_effect = query_side_effect
        ops, qe, log = _make_ops(qe)

        ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("remaining objects" in c for c in debug_calls)

    def test_remaining_objects_lists_trigger(self):
        qe = _make_qe()

        def query_side_effect(connection, sql, params=None):
            if "TRIGGER" in sql:
                return [{"object_name": "TRIG1", "object_type": "TRIGGER"}]
            return []

        qe.execute_query.side_effect = query_side_effect
        ops, qe, log = _make_ops(qe)

        summary = ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        assert any("DROP TRIGGER" in s and "TRIG1" in s for s in summary.statements)


class TestDropDbLinks:
    def test_drop_failure_records_error(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"db_link": "MYLINK", "owner": "MYSCHEMA"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_db_links(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert summary.errors
        log.warning.assert_called()

    def test_query_failure_logs_debug(self):
        qe = _make_qe()
        qe.execute_query.side_effect = RuntimeError("query failed")
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_db_links(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not query private database links" in c for c in debug_calls)


class TestDropViews:
    def test_drop_failure_records_error(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"view_name": "V1"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_views(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert summary.errors
        log.warning.assert_called()


class TestDropMaterializedViews:
    def test_drops_and_records_failure(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"mview_name": "MV1"}, {"mview_name": "MV2"}]

        def stmt_side_effect(connection, sql):
            if "MV2" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_materialized_views(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert any("DROP MATERIALIZED VIEW" in s for s in summary.statements)
        assert summary.errors
        log.warning.assert_called()


class TestDropTables:
    def test_ref_partition_query_failure_falls_back_to_simple_drop(self):
        qe = _make_qe()

        def query_side_effect(connection, sql, params=None):
            if "all_part_tables" in sql:
                raise RuntimeError("query failed")
            if "ALL_TABLES" in sql:
                return [{"table_name": "ORDERS"}]
            return []

        qe.execute_query.side_effect = query_side_effect
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_tables(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert any("DROP TABLE" in s and "ORDERS" in s for s in summary.statements)
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("reference-partitioned table relationships" in c for c in debug_calls)

    def test_drops_children_before_parents_and_records_failure(self):
        qe = _make_qe()

        def query_side_effect(connection, sql, params=None):
            if "all_part_tables" in sql:
                return [{"child_table": "CHILD", "parent_table": "PARENT"}]
            if "ALL_TABLES" in sql:
                return [{"table_name": "PARENT"}, {"table_name": "CHILD"}]
            return []

        qe.execute_query.side_effect = query_side_effect

        def stmt_side_effect(connection, sql):
            if "CHILD" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_tables(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert summary.errors
        assert any("DROP TABLE" in s and "PARENT" in s for s in summary.statements)

    def test_second_pass_drop_failure_is_recorded(self):
        qe = _make_qe()

        def query_side_effect(connection, sql, params=None):
            if "all_part_tables" in sql:
                return []
            if "ALL_TABLES" in sql:
                return [{"table_name": "ORDERS"}]
            return []

        qe.execute_query.side_effect = query_side_effect
        qe.execute_statement.side_effect = RuntimeError("drop failed")
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_tables(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert summary.errors
        log.warning.assert_called()


class TestDropSequences:
    def test_drop_failure_records_error(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"sequence_name": "SEQ1"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_sequences(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert summary.errors
        log.warning.assert_called()


class TestDropProgramObjects:
    def test_drops_type_with_force_and_records_failure(self):
        qe = _make_qe()
        qe.execute_query.return_value = [
            {"object_name": "MY_TYPE", "object_type": "TYPE"},
            {"object_name": "MY_PROC", "object_type": "PROCEDURE"},
        ]

        def stmt_side_effect(connection, sql):
            if "MY_PROC" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_program_objects(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert any("DROP TYPE" in s and "FORCE" in s for s in summary.statements)
        assert summary.errors
        log.warning.assert_called()


class TestDropSynonyms:
    def test_drop_failure_records_error(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"synonym_name": "SYN1"}]
        qe.execute_statement.side_effect = RuntimeError("drop failed")
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_synonyms(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert summary.errors
        log.warning.assert_called()

    def test_drop_success_records_drop(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"synonym_name": "SYN1"}]
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_synonyms(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert any("DROP SYNONYM" in s and "SYN1" in s for s in summary.statements)
        assert not summary.errors


class TestDropRemainingObjects:
    def test_drops_and_logs_debug_on_failure(self):
        qe = _make_qe()
        qe.execute_query.return_value = [
            {"object_name": "TRIG1", "object_type": "TRIGGER"},
            {"object_name": "PROC1", "object_type": "PROCEDURE"},
        ]

        def stmt_side_effect(connection, sql):
            if "PROC1" in sql:
                raise RuntimeError("drop failed")
            return 1

        qe.execute_statement.side_effect = stmt_side_effect
        ops, qe, log = _make_ops(qe)
        summary = CleanExecutionSummary()

        ops._drop_remaining_objects(MagicMock(), "MYSCHEMA", "MYSCHEMA", summary)

        assert any("DROP TRIGGER" in s for s in summary.statements)
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Could not drop" in c for c in debug_calls)


class TestIsSystemGeneratedSequenceExtended:
    def test_identity_check_query_exception_falls_back_to_false(self):
        qe = _make_qe()
        qe.execute_query.side_effect = RuntimeError("query failed")
        ops, qe, log = _make_ops(qe)

        result = ops.is_system_generated_sequence(MagicMock(), "MYSCHEMA", "USER_SEQ")

        assert result is False
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("Identity column query failed" in c for c in debug_calls)


class TestGetActualObjectNameExtended:
    def test_view_object_type(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"table_name": "MY_VIEW"}]
        ops, qe, log = _make_ops(qe)

        result = ops.get_actual_object_name(MagicMock(), "MYSCHEMA", "my_view", object_type="VIEW")

        assert result == "MY_VIEW"
        sql = qe.execute_query.call_args[0][1]
        assert "ALL_VIEWS" in sql

    def test_sequence_object_type(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"table_name": "MY_SEQ"}]
        ops, qe, log = _make_ops(qe)

        result = ops.get_actual_object_name(
            MagicMock(), "MYSCHEMA", "my_seq", object_type="SEQUENCE"
        )

        assert result == "MY_SEQ"
        sql = qe.execute_query.call_args[0][1]
        assert "ALL_SEQUENCES" in sql

    def test_generic_object_type_found(self):
        qe = _make_qe()
        qe.execute_query.return_value = [{"table_name": "MY_TRIGGER"}]
        ops, qe, log = _make_ops(qe)

        result = ops.get_actual_object_name(
            MagicMock(), "MYSCHEMA", "my_trigger", object_type="TRIGGER"
        )

        assert result == "MY_TRIGGER"
        sql = qe.execute_query.call_args[0][1]
        assert "ALL_OBJECTS" in sql

    def test_generic_object_type_not_found(self):
        qe = _make_qe()
        qe.execute_query.return_value = []
        ops, qe, log = _make_ops(qe)

        result = ops.get_actual_object_name(
            MagicMock(), "MYSCHEMA", "my_trigger", object_type="TRIGGER"
        )

        assert result is None

    def test_query_exception_returns_none(self):
        qe = _make_qe()
        qe.execute_query.side_effect = RuntimeError("query failed")
        ops, qe, log = _make_ops(qe)

        result = ops.get_actual_object_name(MagicMock(), "MYSCHEMA", "my_table")

        assert result is None
        log.error.assert_called()


class TestGetSchemasExtended:
    def test_query_exception_returns_empty_list(self):
        qe = _make_qe()
        qe.execute_query.side_effect = RuntimeError("query failed")
        ops, qe, log = _make_ops(qe)

        assert ops.get_schemas(MagicMock()) == []
        log.error.assert_called()
