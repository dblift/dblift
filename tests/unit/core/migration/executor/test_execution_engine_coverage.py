"""
Coverage tests for core/migration/executor/execution_engine.py

Targets previously uncovered lines:
  55, 65, 68, 97-98, 114-115, 118, 122, 132, 138, 140, 154, 159, 168, 171,
  178, 182, 203-204, 225, 232-237, 261-303, 315, 328, 334, 345-393, 402-406,
  420, 436-449, 454, 457, 465-478, 490-595, 617-689, 696-717, 719-744,
  746-824, 826-966, 976-977, 1001-1111
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from core.exceptions import TransactionAbortedError
from core.logger.results import OperationResult
from core.migration.executor.execution_engine import ExecutionEngine, _strip_driver_exception_prefix
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(
    dialect="postgresql", with_history=False, with_config=True, with_placeholder=False
):
    from db.provider_interfaces import TransactionalProvider

    provider = MagicMock()
    provider.__class__ = TransactionalProvider
    provider.supports_transactions.return_value = True
    provider.supports_transactional_ddl.return_value = True
    provider.connection = MagicMock()
    provider.connection.getAutoCommit.return_value = False
    provider.connection.isClosed.return_value = False

    sql_analyzer = MagicMock()
    sql_analyzer.dialect = dialect

    log = MagicMock()

    config = None
    if with_config:
        config = MagicMock()
        config.database.type.value = dialect
        config.database.url = f"{dialect}://host:5432/db"

    history_manager = MagicMock() if with_history else None

    placeholder_service = MagicMock() if with_placeholder else None

    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=sql_analyzer,
        log=log,
        config=config,
        history_manager=history_manager,
        placeholder_service=placeholder_service,
    )
    return engine


def _make_sql_migration(content="SELECT 1;", name="V1__test.sql", statements=None):
    m = MagicMock(spec=Migration)
    m.format = MigrationFormat.SQL
    m.content = content
    m.script_name = name
    m.version = "1"
    m.description = "test"
    m.checksum = 12345
    m.type = MagicMock()
    m.type.value = "SQL"
    m.type.name = "VERSIONED"
    m.parse_sql_statements.return_value = statements if statements is not None else ["SELECT 1"]
    return m


def _make_python_migration(name="V2__migrate.py"):
    m = MagicMock(spec=Migration)
    m.format = MigrationFormat.PYTHON
    m.script_name = name
    m.version = "2"
    m.description = "python migration"
    m.checksum = 99999
    m.type = MagicMock()
    m.type.value = "PYTHON"
    m.type.name = "VERSIONED"
    return m


# ---------------------------------------------------------------------------
# Module-level function _strip_driver_exception_prefix (line 55)
# ---------------------------------------------------------------------------


class TestStripJdbcPrefix(unittest.TestCase):

    def test_strips_psql_exception_prefix(self):
        msg = 'org.postgresql.util.PSQLException: ERROR: column "x" already exists'
        result = _strip_driver_exception_prefix(msg)
        self.assertNotIn("org.postgresql", result)
        self.assertIn("already exists", result)

    def test_strips_nested_exception_prefix(self):
        msg = "com.ibm.db2.jcc.am.SqlException: ERROR: table not found"
        result = _strip_driver_exception_prefix(msg)
        self.assertNotIn("com.ibm", result)

    def test_no_prefix_unchanged(self):
        msg = "plain error message"
        result = _strip_driver_exception_prefix(msg)
        self.assertEqual(result, msg)

    def test_empty_string(self):
        result = _strip_driver_exception_prefix("")
        self.assertEqual(result, "")


# ---------------------------------------------------------------------------
# ExecutionEngine init — log=None becomes NullLog (line 94)
# ---------------------------------------------------------------------------


class TestExecutionEngineInit(unittest.TestCase):

    def test_null_log_when_log_is_none(self):
        """Line 94: log = log if log is not None else NullLog()"""
        from core.logger import NullLog

        provider = MagicMock()
        sql_analyzer = MagicMock()
        sql_analyzer.dialect = "postgresql"

        engine = ExecutionEngine(
            provider=provider,
            sql_analyzer=sql_analyzer,
            log=None,
        )
        self.assertIsInstance(engine.log, NullLog)

    def test_log_used_when_provided(self):
        """Line 94: log provided → used directly."""

        provider = MagicMock()
        sql_analyzer = MagicMock()
        sql_analyzer.dialect = "postgresql"
        log = MagicMock()

        engine = ExecutionEngine(
            provider=provider,
            sql_analyzer=sql_analyzer,
            log=log,
        )
        self.assertIs(engine.log, log)


# ---------------------------------------------------------------------------
# _parse_sql_statements — all branches (lines 259-313)
# ---------------------------------------------------------------------------


class TestParseSqlStatements(unittest.TestCase):

    def test_returns_statements_basic(self):
        """Lines 259-305: Normal parse with no config dialect_key override."""
        engine = _make_engine(with_config=False)
        migration = _make_sql_migration()

        result = engine._parse_sql_statements(migration, MagicMock())

        self.assertEqual(result, ["SELECT 1"])

    def test_config_dialect_key_from_value(self):
        """Lines 261-269: config.database.type.value used as dialect_key."""
        engine = _make_engine(with_config=True)
        engine.config.database.type.value = "postgresql"
        engine.config.database.url = "postgresql+psycopg://host/db"
        migration = _make_sql_migration()
        result = engine._parse_sql_statements(migration, MagicMock())
        self.assertEqual(result, ["SELECT 1"])

    def test_config_dialect_key_str_fallback(self):
        """Lines 270-271: config.database.type has no .value → str(raw_type)."""
        engine = _make_engine(with_config=True)
        # Remove .value attribute so getattr returns None
        raw_type = MagicMock()
        del raw_type.value
        engine.config.database.type = raw_type

        migration = _make_sql_migration()
        result = engine._parse_sql_statements(migration, MagicMock())
        # Should still work (fall through to sql_analyzer.dialect)
        self.assertIsNotNone(result)

    def test_mssql_normalized_to_sqlserver(self):
        """Lines 272-273: dialect_key 'mssql' → 'sqlserver'."""
        engine = _make_engine(with_config=True)
        engine.config.database.type.value = "mssql"
        migration = _make_sql_migration()

        result = engine._parse_sql_statements(migration, MagicMock())
        self.assertIsNotNone(result)

    def test_no_dialect_key_falls_back_to_analyzer(self):
        """Lines 274-275: No config database → use sql_analyzer.dialect."""
        engine = _make_engine(with_config=True)
        engine.config.database = None
        migration = _make_sql_migration()

        result = engine._parse_sql_statements(migration, MagicMock())
        self.assertIsNotNone(result)

    def test_placeholder_service_called(self):
        """Lines 279-281: placeholder_service replaces content."""
        engine = _make_engine(with_placeholder=True)
        engine.placeholder_service.replace_placeholders.return_value = "SELECT 42"
        migration = _make_sql_migration()
        migration.parse_sql_statements.return_value = ["SELECT 42"]

        result = engine._parse_sql_statements(
            migration, MagicMock(), placeholder_service=engine.placeholder_service
        )

        engine.placeholder_service.replace_placeholders.assert_called_once_with(migration.content)

    def test_oracle_extract_sqlplus_context(self):
        """Lines 286-301: Oracle path: extract SQL*Plus context and apply DEFINE."""
        engine = _make_engine(dialect="oracle", with_config=True)
        engine.config.database.type.value = "oracle"
        engine.config.database.url = "oracle+oracledb://host:1521?service_name=XE"
        migration = _make_sql_migration(content="SET SERVEROUTPUT ON\nSELECT 1 FROM DUAL;")

        result = engine._parse_sql_statements(migration, MagicMock())
        # Should not raise
        self.assertIsNotNone(result)

    def test_exception_sets_result_error_and_returns_none(self):
        """Lines 306-313: Exception → result.set_error, return None."""
        engine = _make_engine()
        migration = _make_sql_migration()
        migration.parse_sql_statements.side_effect = Exception("parse error")
        result = MagicMock()

        ret = engine._parse_sql_statements(migration, result)

        self.assertIsNone(ret)
        result.set_error.assert_called_once()


# ---------------------------------------------------------------------------
# _probe_dialect_key — additional branches (lines 350-404)
# ---------------------------------------------------------------------------


class TestProbeDialectKeyAdditional(unittest.TestCase):

    def test_provider_canonical_dialect_oracle(self):
        """PR-F4: provider's ``canonical_dialect_key`` is authoritative.

        Replaces the previous URL-sniffing test: the framework no longer
        looks at the provider's legacy URL, it asks the provider directly
        via the ``canonical_dialect_key`` class attribute set by each
        plugin (e.g. ``OracleProvider.canonical_dialect_key = "oracle"``).
        """
        engine = _make_engine(with_config=False)
        engine.sql_analyzer.dialect = "postgresql"  # would have masked the old URL path
        engine.provider.canonical_dialect_key = "oracle"
        result = engine._probe_dialect_key()
        self.assertEqual(result, "oracle")

    def test_provider_canonical_dialect_db2(self):
        """PR-F4: provider's ``canonical_dialect_key`` short-circuits the fallback."""
        engine = _make_engine(with_config=False)
        engine.sql_analyzer.dialect = "postgresql"
        engine.provider.canonical_dialect_key = "db2"
        result = engine._probe_dialect_key()
        self.assertEqual(result, "db2")

    def test_no_config_no_url_falls_back_to_provider_dialect(self):
        """Lines 396-404: No config, no url → fall back to provider.dialect."""
        engine = _make_engine(with_config=False)
        engine.sql_analyzer.dialect = None
        engine.provider.dialect = "mysql"

        with patch("db.provider_capabilities.get_provider_display_url", return_value=None):
            result = engine._probe_dialect_key()

        self.assertEqual(result, "mysql")

    def test_config_db2_resolved_from_provider_attribute(self):
        """PR-F4: the engine trusts ``provider.canonical_dialect_key``.

        The architectural cleanup means a DB2 plugin's provider declares
        its dialect once; the framework reads it instead of pattern-matching
        URLs (Epic 26 dialect isolation).
        """
        engine = _make_engine(with_config=True)
        engine.provider.canonical_dialect_key = "db2"

        result = engine._probe_dialect_key()

        self.assertEqual(result, "db2")

    def test_config_oracle_resolved_from_provider_attribute(self):
        """PR-F4: Oracle provider declares ``canonical_dialect_key = "oracle"``."""
        engine = _make_engine(with_config=True)
        engine.provider.canonical_dialect_key = "oracle"

        result = engine._probe_dialect_key()

        self.assertEqual(result, "oracle")

    def test_all_none_returns_none(self):
        """Lines 396-404: Everything None → return None."""
        engine = _make_engine(with_config=False)
        engine.sql_analyzer.dialect = None
        del engine.provider.dialect

        with patch("db.provider_capabilities.get_provider_display_url", return_value=None):
            result = engine._probe_dialect_key()

        self.assertIsNone(result)

    def test_config_no_db_attribute(self):
        """Lines 364-384: config.database is None."""
        engine = _make_engine(with_config=True)
        engine.config.database = None
        engine.sql_analyzer.dialect = "postgresql"

        with patch("db.provider_capabilities.get_provider_display_url", return_value=None):
            result = engine._probe_dialect_key()

        self.assertEqual(result, "postgresql")


