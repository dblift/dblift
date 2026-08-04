"""Tests for SqlAlchemyProvider — SQLAlchemy-backed native data-access base.

SqlAlchemyProvider is abstract: it implements the core data-access and
transaction methods but leaves dialect-specific schema/history/locking
operations for per-DB subclasses.  The _Concrete stub below fills those
remaining abstract slots so we can instantiate and exercise the real
behaviour.
"""

import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from config.dblift_config import DbliftConfig
from db.sqlalchemy_provider import SqlAlchemyProvider, _SqlAlchemyQueryExecutor

# ---------------------------------------------------------------------------
# Minimal concrete subclass — stubs out the 15 dialect-specific abstracts
# that SqlAlchemyProvider intentionally leaves unimplemented.
# ---------------------------------------------------------------------------


class _Concrete(SqlAlchemyProvider):
    """Test-only concrete subclass filling per-DB abstract stubs."""

    def create_schema_if_not_exists(self, schema: str) -> None:  # noqa: D102
        pass

    def table_exists(self, schema: str, table_name: str) -> bool:  # noqa: D102
        return False

    def get_database_version(self) -> str:  # noqa: D102
        return "test"

    def set_current_schema(self, schema: str) -> None:  # noqa: D102
        pass

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:  # noqa: D102
        return f"{schema}.{object_name}"

    def clean_schema(self, schema: str) -> Any:  # noqa: D102
        pass

    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_snapshots"
    ) -> None:  # noqa: D102
        pass

    def create_migration_history_table_if_not_exists(
        self, schema: str, create_schema: bool = False, table_name: str = "dblift_schema_history"
    ) -> None:  # noqa: D102
        pass

    def create_history_table(self, schema: str, table_name: str) -> str:  # noqa: D102
        return ""

    def create_history_table_if_not_exists(
        self, schema: str, create_schema: bool = False, table_name: str = "dblift_schema_history"
    ) -> None:  # noqa: D102
        pass

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:  # noqa: D102
        pass

    def acquire_migration_lock(
        self, schema: str, wait_timeout_seconds: int = 60
    ) -> bool:  # noqa: D102
        return True

    def release_migration_lock(self, schema: str) -> bool:  # noqa: D102
        return True

    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:  # noqa: D102
        return []

    def record_migration(
        self,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: str = "dblift_schema_history",
    ) -> None:  # noqa: D102
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg() -> DbliftConfig:
    """Return a minimal DbliftConfig backed by an in-memory SQLite database."""
    return DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})


@pytest.fixture
def provider(cfg: DbliftConfig) -> _Concrete:
    """Yield a connected _Concrete provider; close on teardown."""
    p = _Concrete(cfg)
    p.create_connection()
    yield p
    p.close()


# ---------------------------------------------------------------------------
# Behavioural tests
# ---------------------------------------------------------------------------


def test_execute_statement_then_query(provider: _Concrete) -> None:
    """execute_statement + execute_query round-trip returns correct dicts."""
    provider.execute_statement("CREATE TABLE t (id INTEGER, name TEXT)")
    provider.execute_statement("INSERT INTO t (id, name) VALUES (1, 'a')")
    rows = provider.execute_query("SELECT id, name FROM t")
    assert rows == [{"id": 1, "name": "a"}]


def test_connection_property_returns_active_connection(provider: _Concrete) -> None:
    """connection exposes the SQLAlchemy Connection for provider mixins."""
    assert provider.connection is not None
    assert provider.connection.closed is False


def test_query_executor_exposes_mysql_identifier_helpers() -> None:
    """Native schema operations need the same identifier helpers legacy executors had."""
    from db.plugins.mysql.provider import MySqlProvider
    from db.plugins.mysql.quirks import MysqlQuirks

    provider = object.__new__(MySqlProvider)
    # object.__new__ skips __init__, so seed the quirks cache directly: the lazy
    # quirks property would otherwise resolve via self.config, which is unset here.
    provider._quirks = MysqlQuirks()
    executor = _SqlAlchemyQueryExecutor(provider)

    assert executor.get_quoted_schema_name("my`db") == "`my``db`"
    assert executor.get_schema_qualified_name("my`db", "orders") == "`my``db`.`orders`"


def test_identifier_quote_chars_derived_from_quirks() -> None:
    """_identifier_quote_chars sources quotes from quirks, not the dialect name."""
    from db.base_quirks import BaseQuirks
    from db.plugins.mysql.quirks import MysqlQuirks
    from db.plugins.sqlserver.quirks import SqlserverQuirks

    # The dialects that reach this native path are exactly the ones that
    # override quote_* (mysql/sqlserver) plus everything else on the BaseQuirks
    # default. cosmosdb/sqlite never use SqlAlchemyProvider, so they are out of scope.
    cases = [
        (MysqlQuirks(), ("`", "`", "``")),
        (SqlserverQuirks(), ("[", "]", "]]")),
        (BaseQuirks(), ('"', '"', '""')),
    ]
    for quirks, expected in cases:
        provider = SimpleNamespace(quirks=quirks)
        executor = _SqlAlchemyQueryExecutor(provider)  # type: ignore[arg-type]
        assert executor._identifier_quote_chars() == expected


