"""End-to-end: ``SELECT ... INTO new_table`` runs as a statement.

It starts with ``SELECT`` but returns no rows, so running it through the
row-fetching query path failed with "This result object does not return
rows" — in SQL migrations and in Python migrations' ``context.execute()``.

Requires PostgreSQL on localhost:5432 (postgres/postgres, db testdb) and SQL
Server on localhost:1433 (sa); each test creates and drops its own schema or
database.
"""

import uuid
from pathlib import Path
from typing import Any

import pymssql
import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.sqlserver.config import SqlServerConfig
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_migration

pytestmark = pytest.mark.integration

MSSQL_PASSWORD = "YourStrong@Passw0rd"

PYTHON_MIGRATION = """
def migrate(context):
    context.execute("SELECT id INTO {target} FROM {source}")
"""


def _migrate(config: DbliftConfig, migrations_dir: Path) -> Any:
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
    try:
        return client.migrate()
    finally:
        provider.close()


def _write_migrations(migrations_dir: Path, source: str, sql_target: str, py_target: str) -> None:
    create_migration(
        migrations_dir,
        "V1__source.sql",
        f"CREATE TABLE {source} (id INT);\nINSERT INTO {source} VALUES (1), (2);\n",
    )
    create_migration(
        migrations_dir,
        "V2__select_into.sql",
        f"-- copy the rows\nSELECT id INTO {sql_target} FROM {source};\n",
    )
    create_migration(
        migrations_dir,
        "V3__select_into.py",
        PYTHON_MIGRATION.format(target=py_target, source=source),
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
    schema = f"select_into_{uuid.uuid4().hex[:8]}"
    admin = PostgreSqlProvider(_pg_config("public"))
    admin.create_connection()
    admin.execute_statement(f"CREATE SCHEMA {schema}")
    try:
        yield admin, schema
    finally:
        admin.execute_statement(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        admin.close()


def test_postgresql_select_into(pg_schema, tmp_path) -> None:
    admin, schema = pg_schema
    migrations_dir = tmp_path / "migrations"
    _write_migrations(migrations_dir, f"{schema}.src", f"{schema}.sql_copy", f"{schema}.py_copy")

    result = _migrate(_pg_config(schema), migrations_dir)

    assert result.success, result.error_message
    for table in ("sql_copy", "py_copy"):
        rows = admin.execute_query(f"SELECT count(*) AS n FROM {schema}.{table}")
        assert rows[0]["n"] == 2


def _mssql(database: str) -> "pymssql.Connection":
    return pymssql.connect(
        server="localhost",
        port=1433,
        user="sa",
        password=MSSQL_PASSWORD,
        database=database,
        autocommit=True,
    )


@pytest.fixture
def mssql_database() -> Any:
    name = f"select_into_{uuid.uuid4().hex[:8]}"
    conn = _mssql("master")
    try:
        conn.cursor().execute(f"CREATE DATABASE [{name}]")
    finally:
        conn.close()
    try:
        yield name
    finally:
        conn = _mssql("master")
        try:
            conn.cursor().execute(
                f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE [{name}]"
            )
        finally:
            conn.close()


@pytest.mark.sqlserver
def test_sqlserver_select_into(mssql_database, tmp_path) -> None:
    migrations_dir = tmp_path / "migrations"
    _write_migrations(migrations_dir, "dbo.src", "dbo.sql_copy", "dbo.py_copy")
    config = DbliftConfig(
        database=SqlServerConfig(
            type="sqlserver",
            host="localhost",
            port=1433,
            database=mssql_database,
            username="sa",
            password=MSSQL_PASSWORD,
            schema="dbo",
            encrypt=False,
        )
    )

    result = _migrate(config, migrations_dir)

    assert result.success, result.error_message
    conn = _mssql(mssql_database)
    try:
        cur = conn.cursor()
        for table in ("sql_copy", "py_copy"):
            cur.execute(f"SELECT COUNT(*) FROM dbo.{table}")
            assert cur.fetchone()[0] == 2
    finally:
        conn.close()
