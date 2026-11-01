"""dblift commits the caller's transaction only when dblift itself wrote in it."""

import pytest

from dblift.db.plugins.postgresql.provider import PostgreSqlProvider

pytestmark = pytest.mark.unit


class _Tx:
    pass


class _Connection:
    closed = False

    def __init__(self) -> None:
        self.tx = _Tx()
        self.log = []

    def in_transaction(self) -> bool:
        return self.tx is not None

    def get_transaction(self):
        return self.tx

    def commit(self) -> None:
        self.tx = None
        self.log.append("commit")

    def rollback(self) -> None:
        self.tx = None
        self.log.append("rollback")


def _provider(connection: _Connection) -> PostgreSqlProvider:
    class _Bound(PostgreSqlProvider):
        def __init__(self) -> None:
            self._tx = None
            self._connection = connection
            self._external_connection = True

    return _Bound()


def test_commits_the_transaction_dblift_wrote_in():
    connection = _Connection()
    provider = _provider(connection)
    provider.note_caller_work()

    provider.commit_caller_work()

    assert connection.log == ["commit"]


def test_commits_nothing_when_dblift_wrote_nothing():
    connection = _Connection()

    _provider(connection).commit_caller_work()

    assert connection.log == []


def test_a_transaction_the_caller_started_afterwards_is_left_alone():
    connection = _Connection()
    provider = _provider(connection)
    provider.note_caller_work()
    connection.tx = _Tx()  # the caller committed, then began new work

    provider.commit_caller_work()

    assert connection.log == []


def test_the_mark_is_spent_by_one_commit():
    connection = _Connection()
    provider = _provider(connection)
    provider.note_caller_work()
    provider.commit_caller_work()
    connection.tx = _Tx()

    provider.commit_caller_work()

    assert connection.log == ["commit"]


def test_a_rollback_clears_the_mark():
    connection = _Connection()
    provider = _provider(connection)
    provider.note_caller_work()
    provider.rollback_transaction()
    connection.tx = _Tx()

    provider.commit_caller_work()

    assert connection.log == ["rollback"]