def test_query_executor_statement_commits_without_provider_transaction() -> None:
    provider = SimpleNamespace(_tx=None)
    executor = _SqlAlchemyQueryExecutor(provider)  # type: ignore[arg-type]
    connection = MagicMock()
    connection.exec_driver_sql.return_value.rowcount = 1

    rowcount = executor.execute_statement(connection, "DROP TABLE t")

    assert rowcount == 1
    connection.commit.assert_called_once_with()


def test_create_connection_reuses_open_transaction_connection(cfg: DbliftConfig) -> None:
    """create_connection must not replace the connection tied to an open tx."""
    provider = _Concrete(cfg)
    conn = provider.create_connection()
    provider.begin_transaction()

    try:
        assert provider.create_connection() is conn
        assert conn.closed is False
    finally:
        provider.rollback_transaction()
        provider.close()


def test_engine_property_returns_shared_engine(provider: _Concrete) -> None:
    """engine exposes the SQLAlchemy Engine for native introspection."""
    assert provider.engine is provider._conn_mgr.engine


def test_execute_query_returns_list_of_dicts(provider: _Concrete) -> None:
    """Multiple rows are returned as a list of dicts in insertion order."""
    provider.execute_statement("CREATE TABLE t (id INTEGER)")
    provider.execute_statement("INSERT INTO t VALUES (1)")
    provider.execute_statement("INSERT INTO t VALUES (2)")
    rows = provider.execute_query("SELECT id FROM t ORDER BY id")
    assert rows == [{"id": 1}, {"id": 2}]


def test_rollback_discards_changes(provider: _Concrete) -> None:
    """rollback_transaction discards statements executed inside the tx."""
    provider.execute_statement("CREATE TABLE t (id INTEGER)")
    provider.begin_transaction()
    provider.execute_statement("INSERT INTO t VALUES (99)")
    provider.rollback_transaction()
    assert provider.execute_query("SELECT count(*) AS c FROM t") == [{"c": 0}]


def test_commit_persists_changes(provider: _Concrete) -> None:
    """commit_transaction persists statements executed inside the tx."""
    provider.execute_statement("CREATE TABLE t (id INTEGER)")
    provider.begin_transaction()
    provider.execute_statement("INSERT INTO t VALUES (7)")
    provider.commit_transaction()
    assert provider.execute_query("SELECT id FROM t") == [{"id": 7}]


def test_execute_statement_with_positional_params(provider: _Concrete) -> None:
    """Question-mark positional params bind correctly via execute_statement."""
    provider.execute_statement("CREATE TABLE t (id INTEGER, name TEXT)")
    provider.execute_statement("INSERT INTO t (id, name) VALUES (?, ?)", params=[1, "a"])
    assert provider.execute_query("SELECT id, name FROM t") == [{"id": 1, "name": "a"}]


def test_execute_query_with_positional_params(provider: _Concrete) -> None:
    """Question-mark positional params bind correctly via execute_query."""
    provider.execute_statement("CREATE TABLE t (id INTEGER, name TEXT)")
    provider.execute_statement("INSERT INTO t (id, name) VALUES (1, 'a')")
    provider.execute_statement("INSERT INTO t (id, name) VALUES (2, 'b')")
    rows = provider.execute_query("SELECT name FROM t WHERE id = ?", params=[2])
    assert rows == [{"name": "b"}]


def test_execute_query_then_begin_transaction(provider: _Concrete) -> None:
    """A read before begin_transaction must not leave an autobegin tx open.

    SQLAlchemy 2.0 implicitly begins a transaction on the first execute; if
    execute_query does not commit that implicit tx, the subsequent
    begin_transaction() raises InvalidRequestError. This reproduces the
    real migration sequence (history read precedes the migration tx).
    """
    provider.execute_statement("CREATE TABLE t (id INTEGER)")
    provider.execute_query("SELECT count(*) AS c FROM t")  # opens implicit tx
    provider.begin_transaction()  # must not raise
    provider.execute_statement("INSERT INTO t VALUES (5)")
    provider.commit_transaction()
    assert provider.execute_query("SELECT id FROM t") == [{"id": 5}]


def test_execute_statement_without_params_does_not_parse_colon_tokens(provider: _Concrete) -> None:
    """Raw migration SQL with colon syntax is sent as driver SQL when unbound."""
    provider.execute_statement("CREATE TABLE audit (body TEXT)")
    provider.execute_statement("INSERT INTO audit (body) VALUES ('BEGIN :NEW.id := :OLD.id; END;')")
    assert provider.execute_query("SELECT body FROM audit") == [
        {"body": "BEGIN :NEW.id := :OLD.id; END;"}
    ]