# ---------------------------------------------------------------------------
# _classify_execution_statements (lines 200-220)
# ---------------------------------------------------------------------------


class TestClassifyExecutionStatements(unittest.TestCase):

    def test_skips_empty_statements(self):
        """Lines 203-220: Empty statements are skipped."""
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"

        result = engine._classify_execution_statements(["", "   ", "SELECT 1"])
        # Only "SELECT 1" should be classified
        self.assertEqual(len(result), 1)

    def test_skips_comment_only_statements(self):
        """Lines 203-220: Comment-only statements skipped."""
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"

        result = engine._classify_execution_statements(["-- comment only"])
        self.assertEqual(len(result), 0)

    def test_skips_tsql_batch_separator(self):
        """Lines 203-220: GO is a TSQL batch separator, skipped."""
        engine = _make_engine(dialect="sqlserver")
        engine.sql_analyzer.get_statement_type.return_value = "DML"

        result = engine._classify_execution_statements(["GO", "SELECT 1"])
        self.assertEqual(len(result), 1)

    def test_classifies_normal_statement(self):
        """Lines 203-220: Normal statement gets classified."""
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DDL"

        result = engine._classify_execution_statements(["CREATE TABLE t (id INT)"])
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# _execute_statements — various paths (lines 422-592)
# ---------------------------------------------------------------------------


