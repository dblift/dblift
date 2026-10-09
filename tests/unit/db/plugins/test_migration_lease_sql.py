"""SQL each table-locked engine emits for the migration lock lease.

Every statement runs on a dedicated lock connection (``engine.connect()``) so
the lease commits on its own and a heartbeat can run beside the migration.
Rules pinned for every engine:

* the lease timestamp is written and compared with the database server's own
  clock, in UTC — never with a timestamp computed by the client;
* the lease carries an owner token, and heartbeat and release only touch the
  row that carries the caller's token;
* reclaim is a conditional statement on the server-side expiry;
* an existing lock table gains the owner column.

Snowflake is covered here only (no live account in CI).
"""

from __future__ import annotations

import datetime
import importlib.util
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from dblift.core.logger import NullLog

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("owners", [("other", None), (None, None)])
def test_seeded_lock_refuses_duplicate_rows(owners) -> None:
    """A free duplicate must not let a second holder claim the same lock."""
    from dblift.db.plugins.sql_lease_store import (
        Sqlite3LeaseSession,
        SqlLeaseDialect,
        SqlLeaseStore,
    )

    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE locks (lock_name TEXT, locked_at TEXT, owner_token TEXT)")
        connection.executemany(
            "INSERT INTO locks VALUES ('migration', datetime('now'), ?)",
            [(owner,) for owner in owners],
        )
        connection.commit()
        store = SqlLeaseStore(
            SqlLeaseDialect(
                table="locks",
                lock_name="migration",
                now_utc="datetime('now')",
                seconds_before=lambda clock, seconds: f"datetime({clock}, '-{seconds} seconds')",
                is_busy=lambda error: False,
                seeded_row=True,
            ),
            Sqlite3LeaseSession(connection, owns_connection=False),
        )

        assert store.try_acquire("new-owner") is False
        assert [row[0] for row in connection.execute("SELECT owner_token FROM locks")] == list(
            owners
        )
    finally:
        connection.close()


@dataclass
class _Result:
    rowcount: int = 1
    rows: list = field(default_factory=list)

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.rows[0][0] if self.rows else None

    def mappings(self):
        return SimpleNamespace(all=lambda: list(self.rows), first=lambda: self.fetchone())


class _LeaseConnection:
    """Records every statement; ``handler`` decides each statement's outcome."""

    def __init__(self, log: list, handler: Callable[[str, Any], _Result]) -> None:
        self.log = log
        self.handler = handler
        self.closed = False
        self.dialect = SimpleNamespace(paramstyle="qmark", name="fake")
        self._mutex = threading.Lock()

    def exec_driver_sql(self, sql, params=None, *args, **kwargs):
        with self._mutex:
            self.log.append((str(sql), params))
            return self.handler(str(sql), params)

    def execute(self, statement, params=None, *args, **kwargs):
        return self.exec_driver_sql(str(statement), params)

    def execution_options(self, **_kwargs):
        return self

    def begin(self):
        return SimpleNamespace(commit=lambda: None, rollback=lambda: None)

    def commit(self):
        pass

    def rollback(self):
        pass

    def in_transaction(self):
        return False

    def invalidate(self, *_args):
        pass

    def close(self):
        self.closed = True


class _Engine:
    def __init__(self, log: list, handler) -> None:
        self.log = log
        self.handler = handler
        self.dialect = SimpleNamespace(paramstyle="qmark", name="fake")
        self.url = SimpleNamespace(database="app", drivername="fake")

    def connect(self):
        return _LeaseConnection(self.log, self.handler)

    def raw_connection(self):  # pragma: no cover - not expected
        raise AssertionError("lease must use engine.connect()")


def _duplicate() -> IntegrityError:
    return IntegrityError(
        "INSERT",
        {},
        Exception("duplicate key value violates unique constraint (SQLSTATE 23505) ORA-00001"),
    )


@dataclass
class _Engine_:
    name: str
    build: Callable[[], Any]
    clock: tuple
    seeded_row: bool = False
    schema: str = "APP"