def test_execute_statement_without_params_escapes_percent_for_format_driver(
    cfg: DbliftConfig,
) -> None:
    """Raw SQL with literal percent signs is safe for format/pyformat DBAPIs."""

    class _Result:
        rowcount = 1

    class _Connection:
        dialect = SimpleNamespace(paramstyle="pyformat")

        def __init__(self) -> None:
            self.driver_calls: List[Any] = []
            self.commit_called = 0

        def exec_driver_sql(self, sql: str, params: Any = None) -> _Result:
            self.driver_calls.append((sql, params))
            return _Result()

        def commit(self) -> None:
            self.commit_called += 1

    provider = _Concrete(cfg)
    connection = _Connection()
    provider._ensure_connection = lambda: connection  # type: ignore[method-assign]

    rowcount = provider.execute_statement(
        "CREATE TABLE users (email TEXT CHECK (email LIKE '%@%'))"
    )

    assert rowcount == 1
    assert connection.driver_calls == [
        ("CREATE TABLE users (email TEXT CHECK (email LIKE '%%@%%'))", None)
    ]
    assert connection.commit_called == 1


def test_catalog_query_executor_uses_driver_sql_for_positional_params(
    provider: _Concrete,
) -> None:
    """Native catalog queries bypass SQLAlchemy text() parsing for positional params."""

    class _Result:
        def mappings(self) -> List[Dict[str, Any]]:
            return [{"value": "ok"}]

    class _Connection:
        dialect = SimpleNamespace(paramstyle="pyformat")

        def __init__(self) -> None:
            self.driver_calls: List[Any] = []
            self.execute_calls: List[Any] = []

        def exec_driver_sql(self, sql: str, params: Any = None) -> _Result:
            self.driver_calls.append((sql, params))
            return _Result()

        def execute(self, *args: Any, **kwargs: Any) -> None:
            self.execute_calls.append((args, kwargs))

    connection = _Connection()

    rows = provider.query_executor.execute_query(
        connection,
        "SELECT ps.data_type::text FROM pg_sequences ps "
        "WHERE ps.schemaname = ? AND ps.name NOT LIKE 'pg_%'",
        ["public"],
    )

    assert rows == [{"value": "ok"}]
    assert connection.driver_calls == [
        (
            "SELECT ps.data_type::text FROM pg_sequences ps "
            "WHERE ps.schemaname = %s AND ps.name NOT LIKE 'pg_%%'",
            ("public",),
        )
    ]
    assert connection.execute_calls == []


def test_catalog_query_executor_executes_statements_with_driver_params(
    provider: _Concrete,
) -> None:
    """Native catalog statements keep the old query_executor statement shape."""

    class _Result:
        rowcount = 3

    class _Connection:
        dialect = SimpleNamespace(paramstyle="pyformat")

        def __init__(self) -> None:
            self.driver_calls: List[Any] = []

        def exec_driver_sql(self, sql: str, params: Any = None) -> _Result:
            self.driver_calls.append((sql, params))
            return _Result()

    connection = _Connection()

    affected = provider.query_executor.execute_statement(
        connection,
        "DELETE FROM lock_table WHERE name = ?",
        ["migration"],
    )

    assert affected == 3
    assert connection.driver_calls == [("DELETE FROM lock_table WHERE name = %s", ("migration",))]


def test_catalog_query_executor_without_params_escapes_percent_for_format_driver() -> None:
    """Unbound catalog SQL also escapes literal percent signs for format DBAPIs."""

    class _Result:
        def mappings(self) -> List[Dict[str, Any]]:
            return [{"value": "ok"}]

    class _Connection:
        dialect = SimpleNamespace(paramstyle="format")

        def __init__(self) -> None:
            self.driver_calls: List[Any] = []

        def exec_driver_sql(self, sql: str, params: Any = None) -> _Result:
            self.driver_calls.append((sql, params))
            return _Result()

    provider = SimpleNamespace(_tx=None, _external_connection=False)
    executor = _SqlAlchemyQueryExecutor(provider)  # type: ignore[arg-type]
    connection = _Connection()

    rows = executor.execute_query(connection, "SELECT 1 WHERE email LIKE '%@%'")

    assert rows == [{"value": "ok"}]
    assert connection.driver_calls == [("SELECT 1 WHERE email LIKE '%%@%%'", None)]


# ---------------------------------------------------------------------------
# External engine injection (python-native plan Task 1.2)
# ---------------------------------------------------------------------------


