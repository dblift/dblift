"""SQL callbacks honor the same transaction policy as migrations."""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import CallbackExecutionError
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executor.transaction_policy import TransactionPolicyDecision
from dblift.core.migration.migration import Migration
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.provider_interfaces import TransactionalProvider

pytestmark = pytest.mark.unit

SQL = "CREATE INDEX CONCURRENTLY idx_t_id ON t(id)"


@pytest.fixture
def callback():
    return Migration(script_name="beforeMigrate__index.sql", content=SQL, sql_statements=[SQL])


@pytest.fixture
def engine():
    provider = MagicMock(spec=TransactionalProvider)
    provider.supports_transactions.return_value = True
    service = MagicMock()
    service.execute_statement.return_value = (False, 0)
    engine = ExecutionEngine(provider, SqlAnalyzer(dialect="postgresql"), MagicMock(), service)
    engine._classify_execution_statements = MagicMock(return_value=[])
    engine.transaction_policy = MagicMock()
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(transactional=True)
    return engine


def test_callback_uses_autocommit_when_required(engine, callback):
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(
        transactional=False,
        autocommit_required=True,
        reason="statement requires autocommit",
    )

    engine.execute_callback(callback)

    engine.sql_execution_service.execute_statement.assert_called_once_with(SQL, autocommit=True)
    engine.provider.begin_transaction.assert_not_called()
    engine.provider.commit_transaction.assert_not_called()


def test_callback_uses_explicit_transaction_when_policy_is_transactional(engine, callback):
    engine.execute_callback(callback)

    engine.sql_execution_service.execute_statement.assert_called_once_with(SQL, autocommit=False)
    engine.provider.begin_transaction.assert_called_once_with()
    engine.provider.commit_transaction.assert_called_once_with()
    engine.provider.rollback_transaction.assert_not_called()


def test_callback_skips_explicit_transaction_for_non_transactional_provider(engine, callback):
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(
        transactional=False, reason="Provider does not support explicit transactions"
    )

    engine.execute_callback(callback)

    engine.sql_execution_service.execute_statement.assert_called_once_with(SQL, autocommit=False)
    engine.provider.begin_transaction.assert_not_called()
    engine.provider.commit_transaction.assert_not_called()
    engine.provider.rollback_transaction.assert_not_called()


def test_callback_rejects_mixed_transaction_modes_before_execution(engine, callback):
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(
        transactional=False,
        autocommit_required=True,
        unsupported_mixed_mode=True,
        reason="statement requires autocommit",
    )

    with pytest.raises(CallbackExecutionError, match="statement requires autocommit"):
        engine.execute_callback(callback)

    engine.sql_execution_service.execute_statement.assert_not_called()
    engine.provider.begin_transaction.assert_not_called()
    engine.provider.commit_transaction.assert_not_called()
    engine.provider.rollback_transaction.assert_not_called()


@pytest.mark.parametrize("transactional_provider", [True, False])
def test_callback_autocommit_provider_fallback(engine, callback, transactional_provider):
    engine.sql_execution_service = None
    if not transactional_provider:
        engine.provider = MagicMock()
    engine.provider.execute_statement.return_value = 0
    engine.provider.execute_autocommit_statement.return_value = 0
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(
        transactional=False, autocommit_required=True
    )

    engine.execute_callback(callback)

    if transactional_provider:
        engine.provider.execute_autocommit_statement.assert_called_once_with(SQL)
        engine.provider.execute_statement.assert_not_called()
    else:
        engine.provider.execute_statement.assert_called_once_with(SQL)
        engine.provider.execute_autocommit_statement.assert_not_called()
    engine.provider.begin_transaction.assert_not_called()
    engine.provider.commit_transaction.assert_not_called()


def test_callback_begin_failure_continues_without_commit(engine, callback):
    engine.provider.begin_transaction.side_effect = RuntimeError("begin failed")

    engine.execute_callback(callback)

    engine.sql_execution_service.execute_statement.assert_called_once_with(SQL, autocommit=False)
    engine.provider.commit_transaction.assert_not_called()
    engine.provider.rollback_transaction.assert_not_called()


@pytest.mark.parametrize("transactional", [True, False])
def test_callback_preserves_original_failure_and_rolls_back_only_started_transaction(
    engine, callback, transactional
):
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(
        transactional=transactional, autocommit_required=not transactional
    )
    failure = RuntimeError("statement failed")
    engine.sql_execution_service.execute_statement.side_effect = failure
    engine.provider.rollback_transaction.side_effect = RuntimeError("rollback failed")

    with pytest.raises(RuntimeError) as exc:
        engine.execute_callback(callback)

    assert exc.value is failure
    assert engine.provider.rollback_transaction.call_count == int(transactional)
    engine.provider.commit_transaction.assert_not_called()
