"""The provider session that autocommits for a whole script, on a real SQLite connection."""

import threading
from typing import List

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from dblift.core.exceptions import ExecutionError
from dblift.db.provider_interfaces import TransactionalProvider
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider


class _Provider(SqlAlchemyProvider):
    """A provider over one SQLite connection that records the hook and cleanup calls."""

    def __init__(self, open_transaction: bool = False) -> None:
        self._engine = create_engine("sqlite://")
        self._connection = self._engine.connect()
        self._tx = None
        self._script_session_options = None
        self._lock = threading.RLock()
        self.calls: List[str] = []
        self.open_transaction = open_transaction
        self.level_seen_by_check = None
        self.fail_check = False
        self.check_error: Exception = RuntimeError("check failed")
        self.probe_statement = None
        self.fail_roll_back = False

    def _script_transaction_open(self, conn) -> bool:
        self.calls.append("open?")
        if self.probe_statement:
            self._exec_unbound(conn, self.probe_statement)
        if self.fail_check:
            raise self.check_error
        self.level_seen_by_check = conn.get_execution_options().get("isolation_level")
        return self.open_transaction

    def _roll_back_script_transaction(self, conn) -> None:
        self.calls.append("roll back")
        if self.fail_roll_back:
            raise RuntimeError("roll back failed")

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


def _assert_back_to_normal(provider):
    assert not provider.has_explicit_transaction()
    assert provider._script_session_options is None
    assert "isolation_level" not in provider._connection.get_execution_options()


@pytest.mark.parametrize("hook", ["fail_check", "fail_roll_back"])
def test_end_cleans_up_then_propagates_when_a_hook_raises(provider, hook):
    provider.begin_script_session()
    setattr(provider, hook, True)

    with pytest.raises(RuntimeError):
        provider.end_script_session()

    _assert_back_to_normal(provider)


def test_begin_that_fails_to_open_its_transaction_leaves_the_connection_as_it_was(
    provider, monkeypatch
):
    def refuse():
        raise RuntimeError("begin failed")

    monkeypatch.setattr(provider._connection, "begin", refuse)

    with pytest.raises(RuntimeError):
        provider.begin_script_session()

    _assert_back_to_normal(provider)


def test_a_failing_restore_at_the_end_leaves_the_provider_forgotten_and_raises(
    provider, monkeypatch
):
    provider.begin_script_session()

    def refuse(conn, previous):
        raise RuntimeError("restore failed")

    monkeypatch.setattr(_Provider, "_restore_isolation_level", staticmethod(refuse))

    with pytest.raises(RuntimeError, match="restore failed"):
        provider.end_script_session()

    assert provider._tx is None
    assert provider._script_session_options is None
    assert not provider.has_explicit_transaction()


def test_begin_whose_isolation_switch_raises_leaves_the_connection_as_it_was(provider, monkeypatch):
    conn = provider._connection
    before = conn.get_execution_options()
    real = conn.execution_options

    def fail_on_autocommit(**options):
        real(**options)  # SQLAlchemy records the option before the dialect applies it
        if options.get("isolation_level") == "AUTOCOMMIT":
            raise SQLAlchemyError("switch failed")

    monkeypatch.setattr(conn, "execution_options", fail_on_autocommit)

    with pytest.raises(ExecutionError, match="could not be prepared"):
        provider.begin_script_session()

    monkeypatch.undo()
    assert provider._tx is None
    assert conn.get_execution_options() == before
    _assert_back_to_normal(provider)


def test_begin_whose_check_raises_changes_nothing(provider):
    provider.fail_check = True

    with pytest.raises(RuntimeError):
        provider.begin_script_session()

    _assert_back_to_normal(provider)


def test_end_without_a_session_leaves_an_ordinary_transaction_alone(provider):
    provider.begin_transaction()
    provider._connection.execute(text("CREATE TABLE t (a INTEGER)"))

    assert provider.end_script_session() is False

    assert provider.has_explicit_transaction()
    assert provider._connection.in_transaction()
    provider.rollback_transaction()


_SCRIPT = ("BEGIN", "INSERT INTO t VALUES (1)", "ROLLBACK")


def _run_script_then_count(provider) -> int:
    conn = provider._connection
    conn.execute(text("CREATE TABLE t (a INTEGER)"))
    for statement in _SCRIPT:
        try:
            provider.execute_statement(statement)
        except OperationalError:  # the bare connection has no transaction left to end
            pass
    return conn.execute(text("SELECT count(*) FROM t")).scalar()


def test_the_script_own_rollback_is_real_inside_a_session(provider):
    provider.begin_script_session()
    count = _run_script_then_count(provider)
    provider.end_script_session()

    assert count == 0


def test_control_a_bare_autocommit_connection_commits_after_each_statement(provider):
    provider._connection.execution_options(isolation_level="AUTOCOMMIT")

    assert provider._tx is None
    assert _run_script_then_count(provider) == 1


def test_a_database_error_at_begin_becomes_an_execution_error(provider):
    original = SQLAlchemyError("boom")
    provider.fail_check = True
    provider.check_error = original

    with pytest.raises(
        ExecutionError, match="the connection could not be prepared: boom"
    ) as raised:
        provider.begin_script_session()

    assert raised.value.__cause__ is original
    _assert_back_to_normal(provider)


def test_a_failed_begin_of_the_transaction_becomes_an_execution_error(provider, monkeypatch):
    def refuse():
        raise SQLAlchemyError("begin failed")

    monkeypatch.setattr(provider._connection, "begin", refuse)

    with pytest.raises(ExecutionError, match="could not be prepared: begin failed"):
        provider.begin_script_session()

    _assert_back_to_normal(provider)


def test_an_execution_error_from_the_hook_propagates_unchanged(provider):
    original = ExecutionError("driver cannot tell")
    provider.fail_check = True
    provider.check_error = original

    with pytest.raises(ExecutionError) as raised:
        provider.begin_script_session()

    assert raised.value is original
    _assert_back_to_normal(provider)


def test_begin_succeeds_when_the_check_autobegan_a_transaction(provider):
    provider.probe_statement = "SELECT 1"

    provider.begin_script_session()

    assert provider._connection.get_execution_options()["isolation_level"] == "AUTOCOMMIT"
    assert provider.has_explicit_transaction()