def test_provider_engine_property_returns_injected_engine():
    """Provider constructed via from_engine (or equiv) reuses the caller's engine."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    provider = _Concrete.from_engine(config, engine, owns_engine=False)
    assert provider.engine is engine
    # Provider close must not dispose the injected engine (ownership=False)
    provider.close()
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


# ---------------------------------------------------------------------------
# execute_autocommit_statement — one statement outside a transaction block
# ---------------------------------------------------------------------------


class _RecordingConnection:
    """Connection stand-in recording isolation-level and transaction calls.

    Deliberately not a ``MagicMock``: a mock grows whatever attribute is asked
    of it, so a test written against one passes even when the production code
    calls something that does not exist. That is exactly how the dead
    ``setAutoCommit`` branch this method replaces kept a green test.
    """

    def __init__(
        self,
        isolation_level: str = "READ COMMITTED",
        in_tx: bool = False,
        execution_option: Optional[str] = None,
        configured_autocommit: bool = False,
    ) -> None:
        self.closed = False
        # How the connection was built — an engine created with
        # isolation_level="AUTOCOMMIT" hands out connections whose DBAPI flag
        # is already True, with nothing in the execution options to say so.
        self._configured_autocommit = configured_autocommit
        # The *server* isolation level. Deliberately NOT changed by an
        # AUTOCOMMIT execution option: on a real driver AUTOCOMMIT is a DBAPI
        # flag, and get_isolation_level() keeps reporting READ COMMITTED while
        # dbapi_connection.autocommit is True. Verified against psycopg.
        self._isolation_level = isolation_level
        # A level the caller set on this connection itself, as
        # Connection.get_execution_options() would report it. Empty when the
        # level came from the engine or the dialect default — the case
        # get_isolation_level() cannot describe, since it never says AUTOCOMMIT.
        self._execution_options: Dict[str, Any] = (
            {"isolation_level": execution_option} if execution_option else {}
        )
        self.autocommit = configured_autocommit or execution_option == "AUTOCOMMIT"
        self._in_tx = in_tx
        self.calls: List[str] = []
        self.dialect = SimpleNamespace(reset_isolation_level=self._reset_isolation_level)
        self.connection = SimpleNamespace(dbapi_connection=object())

    def get_isolation_level(self) -> str:
        return self._isolation_level

    def get_execution_options(self) -> Dict[str, Any]:
        # SQLAlchemy returns the live mapping, not a copy — safe there because
        # it is immutable and rebound on every change. Handing back a copy here
        # would let a caller that snapshots it drift from what the real object
        # does.
        return self._execution_options

    def execution_options(self, **kwargs: Any) -> None:
        level = kwargs["isolation_level"]
        # Replaces the mapping rather than mutating it, as SQLAlchemy does:
        # Connection._execution_options is an immutabledict and the real method
        # rebinds it to ``old.union(opt)``. A snapshot taken beforehand must
        # therefore keep describing the state before the switch.
        self._execution_options = {**self._execution_options, "isolation_level": level}
        self.autocommit = level == "AUTOCOMMIT"
        if not self.autocommit:
            self._isolation_level = level
        self.calls.append(f"isolation={level}")

    def _reset_isolation_level(self, dbapi_connection: Any) -> None:
        """Stand-in for SQLAlchemy's return-to-pool hook.

        The real hook restores whatever the connection was configured with —
        engine-level AUTOCOMMIT included — which is why production code calls
        it instead of replaying a level read back from the server.

        It touches the *DBAPI* connection only. It deliberately does **not**
        clear ``isolation_level`` from the execution options: verified against
        SQLAlchemy 2.0, ``get_execution_options()`` still reports
        ``AUTOCOMMIT`` afterwards. A fake that cleared it would be
        self-healing where the real object latches, and would hide any
        capture that reads its own leftover back as the caller's setting.
        """
        self.autocommit = self._configured_autocommit
        self.calls.append("reset_isolation_level")

    def in_transaction(self) -> bool:
        return self._in_tx

    def rollback(self) -> None:
        self._in_tx = False
        self.calls.append("rollback")


def _provider_with(connection: _RecordingConnection, cfg: DbliftConfig) -> _Concrete:
    """Provider whose connection *and* statement execution are both recorded.

    ``execute_statement`` is stubbed on the instance so the test can observe
    the connection's autocommit flag at the moment the statement runs — the
    whole point of the per-statement switch.
    """
    p = _Concrete(cfg)
    p._ensure_connection = lambda: connection  # type: ignore[method-assign,assignment]

    def _record_execute(
        sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        connection.calls.append(f"execute(autocommit={connection.autocommit})")
        return 7

    p.execute_statement = _record_execute  # type: ignore[method-assign,assignment]
    return p


def test_autocommit_statement_switches_and_restores(cfg: DbliftConfig) -> None:
    """The statement itself runs in AUTOCOMMIT; the connection is restored after."""
    conn = _RecordingConnection(isolation_level="READ COMMITTED")
    provider = _provider_with(conn, cfg)

    rows = provider.execute_autocommit_statement("CREATE INDEX CONCURRENTLY ix ON t (c)")

    assert rows == 7
    assert conn.autocommit is False
    assert conn.calls == [
        "isolation=AUTOCOMMIT",
        "execute(autocommit=True)",
        "reset_isolation_level",
    ]


def test_autocommit_statement_restores_after_an_exception(cfg: DbliftConfig) -> None:
    """A failing statement must not leave the session autocommitting.

    Leaving it switched would silently disarm all-or-nothing rollback for every
    later statement — a worse defect than the one this method exists to fix.
    """
    conn = _RecordingConnection(isolation_level="REPEATABLE READ")
    provider = _provider_with(conn, cfg)

    def _boom(sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None) -> int:
        raise RuntimeError("statement failed")

    provider.execute_statement = _boom  # type: ignore[method-assign,assignment]

    with pytest.raises(RuntimeError):
        provider.execute_autocommit_statement("CREATE INDEX CONCURRENTLY ix ON t (c)")

    assert conn.autocommit is False
    assert conn.calls == ["isolation=AUTOCOMMIT", "reset_isolation_level"]


def test_autocommit_statement_replays_a_caller_set_isolation_level(cfg: DbliftConfig) -> None:
    """A level the caller put on the connection itself is reapplied verbatim."""
    conn = _RecordingConnection(execution_option="SERIALIZABLE")
    provider = _provider_with(conn, cfg)

    provider.execute_autocommit_statement("CREATE INDEX CONCURRENTLY ix ON t (c)")

    assert conn.calls == [
        "isolation=AUTOCOMMIT",
        "execute(autocommit=True)",
        "isolation=SERIALIZABLE",
    ]
    assert conn.autocommit is False


def test_autocommit_statement_leaves_an_autocommit_engine_autocommitting(
    cfg: DbliftConfig,
) -> None:
    """A caller's AUTOCOMMIT engine must not be downgraded by one flagged statement.

    ``from_sqlalchemy`` accepts an engine built with
    ``isolation_level="AUTOCOMMIT"``. Nothing in the connection's execution
    options records that, and ``get_isolation_level()`` reports the server
    level (``READ COMMITTED``) — so restoring what it returns would silently
    switch the caller's session to transactional behaviour for good.
    """
    conn = _RecordingConnection(configured_autocommit=True)
    provider = _provider_with(conn, cfg)

    provider.execute_autocommit_statement("CREATE INDEX CONCURRENTLY ix ON t (c)")

    assert conn.calls[-1] == "reset_isolation_level"
    assert conn.autocommit is True


def test_autocommit_statement_ends_an_open_transaction_first(cfg: DbliftConfig) -> None:
    """SQLAlchemy refuses to change isolation level mid-transaction."""
    conn = _RecordingConnection(in_tx=True)
    provider = _provider_with(conn, cfg)

    provider.execute_autocommit_statement("VACUUM")

    assert conn.calls[0] == "rollback"
    assert conn.calls[1] == "isolation=AUTOCOMMIT"


def test_autocommit_statement_rolls_back_a_provider_transaction(cfg: DbliftConfig) -> None:
    """A provider-owned transaction is discarded and cleared, not left dangling."""
    conn = _RecordingConnection()
    provider = _provider_with(conn, cfg)
    tx = MagicMock()
    provider._tx = tx

    provider.execute_autocommit_statement("VACUUM")

    tx.rollback.assert_called_once()
    assert provider._tx is None


def test_autocommit_statement_skips_restore_on_a_closed_connection(cfg: DbliftConfig) -> None:
    """A connection closed by the statement must not be touched on the way out."""
    conn = _RecordingConnection()
    provider = _provider_with(conn, cfg)

    def _close_during(
        sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        conn.closed = True
        return 0

    provider.execute_statement = _close_during  # type: ignore[method-assign,assignment]

    provider.execute_autocommit_statement("VACUUM")

    assert conn.calls == ["isolation=AUTOCOMMIT"]


def test_autocommit_statement_default_delegates_to_plain_execution() -> None:
    """Base contract: providers whose driver already autocommits change nothing."""
    from db.provider_interfaces import TransactionalProvider

    class _Plain(TransactionalProvider):
        def __init__(self) -> None:
            self.executed: List[Any] = []

        def begin_transaction(self) -> None:  # noqa: D102
            pass

        def commit_transaction(self) -> None:  # noqa: D102
            pass

        def rollback_transaction(self) -> None:  # noqa: D102
            pass

        def execute_statement(
            self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
        ) -> int:
            self.executed.append((sql, schema, params))
            return 3

    p = _Plain()

    assert p.execute_autocommit_statement("CREATE THING", schema="s") == 3
    assert p.executed == [("CREATE THING", "s", None)]


def test_autocommit_statement_does_not_latch_on_a_second_call(cfg: DbliftConfig) -> None:
    """Two flagged statements on one connection must not leave it autocommitting.

    One index migration normally carries several ``CREATE INDEX CONCURRENTLY``
    statements. If the switch is restored by replaying whatever the execution
    options report, the second call reads back the option the *first* call
    wrote and reapplies ``AUTOCOMMIT`` — disarming rollback for every migration
    that follows in the same run.
    """
    conn = _RecordingConnection(isolation_level="READ COMMITTED")
    provider = _provider_with(conn, cfg)

    provider.execute_autocommit_statement("CREATE INDEX CONCURRENTLY ix_a ON t (a)")
    provider.execute_autocommit_statement("CREATE INDEX CONCURRENTLY ix_b ON t (b)")

    assert conn.autocommit is False
    assert conn.get_execution_options().get("isolation_level") is None


# ---------------------------------------------------------------------------
# execute_autocommit_statement against real SQLAlchemy — no fake in the way.
#
# The latch is a fact about sqlalchemy.engine.Connection, not about any
# database: reset_isolation_level restores the DBAPI flag and leaves
# isolation_level sitting in the connection's execution options. SQLite is
# enough to pin it, and pysqlite maps AUTOCOMMIT onto dbapi.isolation_level.
# ---------------------------------------------------------------------------


def _sqlite_provider(cfg: DbliftConfig, **engine_kwargs: Any) -> _Concrete:
    """Return a provider on a real in-memory SQLite engine."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite://", **engine_kwargs)
    return _Concrete.from_engine(cfg, engine, owns_engine=True)  # type: ignore[return-value]


