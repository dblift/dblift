"""PostgreSQL native-provider smoke tests."""

import uuid

import pytest

from api import DBLiftClient
from config import DbliftConfig
from config._subclasses.postgresql_config import PostgreSqlConfig
from core.sql_model.base import ConstraintType
from db.provider_registry import ProviderRegistry
from db.sqlalchemy_provider import SqlAlchemyProvider
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
    monkeypatch.setattr("core.licensing._guard._refresh_state", lambda: None)
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


def test_postgresql_native_introspects_tables_without_jdbc_metadata() -> None:
    """PostgreSQL native introspection uses SQLAlchemy metadata, not getMetaData()."""
    from core.introspection.introspector_factory import IntrospectorFactory

    schema = f"dblift_native_{uuid.uuid4().hex[:8]}"
    provider = ProviderRegistry.create_provider(_postgres_config(schema))

    provider.create_connection()
    try:
        provider.execute_statement(f'CREATE SCHEMA "{schema}"')
        provider.execute_statement(
            f'CREATE TABLE "{schema}"."users" ('
            "id INT PRIMARY KEY, "
            "email TEXT NOT NULL UNIQUE)"
        )
        provider.execute_statement(
            f'CREATE TABLE "{schema}"."user_events" ('
            "id INT PRIMARY KEY, "
            f'user_id INT REFERENCES "{schema}"."users"(id) '
            "ON DELETE CASCADE ON UPDATE SET NULL)"
        )
        provider.execute_statement(
            f'CREATE TABLE "{schema}"."accounts" ('
            "id INT, "
            "status TEXT NOT NULL, "
            "deleted_at TIMESTAMP NULL, "
            'CONSTRAINT "accounts_custom_pk" PRIMARY KEY (id), '
            "CONSTRAINT \"accounts_status_check\" CHECK (status IN ('active', 'disabled')))"
        )
        provider.execute_statement(
            f'CREATE SEQUENCE "{schema}"."event_seq" INCREMENT BY 10 CACHE 5'
        )
        provider.execute_statement(
            f'CREATE TABLE "{schema}"."dblift_schema_history" (installed_rank INT PRIMARY KEY)'
        )
        provider.execute_statement(f'CREATE INDEX "idx_users_email" ON "{schema}"."users" (email)')
        provider.execute_statement(
            f'CREATE INDEX "idx_accounts_active" ON "{schema}"."accounts" (status) '
            "WHERE deleted_at IS NULL"
        )
        provider.execute_statement(
            f'CREATE VIEW "{schema}"."user_view" AS SELECT id FROM "{schema}"."users"'
        )
        provider.execute_statement(
            f'CREATE FUNCTION "{schema}"."add_one"(value integer) '
            "RETURNS integer LANGUAGE SQL AS $$ SELECT value + 1 $$"
        )
        provider.execute_statement(
            f'CREATE FUNCTION "{schema}"."user_events_touch"() '
            "RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$"
        )
        provider.execute_statement(
            f'CREATE TRIGGER "user_events_before_insert" BEFORE INSERT '
            f'ON "{schema}"."user_events" FOR EACH ROW '
            f'EXECUTE FUNCTION "{schema}"."user_events_touch"()'
        )
        provider.execute_statement(
            f'CREATE PROCEDURE "{schema}"."touch_event"() '
            "LANGUAGE plpgsql AS $$ BEGIN NULL; END $$"
        )

        introspector = IntrospectorFactory.create(provider)
        tables = introspector.get_tables(schema, table_pattern="user%")
        account_tables = introspector.get_tables(schema, table_pattern="accounts")
        account_indexes = introspector.get_indexes(schema, "accounts")
        all_tables = introspector.get_tables(schema, include_views=True)
        snapshot = introspector.introspect_schema(schema)

        users = next(table for table in tables if table.name == "users")
        accounts = account_tables[0]
        columns = {column.name: column for column in users.columns}
        constraint_types = {constraint.constraint_type for constraint in users.constraints}
        account_constraints = {constraint.name: constraint for constraint in accounts.constraints}
        event_constraints = {
            constraint.constraint_type
            for table in tables
            if table.name == "user_events"
            for constraint in table.constraints
        }
        event_fk = next(
            constraint
            for table in tables
            if table.name == "user_events"
            for constraint in table.constraints
            if constraint.constraint_type == ConstraintType.FOREIGN_KEY
        )
        assert columns["id"].is_primary_key is True
        assert columns["email"].nullable is False
        assert ConstraintType.PRIMARY_KEY in constraint_types
        assert ConstraintType.UNIQUE in constraint_types
        assert (
            account_constraints["accounts_custom_pk"].constraint_type == ConstraintType.PRIMARY_KEY
        )
        assert account_constraints["accounts_status_check"].constraint_type == ConstraintType.CHECK
        assert "status" in (account_constraints["accounts_status_check"].check_expression or "")
        assert ConstraintType.FOREIGN_KEY in event_constraints
        assert event_fk.reference_schema == schema
        assert event_fk.on_delete == "CASCADE"
        assert event_fk.on_update == "SET NULL"
        assert {table.name for table in tables} == {"users", "user_events"}
        assert "dblift_schema_history" not in {table.name for table in all_tables}
        assert "user_view" in {table.name for table in all_tables}
        assert [index.name for index in snapshot["indexes"]["users"]] == ["idx_users_email"]
        assert len(account_indexes) == 1
        assert account_indexes[0].name == "idx_accounts_active"
        assert account_indexes[0].type == "BTREE"
        assert account_indexes[0].condition == "deleted_at IS NULL"
        assert snapshot["views"][0].name == "user_view"
        assert "SELECT" in snapshot["views"][0].query.upper()
        sequence = snapshot["sequences"][0]
        assert sequence.name == "event_seq"
        assert sequence.increment_by == 10
        assert sequence.cache == 5
        assert {trigger.name for trigger in snapshot["triggers"]} == {"user_events_before_insert"}
        assert {procedure.name for procedure in snapshot["procedures"]} == {"touch_event"}
        function_names = {function.name for function in snapshot["functions"]}
        assert {"add_one", "user_events_touch"}.issubset(function_names)
    finally:
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        provider.close()
