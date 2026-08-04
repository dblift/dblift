"""PostgreSQL native provider contract tests."""

from unittest.mock import MagicMock

import pytest

from db.plugins.postgresql.postgresql.locking_manager import _get_advisory_lock_key
from db.plugins.postgresql.provider import PostgreSqlProvider
from db.sqlalchemy_provider import SqlAlchemyProvider


class _Provider(PostgreSqlProvider):
    def __init__(self):
        self.queries = []
        self.statements = []
        self.lock_attempts = 0
        self.history_table_exists = True
        self.history_count = 0

    def create_schema_if_not_exists(self, schema: str) -> None:
        self.statements.append(("create_schema", schema, None))

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        return 1

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if "COUNT(1)" in sql:
            return [{"count": self.history_count}]
        if "pg_try_advisory_lock" in sql:
            self.lock_attempts += 1
            return [{"acquired": self.lock_attempts > 1}]
        if "pg_advisory_unlock" in sql:
            return [{"released": True}]
        return []

    def table_exists(self, schema: str, table_name: str) -> bool:
        return self.history_table_exists


def test_record_migration_lets_database_assign_installed_rank():
    provider = _Provider()

    provider.record_migration(
        "public",
        {
            "version": "1",
            "description": "init",
            "script": "V1.sql",
            "success": True,
        },
    )

    sql, _schema, params = provider.statements[-1]
    assert "installed_rank" not in sql
    assert len(params) == 8


def test_record_undo_records_synthetic_undo_migration():
    provider = _Provider()

    assert provider.record_undo("public", "1", script_name="U1__undo.sql") is True

    sql, _schema, params = provider.statements[-1]
    assert "INSERT INTO" in sql
    assert params[0] == "1"
    assert params[2] == "UNDO_SQL"
    assert params[3] == "U1__undo.sql"


def test_history_table_uses_serial_installed_rank():
    provider = _Provider()

    sql = provider.create_history_table("public", "dblift_schema_history")

    assert "installed_rank SERIAL PRIMARY KEY" in sql


def test_baseline_refuses_existing_populated_history_table():
    provider = _Provider()
    provider.history_count = 2

    try:
        provider.create_migration_history_table_if_not_exists("public", create_schema=True)
    except RuntimeError as exc:
        assert "Baseline cannot be applied" in str(exc)
    else:
        raise AssertionError("expected populated history table to block baseline")

    assert not any("CREATE TABLE" in statement[0] for statement in provider.statements)


def test_clean_preview_uses_native_schema_statements():
    provider = _Provider()

    summary = provider.get_clean_preview("tenant_a")

    assert summary.statements == []
    assert not any("DROP SCHEMA" in statement[0] for statement in provider.statements)


def test_clean_schema_drops_objects_inside_schema_without_recreating_schema(monkeypatch):
    provider = _Provider()

    def fake_query(sql, params=None):
        if "pg_tables" in sql:
            return [{"table_name": "orders"}]
        return []

    def fake_execute(self, sql, schema=None, params=None):
        provider.statements.append((sql, schema, params))
        return 1

    provider.execute_query = fake_query
    monkeypatch.setattr("db.sqlalchemy_provider.SqlAlchemyProvider.execute_statement", fake_execute)

    summary = provider.clean_schema("tenant_a")

    executed_sql = [statement[0] for statement in provider.statements]
    assert not any("DROP SCHEMA" in sql for sql in executed_sql)
    assert not any("CREATE SCHEMA" in sql for sql in executed_sql)
    assert 'DROP TABLE IF EXISTS "tenant_a"."orders" CASCADE' in executed_sql
    assert any(obj.object_type == "table" and obj.name == "orders" for obj in summary.objects)


def test_locking_uses_legacy_deterministic_advisory_key():
    provider = _Provider()

    provider.acquire_migration_lock("public", wait_timeout_seconds=1)

    expected_key = _get_advisory_lock_key("public")
    assert provider.queries[0][0] == f"SELECT pg_try_advisory_lock({expected_key}) AS acquired"


