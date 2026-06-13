"""
Unit tests for SqlExecutionService.

Covers:
  - T-SQL batch separator skipping (GO)
  - Short vs long statement logging
  - Journal start/complete/failed recording
  - QUERY statement type path (execute_query, returns True + result_set)
  - DDL statement type path (execute_statement, returns False + rows)
  - DML statement type path (execute_statement, returns False + rows)
  - Unknown/fallback statement type path
  - Exception handling + re-raise + error logging
  - Oracle DDL normalization (when provider has _normalize_ddl_for_oracle)
  - Object changes recording via journal (DDL path, parser_factory)
  - _extract_table_from_dml (INSERT / UPDATE / DELETE)
  - _extract_simple_table_name (qualified, quoted, bracket, backtick)
"""

import unittest
from unittest.mock import MagicMock, call, patch

import pytest

from core.migration.sql.sql_execution_service import SqlExecutionService
from core.sql_model.base import SqlStatementType
from db.plugins.sqlserver.quirks import SqlserverQuirks

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(
    stmt_type=SqlStatementType.DDL.value,
    has_journal=False,
    has_oracle_normalize=False,
    has_parser_factory=False,
    schema="public",
):
    spec = ["execute_query", "execute_statement"]
    if has_oracle_normalize:
        spec = [*spec, "_normalize_ddl_for_oracle"]
    provider = MagicMock(spec=spec)
    provider.execute_query.return_value = [{"col": "val"}]
    provider.execute_statement.return_value = 1

    if has_oracle_normalize:
        provider._normalize_ddl_for_oracle = MagicMock(side_effect=lambda s: s)

    sql_analyzer = MagicMock()
    sql_analyzer.get_statement_type.return_value = stmt_type

    if has_parser_factory:
        sql_analyzer.parser_factory = MagicMock()
        sql_analyzer.parser_factory.extract_objects.return_value = []
    else:
        # Ensure parser_factory is NOT present
        del sql_analyzer.parser_factory

    logger = MagicMock()

    journal = None
    if has_journal:
        journal = MagicMock()
        journal.record_statement_start = MagicMock()
        journal.record_statement_complete = MagicMock()
        journal.record_statement_failed = MagicMock()

    svc = SqlExecutionService(
        provider=provider,
        sql_analyzer=sql_analyzer,
        logger=logger,
        journal=journal,
        schema=schema,
        quirks=SqlserverQuirks(),
    )
    return svc, provider, sql_analyzer, logger, journal


# ===========================================================================
# T-SQL batch separator
# ===========================================================================


class TestTsqlBatchSeparator(unittest.TestCase):

    def test_go_statement_skipped(self):
        svc, provider, sql_analyzer, logger, journal = _make_service()
        is_query, result = svc.execute_statement("GO")
        assert is_query is False
        assert result == 0
        provider.execute_statement.assert_not_called()
        provider.execute_query.assert_not_called()

    def test_go_lowercase_skipped(self):
        svc, provider, _, _, _ = _make_service()
        is_query, result = svc.execute_statement("go")
        assert is_query is False
        assert result == 0

    def test_go_with_whitespace_skipped(self):
        svc, provider, _, _, _ = _make_service()
        is_query, result = svc.execute_statement("  GO  ")
        assert is_query is False
        assert result == 0


# ===========================================================================
# Statement logging
# ===========================================================================


class TestStatementLogging(unittest.TestCase):

    def test_short_statement_logs_debug(self):
        svc, _, _, logger, _ = _make_service(stmt_type=SqlStatementType.DDL.value)
        svc.execute_statement("SELECT 1")
        # Short statement previews are debug-only; --show-sql owns user-visible SQL.
        logger.info.assert_not_called()
        debug_calls = " ".join(str(c) for c in logger.debug.call_args_list)
        assert "SELECT 1" in debug_calls

    def test_long_statement_logs_debug_preview(self):
        svc, _, _, logger, _ = _make_service(stmt_type=SqlStatementType.DDL.value)
        long_sql = "SELECT " + "x" * 200
        svc.execute_statement(long_sql)
        debug_calls = " ".join(str(c) for c in logger.debug.call_args_list)
        assert "preview" in debug_calls.lower() or "Executing" in debug_calls


# ===========================================================================
# QUERY statement type
# ===========================================================================


