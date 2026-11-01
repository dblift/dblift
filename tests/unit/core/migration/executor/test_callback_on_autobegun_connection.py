"""A callback on a connection that already autobegan still runs in a committed unit.

SQLAlchemy refuses ``begin()`` once the connection has autobegun (a caller-owned
connection after any earlier statement). The callback used to carry on in that
transaction and the next migration's rollback discarded its writes.
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
    """Starts inside a transaction: ``begin_transaction`` fails until it is rolled back."""

    connection = object()  # no ``getAutoCommit``, like a SQLAlchemy connection

    def __init__(self, external: bool = True) -> None:
        self.calls: List[str] = []
        self.in_tx = True
        self._external = external

    def is_caller_owned(self) -> bool:
        return self._external

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


def _run_callback(provider: _AutobegunProvider) -> None:
    engine = ExecutionEngine(provider, StatementReader(dialect="postgresql"), MagicMock())
    engine._classify_execution_statements = MagicMock(return_value=[])
    engine.transaction_policy = MagicMock()
    engine.transaction_policy.decide.return_value = TransactionPolicyDecision(transactional=True)
    callback = make_migration(
        script_name="beforeMigrate__cb.sql", content=SQL, sql_statements=[SQL]
    )

    engine.execute_callback(callback)


def test_callback_on_a_caller_owned_connection_resets_the_boundary_and_commits_its_unit():
    provider = _AutobegunProvider()

    _run_callback(provider)

    assert provider.calls == ["begin-refused", "rollback", "begin", "execute", "commit"]


def test_callback_on_an_owned_connection_still_continues_without_a_transaction():
    provider = _AutobegunProvider(external=False)

    _run_callback(provider)

    assert provider.calls == ["begin-refused", "execute"]
