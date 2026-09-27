"""Live PostgreSQL check: a failed discovery query must fail ``clean``.

Clean first enumerates what to drop, one catalog query per object kind. Each
query used to be wrapped in its own ``try``/``except`` that logged at debug
level and moved on, so a connection clean could not actually use read as an
empty schema: ``clean`` dropped nothing and reported success.

Two ways to get there on stock PostgreSQL are exercised here: a role that
cannot read a catalog view clean needs, and a connection whose transaction
was already aborted by an earlier failed statement.
"""

import psycopg
import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider

pytestmark = pytest.mark.integration

#: Own database: revoking a catalog privilege there leaves ``testdb`` alone.
DATABASE = "dblift_clean_disc"
SCHEMA = "dblift_clean_disc"
ROLE = "dblift_clean_disc"


def _admin_sql(database: str, *statements: str) -> None:
    dsn = f"host=localhost port=5432 dbname={database} user=postgres password=postgres"
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


def _relations() -> list:
    dsn = f"host=localhost port=5432 dbname={DATABASE} user=postgres password=postgres"
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r', 'v') ORDER BY 1",
            [SCHEMA],
        ).fetchall()
    return [row[0] for row in rows]


def _provider(username: str, password: str) -> PostgreSqlProvider:
    return PostgreSqlProvider(
        DbliftConfig(
            database=PostgreSqlConfig(
                type="postgresql",
                host="localhost",
                port=5432,
                database=DATABASE,
                username=username,
                password=password,
                schema=SCHEMA,
            )
        )
    )


@pytest.fixture
def populated_schema():
    _admin_sql(
        "testdb",
        f'DROP DATABASE IF EXISTS "{DATABASE}"',
        f'DROP ROLE IF EXISTS "{ROLE}"',
        f"CREATE ROLE \"{ROLE}\" LOGIN PASSWORD '{ROLE}'",
        f'CREATE DATABASE "{DATABASE}"',
    )
    _admin_sql(
        DATABASE,
        f'CREATE SCHEMA "{SCHEMA}" AUTHORIZATION "{ROLE}"',
        f'CREATE TABLE "{SCHEMA}"."app_users" (id int)',
        f'CREATE VIEW "{SCHEMA}"."app_users_v" AS SELECT id FROM "{SCHEMA}"."app_users"',
        f'ALTER TABLE "{SCHEMA}"."app_users" OWNER TO "{ROLE}"',
        f'ALTER VIEW "{SCHEMA}"."app_users_v" OWNER TO "{ROLE}"',
    )
    try:
        yield
    finally:
        _admin_sql(
            "testdb",
            f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)',
            f'DROP ROLE IF EXISTS "{ROLE}"',
        )


def test_unreadable_catalog_fails_clean_and_drops_nothing(populated_schema, tmp_path) -> None:
    _admin_sql(DATABASE, "REVOKE SELECT ON pg_catalog.pg_tables FROM PUBLIC")
    provider = _provider(ROLE, ROLE)
    try:
        result = DBLiftClient(provider=provider, migrations_dir=tmp_path).clean(clean_enabled=True)
    finally:
        provider.close()

    assert result.success is False
    assert "permission denied for view pg_tables" in result.error_message
    assert _relations() == ["app_users", "app_users_v"]


def test_aborted_transaction_fails_clean_and_drops_nothing(populated_schema, tmp_path) -> None:
    provider = _provider("postgres", "postgres")
    provider.create_connection()
    try:
        with pytest.raises(Exception):
            provider.execute_query("SELECT * FROM dblift_clean_disc_missing_table")
        result = DBLiftClient(provider=provider, migrations_dir=tmp_path).clean(clean_enabled=True)
    finally:
        provider.close()

    assert result.success is False
    assert "current transaction is aborted" in result.error_message
    assert _relations() == ["app_users", "app_users_v"]


def test_readable_catalogs_still_clean(populated_schema, tmp_path) -> None:
    # Control: with every catalog readable, empty object kinds (no sequences,
    # routines, types, extensions here) do not stop the clean.
    provider = _provider(ROLE, ROLE)
    try:
        result = DBLiftClient(provider=provider, migrations_dir=tmp_path).clean(clean_enabled=True)
    finally:
        provider.close()

    assert result.success is True
    assert _relations() == []
