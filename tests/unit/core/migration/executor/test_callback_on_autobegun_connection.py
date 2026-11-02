"""Callbacks and migrations on a connection whose transaction the caller already began.

SQLAlchemy refuses ``begin()`` once a connection has autobegun. A callback then
runs inside the caller's transaction with no begin/commit of its own, and must
never roll that transaction back. Its writes are committed when the next
migration prepares its own unit, so that rollback cannot discard them.
"""

from typing import List
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executor.transaction_policy import TransactionPolicyDecision
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.db.provider_interfaces import TransactionalProvider
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit

SQL = "CREATE TABLE cb (id integer)"


class _AutobegunProvider(TransactionalProvider):
    """Starts inside a transaction: ``begin_transaction`` fails until it is ended."""

    connection = object()  # no ``getAutoCommit``, like a SQLAlchemy connection

    def __init__(self, external: bool = True) -> None:
        self.calls: List[str] = []
        self.in_tx = True
        self._external = external

    def is_caller_owned(self) -> bool:
        return self._external

    def note_caller_work(self) -> None:
        self.calls.append("note")

    def commit_caller_work(self) -> None:
        self.calls.append("commit-caller-work")
        self.in_tx = False

    def check_transaction_state(self) -> None:
        pass

    def begin_transaction(self) -> None:
        if self.in_tx:
            self.calls.append("begin-refused")
            raise RuntimeError("a transaction is already begun")
        self.in_tx = True
        self.calls.append("begin")

    def commit_transaction(self) -> None:
        self.in_tx = False
        self.calls.append("commit")

    def rollback_transaction(self) -> None:
        self.in_tx = False
        self.calls.append("rollback")

    def execute_statement(self, sql, schema=None, params=None) -> int:
        self.calls.append("execute")
        return 0


def _engine(provider: _AutobegunProvider) -> ExecutionEngine:
    engine = ExecutionEngine(provider, StatementReader(dialect="postgresql"), MagicMock())
    engine._classify_execution_statements = MagicMock(return_value=[])
    engine.transaction_policy = MagicMock()
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(transactional=True)
    return engine


def _run_callback(provider: _AutobegunProvider) -> None:
    callback = make_migration(
        script_name="beforeMigrate__cb.sql", content=SQL, sql_statements=[SQL]
    )
    _engine(provider).execute_callback(callback)


def test_callback_on_a_caller_owned_connection_runs_in_the_open_transaction():
    provider = _AutobegunProvider()

    _run_callback(provider)

    assert provider.calls == ["begin-refused", "note", "execute"]


def test_callback_on_an_owned_connection_still_continues_without_a_transaction():
    provider = _AutobegunProvider(external=False)

    _run_callback(provider)

    assert provider.calls == ["begin-refused", "execute"]


def test_next_migration_commits_the_callbacks_work_before_its_own_rollback():
    provider = _AutobegunProvider()
    migration = MagicMock()
    migration.script_name = "V1__t.sql"

    assert _engine(provider)._prepare_transaction(migration)

    assert provider.calls[:3] == ["commit-caller-work", "rollback", "begin"]


def test_next_migration_on_an_owned_connection_commits_nothing_extra():
    provider = _AutobegunProvider(external=False)
    migration = MagicMock()
    migration.script_name = "V1__t.sql"

    _engine(provider)._prepare_transaction(migration)

    assert "commit-caller-work" not in provider.calls