class TestQueryStatementType(unittest.TestCase):

    def test_returns_true_and_result_set(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.QUERY.value)
        is_query, result = svc.execute_statement("SELECT 1")
        assert is_query is True
        assert result == [{"col": "val"}]
        provider.execute_query.assert_called_once()

    def test_empty_result_set_returns_true_and_empty(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.QUERY.value)
        provider.execute_query.return_value = []
        is_query, result = svc.execute_statement("SELECT 1 WHERE 1=0")
        assert is_query is True
        assert result == []

    def test_none_result_set_handled(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.QUERY.value)
        provider.execute_query.return_value = None
        is_query, result = svc.execute_statement("SELECT 1 WHERE 1=0")
        assert is_query is True

    def test_journal_records_query_complete(self):
        svc, _, _, _, journal = _make_service(
            stmt_type=SqlStatementType.QUERY.value, has_journal=True
        )
        svc.execute_statement("SELECT 1", stmt_index=0)
        journal.record_statement_start.assert_called_once()
        journal.record_statement_complete.assert_called_once()

    def test_params_passed_to_execute_query(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.QUERY.value)
        svc.execute_statement("SELECT $1", params=["value"])
        _, kwargs = provider.execute_query.call_args
        assert kwargs.get("params") == ["value"]


# ===========================================================================
# DDL statement type
# ===========================================================================


class TestDdlStatementType(unittest.TestCase):

    def test_returns_false_and_row_count(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.DDL.value)
        is_query, result = svc.execute_statement("CREATE TABLE t (id INT)")
        assert is_query is False
        assert result == 1
        provider.execute_statement.assert_called_once()

    def test_schema_passed_to_provider(self):
        svc, provider, _, _, _ = _make_service(
            stmt_type=SqlStatementType.DDL.value, schema="myschema"
        )
        svc.execute_statement("CREATE TABLE t (id INT)")
        _, kwargs = provider.execute_statement.call_args
        assert kwargs.get("schema") == "myschema"

    def test_journal_records_ddl_complete(self):
        svc, provider, _, _, journal = _make_service(
            stmt_type=SqlStatementType.DDL.value, has_journal=True
        )
        svc.execute_statement("DROP TABLE t", stmt_index=2)
        journal.record_statement_complete.assert_called_once()

    def test_oracle_normalize_called(self):
        svc, provider, _, _, _ = _make_service(
            stmt_type=SqlStatementType.DDL.value, has_oracle_normalize=True
        )
        svc.execute_statement("CREATE TABLE t (id NUMBER)")
        provider._normalize_ddl_for_oracle.assert_called_once()

    def test_oracle_normalize_modified_statement_used(self):
        """When oracle normalizer returns a different statement, that statement is executed."""
        # Build manually so we control side_effect vs return_value precisely
        provider = MagicMock()
        provider.execute_statement.return_value = 1
        original_sql = "CREATE TABLE t (id INT)"
        normalized_sql = "CREATE TABLE t (id NUMBER(10,0))"
        # side_effect must NOT be set — return_value alone is sufficient
        provider._normalize_ddl_for_oracle = MagicMock(return_value=normalized_sql)

        sql_analyzer = MagicMock()
        sql_analyzer.get_statement_type.return_value = SqlStatementType.DDL.value
        # No parser_factory to keep DDL path simple
        if hasattr(sql_analyzer, "parser_factory"):
            del sql_analyzer.parser_factory

        svc = SqlExecutionService(provider=provider, sql_analyzer=sql_analyzer)
        svc.execute_statement(original_sql)
        call_args = provider.execute_statement.call_args[0]
        # The normalized (different) SQL must have been passed to execute_statement
        assert call_args[0] == normalized_sql

    def test_object_changes_recorded_with_parser_factory(self):
        """When parser_factory is available and returns objects, record_object_changes called."""
        from core.sql_model.base import SqlObject, SqlObjectType

        svc, provider, sql_analyzer, _, journal = _make_service(
            stmt_type=SqlStatementType.DDL.value,
            has_journal=True,
            has_parser_factory=True,
        )
        mock_obj = SqlObject(name="my_table", object_type=SqlObjectType.TABLE, schema="public")
        sql_analyzer.parser_factory.extract_objects.return_value = [mock_obj]
        svc.execute_statement("CREATE TABLE my_table (id INT)", stmt_index=0)
        journal.record_object_changes.assert_called_once()