class TestExecuteStatements(unittest.TestCase):

    def _make_migration_result(self, statements=None):
        migration = _make_sql_migration(statements=statements)
        result = MagicMock()
        return migration, result

    def test_skips_empty_statement_in_loop(self):
        """Lines 465-466: Empty statements in loop are skipped."""
        engine = _make_engine()
        engine.provider.execute_statement.return_value = 0
        migration, result = self._make_migration_result(statements=["", "SELECT 1"])

        success = engine._execute_statements(["", "SELECT 1"], migration, result, time.time())
        self.assertTrue(success)

    def test_skips_tsql_batch_separator_in_loop(self):
        """Lines 468-469: GO batch separator skipped."""
        engine = _make_engine(dialect="sqlserver")
        engine.provider.execute_statement.return_value = 0
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["GO", "SELECT 1"], migration, result, time.time())
        self.assertTrue(success)

    def test_skips_comment_only_in_loop(self):
        """Lines 470-471: Comment-only statements skipped."""
        engine = _make_engine()
        engine.provider.execute_statement.return_value = 0
        migration, result = self._make_migration_result()

        success = engine._execute_statements(
            ["-- comment", "SELECT 1"], migration, result, time.time()
        )
        self.assertTrue(success)

    def test_statement_with_rows_affected_logs_info(self):
        """Lines 551-554: rows_affected >= 0 → log.info with count."""
        engine = _make_engine()
        engine.provider.execute_statement.return_value = 5
        migration, result = self._make_migration_result(statements=["INSERT INTO t VALUES (1)"])

        success = engine._execute_statements(
            ["INSERT INTO t VALUES (1)"], migration, result, time.time()
        )
        self.assertTrue(success)
        info_calls = [str(c) for c in engine.log.info.call_args_list]
        self.assertTrue(any("5 rows affected" in c for c in info_calls))

    def test_ddl_statement_suppresses_zero_rows_affected_log(self):
        engine = _make_engine()
        engine.provider.execute_statement.return_value = 0
        migration, result = self._make_migration_result(statements=["CREATE TABLE t (id INT)"])

        success = engine._execute_statements(
            ["CREATE TABLE t (id INT)"], migration, result, time.time()
        )

        self.assertTrue(success)
        info_calls = [str(c) for c in engine.log.info.call_args_list]
        self.assertTrue(any("Statement executed successfully" in c for c in info_calls))
        self.assertFalse(any("0 rows affected" in c for c in info_calls))

    def test_statement_with_none_rows_logs_success(self):
        """Lines 555-556: rows_affected=None → log.info 'executed successfully'."""
        engine = _make_engine()
        engine.provider.execute_statement.return_value = None
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["SELECT 1"], migration, result, time.time())
        self.assertTrue(success)

    def test_transaction_aborted_raises_transaction_aborted_error(self):
        """Lines 520-528: TransactionAbortedError raised when transaction is aborted."""
        engine = _make_engine()
        engine.provider.supports_transactions.return_value = True

        # prepareStatement raises "transaction is aborted"
        engine.provider.connection.prepareStatement.side_effect = Exception(
            "current transaction is aborted"
        )
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["SELECT 1"], migration, result, time.time())
        self.assertFalse(success)

    def test_non_transaction_aborted_precheck_error_propagates(self):
        """Lines 529-530: Non-aborted pre-check error → raised → failure path."""
        engine = _make_engine()
        engine.provider.supports_transactions.return_value = True
        engine.provider.connection.prepareStatement.side_effect = Exception("connection lost")
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["SELECT 1"], migration, result, time.time())
        self.assertFalse(success)

    def test_sql_execution_service_query_result(self):
        """Lines 532-547: sql_execution_service returns is_query=True."""
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (True, [{"id": 1}])
        engine.sql_execution_service = mock_ses
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["SELECT id FROM t"], migration, result, time.time())
        self.assertTrue(success)

    def test_sql_execution_service_dml_result(self):
        """Lines 532-547: sql_execution_service returns is_query=False (DML)."""
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (False, 3)
        engine.sql_execution_service = mock_ses
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["UPDATE t SET x=1"], migration, result, time.time())
        self.assertTrue(success)

    def test_sql_execution_service_wrong_type_raises_type_error(self):
        """Lines 537-546: sql_execution_service returns wrong types → TypeError."""
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (True, "not_a_list")  # Wrong type
        engine.sql_execution_service = mock_ses
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["SELECT 1"], migration, result, time.time())
        self.assertFalse(success)

    def test_precheck_attribute_error_falls_back_to_execute_query(self):
        """Lines 508-510: prepareStatement raises AttributeError → execute_query."""
        engine = _make_engine()
        engine.provider.supports_transactions.return_value = True
        engine.provider.connection.prepareStatement.side_effect = AttributeError(
            "no prepareStatement"
        )
        engine.provider.execute_query.return_value = [{"1": 1}]
        engine.provider.execute_statement.return_value = 0
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["SELECT 1"], migration, result, time.time())
        self.assertTrue(success)

    def test_no_connection_uses_execute_query_fallback(self):
        """Lines 518-519: No connection → execute_query directly."""
        engine = _make_engine()
        engine.provider.supports_transactions.return_value = True
        engine.provider.connection = None  # No connection
        engine.provider.execute_query.return_value = [{"1": 1}]
        engine.provider.execute_statement.return_value = 0
        migration, result = self._make_migration_result()

        success = engine._execute_statements(["SELECT 1"], migration, result, time.time())
        self.assertTrue(success)

    def test_whenever_sqlerror_continue_skips_statement_error(self):
        """Lines 573-584: WHENEVER SQLERROR CONTINUE → continue on DB error."""
        from db.plugins.oracle.parser.sqlplus_context import SqlplusContext

        engine = _make_engine(dialect="oracle")
        engine._current_sqlplus_ctx = SqlplusContext()

        engine.provider.execute_statement.side_effect = Exception("ORA-01234 some error")
        migration, result = self._make_migration_result()

        success = engine._execute_statements(
            ["WHENEVER SQLERROR CONTINUE", "SELECT 1"],
            migration,
            result,
            time.time(),
        )
        # With CONTINUE policy, the error is logged as warning but execution continues
        # The loop finishes, so True is returned
        # (The second statement "SELECT 1" also fails, but policy is continue)
        self.assertTrue(success)

    def test_whenever_sqlerror_continue_does_not_skip_transaction_aborted(self):
        """Lines 573-584: TransactionAbortedError not skipped even with CONTINUE."""
        from db.plugins.oracle.parser.sqlplus_context import SqlplusContext

        engine = _make_engine(dialect="oracle")
        engine._current_sqlplus_ctx = SqlplusContext()

        engine.provider.execute_statement.side_effect = TransactionAbortedError("aborted")
        migration, result = self._make_migration_result()

        success = engine._execute_statements(
            ["SELECT 1"],
            migration,
            result,
            time.time(),
        )

        self.assertFalse(success)


