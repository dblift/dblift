"""PostgreSQL native-provider smoke tests."""

import uuid

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider
from tests.integration.helpers.migration_helper import (
    create_repeatable_migration,
    create_versioned_migration,
)

pytestmark = pytest.mark.integration


def _postgres_config(schema: str) -> DbliftConfig:
    database = PostgreSqlConfig(
        type="postgresql",
        host="localhost",
        port=5432,
        database="testdb",
        username="postgres",
        password="postgres",
        schema=schema,
    )
    return DbliftConfig(database=database)


def test_postgresql_provider_is_native_sqlalchemy() -> None:
    """The PostgreSQL plugin resolves to a native SQLAlchemy provider."""
    config = _postgres_config("test_schema")

    provider = ProviderRegistry.create_provider(config)

    assert isinstance(provider, SqlAlchemyProvider)
    assert not hasattr(provider, "jvm_manager")


def test_postgresql_native_roundtrip() -> None:
    """PostgreSQL executes SQL through SQLAlchemy without JDBC/JVM."""
    schema = f"dblift_native_{uuid.uuid4().hex[:8]}"
    table = "roundtrip"
    provider = ProviderRegistry.create_provider(_postgres_config(schema))

    provider.create_connection()
    try:
        provider.execute_statement(f'CREATE SCHEMA "{schema}"')
        provider.execute_statement(
            f'CREATE TABLE "{schema}"."{table}" (id INT PRIMARY KEY, n TEXT)'
        )
        provider.execute_statement(f'INSERT INTO "{schema}"."{table}" VALUES (1, \'x\')')

        rows = provider.execute_query(f'SELECT n FROM "{schema}"."{table}" WHERE id = 1')

        assert rows == [{"n": "x"}]
    finally:
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        provider.close()


def test_postgresql_native_records_multiple_migrations() -> None:
    """PostgreSQL assigns distinct history ranks for consecutive migrations."""
    schema = f"dblift_native_{uuid.uuid4().hex[:8]}"
    provider = ProviderRegistry.create_provider(_postgres_config(schema))

    provider.create_connection()
    try:
        provider.create_schema_if_not_exists(schema)
        provider.record_migration(schema, {"version": "1", "script": "V1__one.sql"})
        provider.record_migration(schema, {"version": "2", "script": "V2__two.sql"})

        rows = provider.get_applied_migrations(schema)

        assert [row["installed_rank"] for row in rows] == [1, 2]
        assert [row["script"] for row in rows] == ["V1__one.sql", "V2__two.sql"]
    finally:
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        provider.close()


def test_postgresql_native_migrate_applies_versioned_and_repeatable(monkeypatch, tmp_path) -> None:
    """PostgreSQL migrate uses the native provider for versioned and repeatable scripts."""
    schema = f"dblift_native_{uuid.uuid4().hex[:8]}"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()

    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_products",
        f"""
        CREATE SCHEMA IF NOT EXISTS "{schema}";
        CREATE TABLE "{schema}"."products" (
            id INT PRIMARY KEY,
            name TEXT NOT NULL
        );
        """,
    )
    create_repeatable_migration(
        migrations_dir,
        "create_product_view",
        f"""
        CREATE OR REPLACE VIEW "{schema}"."product_names" AS
        SELECT name FROM "{schema}"."products";
        """,
    )

    config = _postgres_config(schema)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

    try:
        provider.create_connection()
        provider.create_schema_if_not_exists(schema)
        result = client.migrate()

        assert result.success, result.error_message
        error_message = result.error_message or ""
        assert "jpype" not in error_message.lower()
        assert "jvm" not in error_message.lower()
        assert "jpype" not in str(result.migrations_applied).lower()
        assert "jvm" not in str(result.migrations_applied).lower()
        assert not hasattr(provider, "jvm_manager")

        tables = provider.execute_query(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :schema
            ORDER BY table_name
            """,
            {"schema": schema},
        )
        applied = provider.get_applied_migrations(schema)

        assert {row["table_name"] for row in tables} >= {
            "dblift_schema_history",
            "products",
            "product_names",
        }
        assert [row["script"] for row in applied] == [
            "V1_0_0__create_products.sql",
            "R__create_product_view.sql",
        ]
    finally:
        provider.create_connection()
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        provider.close()
