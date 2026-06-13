"""Tests for SQL*Plus context integration in ExecutionEngine."""

from unittest.mock import MagicMock, patch

from core.exceptions import TransactionAbortedError
from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration
from db.plugins.oracle.parser.sqlplus_context import SqlplusContext


def _make_engine(dialect="oracle"):
    provider = MagicMock()
    provider.supports_transactions.return_value = True
    provider.connection = None  # no native connection in unit tests
    sql_analyzer = MagicMock()
    sql_analyzer.dialect = dialect
    log = MagicMock()
    config = MagicMock()
    config.database.type.value = dialect
    config.database.url = "oracle+oracledb://host:1521?service_name=XE"
    return ExecutionEngine(provider=provider, sql_analyzer=sql_analyzer, log=log, config=config)


def _make_sql_migration(content: str) -> Migration:
    m = MagicMock(spec=Migration)
    m.format = MigrationFormat.SQL
    m.content = content
    m.script_name = "V1__test.sql"
    m.parse_sql_statements.return_value = ["SELECT 1 FROM DUAL"]
    return m


class TestSqlplusContextExtraction:
    def test_context_extracted_for_oracle(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration("SET SERVEROUTPUT ON\nSELECT 1 FROM DUAL;")
        result = MagicMock()
        result.has_error.return_value = False

        engine._parse_sql_statements(migration, result)

        assert engine._current_sqlplus_ctx is not None
        assert engine._current_sqlplus_ctx.serveroutput is True

    def test_no_context_for_non_oracle(self):
        engine = _make_engine("postgresql")
        migration = _make_sql_migration("SET SERVEROUTPUT ON\nSELECT 1;")
        result = MagicMock()
        result.has_error.return_value = False

        engine._parse_sql_statements(migration, result)

        assert engine._current_sqlplus_ctx is None

    def test_define_substitution_applied_before_parsing(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration("DEFINE owner = APP_SCHEMA\nSELECT * FROM &owner.users;")
        result = MagicMock()

        engine._parse_sql_statements(migration, result)

        # content_override passed to parse_sql_statements must have substitution applied
        call_kwargs = migration.parse_sql_statements.call_args
        content_arg = call_kwargs.kwargs.get("content_override") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        assert content_arg is not None
        assert "&owner" not in content_arg
        assert "APP_SCHEMA" in content_arg

    def test_define_off_skips_substitution(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration(
            "SET DEFINE OFF\nDEFINE owner = APP\nSELECT * FROM &owner.t;"
        )
        result = MagicMock()

        engine._parse_sql_statements(migration, result)

        ctx = engine._current_sqlplus_ctx
        assert ctx.define_on is False

    def test_prompt_messages_logged(self):
        engine = _make_engine("oracle")
        migration = _make_sql_migration("PROMPT Starting data migration\nSELECT 1 FROM DUAL;")
        result = MagicMock()

        engine._parse_sql_statements(migration, result)

        log_calls = [str(c) for c in engine.log.info.call_args_list]
        assert any("Starting data migration" in c for c in log_calls)


class TestWheneverSqlerrorContinue:
    def test_continue_policy_skips_failed_statement(self):
        # WHENEVER SQLERROR CONTINUE in the statement list switches policy positionally.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = [
            Exception("ORA-00942: table or view does not exist"),
            5,
        ]

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR CONTINUE", "DROP TABLE maybe_exists", "SELECT 5 FROM DUAL"],
            migration,
            result,
            0.0,
        )

        assert outcome is True
        assert engine.provider.execute_statement.call_count == 2
        engine.log.warning.assert_called()

    def test_exit_policy_stops_on_first_failure(self):
        # Default policy is "exit"; explicit WHENEVER SQLERROR EXIT also sets it.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = Exception("ORA-00942")

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR EXIT", "DROP TABLE maybe_exists", "SELECT 5 FROM DUAL"],
            migration,
            result,
            0.0,
        )

        assert outcome is False
        assert engine.provider.execute_statement.call_count == 1

    def test_policy_switches_mid_script(self):
        # CONTINUE before critical section, EXIT after — each statement runs under its policy.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = [
            Exception("ORA-00942"),  # cleanup DDL fails → CONTINUE skips
            0,  # main DDL succeeds
        ]

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            [
                "WHENEVER SQLERROR CONTINUE",
                "DROP TABLE maybe_exists",  # fails, skipped
                "WHENEVER SQLERROR EXIT",
                "CREATE TABLE t (id NUMBER)",  # succeeds
            ],
            migration,
            result,
            0.0,
        )

        assert outcome is True
        assert engine.provider.execute_statement.call_count == 2

    def test_infrastructure_error_not_swallowed_by_continue(self):
        # TransactionAbortedError must not be swallowed by WHENEVER SQLERROR CONTINUE;
        # only database-level SQL errors are skippable.
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext()
        engine.provider.execute_statement.side_effect = TransactionAbortedError("tx aborted")

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR CONTINUE", "DROP TABLE t"],
            migration,
            result,
            0.0,
        )

        assert outcome is False
        assert engine.provider.execute_statement.call_count == 1
        result.set_error.assert_called()

    def test_whenever_ignored_for_non_oracle_dialect(self):
        # For non-Oracle dialects, WHENEVER SQLERROR CONTINUE must not suppress errors.
        engine = _make_engine("postgresql")
        engine._current_sqlplus_ctx = None  # non-Oracle: no SqlplusContext
        engine.provider.execute_statement.side_effect = Exception("relation does not exist")

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()
        result.has_error.return_value = False

        outcome = engine._execute_statements(
            ["WHENEVER SQLERROR CONTINUE", "DROP TABLE t"],
            migration,
            result,
            0.0,
        )

        # WHENEVER SQLERROR CONTINUE is not processed for non-Oracle: statement fails normally.
        assert outcome is False
        assert engine.provider.execute_statement.call_count == 1


class TestDbmsOutputIntegration:
    def test_serveroutput_on_enables_dbms_output(self):
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext(serveroutput=True)
        conn = MagicMock()
        engine.provider.connection = conn
        engine.provider.execute_statement.return_value = 0

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()

        with (
            patch("db.plugins.oracle.oracle.dbms_output.enable_dbms_output") as mock_enable,
            patch("db.plugins.oracle.oracle.dbms_output.read_dbms_output") as mock_read,
        ):
            engine._execute_statements(["SELECT 1 FROM DUAL"], migration, result, 0.0)

        mock_enable.assert_called_once_with(conn)
        mock_read.assert_called_once_with(conn, engine.log)

    def test_serveroutput_off_does_not_enable(self):
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext(serveroutput=False)
        engine.provider.connection = MagicMock()
        engine.provider.execute_statement.return_value = 0

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()

        with patch("db.plugins.oracle.oracle.dbms_output.enable_dbms_output") as mock_enable:
            engine._execute_statements(["SELECT 1 FROM DUAL"], migration, result, 0.0)

        mock_enable.assert_not_called()

    def test_no_connection_skips_dbms_output(self):
        engine = _make_engine("oracle")
        engine._current_sqlplus_ctx = SqlplusContext(serveroutput=True)
        engine.provider.connection = None  # no connection
        engine.provider.execute_statement.return_value = 0

        migration = MagicMock()
        migration.script_name = "V1__test.sql"
        result = MagicMock()

        with patch("db.plugins.oracle.oracle.dbms_output.enable_dbms_output") as mock_enable:
            engine._execute_statements(["SELECT 1 FROM DUAL"], migration, result, 0.0)

        mock_enable.assert_not_called()