# ===========================================================================
# DML statement type
# ===========================================================================


class TestDmlStatementType(unittest.TestCase):

    def test_returns_false_and_row_count(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.DML.value)
        is_query, result = svc.execute_statement("INSERT INTO t VALUES (1)")
        assert is_query is False
        assert result == 1

    def test_journal_records_dml_complete(self):
        svc, _, _, _, journal = _make_service(
            stmt_type=SqlStatementType.DML.value, has_journal=True
        )
        svc.execute_statement("DELETE FROM t WHERE id=1", stmt_index=3)
        journal.record_statement_complete.assert_called_once()

    def test_params_passed_to_provider(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.DML.value)
        svc.execute_statement("UPDATE t SET x=$1", params=[99])
        _, kwargs = provider.execute_statement.call_args
        assert kwargs.get("params") == [99]


# ===========================================================================
# Unknown/fallback statement type
# ===========================================================================


class TestUnknownStatementType(unittest.TestCase):

    def test_fallback_calls_execute_statement(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.UNKNOWN.value)
        is_query, result = svc.execute_statement("PRAGMA foreign_keys=ON")
        assert is_query is False
        provider.execute_statement.assert_called_once()

    def test_journal_records_unknown_complete(self):
        svc, _, _, _, journal = _make_service(
            stmt_type=SqlStatementType.UNKNOWN.value, has_journal=True
        )
        svc.execute_statement("PRAGMA x", stmt_index=7)
        journal.record_statement_complete.assert_called_once()


# ===========================================================================
# Exception handling
# ===========================================================================


class TestExceptionHandling(unittest.TestCase):

    def test_exception_reraises(self):
        svc, provider, _, _, _ = _make_service(stmt_type=SqlStatementType.DDL.value)
        provider.execute_statement.side_effect = RuntimeError("db error")
        with self.assertRaises(RuntimeError):
            svc.execute_statement("CREATE TABLE x (id INT)")

    def test_error_logged_on_exception(self):
        svc, provider, _, logger, _ = _make_service(stmt_type=SqlStatementType.DDL.value)
        provider.execute_statement.side_effect = RuntimeError("bad sql")
        try:
            svc.execute_statement("BAD SQL")
        except RuntimeError:
            pass
        logger.error.assert_has_calls([call("SQL: BAD SQL"), call("bad sql")])

    def test_journal_records_failure_on_exception(self):
        svc, provider, _, _, journal = _make_service(
            stmt_type=SqlStatementType.DDL.value, has_journal=True
        )
        provider.execute_statement.side_effect = RuntimeError("oops")
        try:
            svc.execute_statement("DROP TABLE x", stmt_index=9)
        except RuntimeError:
            pass
        journal.record_statement_failed.assert_called_once()

    def test_sqlstate_included_in_error_when_available(self):
        svc, provider, _, logger, _ = _make_service(stmt_type=SqlStatementType.DDL.value)
        exc = RuntimeError("error")
        exc.sqlstate = "42000"
        provider.execute_statement.side_effect = exc
        try:
            svc.execute_statement("BAD")
        except RuntimeError:
            pass
        error_text = " ".join(str(c) for c in logger.error.call_args_list)
        assert "42000" in error_text

    def test_errorcode_included_in_error_when_available(self):
        svc, provider, _, logger, _ = _make_service(stmt_type=SqlStatementType.DDL.value)
        exc = RuntimeError("error")
        exc.errorcode = 9999
        provider.execute_statement.side_effect = exc
        try:
            svc.execute_statement("BAD")
        except RuntimeError:
            pass
        error_text = " ".join(str(c) for c in logger.error.call_args_list)
        assert "9999" in error_text


# ===========================================================================
# NullLog when no logger provided
# ===========================================================================