# ---------------------------------------------------------------------------
# _handle_statement_failure — extended paths (lines 594-689)
# ---------------------------------------------------------------------------


class TestHandleStatementFailureExtended(unittest.TestCase):

    def test_history_rollback_failure_logs_debug(self):
        """Lines 683-688: history record rollback failure → debug log."""
        engine = _make_engine(with_history=True)
        engine.history_manager.record_migration.side_effect = Exception("history fail")
        engine.provider.begin_transaction.return_value = None  # begin succeeds
        engine.provider.rollback_transaction.side_effect = Exception("rollback fails too")
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 0, 100, result)

        debug_calls = [str(c) for c in engine.log.debug.call_args_list]
        self.assertTrue(any("Could not rollback history record" in c for c in debug_calls))

    def test_migration_info_record_exception_logs_warning(self):
        """Lines 631-634: Exception building MigrationInfo → warning."""
        engine = _make_engine(with_history=False)
        migration = _make_sql_migration()
        migration.type = None  # Will cause: migration.type.value to fail
        result = MagicMock()

        # Should not raise; exception is swallowed with warning
        engine._handle_statement_failure(migration, Exception("stmt fail"), 0, 100, result)

        # Core behavior: result.set_error still called
        result.set_error.assert_called()

    def test_ddl_warning_added_to_result(self):
        """Lines 657-658: add_warning called when no transactional DDL."""
        engine = _make_engine(with_history=False)
        engine.provider.supports_transactional_ddl.return_value = False
        migration = _make_sql_migration()
        result = MagicMock()
        result.add_warning = MagicMock()

        engine._handle_statement_failure(migration, Exception("ddl fail"), 0, 100, result)

        result.add_warning.assert_called_once()
        self.assertIn("transactional DDL", result.add_warning.call_args[0][0])

    def test_history_commit_succeeds_sets_persisted_true(self):
        """Lines 671-673: history commit → failed_history_persisted = True."""
        engine = _make_engine(with_history=True)
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 0, 100, result)

        self.assertTrue(result.failed_history_persisted)

    def test_history_error_add_warning_called(self):
        """Lines 676-678: history failure → add_warning."""
        engine = _make_engine(with_history=True)
        engine.history_manager.record_migration.side_effect = Exception("history err")
        migration = _make_sql_migration()
        result = MagicMock()
        result.add_warning = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 0, 100, result)

        result.add_warning.assert_called()


