"""End-to-end: a ``pg_dump`` ``COPY ... FROM stdin`` block loads its rows.

psycopg refuses ``COPY ... FROM STDIN`` through ``cursor.execute``, and the
failed attempt left the connection mid-COPY: the rollback, the failed-history
write and the migration-lock release all errored, so ``info`` reported the
migration as pending. The block is now streamed through the driver's copy API.

Requires PostgreSQL on localhost:5432 (same server as
tests/integration/test_postgresql_statement_verbatim.py).
"""

from pathlib import Path
from typing import Any

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_versioned_migration

pytestmark = pytest.mark.integration

SCHEMA = "copy_stdin_test"

COPY_MIGRATION = (
    "\\restrict dumptoken\n"
    f'CREATE TABLE "{SCHEMA}"."t" (id INT, v TEXT);\n'
    f'COPY "{SCHEMA}"."t" (id, v) FROM stdin;\n'
    "1\talpha\n"
    "2\t\\N\n"
    "3\tsemi; DROP TABLE t;\n"
    "\\.\n"
    "\n"
    f'SELECT count(*) FROM "{SCHEMA}"."t";\n'
    "\\unrestrict dumptoken\n"
)


def _pg_config(schema: str) -> DbliftConfig:
    return DbliftConfig(
        database=PostgreSqlConfig(
            type="postgresql",
            host="localhost",
            port=5432,
            database="testdb",
            username="postgres",
            password="postgres",
            schema=schema,
        )
    )


@pytest.fixture
def pg_schema() -> Any:
    admin = PostgreSqlProvider(_pg_config("public"))
    admin.create_connection()
    admin.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    admin.execute_statement(f'CREATE SCHEMA "{SCHEMA}"')
    try:
        yield admin
    finally:
        admin.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        admin.close()


def _migrate(migrations_dir: Path) -> Any:
    config = _pg_config(SCHEMA)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
    try:
        return client.migrate()
    finally:
        provider.close()


def _history(admin: PostgreSqlProvider) -> Any:
    return admin.execute_query(
        f'SELECT version, success FROM "{SCHEMA}"."dblift_schema_history" '
        "ORDER BY installed_rank"
    )


def test_copy_from_stdin_block_loads_rows(pg_schema, tmp_path) -> None:
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(migrations_dir, "1", "copy_data", COPY_MIGRATION)

    result = _migrate(migrations_dir)

    assert result.success, result.error_message
    rows = admin.execute_query(f'SELECT id, v FROM "{SCHEMA}"."t" ORDER BY id')
    assert rows == [
        {"id": 1, "v": "alpha"},
        {"id": 2, "v": None},
        {"id": 3, "v": "semi; DROP TABLE t;"},
    ]
    assert _history(admin) == [{"version": "1", "success": True}]


def test_copy_with_bad_data_records_failure_and_releases_lock(pg_schema, tmp_path) -> None:
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(migrations_dir, "1", "copy_data", COPY_MIGRATION)
    create_versioned_migration(
        migrations_dir,
        "2",
        "bad_copy",
        f'COPY "{SCHEMA}"."t" (id, v) FROM stdin;\n4\tok\nnotanint\tboom\n\\.\n',
    )

    result = _migrate(migrations_dir)

    assert not result.success
    assert "notanint" in (result.error_message or "")
    assert _history(admin) == [
        {"version": "1", "success": True},
        {"version": "2", "success": False},
    ]
    # The failed COPY rolled back as a whole: its good row is not loaded.
    rows = admin.execute_query(f'SELECT count(*) AS n FROM "{SCHEMA}"."t" WHERE id = 4')
    assert rows[0]["n"] == 0
    # The migration lock was released, so another session can take it at once.
    other = PostgreSqlProvider(_pg_config(SCHEMA))
    other.create_connection()
    try:
        assert other.acquire_migration_lock(SCHEMA, wait_timeout_seconds=1)
        other.release_migration_lock(SCHEMA)
    finally:
        other.close()