class TestNullLogDefault(unittest.TestCase):

    def test_no_logger_uses_nulllog(self):
        from core.logger import NullLog

        provider = MagicMock()
        provider.execute_statement.return_value = 0
        sql_analyzer = MagicMock()
        sql_analyzer.get_statement_type.return_value = SqlStatementType.DDL.value
        svc = SqlExecutionService(provider=provider, sql_analyzer=sql_analyzer)
        assert isinstance(svc.log, NullLog)

    def test_no_logger_execute_does_not_crash(self):
        provider = MagicMock()
        provider.execute_statement.return_value = 0
        sql_analyzer = MagicMock()
        sql_analyzer.get_statement_type.return_value = SqlStatementType.DDL.value
        svc = SqlExecutionService(provider=provider, sql_analyzer=sql_analyzer)
        # Should not raise
        svc.execute_statement("CREATE TABLE t (id INT)")


# ===========================================================================
# _extract_simple_table_name
# ===========================================================================


class TestExtractSimpleTableName(unittest.TestCase):

    def test_plain_identifier(self):
        assert SqlExecutionService._extract_simple_table_name("users") == "users"

    def test_schema_qualified(self):
        assert SqlExecutionService._extract_simple_table_name("public.users") == "users"

    def test_three_part(self):
        assert SqlExecutionService._extract_simple_table_name("catalog.schema.users") == "users"

    def test_double_quoted(self):
        assert SqlExecutionService._extract_simple_table_name('"my.table"') == "my.table"

    def test_bracket_notation(self):
        assert SqlExecutionService._extract_simple_table_name("[dbo].[users]") == "users"

    def test_backtick_quoted(self):
        assert SqlExecutionService._extract_simple_table_name("`my_table`") == "my_table"

    def test_empty_returns_empty(self):
        assert SqlExecutionService._extract_simple_table_name("") == ""

    def test_none_returns_none(self):
        assert SqlExecutionService._extract_simple_table_name(None) is None


# ===========================================================================
# _extract_table_from_dml
# ===========================================================================


class TestExtractTableFromDml(unittest.TestCase):

    def setUp(self):
        provider = MagicMock()
        sql_analyzer = MagicMock()
        self.svc = SqlExecutionService(provider=provider, sql_analyzer=sql_analyzer)

    def test_insert_into(self):
        result = self.svc._extract_table_from_dml("INSERT INTO users VALUES (1, 'Alice')")
        assert result == "users"

    def test_insert_qualified(self):
        result = self.svc._extract_table_from_dml("INSERT INTO public.orders VALUES (1)")
        assert result == "orders"

    def test_update_table(self):
        result = self.svc._extract_table_from_dml("UPDATE products SET price=10 WHERE id=1")
        assert result == "products"

    def test_update_qualified(self):
        result = self.svc._extract_table_from_dml("UPDATE dbo.products SET price=10")
        assert result == "products"

    def test_delete_from(self):
        result = self.svc._extract_table_from_dml("DELETE FROM orders WHERE id=1")
        assert result == "orders"

    def test_delete_qualified(self):
        result = self.svc._extract_table_from_dml("DELETE FROM public.orders WHERE id=1")
        assert result == "orders"

    def test_none_statement_returns_none(self):
        result = self.svc._extract_table_from_dml(None)
        assert result is None

    def test_empty_statement_returns_none(self):
        result = self.svc._extract_table_from_dml("")
        assert result is None

    def test_unknown_dml_returns_none(self):
        result = self.svc._extract_table_from_dml("MERGE INTO t USING s ON ...")
        assert result is None

    def test_insert_bracket_notation(self):
        result = self.svc._extract_table_from_dml("INSERT INTO [dbo].[users] VALUES (1)")
        assert result == "users"


# ===========================================================================
# Journal without the optional methods (getattr guard)
# ===========================================================================


class TestJournalWithoutOptionalMethods(unittest.TestCase):

    def test_journal_without_record_start_no_crash(self):
        """Journal without record_statement_start should not crash."""
        provider = MagicMock()
        provider.execute_statement.return_value = 0
        sql_analyzer = MagicMock()
        sql_analyzer.get_statement_type.return_value = SqlStatementType.DDL.value

        # Journal without record_statement_start attribute
        journal = MagicMock(spec=["record_statement_complete", "record_statement_failed"])
        journal.record_statement_complete = MagicMock()

        svc = SqlExecutionService(provider=provider, sql_analyzer=sql_analyzer, journal=journal)
        svc.execute_statement("CREATE TABLE t (id INT)")  # Should not raise


if __name__ == "__main__":
    unittest.main()