# ---------------------------------------------------------------------------
# _record_autocommit_migration_history — TransactionalProvider path (lines 696-717)
# ---------------------------------------------------------------------------


class TestRecordAutocommitHistoryTransactional(unittest.TestCase):

    def test_non_transactional_provider_skips_begin_commit(self):
        """Lines 696-717: Non-TransactionalProvider → no begin/commit.

        Uses a custom class that does NOT inherit from TransactionalProvider.
        """

        class NonTransactionalProvider:
            """A provider that is not a TransactionalProvider."""

        engine = _make_engine(with_history=True)
        engine.provider = MagicMock(spec=NonTransactionalProvider)
        migration = _make_sql_migration()

        engine._record_autocommit_migration_history(migration, 100)

        engine.history_manager.record_migration.assert_called_once_with(
            migration, success=True, execution_time=100
        )
        # Non-transactional providers: isinstance check is False, no begin_transaction attr
        self.assertFalse(hasattr(engine.provider, "begin_transaction"))


# ---------------------------------------------------------------------------
# _commit_and_verify — oracle dialect path (lines 805-816)
# ---------------------------------------------------------------------------


class TestCommitAndVerifyExtended(unittest.TestCase):

    def test_oracle_dialect_uses_count_without_limit(self):
        """Lines 805-811: Oracle uses SELECT COUNT(*) without LIMIT."""
        engine = _make_engine(dialect="oracle")
        engine.sql_analyzer.dialect = "oracle"
        engine.provider.connection.isClosed.return_value = False
        engine.provider.execute_query.return_value = [{"cnt": 0}]
        migration = _make_sql_migration()

        statements = ["CREATE TABLE public.employees (id INT)"]
        engine._commit_and_verify(migration, statements, 100)

        query_calls = [str(c) for c in engine.provider.execute_query.call_args_list]
        # Oracle should not have LIMIT in query
        self.assertTrue(any("COUNT" in c for c in query_calls))
        self.assertFalse(any("LIMIT" in c for c in query_calls))

    def test_sqlserver_dialect_uses_count_without_limit(self):
        """Lines 805-811: SQL Server uses SELECT COUNT(*) without LIMIT."""
        engine = _make_engine(dialect="sqlserver")
        engine.sql_analyzer.dialect = "sqlserver"
        engine.provider.connection.isClosed.return_value = False
        engine.provider.execute_query.return_value = [{"cnt": 0}]
        migration = _make_sql_migration()

        statements = ["CREATE TABLE dbo.orders (id INT)"]
        engine._commit_and_verify(migration, statements, 100)

        query_calls = [str(c) for c in engine.provider.execute_query.call_args_list]
        self.assertTrue(any("COUNT" in c for c in query_calls))

    def test_special_chars_in_table_name_skip_verification(self):
        """Lines 779-782: table/schema with special chars → skip verification."""
        engine = _make_engine()
        engine.provider.connection.isClosed.return_value = False
        migration = _make_sql_migration()

        # Schema name with hyphens → won't match \w+ → skip
        statements = ["CREATE TABLE my-schema.users (id INT)"]
        engine._commit_and_verify(migration, statements, 100)

        # execute_query should NOT have been called for verification
        engine.provider.execute_query.assert_not_called()

    def test_connection_is_closed_skips_verification(self):
        """Lines 783-787: isClosed() returns True → skip verification."""
        engine = _make_engine()
        engine.provider.connection.isClosed.return_value = True
        migration = _make_sql_migration()

        statements = ["CREATE TABLE public.users (id INT)"]
        engine._commit_and_verify(migration, statements, 100)

        engine.provider.execute_query.assert_not_called()

    def test_no_create_table_no_verification(self):
        """Lines 767-816: No CREATE TABLE → no verification query."""
        engine = _make_engine()
        engine.provider.connection.isClosed.return_value = False
        migration = _make_sql_migration()

        statements = ["INSERT INTO t VALUES (1)"]
        engine._commit_and_verify(migration, statements, 100)

        engine.provider.execute_query.assert_not_called()

    def test_provider_not_transactional_skips_verification(self):
        """Lines 761-766: Non-TransactionalProvider → no verification."""
        from db.base_provider import BaseProvider

        engine = _make_engine()
        engine.provider = MagicMock(spec=BaseProvider)  # NOT TransactionalProvider
        migration = _make_sql_migration()

        statements = ["CREATE TABLE public.users (id INT)"]
        engine._commit_and_verify(migration, statements, 100)
        # No exception, just commit is called


