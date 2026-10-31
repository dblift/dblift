"""A rolled-back transaction may undo an uncommitted ``SET search_path``.

PostgreSQL documents a plain ``SET`` as transactional: when the statement ran
inside a transaction that is later rolled back, the session is back on its
previous ``search_path``. ``PostgreSqlProvider`` remembers the schema it last
applied so it does not re-issue the statement on every migration statement;
that memory is only valid while the ``SET`` is still in effect.

On a caller-owned SQLAlchemy connection (``DBLiftClient.from_sqlalchemy(
connection=...)``) nothing commits the ``SET``: the provider never commits
on an external connection, and SQLAlchemy opens a transaction implicitly
on the first statement. The provider's own rollbacks then undo the ``SET``
while the cache still says it is applied.
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
