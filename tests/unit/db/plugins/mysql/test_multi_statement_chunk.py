"""A chunk holding several statements runs as one query and reports every error."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest
from pymysql.constants import CLIENT
from sqlalchemy import create_engine, event

from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.provider import _DRAIN_KEY, MySqlProvider, _drain_result_sets
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider


class _FakeCursor:
    """Pymysql-shaped cursor: ``nextset`` walks a script of results or errors."""

    def __init__(self, script: List[Optional[Exception]]) -> None:
        self._script = list(script)
        self.calls = 0

    def nextset(self) -> Optional[bool]:
        self.calls += 1
        if not self._script:
            return None
        step = self._script.pop(0)
        if isinstance(step, Exception):
            raise step
        return True


def _drain(cursor: Any, armed: bool = True) -> None:
    conn = SimpleNamespace(info={_DRAIN_KEY: True} if armed else {})
    _drain_result_sets(conn, cursor, "", None, None, False)


@pytest.mark.parametrize("quirks", [MysqlQuirks(), MariadbQuirks()])
def test_engine_options_enable_multi_statements(quirks: Any) -> None:
    flag = quirks.engine_pool_options()["connect_args"]["client_flag"]
    assert flag & CLIENT.MULTI_STATEMENTS
    # SQLAlchemy's own client_flag is replaced by this one: without FOUND_ROWS an UPDATE
    # reports changed rows instead of matched rows.
    assert flag & CLIENT.FOUND_ROWS


def test_drain_consumes_every_result_set() -> None:
    cursor = _FakeCursor([None, None])
    _drain(cursor)
    # Two further results, then the call that reports there are no more.
    assert cursor.calls == 3


def test_drain_on_a_single_statement_is_one_call() -> None:
    cursor = _FakeCursor([])
    _drain(cursor)
    assert cursor.calls == 1


def test_drain_surfaces_a_later_statement_error() -> None:
    cursor = _FakeCursor([None, RuntimeError("1146 table doesn't exist")])
    with pytest.raises(RuntimeError, match="1146"):
        _drain(cursor)


def test_drain_leaves_a_query_alone() -> None:
    cursor = _FakeCursor([None])
    _drain(cursor, armed=False)
    assert cursor.calls == 0


def test_create_connection_registers_the_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite://")
    conn = engine.connect()
    monkeypatch.setattr(SqlAlchemyProvider, "create_connection", lambda self: conn)
    provider = object.__new__(MySqlProvider)
    assert provider.create_connection() is conn
    assert event.contains(conn, "after_cursor_execute", _drain_result_sets)


def test_execute_statement_arms_the_drain_only_while_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = SimpleNamespace(info={})
    seen = []

    def fake_execute(self: Any, sql: str, schema: Any = None, params: Any = None) -> int:
        seen.append(conn.info.get(_DRAIN_KEY))
        return 0

    monkeypatch.setattr(SqlAlchemyProvider, "execute_statement", fake_execute)
    provider = object.__new__(MySqlProvider)
    provider._lock = threading.RLock()
    provider._ensure_connection = lambda: conn  # type: ignore[method-assign]
    provider.execute_statement("SELECT 1")
    assert seen == [True]
    assert _DRAIN_KEY not in conn.info


def test_create_connection_does_not_arm_the_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = create_engine("sqlite://").connect()
    monkeypatch.setattr(SqlAlchemyProvider, "create_connection", lambda self: conn)
    object.__new__(MySqlProvider).create_connection()
    assert _DRAIN_KEY not in conn.info


def test_execute_statement_disarms_the_drain_when_the_statement_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = SimpleNamespace(info={})

    def failing(self: Any, sql: str, schema: Any = None, params: Any = None) -> int:
        raise RuntimeError("1146")

    monkeypatch.setattr(SqlAlchemyProvider, "execute_statement", failing)
    provider = object.__new__(MySqlProvider)
    provider._lock = threading.RLock()
    provider._ensure_connection = lambda: conn  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        provider.execute_statement("SELECT 1")
    assert _DRAIN_KEY not in conn.info