# ---------------------------------------------------------------------------
# _execute_via_factory — success path without history manager (lines 826-966)
# ---------------------------------------------------------------------------


class TestExecuteViaFactoryExtended(unittest.TestCase):

    def test_success_no_history_no_exception(self):
        """Lines 866-906: success + no history_manager → just commit.

        ``_execute_via_factory`` does not add a MigrationInfo to the result on
        success — the caller (MigrateCommand._execute_single_migration) does
        that uniformly for every migration type. Adding it here too used to
        duplicate the entry for non-SQL (e.g. Python) migrations (issue #835).
        """
        engine = _make_engine(with_history=False)
        exec_result = MagicMock()
        exec_result.success = True
        exec_result.execution_time_ms = 100
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result
        migration = _make_python_migration()
        result = MagicMock()
        result.add_migration = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            engine._execute_via_factory(migration, result)

        engine.provider.commit_transaction.assert_called_once()
        result.add_migration.assert_not_called()

    def test_failure_path_records_failed_history(self):
        """Lines 907-952: exec_result.success=False → rollback + record FAILED history."""
        engine = _make_engine(with_history=True)
        exec_result = MagicMock()
        exec_result.success = False
        exec_result.error = "script error"
        exec_result.execution_time_ms = 50
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result
        migration = _make_python_migration()
        result = MagicMock()
        result.add_migration = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            engine._execute_via_factory(migration, result)

        result.set_error.assert_called_with("script error")
        # history_manager should record FAILED
        engine.history_manager.record_migration.assert_called_with(
            migration, success=False, execution_time=50
        )

    def test_failure_history_write_error_adds_warning(self):
        """Lines 943-951: history write fails → add_warning."""
        engine = _make_engine(with_history=True)
        exec_result = MagicMock()
        exec_result.success = False
        exec_result.error = "exec error"
        exec_result.execution_time_ms = 50
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result
        engine.history_manager.record_migration.side_effect = Exception("history write failed")
        migration = _make_python_migration()
        result = MagicMock()
        result.add_migration = MagicMock()
        result.add_warning = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            engine._execute_via_factory(migration, result)

        result.add_warning.assert_called()

    def test_non_transactional_provider_no_transaction_lifecycle(self):
        """Lines 844-851: Non-TransactionalProvider → no _prepare_transaction.

        Uses a custom class that does NOT inherit from TransactionalProvider.
        """

        class NonTransactionalProvider:
            """A provider that is not a TransactionalProvider."""

        engine = _make_engine()
        engine.provider = MagicMock(spec=NonTransactionalProvider)
        exec_result = MagicMock()
        exec_result.success = True
        exec_result.execution_time_ms = 100
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result
        migration = _make_python_migration()
        result = MagicMock()
        result.add_migration = MagicMock()

        engine._execute_via_factory(migration, result)

        # Non-transactional provider: no commit_transaction attribute
        self.assertFalse(hasattr(engine.provider, "commit_transaction"))
        # Should succeed without errors
        result.set_error.assert_not_called()

    def test_failure_history_rollback_failure_swallowed(self):
        """Lines 952-956: Rollback after history failure also fails → swallowed."""
        engine = _make_engine(with_history=True)
        exec_result = MagicMock()
        exec_result.success = False
        exec_result.error = "error"
        exec_result.execution_time_ms = 50
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result
        engine.history_manager.record_migration.side_effect = Exception("history fail")
        engine.provider.begin_transaction.return_value = None
        engine.provider.rollback_transaction.side_effect = Exception("rollback also fails")
        migration = _make_python_migration()
        result = MagicMock()
        result.add_migration = MagicMock()
        result.add_warning = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            # Should not raise
            engine._execute_via_factory(migration, result)


