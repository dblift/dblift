"""End-to-end: a committed migration creating quoted-name tables stays green.

The engine used to probe each created table with a ``SELECT`` after the
commit. It read the table name with a ``\\w+`` regex, so ``"s"."Wide Rows"``
was probed as ``"s"."Wide"``. The probe failed, which on PostgreSQL aborted
the transaction it had opened: the migration was committed and recorded as a
success, but the migration-lock release then failed and ``migrate`` reported
a failure. The probe was removed.

Requires PostgreSQL on localhost:5432 (same server as
tests/integration/test_postgresql_copy_from_stdin.py).
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

SCHEMA = "post_commit_quoted"
# A quoted schema, created by the migration itself, as pg_dump writes it.
DUMP_SCHEMA = "Post Commit Dump"


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
    for name in (SCHEMA, DUMP_SCHEMA):
        admin.execute_statement(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
    admin.execute_statement(f'CREATE SCHEMA "{SCHEMA}"')
    try:
        yield admin
    finally:
        for name in (SCHEMA, DUMP_SCHEMA):
            admin.execute_statement(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
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


def _assert_green(admin: PostgreSqlProvider, result: Any, versions: list) -> None:
    assert result.success, result.error_message
    history = admin.execute_query(
        f'SELECT version, success FROM "{SCHEMA}"."dblift_schema_history" '
        "ORDER BY installed_rank"
    )
    assert history == [{"version": v, "success": True} for v in versions]
    # The migration lock was released, so another session can take it at once.
    other = PostgreSqlProvider(_pg_config(SCHEMA))
    other.create_connection()
    try:
        assert other.acquire_migration_lock(SCHEMA, wait_timeout_seconds=1)
        other.release_migration_lock(SCHEMA)
    finally:
        other.close()


def test_quoted_table_names_with_non_word_characters(pg_schema, tmp_path) -> None:
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1",
        "pg_dump",
        "SELECT pg_catalog.set_config('search_path', '', false);\n"
        f'CREATE SCHEMA "{DUMP_SCHEMA}";\n'
        f'CREATE TABLE "{SCHEMA}"."Wide Rows" (id integer NOT NULL);\n'
        f'CREATE TABLE "{SCHEMA}"."Child-Rows" (id integer);\n'
        f'CREATE TABLE "{SCHEMA}"."Ünïcode" (id integer);\n'
        f'CREATE TABLE "{DUMP_SCHEMA}"."Wide Rows" (id integer);\n',
    )
    # A later migration must run on the same connection without error.
    create_versioned_migration(
        migrations_dir, "2", "insert", f'INSERT INTO "{SCHEMA}"."Wide Rows" VALUES (1);\n'
    )

    result = _migrate(migrations_dir)

    _assert_green(admin, result, ["1", "2"])
    rows = admin.execute_query(f'SELECT count(*) AS n FROM "{SCHEMA}"."Wide Rows"')
    assert rows[0]["n"] == 1


def test_table_dropped_in_the_same_migration(pg_schema, tmp_path) -> None:
    """A table created and dropped by one migration is gone at commit time;
    nothing after the commit may touch it and abort the next transaction."""
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1",
        "create_and_drop",
        f'CREATE TABLE "{SCHEMA}"."scratch" (id integer);\n' f'DROP TABLE "{SCHEMA}"."scratch";\n',
    )
    create_versioned_migration(
        migrations_dir, "2", "create", f'CREATE TABLE "{SCHEMA}"."kept" (id integer);\n'
    )

    result = _migrate(migrations_dir)

    _assert_green(admin, result, ["1", "2"])
