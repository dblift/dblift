"""Characterization of ExecutionEngine._execute_statements: skipped failures and success logs."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dblift.core.exceptions import TransactionAbortedError
from dblift.core.migration.executor import execution_engine
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.db.plugins.oracle.parser.sqlplus_context import SqlplusContext
from dblift.db.provider_interfaces import TransactionalProvider

pytestmark = pytest.mark.unit


def _oracle_engine() -> ExecutionEngine:
    provider = MagicMock()
    provider.connection = None
    sql_analyzer = MagicMock()
    sql_analyzer.dialect = "oracle"
    engine = ExecutionEngine(provider=provider, sql_analyzer=sql_analyzer, log=MagicMock())
    engine._current_sqlplus_ctx = SqlplusContext()
    return engine


def test_whenever_sqlerror_continue_does_not_skip_an_os_error():
    engine = _oracle_engine()
    engine.provider.execute_statement.side_effect = [OSError("socket closed"), 1]
    migration = MagicMock()
    migration.script_name = "V1__t.sql"
    result = MagicMock()

    outcome = engine._execute_statements(
        ["WHENEVER SQLERROR CONTINUE", "DROP TABLE t", "SELECT 1 FROM DUAL"],
        migration,
        result,
        0.0,
    )

    assert outcome is False
    assert engine.provider.execute_statement.call_count == 1
    result.set_error.assert_called_once()
    assert "socket closed" in result.set_error.call_args.args[0]


def _plain_engine(service=None) -> ExecutionEngine:
    provider = MagicMock()
    provider.connection = None
    sql_analyzer = MagicMock()
    sql_analyzer.dialect = "postgresql"
    return ExecutionEngine(
        provider=provider,
        sql_analyzer=sql_analyzer,
        log=MagicMock(),
        sql_execution_service=service,
    )


def _info_messages(engine: ExecutionEngine) -> list:
    return [call.args[0] for call in engine.log.info.call_args_list]


def test_a_statement_that_affects_no_row_logs_zero_rows():
    engine = _plain_engine()
    engine.provider.execute_statement.return_value = 0

    assert engine._execute_statements(["UPDATE t SET a = 1"], MagicMock(), MagicMock(), 0.0)

    assert _info_messages(engine) == ["Statement executed successfully, 0 rows affected "]


def test_a_query_that_returns_no_row_logs_zero_rows():
    service = MagicMock()
    service.execute_statement.return_value = (True, [])
    engine = _plain_engine(service)
    result = MagicMock()
    result.show_query_results = False

    assert engine._execute_statements(["SELECT a FROM t"], MagicMock(), result, 0.0)

    assert _info_messages(engine) == ["Statement executed successfully, 0 rows affected "]


def test_the_aborted_transaction_error_keeps_the_driver_cause():
    driver_error = ValueError("server closed the transaction")
    aborted = TransactionAbortedError("aborted")
    aborted.__cause__ = driver_error
    provider = MagicMock(spec=TransactionalProvider)
    provider.check_transaction_state.side_effect = aborted
    engine = ExecutionEngine(provider=provider, sql_analyzer=MagicMock(), log=MagicMock())
    failures = []
    engine._handle_statement_failure = lambda *args: failures.append(args)

    assert not engine._execute_statements(["SELECT 1"], MagicMock(), MagicMock(), 0.0)

    error = failures[0][1]
    assert isinstance(error, TransactionAbortedError)
    assert error.__cause__ is driver_error


def test_a_context_without_the_session_output_flag_enables_no_capture():
    engine = _oracle_engine()
    engine._current_sqlplus_ctx = SimpleNamespace()
    engine.provider.connection = MagicMock()
    engine.provider.execute_statement.return_value = 0

    with patch("dblift.db.plugins.oracle.oracle.dbms_output.enable_dbms_output") as enable:
        engine._execute_statements(["SELECT 1 FROM DUAL"], MagicMock(), MagicMock(), 0.0)

    enable.assert_not_called()


def test_an_end_of_unit_failure_without_a_statement_index_names_the_last_statement():
    engine = _plain_engine()
    engine.provider.execute_statement.return_value = 1
    engine.provider.finish_migration_statements.side_effect = RuntimeError("deferred failure")
    migration = MagicMock()
    migration.script_name = "V1__t.sql"
    result = MagicMock()

    assert not engine._execute_statements(["SELECT 1", "SELECT 2"], migration, result, 0.0)

    assert result.set_error.call_args.args[0].startswith(
        "Failed to execute statement 2 in V1__t.sql:"
    )


def test_a_failed_statement_is_timed_from_the_start_of_the_migration(monkeypatch):
    clock = iter([10.0, 10.5, 11.0])
    monkeypatch.setattr(execution_engine, "time", SimpleNamespace(time=lambda: next(clock)))
    history = MagicMock()
    engine = ExecutionEngine(
        provider=MagicMock(), sql_analyzer=MagicMock(), log=MagicMock(), history_manager=history
    )
    engine.provider.execute_statement.side_effect = RuntimeError("syntax error")
    migration = MagicMock()
    migration.script_name = "V1__t.sql"

    assert not engine._execute_statements(["SELEC 1"], migration, MagicMock(), 4.0)

    assert history.record_migration.call_args.kwargs["execution_time"] == 7000
