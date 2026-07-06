"""Provider-specific locking for PostgreSQL-compatible dialects."""

from unittest.mock import MagicMock

import pytest

from db.plugins.cockroachdb.provider import CockroachdbProvider
from db.plugins.redshift.provider import RedshiftProvider


def _compact(sql: str) -> str:
    return " ".join(sql.split())


class _FakeTransaction:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class _FakeConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.transaction = _FakeTransaction()
        self.closed = False

    def begin(self) -> _FakeTransaction:
        self.statements.append("BEGIN")
        return self.transaction

    def exec_driver_sql(self, sql: str):
        self.statements.append(sql)
        return MagicMock(rowcount=1)

    def close(self) -> None:
        self.closed = True


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnection:
        return self.connection


class _RedshiftProvider(RedshiftProvider):
    def __init__(self) -> None:
        self.statements: list[tuple[str, object, object]] = []
        self.queries: list[tuple[str, object]] = []
        self.lock_connection = _FakeConnection()
        self._engine = _FakeEngine(self.lock_connection)

    @property
    def engine(self) -> _FakeEngine:
        return self._engine

    def create_schema_if_not_exists(self, schema: str) -> None:
        self.statements.append(("create_schema", schema, None))

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        return 1

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return [{"acquired": True}]
        if "pg_advisory_unlock" in sql:
            return [{"released": True}]
        return []


class _CockroachProvider(CockroachdbProvider):
    def __init__(self) -> None:
        self.statements: list[tuple[str, object, object]] = []
        self.queries: list[tuple[str, object]] = []
        self.rollback_count = 0
        self._connection = MagicMock()

    def create_schema_if_not_exists(self, schema: str) -> None:
        self.statements.append(("create_schema", schema, None))

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        return 1

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return [{"acquired": True}]
        if "pg_advisory_unlock" in sql:
            return [{"released": True}]
        return []

    def table_exists(self, schema: str, table_name: str) -> bool:
        return True


@pytest.mark.unit
def test_redshift_history_table_uses_identity_not_serial() -> None:
    provider = _RedshiftProvider()

    sql = provider.create_history_table("public", "dblift_schema_history")

    compact_sql = _compact(sql)
    assert "SERIAL" not in compact_sql.upper()
    assert "installed_rank INTEGER IDENTITY(1,1) PRIMARY KEY" in compact_sql


@pytest.mark.unit
def test_redshift_lock_uses_table_lock() -> None:
    provider = _RedshiftProvider()

    acquired = provider.acquire_migration_lock(
        "public",
        wait_timeout_seconds=1,
    )
    assert acquired is True
    assert provider.release_migration_lock("public") is True

    lock_sql = "\n".join(provider.lock_connection.statements)
    query_sql = "\n".join(sql for sql, _params in provider.queries)
    assert "pg_try_advisory_lock" not in query_sql
    assert "pg_advisory_unlock" not in query_sql
    assert 'LOCK "public"."dblift_migration_lock"' in lock_sql
    assert "SET statement_timeout = 1000" in lock_sql
    assert provider.lock_connection.transaction.committed is True
    assert provider.lock_connection.closed is True


@pytest.mark.unit
def test_cockroachdb_lock_uses_table_row() -> None:
    provider = _CockroachProvider()

    acquired = provider.acquire_migration_lock(
        "public",
        wait_timeout_seconds=1,
    )
    assert acquired is True
    assert provider.release_migration_lock("public") is True

    statement_values = [sql for sql, _schema, _params in provider.statements]
    statement_sql = "\n".join(statement_values)
    query_sql = "\n".join(sql for sql, _params in provider.queries)
    assert "pg_try_advisory_lock" not in query_sql
    assert "pg_advisory_unlock" not in query_sql
    assert 'INSERT INTO "public"."dblift_migration_lock"' in statement_sql
    assert 'DELETE FROM "public"."dblift_migration_lock"' in statement_sql
