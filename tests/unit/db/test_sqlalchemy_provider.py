"""Tests for SqlAlchemyProvider — SQLAlchemy-backed native data-access base.

SqlAlchemyProvider is abstract: it implements the core data-access and
transaction methods but leaves dialect-specific schema/history/locking
operations for per-DB subclasses.  The _Concrete stub below fills those
remaining abstract slots so we can instantiate and exercise the real
behaviour.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

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

    provider = object.__new__(MySqlProvider)
    executor = _SqlAlchemyQueryExecutor(provider)

    assert executor.get_quoted_schema_name("my`db") == "`my``db`"
    assert executor.get_schema_qualified_name("my`db", "orders") == "`my``db`.`orders`"


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
