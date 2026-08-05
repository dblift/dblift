"""Extended unit tests for ExecutionEngine covering uncovered branches.

Target file: core/migration/executor/execution_engine.py
Focuses on: execute_migration full path, _is_comment_only_statement, _prepare_transaction,
_probe_dialect_key, _transaction_liveness_probe_sql, _record_migration_history,
_record_autocommit_migration_history, _commit_and_verify, _handle_statement_failure,
execute_callback, _execute_via_factory, autocommit statement routing.
"""

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from core.exceptions import CallbackExecutionError
from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration
from db.provider_interfaces import TransactionalProvider


def _make_engine(dialect="postgresql", with_history=False, with_config=True):
    """Build a minimal ExecutionEngine suitable for unit tests."""
    from db.base_provider import TransactionalProvider

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

    engine = ExecutionEngine(
        provider=provider,
        sql_analyzer=sql_analyzer,
        log=log,
        config=config,
        history_manager=history_manager,
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
# _is_comment_only_statement
# ---------------------------------------------------------------------------


class TestIsCommentOnlyStatement(unittest.TestCase):
    def test_empty_string_is_comment_only(self):
        self.assertTrue(ExecutionEngine._is_comment_only_statement(""))

    def test_whitespace_only_is_comment_only(self):
        self.assertTrue(ExecutionEngine._is_comment_only_statement("   \n\t  "))

    def test_block_comment_only(self):
        self.assertTrue(ExecutionEngine._is_comment_only_statement("/* this is a comment */"))

    def test_line_comment_only(self):
        self.assertTrue(ExecutionEngine._is_comment_only_statement("-- line comment"))

    def test_multi_line_block_comment(self):
        self.assertTrue(ExecutionEngine._is_comment_only_statement("/* \n multi\n line\n */"))

    def test_sql_with_comment_is_not_comment_only(self):
        self.assertFalse(ExecutionEngine._is_comment_only_statement("-- comment\nSELECT 1"))

    def test_plain_sql_is_not_comment_only(self):
        self.assertFalse(ExecutionEngine._is_comment_only_statement("SELECT 1"))

    def test_block_comment_followed_by_sql(self):
        self.assertFalse(
            ExecutionEngine._is_comment_only_statement("/* intro */ CREATE TABLE t (id INT)")
        )


class TestExecutableSqlStatements(unittest.TestCase):
    def test_filters_non_executable_statements_after_parsing(self):
        engine = _make_engine()
        migration = _make_sql_migration(
            statements=[
                "",
                "-- comment only",
                "/* block comment */",
                "CREATE TABLE users (id INT)",
            ]
        )

        statements = engine.get_executable_sql_statements(migration, MagicMock())

        self.assertEqual(statements, ["CREATE TABLE users (id INT)"])


# ---------------------------------------------------------------------------
# execute_migration — main flow
# ---------------------------------------------------------------------------


class TestExecuteMigrationMainFlow(unittest.TestCase):
    """Tests for execute_migration() covering previously uncovered branches."""

    def _make_engine_with_policy(self, transactional=True, autocommit_required=False, mixed=False):
        engine = _make_engine(with_history=True)
        policy = MagicMock()
        policy.transactional = transactional
        policy.autocommit_required = autocommit_required
        policy.unsupported_mixed_mode = mixed
        policy.reason = "test reason"
        engine.transaction_policy = MagicMock()
        engine.transaction_policy.decide.return_value = policy
        return engine, policy

    def test_non_sql_format_routes_to_factory(self):
        engine = _make_engine()
        migration = _make_python_migration()
        result = MagicMock()

        exec_result = MagicMock()
        exec_result.success = True
        exec_result.execution_time_ms = 100
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result

        with patch.object(engine, "_execute_via_factory") as mock_factory:
            engine.execute_migration(migration, result)
            mock_factory.assert_called_once_with(migration, result)

    def test_mixed_mode_policy_sets_error(self):
        engine, policy = self._make_engine_with_policy(transactional=False, mixed=True)
        migration = _make_sql_migration()
        result = MagicMock()

        with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
            with patch.object(engine, "_classify_execution_statements", return_value=[]):
                engine.execute_migration(migration, result)

        result.set_error.assert_called_once()
        error_msg = result.set_error.call_args[0][0]
        self.assertIn("mixes transactional", error_msg)

    def test_transaction_begin_failure_sets_error(self):
        engine, policy = self._make_engine_with_policy(transactional=True)
        migration = _make_sql_migration()
        result = MagicMock()

        with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
            with patch.object(engine, "_classify_execution_statements", return_value=[]):
                with patch.object(engine, "_prepare_transaction", return_value=False):
                    engine.execute_migration(migration, result)

        result.set_error.assert_called_once()
        self.assertIn("Could not begin transaction", result.set_error.call_args[0][0])

    def test_autocommit_path_calls_record_autocommit_history(self):
        engine, policy = self._make_engine_with_policy(
            transactional=False, autocommit_required=True
        )
        migration = _make_sql_migration()
        result = MagicMock()

        with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
            with patch.object(engine, "_classify_execution_statements", return_value=[]):
                with patch.object(engine, "_execute_statements", return_value=True) as mock_exec:
                    with patch.object(engine, "_record_autocommit_migration_history") as mock_rec:
                        engine.execute_migration(migration, result)

        self.assertTrue(mock_exec.call_args.kwargs.get("autocommit"))
        mock_rec.assert_called_once()

    def test_transactional_path_calls_record_and_commit(self):
        engine, policy = self._make_engine_with_policy(transactional=True)
        migration = _make_sql_migration()
        result = MagicMock()

        with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
            with patch.object(engine, "_classify_execution_statements", return_value=[]):
                with patch.object(engine, "_prepare_transaction", return_value=True):
                    with patch.object(engine, "_execute_statements", return_value=True):
                        with patch.object(engine, "_record_migration_history") as mock_rec:
                            with patch.object(engine, "_commit_and_verify") as mock_commit:
                                engine.execute_migration(migration, result)

        mock_rec.assert_called_once()
        mock_commit.assert_called_once()

    def test_exception_during_execution_triggers_rollback(self):
        engine, policy = self._make_engine_with_policy(transactional=True)
        migration = _make_sql_migration()
        result = MagicMock()

        with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
            with patch.object(engine, "_classify_execution_statements", return_value=[]):
                with patch.object(engine, "_prepare_transaction", return_value=True):
                    with patch.object(
                        engine, "_execute_statements", side_effect=RuntimeError("unexpected")
                    ):
                        with self.assertRaises(RuntimeError):
                            engine.execute_migration(migration, result)

        engine.provider.rollback_transaction.assert_called()

    def test_exception_rollback_failure_logs_warning(self):
        engine, policy = self._make_engine_with_policy(transactional=True)
        engine.provider.rollback_transaction.side_effect = Exception("rollback failed")
        migration = _make_sql_migration()
        result = MagicMock()

        with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
            with patch.object(engine, "_classify_execution_statements", return_value=[]):
                with patch.object(engine, "_prepare_transaction", return_value=True):
                    with patch.object(
                        engine, "_execute_statements", side_effect=RuntimeError("oops")
                    ):
                        with self.assertRaises(RuntimeError):
                            engine.execute_migration(migration, result)

        engine.log.warning.assert_called()

    def test_execute_statements_returns_false_stops_execution(self):
        engine, policy = self._make_engine_with_policy(transactional=True)
        migration = _make_sql_migration()
        result = MagicMock()

        with patch.object(engine, "_parse_sql_statements", return_value=["SELECT 1"]):
            with patch.object(engine, "_classify_execution_statements", return_value=[]):
                with patch.object(engine, "_prepare_transaction", return_value=True):
                    with patch.object(engine, "_execute_statements", return_value=False):
                        with patch.object(engine, "_record_migration_history") as mock_rec:
                            engine.execute_migration(migration, result)

        mock_rec.assert_not_called()


# ---------------------------------------------------------------------------
# _prepare_transaction
# ---------------------------------------------------------------------------


class TestPrepareTransaction(unittest.TestCase):
    def test_begin_transaction_success_returns_true(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.begin_transaction.return_value = None

        result = engine._prepare_transaction(migration)

        self.assertTrue(result)
        engine.provider.begin_transaction.assert_called_once()

    def test_begin_transaction_failure_returns_false(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.begin_transaction.side_effect = Exception("cannot begin")

        result = engine._prepare_transaction(migration)

        self.assertFalse(result)
        engine.log.warning.assert_called()

    def test_autocommit_false_triggers_rollback_before_begin(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection.getAutoCommit.return_value = False
        engine.provider.begin_transaction.return_value = None

        result = engine._prepare_transaction(migration)

        self.assertTrue(result)
        engine.provider.rollback_transaction.assert_called_once()

    def test_autocommit_true_no_rollback_before_begin(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection.getAutoCommit.return_value = True
        engine.provider.begin_transaction.return_value = None

        engine._prepare_transaction(migration)

        engine.provider.rollback_transaction.assert_not_called()

    def test_getautocommit_exception_logs_debug(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection.getAutoCommit.side_effect = Exception("jdbc error")
        engine.provider.begin_transaction.return_value = None

        result = engine._prepare_transaction(migration)

        self.assertTrue(result)
        debug_calls = [str(c) for c in engine.log.debug.call_args_list]
        self.assertTrue(any("Could not check connection state" in c for c in debug_calls))

    def test_no_getautocommit_attribute_rolls_back_defensively(self):
        """Python DB-API drivers (e.g. python-oracledb) expose autocommit as a
        property, not a getAutoCommit() method. Without a guard, the missing
        attribute raised AttributeError, was swallowed by the outer
        try/except, and the pre-migration rollback check never ran. It
        should instead fall back to rolling back defensively, the same way
        db/plugins/mysql/mysql/schema_operations.py and
        db/plugins/db2/db2/schema_operations.py fall back when they can't
        check getAutoCommit().
        """
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection = object()  # no getAutoCommit()/isClosed()
        engine.provider.begin_transaction.return_value = None

        result = engine._prepare_transaction(migration)

        self.assertTrue(result)
        engine.provider.rollback_transaction.assert_called_once()
        debug_calls = [str(c) for c in engine.log.debug.call_args_list]
        self.assertFalse(
            any("Could not check connection state" in c for c in debug_calls),
            "getAutoCommit() absence should be handled by a guard, not caught as an error",
        )

    def test_rollback_before_begin_failure_logs_debug(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection.getAutoCommit.return_value = False
        engine.provider.rollback_transaction.side_effect = Exception("rollback err")
        engine.provider.begin_transaction.return_value = None

        result = engine._prepare_transaction(migration)

        self.assertTrue(result)
        debug_calls = [str(c) for c in engine.log.debug.call_args_list]
        self.assertTrue(any("Could not rollback pre-migration" in c for c in debug_calls))

    def test_no_connection_skips_autocommit_check(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection = None
        engine.provider.begin_transaction.return_value = None

        result = engine._prepare_transaction(migration)

        self.assertTrue(result)
        engine.provider.connection  # accessed attribute was None


# ---------------------------------------------------------------------------
# _probe_dialect_key
# ---------------------------------------------------------------------------


class TestProbeDialectKey(unittest.TestCase):
    """PR-F4 updated tests: the engine no longer URL-sniffs.

    Each plugin's provider declares its own ``canonical_dialect_key`` and
    the framework asks the provider directly. The legacy fallback cascade
    (``sql_analyzer.dialect`` → ``config.database.type`` →
    ``provider.dialect``) is retained for providers / fakes that don't
    declare the attribute, and these tests still exercise it.
    """

    def test_provider_canonical_dialect_oracle(self):
        engine = _make_engine()
        engine.provider.canonical_dialect_key = "oracle"
        self.assertEqual(engine._probe_dialect_key(), "oracle")

    def test_provider_canonical_dialect_db2(self):
        engine = _make_engine()
        engine.provider.canonical_dialect_key = "db2"
        self.assertEqual(engine._probe_dialect_key(), "db2")

    def test_falls_back_to_config_type_when_provider_missing_attribute(self):
        engine = _make_engine()
        engine.provider.canonical_dialect_key = ""  # not declared
        engine.sql_analyzer.dialect = None
        engine.config.database.url = ""
        # ``database.type`` is a plain string (real configs do this when not
        # using the ``DatabaseType`` enum). A bare ``MagicMock`` would defeat
        # ``_normalize``'s ``isinstance(raw, Enum)`` branch and fall through
        # to ``str(MagicMock(...))`` — nonsense the registry can't resolve.
        engine.config.database.type = "oracle"
        self.assertEqual(engine._probe_dialect_key(), "oracle")

    def test_no_config_falls_back_to_analyzer_dialect(self):
        engine = _make_engine(with_config=False)
        engine.provider.canonical_dialect_key = ""
        engine.sql_analyzer.dialect = "mysql"
        result = engine._probe_dialect_key()
        self.assertEqual(result, "mysql")

    def test_mssql_alias_normalised_to_sqlserver(self):
        engine = _make_engine()
        engine.provider.canonical_dialect_key = ""
        engine.sql_analyzer.dialect = None
        engine.config.database.url = ""
        # See note in ``test_falls_back_to_config_type_when_provider_missing_attribute``
        # — pass a real string so ``_normalize`` runs the registry resolution
        # path. ``mssql`` is the SQLAlchemy alias the registry canonicalizes to
        # ``sqlserver``.
        engine.config.database.type = "mssql"
        self.assertEqual(engine._probe_dialect_key(), "sqlserver")


# ---------------------------------------------------------------------------
# _transaction_liveness_probe_sql
# ---------------------------------------------------------------------------


class TestTransactionLivenessProbeSQL(unittest.TestCase):
    """PR-F4: the per-dialect probe SQL comes from ``ProviderRegistry.get_quirks(...)``.

    The dialect key the registry receives now flows through
    ``provider.canonical_dialect_key`` (set by each plugin) instead of a
    framework-side URL-sniff.
    """

    def test_oracle_returns_dual(self):
        engine = _make_engine()
        engine.provider.canonical_dialect_key = "oracle"
        probe = engine._transaction_liveness_probe_sql()
        self.assertIn("DUAL", probe)

    def test_db2_returns_sysibm(self):
        engine = _make_engine()
        engine.provider.canonical_dialect_key = "db2"
        probe = engine._transaction_liveness_probe_sql()
        self.assertIn("SYSIBM", probe)

    def test_postgresql_returns_select_1(self):
        engine = _make_engine(dialect="postgresql")
        engine.provider.canonical_dialect_key = "postgresql"
        probe = engine._transaction_liveness_probe_sql()
        self.assertEqual(probe, "SELECT 1")


# ---------------------------------------------------------------------------
# _record_migration_history
# ---------------------------------------------------------------------------


class TestRecordMigrationHistory(unittest.TestCase):
    def test_no_history_manager_does_nothing(self):
        engine = _make_engine(with_history=False)
        migration = _make_sql_migration()
        # Should not raise
        engine._record_migration_history(migration, 100)

    def test_success_records_migration(self):
        engine = _make_engine(with_history=True)
        migration = _make_sql_migration()

        engine._record_migration_history(migration, 200)

        engine.history_manager.record_migration.assert_called_once_with(
            migration, success=True, execution_time=200
        )

    def test_history_error_triggers_rollback_and_reraises(self):
        engine = _make_engine(with_history=True)
        engine.history_manager.record_migration.side_effect = Exception("db error")
        migration = _make_sql_migration()

        with self.assertRaises(Exception, msg="db error"):
            engine._record_migration_history(migration, 100)

        engine.provider.rollback_transaction.assert_called_once()
        engine.log.error.assert_called()

    def test_history_error_rollback_failure_logs_warning(self):
        engine = _make_engine(with_history=True)
        engine.history_manager.record_migration.side_effect = Exception("history err")
        engine.provider.rollback_transaction.side_effect = Exception("rollback err")
        migration = _make_sql_migration()

        with self.assertRaises(Exception):
            engine._record_migration_history(migration, 100)

        engine.log.warning.assert_called()


# ---------------------------------------------------------------------------
# _record_autocommit_migration_history
# ---------------------------------------------------------------------------


class TestRecordAutocommitMigrationHistory(unittest.TestCase):
    def test_no_history_manager_does_nothing(self):
        engine = _make_engine(with_history=False)
        migration = _make_sql_migration()
        engine._record_autocommit_migration_history(migration, 50)  # no raise

    def test_records_and_commits(self):
        engine = _make_engine(with_history=True)
        migration = _make_sql_migration()

        engine._record_autocommit_migration_history(migration, 150)

        engine.history_manager.record_migration.assert_called_once_with(
            migration, success=True, execution_time=150
        )
        engine.provider.commit_transaction.assert_called_once()

    def test_history_error_triggers_rollback_and_reraises(self):
        engine = _make_engine(with_history=True)
        engine.history_manager.record_migration.side_effect = Exception("record failed")
        migration = _make_sql_migration()

        with self.assertRaises(Exception):
            engine._record_autocommit_migration_history(migration, 50)

        engine.provider.rollback_transaction.assert_called_once()

    def test_rollback_failure_logged_as_warning(self):
        engine = _make_engine(with_history=True)
        engine.history_manager.record_migration.side_effect = Exception("record error")
        engine.provider.rollback_transaction.side_effect = Exception("rollback error")
        migration = _make_sql_migration()

        with self.assertRaises(Exception):
            engine._record_autocommit_migration_history(migration, 50)

        engine.log.warning.assert_called()


# ---------------------------------------------------------------------------
# _handle_statement_failure
# ---------------------------------------------------------------------------


class TestHandleStatementFailure(unittest.TestCase):
    def test_sets_error_and_rollback(self):
        engine = _make_engine(with_history=True)
        migration = _make_sql_migration()
        result = MagicMock()
        result.add_migration = MagicMock()

        engine._handle_statement_failure(migration, Exception("sql error"), 0, 100, result)

        result.set_error.assert_called_once()
        engine.provider.rollback_transaction.assert_called_once()

    def test_adds_migration_info_to_result(self):
        engine = _make_engine(with_history=True)
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 1, 200, result)

        result.add_migration.assert_called_once()
        info = result.add_migration.call_args[0][0]
        self.assertEqual(info.status, "FAILED")
        self.assertEqual(info.script, migration.script_name)

    def test_records_failed_history_when_history_manager_present(self):
        engine = _make_engine(with_history=True)
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 0, 100, result)

        engine.history_manager.record_migration.assert_called_once_with(
            migration, success=False, execution_time=100
        )
        engine.provider.commit_transaction.assert_called_once()

    def test_no_history_manager_skips_history(self):
        engine = _make_engine(with_history=False)
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 0, 50, result)

        # no history_manager so record_migration never called
        # (no attribute to assert on, just shouldn't raise)

    def test_history_write_failure_sets_failed_history_persisted_false(self):
        engine = _make_engine(with_history=True)
        engine.history_manager.record_migration.side_effect = Exception("history fail")
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("stmt fail"), 0, 100, result)

        self.assertFalse(result.failed_history_persisted)

    def test_non_transactional_ddl_warns(self):
        engine = _make_engine(with_history=True)
        engine.provider.supports_transactional_ddl.return_value = False
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 0, 100, result)

        warning_calls = [str(c) for c in engine.log.warning.call_args_list]
        self.assertTrue(any("transactional DDL" in c for c in warning_calls))

    def test_rollback_failure_logs_warning(self):
        engine = _make_engine(with_history=False)
        engine.provider.rollback_transaction.side_effect = Exception("rollback failed")
        migration = _make_sql_migration()
        result = MagicMock()

        engine._handle_statement_failure(migration, Exception("fail"), 0, 100, result)

        warning_calls = [str(c) for c in engine.log.warning.call_args_list]
        self.assertTrue(any("Could not rollback transaction" in c for c in warning_calls))

    def test_preserves_embedded_sql_for_migration_script_statement_errors(self):
        """Regression guard: unlike format_connection_error (which hides
        dblift's own schema-setup SQL from connection/setup errors),
        _handle_statement_failure reports failures in a *user's own*
        migration script, so the failing '[SQL: ...]' statement must stay
        visible in the message so they can tell which statement broke.

        _strip_driver_exception_prefix (shared with format_connection_error)
        must not gain SQL-block stripping — that behavior belongs only to
        format_connection_error's db_type-specific formatting.
        """
        engine = _make_engine(with_history=False)
        migration = _make_sql_migration()
        result = MagicMock()
        raw_error = OperationalError(
            "CREATE TABLE users (id INT)", None, Exception("ORA-00001: unique constraint violated")
        )

        engine._handle_statement_failure(migration, raw_error, 0, 100, result)

        error_message = result.set_error.call_args[0][0]
        self.assertIn("CREATE TABLE users (id INT)", error_message)


# ---------------------------------------------------------------------------
# _commit_and_verify
# ---------------------------------------------------------------------------


class TestCommitAndVerify(unittest.TestCase):
    def test_commits_transaction(self):
        engine = _make_engine()
        migration = _make_sql_migration()

        engine._commit_and_verify(migration, ["SELECT 1"], 100)

        engine.provider.commit_transaction.assert_called_once()

    def test_commit_failure_raises(self):
        engine = _make_engine()
        engine.provider.commit_transaction.side_effect = Exception("commit failed")
        migration = _make_sql_migration()

        with self.assertRaises(Exception, msg="commit failed"):
            engine._commit_and_verify(migration, ["SELECT 1"], 100)

        engine.log.warning.assert_called()

    def test_create_table_triggers_verification(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection.isClosed.return_value = False
        engine.provider.execute_query.return_value = [{"cnt": 0}]
        engine.sql_analyzer.dialect = "postgresql"

        statements = ["CREATE TABLE public.users (id SERIAL)"]
        engine._commit_and_verify(migration, statements, 100)

        engine.provider.commit_transaction.assert_called_once()
        # execute_query for verification
        query_calls = [str(c) for c in engine.provider.execute_query.call_args_list]
        self.assertTrue(any("users" in c.lower() for c in query_calls))

    def test_create_table_verification_failure_is_non_critical(self):
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection.isClosed.return_value = False
        engine.provider.execute_query.side_effect = Exception("table not found")
        engine.sql_analyzer.dialect = "postgresql"

        statements = ["CREATE TABLE public.users (id SERIAL)"]
        # Should not raise
        engine._commit_and_verify(migration, statements, 100)

        debug_calls = [str(c) for c in engine.log.debug.call_args_list]
        self.assertTrue(any("Post-commit verification" in c for c in debug_calls))

    def test_no_isclosed_attribute_still_runs_verification(self):
        """Python DB-API drivers (e.g. python-oracledb) expose ``closed`` as a
        property, not an isClosed() method. Without a guard, the missing
        attribute raised AttributeError, was swallowed by the inner
        try/except, and the post-commit verification query never ran. It
        should instead fall back to assuming the connection is open (the
        caller already confirmed ``self.provider.connection`` is truthy) and
        actually run the verification query.
        """
        engine = _make_engine()
        migration = _make_sql_migration()
        engine.provider.connection = object()  # no getAutoCommit()/isClosed()
        engine.provider.execute_query.return_value = [{"cnt": 0}]
        engine.sql_analyzer.dialect = "postgresql"

        statements = ["CREATE TABLE public.users (id SERIAL)"]
        engine._commit_and_verify(migration, statements, 100)

        engine.provider.execute_query.assert_called_once()
        debug_calls = [str(c) for c in engine.log.debug.call_args_list]
        self.assertFalse(
            any("Post-commit verification query failed" in c for c in debug_calls),
            "isClosed() absence should be handled by a guard, not caught as an error",
        )


# ---------------------------------------------------------------------------
# execute_callback
# ---------------------------------------------------------------------------


class TestExecuteCallback(unittest.TestCase):
    def _make_callback(self, sql_statements=None, name="afterEach__log.sql"):
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.SQL
        cb.script_name = name
        cb.dialect = "postgresql"
        cb.parse_sql_statements.return_value = sql_statements or ["INSERT INTO t VALUES (1)"]
        return cb

    def test_sql_callback_executes_dml_statement(self):
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.execute_statement.return_value = 1
        cb = self._make_callback()

        engine.execute_callback(cb)

        engine.provider.execute_statement.assert_called_once()
        engine.provider.commit_transaction.assert_called_once()

    def test_sql_callback_sets_configured_schema_before_statements(self):
        engine = _make_engine()
        engine.config.database.schema = "app"
        engine.sql_analyzer.get_statement_type.return_value = "DDL"
        engine.provider.execute_statement.return_value = 0

        cb = self._make_callback(sql_statements=["CREATE TABLE callback_log (id INT)"])

        engine.execute_callback(cb)

        engine.provider.set_current_schema.assert_called_once_with("app")
        assert engine.provider.method_calls.index(
            unittest.mock.call.set_current_schema("app")
        ) < engine.provider.method_calls.index(
            unittest.mock.call.execute_statement("CREATE TABLE callback_log (id INT)")
        )

    def test_sql_callback_uses_sql_execution_service_when_available(self):
        engine = _make_engine()
        engine.sql_execution_service = MagicMock()
        engine.sql_execution_service.execute_statement.return_value = (False, 1)
        cb = self._make_callback(sql_statements=["CREATE TABLE callback_log (id INT)"])

        engine.execute_callback(cb)

        engine.sql_execution_service.execute_statement.assert_called_once_with(
            "CREATE TABLE callback_log (id INT)"
        )
        engine.provider.execute_statement.assert_not_called()
        engine.provider.commit_transaction.assert_called_once()

    def test_sql_callback_executes_query_statement(self):
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "QUERY"
        engine.provider.execute_query.return_value = [{"id": 1}]
        cb = self._make_callback(sql_statements=["SELECT 1"])

        engine.execute_callback(cb)

        engine.provider.execute_query.assert_called_once()
        engine.provider.commit_transaction.assert_called_once()

    def test_sql_callback_commit_failure_logs_warning(self):
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.execute_statement.return_value = 0
        engine.provider.commit_transaction.side_effect = Exception("commit failed")
        cb = self._make_callback()

        # Should not raise
        engine.execute_callback(cb)

        engine.log.warning.assert_called()

    def test_sql_callback_statement_failure_triggers_rollback(self):
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.execute_statement.side_effect = Exception("constraint violation")
        cb = self._make_callback()

        with self.assertRaises(Exception):
            engine.execute_callback(cb)

        engine.provider.rollback_transaction.assert_called()

    def test_sql_callback_begin_transaction_failure_continues(self):
        """begin_transaction failure is not fatal for callbacks."""
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.begin_transaction.side_effect = Exception("begin failed")
        engine.provider.execute_statement.return_value = 0
        cb = self._make_callback()

        # Should not raise; the callback continues without explicit transaction
        engine.execute_callback(cb)

        engine.log.warning.assert_called()
        engine.provider.execute_statement.assert_called_once()

    def test_python_callback_success(self):
        engine = _make_engine()
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.PYTHON
        cb.script_name = "afterEach__log.py"

        exec_result = MagicMock()
        exec_result.success = True
        exec_result.error = None
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result

        engine.execute_callback(cb)

        engine.log.info.assert_called()
        info_calls = [str(c) for c in engine.log.info.call_args_list]
        self.assertTrue(any("successfully" in c for c in info_calls))

    def test_python_callback_failure_raises_callback_error(self):
        engine = _make_engine()
        cb = MagicMock(spec=Migration)
        cb.format = MigrationFormat.PYTHON
        cb.script_name = "afterEach__log.py"

        exec_result = MagicMock()
        exec_result.success = False
        exec_result.error = "script raised ValueError"
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result

        with self.assertRaises(CallbackExecutionError):
            engine.execute_callback(cb)

    def test_sql_callback_parse_error_reraises(self):
        engine = _make_engine()
        cb = self._make_callback()
        cb.parse_sql_statements.side_effect = Exception("parse error")

        with self.assertRaises(Exception):
            engine.execute_callback(cb)

    def test_callback_content_is_substituted_once_before_parsing(self):
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "DML"
        engine.provider.execute_statement.return_value = 0
        engine.placeholder_service = MagicMock()
        engine.placeholder_service.replace_placeholders.return_value = "INSERT INTO t VALUES (42)"
        cb = self._make_callback(sql_statements=["INSERT INTO t VALUES (42)"])
        cb.content = "INSERT INTO t VALUES (${val})"

        engine.execute_callback(cb)

        # Substitution runs once, on the whole file, and the parser gets the result.
        engine.placeholder_service.replace_placeholders.assert_called_once_with(
            "INSERT INTO t VALUES (${val})"
        )
        assert (
            cb.parse_sql_statements.call_args.kwargs["content_override"]
            == "INSERT INTO t VALUES (42)"
        )

    def test_query_result_zero_rows_logs_info(self):
        engine = _make_engine()
        engine.sql_analyzer.get_statement_type.return_value = "QUERY"
        engine.provider.execute_query.return_value = []
        cb = self._make_callback(sql_statements=["SELECT 1 WHERE 1=0"])

        engine.execute_callback(cb)

        engine.provider.execute_query.assert_called_once()


# ---------------------------------------------------------------------------
# _execute_via_factory — edge cases
# ---------------------------------------------------------------------------


class TestExecuteViaFactory(unittest.TestCase):
    def test_no_executor_found_sets_error(self):
        engine = _make_engine()
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.side_effect = ValueError("no executor for format PYTHON")
        migration = _make_python_migration()
        result = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            engine._execute_via_factory(migration, result)

        result.set_error.assert_called()
        error_msg = result.set_error.call_args[0][0]
        self.assertIn("No executor found", error_msg)

    def test_unexpected_exception_sets_error(self):
        engine = _make_engine()
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.side_effect = RuntimeError("unexpected crash")
        migration = _make_python_migration()
        result = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            engine._execute_via_factory(migration, result)

        result.set_error.assert_called()
        error_msg = result.set_error.call_args[0][0]
        self.assertIn("Unexpected error", error_msg)

    def test_history_error_sets_error_and_rollback(self):
        engine = _make_engine(with_history=True)
        exec_result = MagicMock()
        exec_result.success = True
        exec_result.execution_time_ms = 100
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result
        engine.history_manager.record_migration.side_effect = Exception("history fail")
        migration = _make_python_migration()
        result = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            engine._execute_via_factory(migration, result)

        result.set_error.assert_called()
        engine.provider.rollback_transaction.assert_called()

    def test_commit_error_sets_error_and_rollback(self):
        engine = _make_engine(with_history=True)
        exec_result = MagicMock()
        exec_result.success = True
        exec_result.execution_time_ms = 100
        engine.executor_factory = MagicMock()
        engine.executor_factory.execute.return_value = exec_result
        engine.provider.commit_transaction.side_effect = Exception("commit failed")
        migration = _make_python_migration()
        result = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=True):
            engine._execute_via_factory(migration, result)

        result.set_error.assert_called()

    def test_prepare_transaction_failure_aborts(self):
        engine = _make_engine()
        migration = _make_python_migration()
        result = MagicMock()

        with patch.object(engine, "_prepare_transaction", return_value=False):
            engine._execute_via_factory(migration, result)

        result.set_error.assert_called_once()
        self.assertIn("Could not begin transaction", result.set_error.call_args[0][0])


if __name__ == "__main__":
    unittest.main()


class _RoutingProvider(TransactionalProvider):
    """Minimal provider recording which execution path each statement takes.

    Not a ``MagicMock`` on purpose: routing must fail loudly if the engine
    calls a method this contract does not have.
    """

    def __init__(self):
        self.connection = None
        self.calls = []

    def begin_transaction(self):  # noqa: D102
        pass

    def commit_transaction(self):  # noqa: D102
        pass

    def rollback_transaction(self):  # noqa: D102
        pass

    def execute_query(self, sql, params=None):
        self.calls.append(("query", sql))
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.calls.append(("execute", sql))
        return 1

    def execute_autocommit_statement(self, sql, schema=None, params=None):
        self.calls.append(("autocommit", sql))
        return 1


class _PlainProvider:
    """Provider outside the TransactionalProvider contract."""

    def __init__(self):
        self.calls = []

    def execute_statement(self, sql, schema=None, params=None):
        self.calls.append(("execute", sql))
        return 1


class TestAutocommitStatementRouting(unittest.TestCase):
    """_execute_statements routes flagged migrations through the provider's autocommit call.

    The engine deliberately holds no dialect knowledge: which statements need
    autocommit is policy, and *how* to run one outside a transaction block
    belongs to whichever provider owns the connection. The switch is per
    statement, so nothing else the engine does inherits it.
    """

    @staticmethod
    def _engine_with(provider):
        analyzer = MagicMock()
        analyzer.dialect = "postgresql"
        return ExecutionEngine(
            provider=provider,
            sql_analyzer=analyzer,
            log=MagicMock(),
            config=None,
            history_manager=None,
        )

    def test_autocommit_migration_uses_the_autocommit_call(self):
        provider = _RoutingProvider()
        engine = self._engine_with(provider)
        statement = "CREATE INDEX CONCURRENTLY ix ON t (c)"

        ok = engine._execute_statements(
            [statement], _make_sql_migration(), MagicMock(), 0.0, autocommit=True
        )

        self.assertTrue(ok)
        self.assertIn(("autocommit", statement), provider.calls)
        self.assertNotIn(("execute", statement), provider.calls)

    def test_ordinary_migration_uses_plain_execution(self):
        provider = _RoutingProvider()
        engine = self._engine_with(provider)
        statement = "CREATE TABLE t (id INT)"

        ok = engine._execute_statements([statement], _make_sql_migration(), MagicMock(), 0.0)

        self.assertTrue(ok)
        self.assertIn(("execute", statement), provider.calls)
        self.assertTrue(all(kind != "autocommit" for kind, _ in provider.calls))

    def test_provider_outside_the_contract_falls_back_to_plain_execution(self):
        """A provider without the contract must still be usable, not crash."""
        provider = _PlainProvider()
        engine = self._engine_with(provider)
        statement = "CREATE THING"

        ok = engine._execute_statements(
            [statement], _make_sql_migration(), MagicMock(), 0.0, autocommit=True
        )

        self.assertTrue(ok)
        self.assertEqual(provider.calls, [("execute", statement)])