def _stub(cls, log: list, handler, **attrs):
    """A provider instance wired to a recording engine and main connection."""

    class _Stub(cls):  # type: ignore[misc, valid-type]
        @property
        def engine(self):
            return self._fake_engine

    provider = _Stub.__new__(_Stub)
    provider.__dict__.update(
        {
            "log": NullLog(),
            "config": SimpleNamespace(database=SimpleNamespace(type="x", schema="APP")),
            "_fake_engine": _Engine(log, handler),
            "_connection": None,
            "_tx": None,
            "_lock": threading.RLock(),
            "_conn_mgr": MagicMock(),
        }
    )
    provider.__dict__.update(attrs)

    def _main_statement(sql, schema=None, params=None):
        log.append((str(sql), params))
        return handler(str(sql), params).rowcount

    def _main_query(sql, params=None):
        log.append((str(sql), params))
        return handler(str(sql), params).rows

    provider.execute_statement = _main_statement
    provider.execute_query = _main_query
    provider.table_exists = lambda *_a, **_k: True
    provider.create_schema_if_not_exists = lambda *_a, **_k: None
    return provider


def _cockroach(log, handler):
    from dblift.db.plugins.cockroachdb.provider import CockroachdbProvider

    return _stub(CockroachdbProvider, log, handler)


def _duckdb(log, handler):
    from dblift.db.plugins.duckdb.provider import DuckDBProvider

    return _stub(DuckDBProvider, log, handler)


def _db2(log, handler):
    from dblift.db.plugins.db2.provider import Db2Provider

    return _stub(Db2Provider, log, handler)


def _oracle(log, handler):
    from dblift.db.plugins.oracle.provider import OracleProvider

    def oracle_handler(sql, params):
        if "DBMS_" in sql.upper():
            raise RuntimeError("PLS-00201: identifier 'DBMS_LOCK' must be declared")
        return handler(sql, params)

    provider = _stub(OracleProvider, log, oracle_handler, _lock_handles={})
    provider._guard_unquoted_existing_schema = lambda *_a, **_k: None
    return provider


def _snowflake(log, handler):
    from dblift.db.plugins.snowflake.provider import SnowflakeProvider

    return _stub(
        SnowflakeProvider,
        log,
        handler,
        _migration_lock_connection=None,
        _migration_lock_transaction=None,
        _migration_lock_prior_timeout=None,
    )


_UTC_PG_STYLE = (
    "now() at time zone 'utc'",
    "timezone('utc', now())",
    "current_timestamp at time zone 'utc'",
    "timezone('utc', current_timestamp)",
)

ENGINES = [
    _Engine_("cockroachdb", _cockroach, _UTC_PG_STYLE),
    _Engine_("duckdb", _duckdb, _UTC_PG_STYLE),
    _Engine_("db2", _db2, ("current timestamp - current timezone",)),
    _Engine_("oracle", _oracle, ("sys_extract_utc(systimestamp)",)),
    _Engine_("snowflake", _snowflake, ("sysdate()",), seeded_row=True),
]
IDS = [engine.name for engine in ENGINES]

_TOKEN = re.compile(r"^[0-9a-f-]{16,}$")


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


def _values(params) -> list:
    if params is None:
        return []
    if isinstance(params, dict):
        return list(params.values())
    if isinstance(params, (list, tuple)):
        flat = []
        for value in params:
            flat.extend(_values(value) if isinstance(value, (list, tuple, dict)) else [value])
        return flat
    return [params]


def _tokens(params) -> list:
    return [value for value in _values(params) if isinstance(value, str) and _TOKEN.match(value)]


def _verb(sql: str) -> str:
    return _norm(sql).split(" ", 1)[0]


def _uses_clock(engine: _Engine_, sql: str) -> bool:
    text = _norm(sql)
    return any(fragment in text for fragment in engine.clock)


def _is_lock_table(sql: str) -> bool:
    return "dblift_migration_lock" in _norm(sql)


def _lock_writes(log: list) -> list:
    return [
        (sql, params)
        for sql, params in log
        if _is_lock_table(sql) and _verb(sql) in ("insert", "update", "delete")
    ]


def _assert_where_owned(sql: str) -> None:
    """The statement's WHERE clause requires the caller's owner token."""
    where = _norm(sql).split(" where ", 1)[-1]
    assert " where " in f" {_norm(sql)} ", sql
    assert re.search(r"owner_token\s*=\s*\?", where), sql
    assert " or " not in f" {where} ", sql