def _dbapi_autocommitting(conn: Any) -> bool:
    """Report the real DBAPI autocommit state of *conn*.

    pysqlite expresses AUTOCOMMIT as ``dbapi_connection.isolation_level is
    None``; any transactional level leaves it a string. This is the flag that
    decides whether a failed migration can still be rolled back, so it is what
    the assertions are made against — not the execution options, which are
    only how the level was asked for.
    """
    return bool(conn.connection.dbapi_connection.isolation_level is None)


def test_autocommit_statement_does_not_latch_a_real_connection(cfg: DbliftConfig) -> None:
    """Repeated flagged statements leave a real connection transactional."""
    provider = _sqlite_provider(cfg)
    try:
        provider.execute_autocommit_statement("CREATE TABLE a (c INTEGER)")
        conn = provider.connection
        assert _dbapi_autocommitting(conn) is False

        provider.execute_autocommit_statement("CREATE TABLE b (c INTEGER)")

        assert conn is provider.connection
        assert _dbapi_autocommitting(conn) is False
        # The option must be gone, not merely overridden: leaving it behind is
        # what makes the *next* capture read dblift's own switch back as the
        # caller's configuration.
        assert conn.get_execution_options().get("isolation_level") is None
    finally:
        provider.close()


def test_autocommit_statement_keeps_an_autocommit_engine_autocommitting(
    cfg: DbliftConfig,
) -> None:
    """An engine built with ``isolation_level="AUTOCOMMIT"`` stays autocommitting.

    ``from_sqlalchemy`` accepts such an engine. Nothing in the connection's
    execution options records it, and ``get_isolation_level()`` reports the
    server level, so restoring what either reports would silently downgrade
    the caller's session.
    """
    provider = _sqlite_provider(cfg, isolation_level="AUTOCOMMIT")
    try:
        conn = provider._ensure_connection()
        assert _dbapi_autocommitting(conn) is True

        provider.execute_autocommit_statement("CREATE TABLE a (c INTEGER)")
        assert _dbapi_autocommitting(conn) is True

        provider.execute_autocommit_statement("CREATE TABLE b (c INTEGER)")
        assert _dbapi_autocommitting(conn) is True
        assert conn.get_execution_options().get("isolation_level") is None
    finally:
        provider.close()


