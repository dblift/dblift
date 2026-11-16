"""The provider session that autocommits for a whole script, on a real SQLite connection."""

import threading
from typing import List

import pytest
from sqlalchemy import create_engine, text

from dblift.db.provider_interfaces import TransactionalProvider
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider


class _Provider(SqlAlchemyProvider):
    """A provider over one SQLite connection that records the hook and cleanup calls."""

    def __init__(self, open_transaction: bool = False) -> None:
        self._engine = create_engine("sqlite://")
        self._connection = self._engine.connect()
        self._tx = None
        self._lock = threading.RLock()
        self.calls: List[str] = []
        self.open_transaction = open_transaction
        self.level_seen_by_check = None

    def _script_transaction_open(self, conn) -> bool:
        self.calls.append("open?")
        self.level_seen_by_check = conn.get_execution_options().get("isolation_level")
        return self.open_transaction

    def _roll_back_script_transaction(self, conn) -> None:
        self.calls.append("roll back")

    def _end_open_transaction(self, conn) -> None:
        self.calls.append("end open")
        super()._end_open_transaction(conn)

    @staticmethod
    def _restore_isolation_level(conn, previous) -> None:
        _Provider.restored = previous
        SqlAlchemyProvider._restore_isolation_level(conn, previous)


_Provider.__abstractmethods__ = frozenset()


@pytest.fixture
def provider():
    p = _Provider()
    yield p
    p._connection.close()
    p._engine.dispose()


def test_defaults_raise_on_the_interface_and_the_base_hook():
    with pytest.raises(NotImplementedError):
        TransactionalProvider.begin_script_session(object.__new__(_Provider))
    with pytest.raises(NotImplementedError):
        TransactionalProvider.end_script_session(object.__new__(_Provider))
    with pytest.raises(NotImplementedError):
        SqlAlchemyProvider._script_transaction_open(object.__new__(_Provider), None)


def test_begin_ends_open_transaction_asks_once_then_autocommits(provider):
    provider.begin_script_session()

    assert provider.calls == ["end open", "open?"]
    assert provider.level_seen_by_check is None
    conn = provider._connection
    assert conn.get_execution_options()["isolation_level"] == "AUTOCOMMIT"
    assert provider.has_explicit_transaction()


def test_end_follows_the_close_order_and_returns_what_the_check_said(provider):
    provider.open_transaction = True
    captured = provider._connection.get_execution_options()
    provider.begin_script_session()
    provider.calls.clear()

    assert provider.end_script_session() is True

    assert provider.calls == ["open?", "roll back", "end open"]
    assert _Provider.restored is captured
    assert not provider.has_explicit_transaction()
    assert "isolation_level" not in provider._connection.get_execution_options()


def test_end_returns_false_when_nothing_was_left_open(provider):
    provider.begin_script_session()

    assert provider.end_script_session() is False
    assert not provider.has_explicit_transaction()


def test_the_script_session_forgets_the_captured_options(provider):
    provider.begin_script_session()
    provider.end_script_session()
    provider.calls.clear()

    assert provider.end_script_session() is False
    assert provider.calls == []


def test_end_on_a_closed_connection_touches_nothing_and_clears_state(provider):
    provider.begin_script_session()
    provider._connection.close()
    provider.calls.clear()

    assert provider.end_script_session() is False

    assert provider.calls == []
    assert not provider.has_explicit_transaction()


def test_statements_run_inside_the_session_without_a_per_statement_commit(provider):
    provider.begin_script_session()
    conn = provider._connection
    conn.execute(text("CREATE TABLE t (a INTEGER)"))
    assert provider._tx is not None
    provider.end_script_session()
    assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 0