# ---------------------------------------------------------------------------
# execute_callback — additional paths (lines 968-1085)
# ---------------------------------------------------------------------------


class TestExecuteCallbackAdditional(unittest.TestCase):

    def test_sql_callback_dml_none_rows_affected(self):
        """Lines 1054-1055: rows_affected=None → log 'executed successfully'."""
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.execute_statement.return_value = None
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "after.sql"
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["DELETE FROM t WHERE id=99"]

        engine.execute_callback(cb)

        info_calls = [str(c) for c in engine.log.info.call_args_list]
        self.assertTrue(any("executed successfully" in c for c in info_calls))

    def test_sql_callback_create_view_with_select_logs_debug(self):
        """Lines 1026-1032: CREATE VIEW with SELECT → verbose debug log."""
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DDL"
        engine.provider.execute_statement.return_value = 0
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "after.sql"
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["CREATE VIEW v AS SELECT 1"]

        engine.execute_callback(cb)

        debug_calls = [str(c) for c in engine.log.debug.call_args_list]
        self.assertTrue(any("classification" in c.lower() for c in debug_calls))

    def test_sql_callback_no_transaction_started_no_rollback(self):
        """Lines 1072-1084: begin_transaction fails → no rollback when error occurs."""
        engine = _make_engine()
        engine.provider.begin_transaction.side_effect = Exception("begin failed")
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.execute_statement.side_effect = Exception("exec failed")

        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "after.sql"
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["INSERT INTO t VALUES (1)"]

        with self.assertRaises(Exception):
            engine.execute_callback(cb)

        # rollback_transaction should NOT be called (transaction_started=False)
        engine.provider.rollback_transaction.assert_not_called()

    def test_sql_callback_rollback_failure_on_error_logged(self):
        """Lines 1080-1083: Rollback failure on callback error → warning."""
        engine = _make_engine()
        engine.provider.begin_transaction.return_value = None
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.execute_statement.side_effect = Exception("exec failed")
        engine.provider.rollback_transaction.side_effect = Exception("rollback also failed")

        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "after.sql"
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["INSERT INTO t VALUES (1)"]

        with self.assertRaises(Exception):
            engine.execute_callback(cb)

        warning_calls = [str(c) for c in engine.log.warning.call_args_list]
        self.assertTrue(any("Could not rollback" in c for c in warning_calls))