def test_autocommit_statement_preserves_a_caller_set_autocommit_connection(
    cfg: DbliftConfig,
) -> None:
    """A caller who set AUTOCOMMIT on the connection itself keeps it."""
    provider = _sqlite_provider(cfg)
    try:
        conn = provider.create_connection()
        conn.execution_options(isolation_level="AUTOCOMMIT")

        provider.execute_autocommit_statement("CREATE TABLE a (c INTEGER)")
        provider.execute_autocommit_statement("CREATE TABLE b (c INTEGER)")

        assert _dbapi_autocommitting(conn) is True
        assert conn.get_execution_options().get("isolation_level") == "AUTOCOMMIT"
    finally:
        provider.close()


def test_autocommit_statement_preserves_a_caller_set_transactional_connection(
    cfg: DbliftConfig,
) -> None:
    """A transactional level set on the connection is restored, not cleared."""
    provider = _sqlite_provider(cfg)
    try:
        conn = provider.create_connection()
        conn.execution_options(isolation_level="SERIALIZABLE")

        provider.execute_autocommit_statement("CREATE TABLE a (c INTEGER)")
        provider.execute_autocommit_statement("CREATE TABLE b (c INTEGER)")

        assert _dbapi_autocommitting(conn) is False
        assert conn.get_execution_options().get("isolation_level") == "SERIALIZABLE"
    finally:
        provider.close()


def test_autocommit_statement_keeps_unrelated_execution_options(cfg: DbliftConfig) -> None:
    """Restoring the isolation level must not discard the caller's other options."""
    provider = _sqlite_provider(cfg)
    try:
        conn = provider.create_connection()
        conn.execution_options(logging_token="caller")

        provider.execute_autocommit_statement("CREATE TABLE a (c INTEGER)")

        assert conn.get_execution_options().get("logging_token") == "caller"
        assert conn.get_execution_options().get("isolation_level") is None
    finally:
        provider.close()


# ---------------------------------------------------------------------------
# Thread safety (issue #819) — concurrent read-only calls on one shared
# provider must not race on its single cached connection.
# ---------------------------------------------------------------------------