def _no_client_timestamps(log: list) -> None:
    for sql, params in log:
        for value in _values(params):
            assert not isinstance(value, (datetime.datetime, datetime.date)), (sql, params)


def _patch_lease(monkeypatch, name: str, value: float) -> None:
    """Shorten a lease timing (no-op on a dblift without the shared lease)."""
    if importlib.util.find_spec("dblift.db.plugins.lease_lock") is not None:
        monkeypatch.setattr(f"dblift.db.plugins.lease_lock.{name}", value)


@pytest.fixture(autouse=True)
def _fast_lease(monkeypatch):
    _patch_lease(monkeypatch, "POLL_INTERVAL_SECONDS", 0.01)


def _free_handler(engine: _Engine_):
    def handler(sql, params):
        return _Result(rowcount=1)

    return handler


def _acquire(engine: _Engine_, handler):
    log: list = []
    provider = engine.build(log, handler)
    provider.create_migration_lock_table_if_not_exists = lambda *_a, **_k: None
    acquired = provider.acquire_migration_lock(engine.schema, wait_timeout_seconds=2)
    return provider, log, acquired


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_acquire_writes_owner_token_with_the_server_utc_clock(engine):
    provider, log, acquired = _acquire(engine, _free_handler(engine))
    try:
        assert acquired is True
        writes = _lock_writes(log)
        assert writes, log
        sql, params = writes[0]
        assert _verb(sql) == ("update" if engine.seeded_row else "insert"), sql
        assert "owner_token" in _norm(sql), sql
        assert _uses_clock(engine, sql), sql
        assert len(_tokens(params)) == 1, (sql, params)
        _no_client_timestamps(log)
    finally:
        provider.release_migration_lock(engine.schema)


def _contended_then_expired(engine: _Engine_):
    """First attempt finds the lease held; reclaim removes an expired one."""
    state = {"attempts": 0}

    def handler(sql, params):
        verb = _verb(sql)
        if not _is_lock_table(sql):
            return _Result()
        text = _norm(sql)
        if engine.seeded_row and verb == "update" and _tokens(params) and "is null" in text:
            state["attempts"] += 1
            return _Result(rowcount=0 if state["attempts"] == 1 else 1)
        if not engine.seeded_row and verb == "insert":
            state["attempts"] += 1
            if state["attempts"] == 1:
                raise _duplicate()
        return _Result(rowcount=1)

    return handler


