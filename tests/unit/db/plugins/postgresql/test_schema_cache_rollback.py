"""A rollback that had a transaction open undoes the ``SET search_path`` the provider cached.

PostgreSQL rolls back a plain ``SET``; on a caller-owned connection nothing
commits it, so the schema cache must be cleared by every such rollback.
"""

from unittest.mock import MagicMock

from dblift.db.plugins.postgresql.provider import PostgreSqlProvider


class _FakeConnection:
    closed = False

    def __init__(self, open_transaction: bool) -> None:
        self._open = open_transaction
        self.rollbacks = 0

    def in_transaction(self) -> bool:
        return self._open

    def rollback(self) -> None:
        self.rollbacks += 1
        self._open = False


class _Provider(PostgreSqlProvider):
    def __init__(self, connection: _FakeConnection, tx=None) -> None:
        self._connection = connection
        self._tx = tx
        self._schema_applied_for = "app"


def test_rollback_of_open_connection_transaction_forgets_applied_schema():
    """External-connection shape: no provider ``_tx``, but the connection's
    implicit transaction holds the uncommitted ``SET``."""
    provider = _Provider(_FakeConnection(open_transaction=True))

    provider.rollback_transaction()

    assert provider._schema_applied_for is None


def test_rollback_with_nothing_open_keeps_applied_schema():
    """The routine defensive rollback with nothing open undoes nothing, so the
    schema statement must not be issued a second time."""
    provider = _Provider(_FakeConnection(open_transaction=False))

    provider.rollback_transaction()

    assert provider._schema_applied_for == "app"


def test_rollback_of_explicit_transaction_forgets_applied_schema():
    tx = MagicMock()
    provider = _Provider(_FakeConnection(open_transaction=True), tx=tx)

    provider.rollback_transaction()

    tx.rollback.assert_called_once()
    assert provider._schema_applied_for is None


def test_ending_open_transaction_before_autocommit_forgets_applied_schema():
    """``execute_autocommit_statement`` rolls the connection back to a clean
    boundary first; on an external connection that undoes the ``SET`` too."""
    connection = _FakeConnection(open_transaction=True)
    provider = _Provider(connection)

    provider._end_open_transaction(connection)

    assert connection.rollbacks == 1
    assert provider._schema_applied_for is None


def test_ending_transaction_with_nothing_open_keeps_applied_schema():
    connection = _FakeConnection(open_transaction=False)
    provider = _Provider(connection)

    provider._end_open_transaction(connection)

    assert provider._schema_applied_for == "app"