def test_concurrent_execute_query_from_several_threads_does_not_race(tmp_path: Any) -> None:
    """Several threads sharing one provider must not race on its cached connection.

    ``DBLiftClient.info()`` fans out into several calls to
    ``provider.execute_query`` / ``execute_statement`` against the single
    ``Connection`` object cached on the provider (see ``create_connection``).
    Nothing guarded that shared state, so concurrent callers on one client
    instance could pass the "no connection yet" check together, each install
    a connection of their own onto ``self._connection``, and tear down a
    sibling's still-live connection out from under it — exactly the failure
    mode the bug report describes (an ``AssertionError``, ``success=False``
    with no message, and a leaked "transaction already deassociated from
    connection" warning), reported against Citus but rooted in this
    dialect-agnostic base class.

    Deterministic reproduction: two chokepoints on the connection lifecycle
    are each patched with a short sleep — a plain sleep, not a rendezvous the
    fix's lock would starve, since the fix must remain free to serialize
    threads one at a time through them without the test itself deadlocking.
    ``NativeConnectionManager.create_connection`` (the swap-in of a fresh
    connection onto the provider's cached ``self._connection``) widens the
    window in which several threads that all saw "no connection yet" are
    still creating one together. ``_escape_driver_percent_literals`` (called
    immediately before every ``exec_driver_sql``, i.e. right after a thread
    has *obtained* a connection and is about to use it) widens the window in
    which a thread is actively using a connection a sibling could still tear
    down. Several independent rounds, each against a fresh never-yet-connected
    provider so every thread's first call is the racy one, drive the odds of
    the whole test run missing the bug to effectively zero without relying on
    a single lucky interleaving.
    """
    from db.native_connection_manager import NativeConnectionManager

    # A real on-disk file (not ``:memory:``) so the table exists for every
    # round's freshly-constructed provider — an in-memory SQLite database is
    # private to whichever connection created it.
    db_path = tmp_path / "race.db"
    file_cfg = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": str(db_path)}})

    setup_provider = _Concrete(file_cfg)
    setup_provider.create_connection()
    setup_provider.execute_statement("CREATE TABLE t (id INTEGER)")
    setup_provider.execute_statement("INSERT INTO t (id) VALUES (1)")
    setup_provider.close()

    real_create_connection = NativeConnectionManager.create_connection

    def slow_create_connection(self: NativeConnectionManager) -> Any:
        time.sleep(0.02)
        return real_create_connection(self)

    real_escape = SqlAlchemyProvider.__dict__["_escape_driver_percent_literals"].__func__

    def slow_escape(sql: str, paramstyle: str) -> str:
        time.sleep(0.02)
        return real_escape(sql, paramstyle)

    thread_count = 5
    rounds = 15
    errors: List[BaseException] = []
    errors_lock = threading.Lock()

    with (
        patch.object(NativeConnectionManager, "create_connection", slow_create_connection),
        patch.object(
            SqlAlchemyProvider, "_escape_driver_percent_literals", staticmethod(slow_escape)
        ),
    ):
        for _ in range(rounds):
            # A fresh, never-yet-connected provider each round: every
            # thread's first call is the one guaranteed to see "no
            # connection yet", win or lose the race.
            provider = _Concrete(file_cfg)
            start_barrier = threading.Barrier(thread_count)

            def worker() -> None:
                try:
                    start_barrier.wait()
                    rows = provider.execute_query("SELECT id FROM t")
                    assert rows == [{"id": 1}], f"unexpected rows: {rows!r}"
                except BaseException as exc:  # noqa: BLE001 - collected and reported below
                    with errors_lock:
                        errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(thread_count)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            provider.close()

    assert not errors, f"Concurrent execute_query raised on a shared connection: {errors!r}"


