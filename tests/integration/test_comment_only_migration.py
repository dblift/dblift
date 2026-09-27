"""A migration file holding only comments is a successful no-op.

The PostgreSQL and MySQL splitters correctly find no statements in a
block-comment-only file, but the permissive fallback splitter then ran and
kept the ``*`` of the closing ``*/``, so the server received ``*`` and the
migration failed with a syntax error.
"""

import uuid
from pathlib import Path
from typing import Any

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.mysql.config import MySqlConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_versioned_migration

pytestmark = pytest.mark.integration

COMMENT_ONLY_SCRIPTS = [
    "/* just a comment */\n",
    "/* block comment */\n-- line comment\n",
    "-- only a line comment\n",
]


def _write_migrations(migrations_dir: Path) -> None:
    for index, sql in enumerate(COMMENT_ONLY_SCRIPTS, start=1):
        create_versioned_migration(migrations_dir, f"{index}.0.0", f"comment_only_{index}", sql)


def _assert_all_applied(client: DBLiftClient) -> None:
    result = client.migrate()

    assert result.success, result.error_message
    assert len(client.info().migrations_applied) == len(COMMENT_ONLY_SCRIPTS)


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


def test_postgresql_comment_only_migrations_succeed(tmp_path) -> None:
    schema = f"fix_comment_only_{uuid.uuid4().hex[:8]}"
    admin = PostgreSqlProvider(_pg_config("public"))
    admin.create_connection()
    admin.execute_statement(f'CREATE SCHEMA "{schema}"')
    migrations_dir = tmp_path / "migrations"
    _write_migrations(migrations_dir)
    config = _pg_config(schema)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    try:
        _assert_all_applied(
            DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
        )
    finally:
        provider.close()
        admin.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.close()


def test_mysql_comment_only_migrations_succeed(mysql_container: dict[str, Any], tmp_path) -> None:
    database = f"fix_comment_only_{uuid.uuid4().hex[:8]}"
    migrations_dir = tmp_path / "migrations"
    _write_migrations(migrations_dir)
    config = DbliftConfig(
        database=MySqlConfig(
            type="mysql",
            host=mysql_container["host"],
            port=mysql_container["port"],
            database=mysql_container["database"],
            username=mysql_container["username"],
            password=mysql_container["password"],
            schema=database,
        )
    )
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        provider.execute_statement(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        _assert_all_applied(
            DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
        )
    finally:
        provider.execute_statement(f"DROP DATABASE IF EXISTS `{database}`")
        provider.close()