def test_locking_retries_until_timeout(monkeypatch):
    provider = _Provider()
    now = iter([0.0, 0.2, 0.4, 0.6])
    sleeps = []
    monkeypatch.setattr("db.plugins.postgresql.provider.time.monotonic", lambda: next(now))
    monkeypatch.setattr("db.plugins.postgresql.provider.time.sleep", sleeps.append)

    assert provider.acquire_migration_lock("public", wait_timeout_seconds=1) is True

    assert len(provider.queries) == 2
    assert sleeps == [0.2]


def test_provider_declares_migration_lock_table_name():
    assert PostgreSqlProvider.MIGRATION_LOCK_TABLE == "dblift_migration_lock"


def test_provider_does_not_own_model_capture_table_creation():
    method_name = "create_" + "snap" + "shot_table_if_not_exists"

    assert method_name not in PostgreSqlProvider.__dict__
    assert method_name not in PostgreSqlProvider.__abstractmethods__


def test_existing_schema_skips_create_schema_statement(monkeypatch):
    provider = _Provider()
    provider.execute_query = lambda sql, params=None: [{"exists": True}]

    PostgreSqlProvider.create_schema_if_not_exists(provider, "tenant_a")

    assert provider.statements == []


def test_missing_schema_executes_create_schema_statement(monkeypatch):
    provider = _Provider()
    provider.execute_query = lambda sql, params=None: [{"exists": False}]

    PostgreSqlProvider.create_schema_if_not_exists(provider, "tenant_a")

    assert provider.statements[-1][0] == 'CREATE SCHEMA IF NOT EXISTS "tenant_a"'


def test_set_current_schema_keeps_public_resolvable(monkeypatch):
    """``SET search_path`` keeps ``public`` after the target schema.

    Extensions install their callable API into ``public``; a schema-only path
    makes those functions unresolvable for anything dblift runs through this
    seam (callbacks, schema-scoped statements, and Redshift, whose URL builder
    sets no search path at all).
    """
    executed = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: executed.append(sql),
    )
    provider = _Provider()

    PostgreSqlProvider.set_current_schema(provider, "tenant_a")

    assert executed == ['SET search_path TO "tenant_a", "public"']


def test_set_current_schema_does_not_repeat_public_schema(monkeypatch):
    """A ``public`` target schema is not listed twice."""
    executed = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: executed.append(sql),
    )
    provider = _Provider()

    PostgreSqlProvider.set_current_schema(provider, "public")

    assert executed == ['SET search_path TO "public"']


def test_release_uses_same_deterministic_advisory_key():
    provider = _Provider()

    assert provider.release_migration_lock("public") is True

    expected_key = _get_advisory_lock_key("public")
    assert provider.queries[-1][0] == f"SELECT pg_advisory_unlock({expected_key}) AS released"


def test_create_migration_lock_table_survives_concurrent_duplicate_object_race():
    """Two first-ever ``migrate()`` calls both run ``CREATE TABLE IF NOT
    EXISTS`` before either one reaches the advisory lock that is meant to
    serialize them. PostgreSQL can respond to the loser with a
    ``DuplicateObject`` error on the table's implicit row type instead of
    silently no-op'ing, so the table-creation step must treat that as
    success instead of letting it fail the whole migration."""
    provider = _Provider()

    def raise_duplicate_object(sql, schema=None, params=None):
        if "CREATE TABLE IF NOT EXISTS" in sql:
            raise Exception(
                '(psycopg.errors.DuplicateObject) type "dblift_migration_lock" already exists'
            )
        provider.statements.append((sql, schema, params))
        return 1

    provider.execute_statement = raise_duplicate_object
    provider._connection = MagicMock()

    provider.create_migration_lock_table_if_not_exists("public")

    provider._connection.rollback.assert_called_once()