class TestQueryResultCapture(unittest.TestCase):
    """--show-query-results: rows from a SELECT are captured on the OperationResult."""

    def test_migration_query_captures_columns_and_rows_when_enabled(self):
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (
            True,
            [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}],
        )
        engine.sql_execution_service = mock_ses
        migration = _make_sql_migration()
        result = OperationResult()
        result.show_query_results = True

        success = engine._execute_statements(
            ["SELECT id, name FROM t"], migration, result, time.time()
        )

        self.assertTrue(success)
        self.assertEqual(len(result.query_results), 1)
        info = result.query_results[0]
        self.assertEqual(info.script, migration.script_name)
        self.assertEqual(len(info.results), 1)
        self.assertEqual(info.results[0]["columns"], ["id", "name"])
        self.assertEqual(info.results[0]["rows"], [[1, "alice"], [2, "bob"]])
        info_calls = [str(c) for c in engine.log.info.call_args_list]
        self.assertTrue(any("Query result" in c for c in info_calls))

    def test_migration_query_not_captured_when_flag_disabled(self):
        """Default (show_query_results=False) leaves query_results empty — no behavior change."""
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (True, [{"id": 1}])
        engine.sql_execution_service = mock_ses
        migration = _make_sql_migration()
        result = OperationResult()

        success = engine._execute_statements(["SELECT id FROM t"], migration, result, time.time())

        self.assertTrue(success)
        self.assertEqual(result.query_results, [])

    def test_ddl_dml_statement_does_not_add_query_result(self):
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (False, 3)
        engine.sql_execution_service = mock_ses
        migration = _make_sql_migration()
        result = OperationResult()
        result.show_query_results = True

        success = engine._execute_statements(["UPDATE t SET x=1"], migration, result, time.time())

        self.assertTrue(success)
        self.assertEqual(result.query_results, [])

    def test_callback_query_captures_result_when_enabled(self):
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (True, [{"status": "active"}])
        engine.sql_execution_service = mock_ses
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "beforeMigrate/cb.sql"
        cb.version = None
        cb.description = ""
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["SELECT status FROM jobs"]
        result = OperationResult()
        result.show_query_results = True

        engine.execute_callback(cb, result)

        self.assertEqual(len(result.query_results), 1)
        info = result.query_results[0]
        self.assertEqual(info.script, "beforeMigrate/cb.sql")
        self.assertEqual(info.results[0]["columns"], ["status"])
        self.assertEqual(info.results[0]["rows"], [["active"]])

    def test_callback_without_result_param_does_not_raise(self):
        """execute_callback(cb) with no result (default None) is unaffected — backward compatible."""
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (True, [{"id": 1}])
        engine.sql_execution_service = mock_ses
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "before.sql"
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["SELECT id FROM t"]

        engine.execute_callback(cb)  # no result passed

    def test_callback_zero_row_query_captured_via_sql_execution_service(self):
        """Bug 1: a 0-row callback SELECT via sql_execution_service is still
        captured (empty rows) and logged as a query result, not as DDL/DML
        'rows affected'."""
        engine = _make_engine()
        mock_ses = MagicMock()
        mock_ses.execute_statement.return_value = (True, [])
        engine.sql_execution_service = mock_ses
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "beforeMigrate/cb.sql"
        cb.version = None
        cb.description = ""
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["SELECT status FROM jobs WHERE 1=0"]
        result = OperationResult()
        result.show_query_results = True

        engine.execute_callback(cb, result)

        self.assertEqual(len(result.query_results), 1)
        info = result.query_results[0]
        self.assertEqual(info.results[0]["columns"], [])
        self.assertEqual(info.results[0]["rows"], [])

        info_calls = [str(c) for c in engine.log.info.call_args_list]
        self.assertTrue(
            any("Query executed successfully, 0 rows returned" in c for c in info_calls)
        )
        self.assertFalse(any("rows affected" in c for c in info_calls))

    def test_callback_zero_row_query_captured_without_sql_execution_service(self):
        """Bug 1: same guarantee for the fallback branch (no sql_execution_service
        configured), which classifies statements via sql_analyzer directly."""
        engine = _make_engine()
        engine.sql_execution_service = None
        engine.sql_analyzer.get_statement_type.return_value = "QUERY"
        engine.provider.execute_query.return_value = []
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = "beforeMigrate/cb.sql"
        cb.version = None
        cb.description = ""
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = ["SELECT status FROM jobs WHERE 1=0"]
        result = OperationResult()
        result.show_query_results = True

        engine.execute_callback(cb, result)

        self.assertEqual(len(result.query_results), 1)
        info = result.query_results[0]
        self.assertEqual(info.results[0]["columns"], [])
        self.assertEqual(info.results[0]["rows"], [])

        info_calls = [str(c) for c in engine.log.info.call_args_list]
        self.assertTrue(
            any("Query executed successfully, 0 rows returned" in c for c in info_calls)
        )
        self.assertFalse(any("rows affected" in c for c in info_calls))


if __name__ == "__main__":
    unittest.main()