def _reclaims(engine: _Engine_, log: list) -> list:
    found = []
    for sql, params in _lock_writes(log):
        text = _norm(sql)
        if engine.seeded_row:
            if _verb(sql) == "update" and not _tokens(params) and "owner_token" in text:
                found.append(sql)
        elif _verb(sql) == "delete" and not _tokens(params):
            found.append(sql)
    return found


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_reclaim_is_conditional_on_server_side_expiry(engine):
    provider, log, acquired = _acquire(engine, _contended_then_expired(engine))
    try:
        assert acquired is True
        reclaims = _reclaims(engine, log)
        assert reclaims, log
        for sql in reclaims:
            assert _uses_clock(engine, sql), sql
            assert "owner_token" in _norm(sql), sql
        _no_client_timestamps(log)
    finally:
        provider.release_migration_lock(engine.schema)


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_release_only_touches_the_callers_own_lease(engine):
    provider, log, acquired = _acquire(engine, _free_handler(engine))
    assert acquired is True
    token = _tokens(_lock_writes(log)[0][1])[0]
    before = len(log)

    provider.release_migration_lock(engine.schema)

    releases = [
        (sql, params) for sql, params in _lock_writes(log[before:]) if token in _tokens(params)
    ]
    assert releases, log[before:]
    sql, _ = releases[-1]
    assert _verb(sql) == ("update" if engine.seeded_row else "delete"), sql
    _assert_where_owned(sql)
    unowned = [
        sql
        for sql, params in _lock_writes(log[before:])
        if _verb(sql) in ("delete", "update") and token not in _tokens(params)
    ]
    assert not unowned, unowned


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_heartbeat_refreshes_only_the_callers_lease_with_the_server_clock(engine, monkeypatch):
    _patch_lease(monkeypatch, "LEASE_EXPIRY_SECONDS", 0.3)
    provider, log, acquired = _acquire(engine, _free_handler(engine))
    try:
        assert acquired is True
        token = _tokens(_lock_writes(log)[0][1])[0]
        before = len(log)
        time.sleep(0.45)
        beats = [
            sql
            for sql, params in _lock_writes(log[before:])
            if _verb(sql) == "update" and token in _tokens(params)
        ]
        assert beats, log[before:]
        for sql in beats:
            assert _uses_clock(engine, sql), sql
            _assert_where_owned(sql)
    finally:
        provider.release_migration_lock(engine.schema)


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_existing_lock_table_gains_the_owner_column(engine):
    """A table created by an earlier dblift has no owner column; creating the
    lock table must add it (catalog queries report the legacy columns only)."""
    legacy_columns = [
        {"column_name": "lock_name", "COLUMN_NAME": "LOCK_NAME", "name": "lock_name"},
        {"column_name": "locked_at", "COLUMN_NAME": "ACQUIRED_AT", "name": "locked_at"},
    ]

    def handler(sql, params):
        if _verb(sql) in ("select", "show", "pragma", "with", "describe"):
            return _Result(rows=legacy_columns)
        return _Result()

    log: list = []
    provider = engine.build(log, handler)
    provider.create_migration_lock_table_if_not_exists(engine.schema)

    adds = [sql for sql, _ in log if "add" in _norm(sql) and "owner_token" in _norm(sql)]
    assert adds, log
    assert all(_verb(sql) == "alter" for sql in adds), adds


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_close_releases_a_held_lease(engine):
    provider, log, acquired = _acquire(engine, _free_handler(engine))
    assert acquired is True
    token = _tokens(_lock_writes(log)[0][1])[0]
    before = len(log)

    provider.close()

    assert any(token in _tokens(params) for _, params in _lock_writes(log[before:])), log[before:]


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_lease_lost_is_reported_to_the_caller(engine, monkeypatch):
    _patch_lease(monkeypatch, "LEASE_EXPIRY_SECONDS", 0.3)
    state = {"taken_over": False}

    def handler(sql, params):
        if state["taken_over"] and _verb(sql) == "update" and _tokens(params):
            return _Result(rowcount=0)  # another process now owns the row
        return _Result(rowcount=1)

    provider, log, acquired = _acquire(engine, handler)
    try:
        assert acquired is True
        assert provider.migration_lock_lost() is False
        state["taken_over"] = True
        time.sleep(0.45)
        assert provider.migration_lock_lost() is True
    finally:
        provider.release_migration_lock(engine.schema)


_BUSY_ERRORS = {
    "cockroachdb": "restart transaction: TransactionRetryWithProtoRefreshError (SQLSTATE 40001)",
    "duckdb": "TransactionContext Error: Conflict on tuple deletion!",
    "db2": "SQL0911N The current transaction has been rolled back because of a deadlock "
    'or timeout. Reason code "68". SQLSTATE=40001',
    "oracle": "ORA-00054: resource busy and acquire with NOWAIT specified or timeout expired",
    "snowflake": "000625 (57014): Statement was aborted because the lock timeout was exceeded",
}


@pytest.mark.parametrize("engine", ENGINES, ids=IDS)
def test_write_conflict_on_the_lock_table_is_contention_not_an_error(engine):
    """A lock-table write that collides with another live writer (conflict,
    serialization retry, lock wait timeout) means the lock is busy: keep
    waiting rather than failing the migration."""
    state = {"failed": False}

    def handler(sql, params):
        if _is_lock_table(sql) and _tokens(params) and not state["failed"]:
            if _verb(sql) in ("insert", "update"):
                state["failed"] = True
                raise RuntimeError(_BUSY_ERRORS[engine.name])
        return _Result(rowcount=1)

    provider, log, acquired = _acquire(engine, handler)
    try:
        assert state["failed"] is True
        assert acquired is True
    finally:
        provider.release_migration_lock(engine.schema)
