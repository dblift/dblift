"""Characterize how a SQL callback handles each statement's outcome.

Covers query results that are not row lists, non-query results without a row
count, and the presentation of captured query rows, on both execution paths:
through the SQL execution service and directly through the provider.
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.logger.results import CallbackExecution, OperationResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executor.transaction_policy import TransactionPolicyDecision
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.db.provider_interfaces import TransactionalProvider
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit

QUERY = "SELECT status FROM jobs"
UPDATE = "UPDATE jobs SET status = 'done'"


def _callback(*statements: str):
    return make_migration(
        script_name="afterMigrate__report.sql",
        content=";\n".join(statements),
        sql_statements=list(statements),
    )


def _engine(service=None, presenter=None):
    provider = MagicMock()
    provider.__class__ = TransactionalProvider
    provider.supports_transactions.return_value = True
    engine = ExecutionEngine(provider, StatementReader(dialect="postgresql"), MagicMock(), service)
    engine._classify_execution_statements = MagicMock(return_value=[])
    engine.transaction_policy = MagicMock()
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(transactional=True)
    engine._presentation = presenter
    return engine


def _service(*outcomes):
    service = MagicMock()
    service.execute_statement.side_effect = list(outcomes)
    return service


def _shown_result():
    result = OperationResult()
    result.show_query_results = True
    return result


def _info_messages(engine):
    return [call.args[0] for call in engine.log.info.call_args_list]


def test_service_query_result_that_is_not_a_row_list_fails_the_callback():
    engine = _engine(_service((True, "not rows")))

    with pytest.raises(TypeError, match="^Expected list for query result, got str$"):
        engine.execute_callback(_callback(QUERY))

    engine.provider.rollback_transaction.assert_called_once_with()
    engine.provider.commit_transaction.assert_not_called()


def test_service_query_rows_are_presented_when_a_presenter_is_composed():
    presenter = MagicMock()
    engine = _engine(
        _service((True, [{"status": "active"}, {"status": "idle"}])), presenter=presenter
    )
    record = CallbackExecution("afterMigrate", "report", "afterMigrate__report.sql")

    engine.execute_callback(_callback(QUERY), _shown_result(), record)

    presenter.present_query_result.assert_called_once_with(
        engine, ["status"], [["active"], ["idle"]]
    )
    assert record.result_sets == [
        {"statement": QUERY, "columns": ["status"], "rows": [["active"], ["idle"]]}
    ]
    assert record.row_count == 2


def test_service_statement_without_a_row_count_logs_plain_success():
    engine = _engine(_service((False, None)))

    engine.execute_callback(_callback(UPDATE))

    assert _info_messages(engine) == ["Statement executed successfully"]


def test_provider_query_result_that_is_not_a_row_list_is_logged_and_skipped():
    engine = _engine()
    engine.provider.execute_query.return_value = None
    engine.provider.execute_statement.return_value = 2
    record = CallbackExecution("afterMigrate", "report", "afterMigrate__report.sql")

    engine.execute_callback(_callback(QUERY, UPDATE), _shown_result(), record)

    assert _info_messages(engine) == [
        "Query executed successfully, unknown rows returned",
        "Statement executed successfully, 2 rows affected",
    ]
    assert [statement.rstrip(";") for statement in record.statements] == [QUERY, UPDATE]
    assert record.result_sets == []
    assert record.row_count == 0
    engine.provider.commit_transaction.assert_called_once_with()


def test_provider_query_rows_are_presented_when_a_presenter_is_composed():
    presenter = MagicMock()
    engine = _engine(presenter=presenter)
    engine.provider.execute_query.return_value = [{"status": "active"}, {"status": "idle"}]
    result = _shown_result()
    record = CallbackExecution("afterMigrate", "report", "afterMigrate__report.sql")

    engine.execute_callback(_callback(QUERY), result, record)

    presenter.present_query_result.assert_called_once_with(
        engine, ["status"], [["active"], ["idle"]]
    )
    assert result.query_results[0].results[0]["rows"] == [["active"], ["idle"]]
    assert record.result_sets == [
        {"statement": QUERY, "columns": ["status"], "rows": [["active"], ["idle"]]}
    ]
    assert record.row_count == 2


def test_provider_query_rows_are_kept_without_a_presenter():
    engine = _engine(presenter=None)
    engine.provider.execute_query.return_value = [{"status": "active"}]
    result = _shown_result()

    engine.execute_callback(_callback(QUERY), result)

    assert result.query_results[0].results[0]["rows"] == [["active"]]
    engine.provider.commit_transaction.assert_called_once_with()