def test_concurrent_close_races_readers_without_raising(tmp_path: Any) -> None:
    """``close()`` racing concurrent readers on a shared client must not raise.

    ``DBLiftClient.close()``/``__exit__`` reach ``SqlAlchemyProvider.close()``,
    and ``BaseCommand._ensure_connected()`` (phase 1 of every command,
    including ``InfoCommand``) reaches ``is_connected()`` — both read/mutate
    the same cached ``self._connection`` that ``execute_query`` et al. use.
    Before this fix neither method took ``self._lock``, so a concurrent
    ``close()`` was free to run *while a reader thread's own lock-protected
    section was already in flight* (the reader's lock does nothing to stop an
    unlocked caller), nulling ``self._connection`` and disposing the engine
    out from under a sibling mid ``execute_query``. Confirmed live (see task):
    racing ``close()`` against concurrent readers reliably raised
    ``sqlalchemy.exc.ResourceClosedError: This Connection is closed`` — the
    same family of failure as the original bug report's
    ``ConnectionError: transaction already deassociated from connection``.

    Reproduction needs the provider already connected (so readers actually
    reach the query path instead of finding ``is_connected() is False`` and
    stopping) and a wide-enough window inside the locked section for the
    closer to land its unlocked ``close()`` mid-flight — provided here by
    patching ``_escape_driver_percent_literals`` (called from inside
    ``execute_query``'s critical section, right before the connection is
    used) to sleep. Many independent short-lived providers (one per round),
    each racing several readers against one closer via a barrier plus a
    short closer-side delay, drive the odds of missing the window to
    effectively zero: this reproduces on every round pre-fix.
    """
    real_escape = SqlAlchemyProvider.__dict__["_escape_driver_percent_literals"].__func__

    def slow_escape(sql: str, paramstyle: str) -> str:
        time.sleep(0.05)
        return real_escape(sql, paramstyle)

    reader_count = 6
    rounds = 25
    errors: List[BaseException] = []
    errors_lock = threading.Lock()

    with patch.object(
        SqlAlchemyProvider, "_escape_driver_percent_literals", staticmethod(slow_escape)
    ):
        for round_index in range(rounds):
            db_path = tmp_path / f"race_close_{round_index}.db"
            file_cfg = DbliftConfig.from_dict(
                {"database": {"type": "sqlite", "path": str(db_path)}}
            )

            setup_provider = _Concrete(file_cfg)
            setup_provider.create_connection()
            setup_provider.execute_statement("CREATE TABLE t (id INTEGER)")
            setup_provider.execute_statement("INSERT INTO t (id) VALUES (1)")
            setup_provider.close()

            provider = _Concrete(file_cfg)
            provider.create_connection()
            start_barrier = threading.Barrier(reader_count + 1)

            def reader() -> None:
                try:
                    start_barrier.wait()
                    connected = provider.is_connected()
                    if connected:
                        rows = provider.execute_query("SELECT id FROM t")
                        assert rows == [{"id": 1}], f"unexpected rows: {rows!r}"
                except BaseException as exc:  # noqa: BLE001 - collected and reported below
                    with errors_lock:
                        errors.append(exc)

            def closer() -> None:
                start_barrier.wait()
                # Give readers a head start into their locked, sleeping
                # section before close() (unlocked, pre-fix) races in.
                time.sleep(0.01)
                provider.close()

            threads = [threading.Thread(target=reader) for _ in range(reader_count)]
            threads.append(threading.Thread(target=closer))
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

    assert not errors, f"Concurrent close() raced a reader unsafely: {errors!r}"


def test_getattr_lock_fallback_converges_on_one_lock_under_concurrent_first_touch() -> None:
    """Concurrent first-touch access to the ``__getattr__`` fallback lock must agree.

    Some existing test doubles construct a provider through
    ``object.__new__`` (skipping ``__init__``, e.g.
    ``test_query_executor_exposes_mysql_identifier_helpers`` above), so
    ``self._lock`` is never assigned and the first access falls through to
    ``__getattr__``. Before this fix that fallback was an unsynchronized
    check-then-act (build a lock, then store it), so many threads touching
    ``obj._lock`` for the first time simultaneously could each observe the
    attribute missing, each build their own ``RLock``, and each overwrite the
    previous store — leaving different threads holding different lock
    objects with zero mutual exclusion between them. All threads must
    converge on exactly one ``RLock`` instance.

    The unsynchronized version of ``__getattr__`` returns the *local*
    ``lock`` variable it just built, not whatever ends up stored on
    ``self.__dict__`` — so even a single interleaving between two threads'
    "check missing, then construct" is enough for both to walk away with
    their own distinct object. In plain execution the whole check-construct-
    store sequence is fast enough that the GIL rarely switches threads mid
    sequence, so the race is real but easy to miss by chance (confirmed live:
    the reviewer needed 32 threads to catch it 3-ways-distinct). To make the
    reproduction deterministic rather than lucky, ``threading.RLock`` is
    patched (module-locally, in ``db.sqlalchemy_provider``) to add a short
    sleep between construction and return — this only widens the window
    threads race inside, it does not change what either version of
    ``__getattr__`` does with the result.
    """
    import db.sqlalchemy_provider as sqlalchemy_provider_module

    real_rlock = threading.RLock

    def slow_rlock(*args: Any, **kwargs: Any) -> threading.RLock:
        lock = real_rlock(*args, **kwargs)
        time.sleep(0.01)
        return lock

    instance = object.__new__(_Concrete)
    thread_count = 32
    observed: List[threading.RLock] = []
    observed_lock = threading.Lock()
    start_barrier = threading.Barrier(thread_count)

    def touch() -> None:
        start_barrier.wait()
        lock = instance._lock
        with observed_lock:
            observed.append(lock)

    with patch.object(sqlalchemy_provider_module.threading, "RLock", slow_rlock):
        threads = [threading.Thread(target=touch) for _ in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

    assert len(observed) == thread_count
    distinct_ids = {id(lock) for lock in observed}
    assert len(distinct_ids) == 1, (
        f"Expected every thread to converge on one RLock, got {len(distinct_ids)} distinct "
        "lock objects — threads holding different locks have no mutual exclusion between them."
    )
