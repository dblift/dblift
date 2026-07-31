"""Live check: statements the policy flags as non-transactional really run outside a transaction.

``TransactionPolicy`` already decides that e.g. ``CREATE INDEX CONCURRENTLY``
must not be wrapped in a migration transaction, and the engine logs that it is
skipping the transaction. That decision was never carried through to the
driver: SQLAlchemy's default isolation level leaves the DBAPI connection with
``autocommit=False``, so psycopg opens a transaction block for the statement
anyway and PostgreSQL rejects it with *"CREATE INDEX CONCURRENTLY cannot run
inside a transaction block"*. Committing after the statement — which is what
``SqlAlchemyProvider.execute_statement`` does — is too late; the statement has
already been sent inside a block.

These tests assert database state after a real ``migrate()``, not that some
method was called: a mock-based test passes whether or not the statement ever
reaches the server outside a transaction, which is exactly how this survived.

Requires PostgreSQL on localhost:5432; the fixture provisions its own role and
schema and drops both afterwards.
"""

from pathlib import Path
from typing import Any, List

import pytest

from api import DBLiftClient
from config import DbliftConfig
from db.plugins.postgresql.config import PostgreSqlConfig
from db.plugins.postgresql.provider import PostgreSqlProvider
from db.plugins.sqlite.config import SQLiteConfig
from db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_versioned_migration

pytestmark = pytest.mark.integration

SCHEMA = "ac_test"
ROLE = "ac_test"


def _pg_config(username: str, password: str, schema: str) -> DbliftConfig:
    return DbliftConfig(
        database=PostgreSqlConfig(
            type="postgresql",
            host="localhost",
            port=5432,
            database="testdb",
            username=username,
            password=password,
            schema=schema,
        )
    )


@pytest.fixture
def pg_schema() -> Any:
    """An empty schema owned by a dedicated login role, dropped again afterwards.

    The role is created once and left in place: it is a privilege-less login
    role, and dropping it would need every grant it ever received revoked first.
    The schema — everything the tests actually observe — is recreated per test.
    """
    admin = PostgreSqlProvider(_pg_config("postgres", "postgres", "public"))
    admin.create_connection()
    admin.execute_statement(
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN "
        f"CREATE ROLE \"{ROLE}\" LOGIN PASSWORD '{ROLE}'; "
        f"END IF; END $$"
    )
    admin.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    admin.execute_statement(f'CREATE SCHEMA "{SCHEMA}" AUTHORIZATION "{ROLE}"')
    try:
        yield admin
    finally:
        admin.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        admin.close()


def _tables(admin: PostgreSqlProvider) -> List[str]:
    rows = admin.execute_query(
        "SELECT tablename AS name FROM pg_tables WHERE schemaname = ? ORDER BY tablename",
        [SCHEMA],
    )
    return [row["name"] for row in rows]


def _indexes(admin: PostgreSqlProvider) -> List[str]:
    rows = admin.execute_query(
        "SELECT indexname AS name FROM pg_indexes WHERE schemaname = ? ORDER BY indexname",
        [SCHEMA],
    )
    return [row["name"] for row in rows]


def _migrate_as_schema_owner(migrations_dir: Path) -> Any:
    config = _pg_config(ROLE, ROLE, SCHEMA)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
    try:
        return client.migrate()
    finally:
        provider.close()


def test_create_index_concurrently_migration_succeeds(pg_schema, tmp_path) -> None:
    """A statement flagged non-transactional must reach the server outside a transaction."""
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_docs",
        f'CREATE TABLE "{SCHEMA}"."docs" (id INT PRIMARY KEY, body TEXT);',
    )
    create_versioned_migration(
        migrations_dir,
        "2.0.0",
        "index_docs",
        f'CREATE INDEX CONCURRENTLY "ix_docs_body" ON "{SCHEMA}"."docs" (body);',
    )

    result = _migrate_as_schema_owner(migrations_dir)

    assert result.success, result.error_message
    assert "ix_docs_body" in _indexes(admin)


def test_failed_autocommit_migration_still_records_failure_history(pg_schema, tmp_path) -> None:
    """A flagged migration failing mid-way still gets its failure row in history.

    The autocommit switch is scoped to each statement, so by the time the
    failure handler opens its history transaction the session is back at its
    normal isolation level — the failure record rides a real transaction, not
    a driver-specific tolerance for ``begin()`` under autocommit.
    """
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_docs",
        f'CREATE TABLE "{SCHEMA}"."docs" (id INT PRIMARY KEY, body TEXT);',
    )
    create_versioned_migration(
        migrations_dir,
        "2.0.0",
        "index_then_fail",
        f'CREATE INDEX CONCURRENTLY "ix_ok" ON "{SCHEMA}"."docs" (body);\n'
        f'CREATE INDEX CONCURRENTLY "ix_bad" ON "{SCHEMA}"."nonexistent_table" (col);',
    )

    result = _migrate_as_schema_owner(migrations_dir)

    assert result.success is False
    assert "ix_ok" in _indexes(admin)  # per-statement commit: the first one stays
    history = admin.execute_query(
        f'SELECT script, success FROM "{SCHEMA}"."dblift_schema_history" ORDER BY installed_rank'
    )
    by_script = {row["script"]: row["success"] for row in history}
    assert by_script.get("V2_0_0__index_then_fail.sql") is False


def test_ordinary_ddl_still_rolls_back_on_failure(pg_schema, tmp_path) -> None:
    """A migration with no flagged statement keeps its all-or-nothing guarantee."""
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "half_applied",
        f'CREATE TABLE "{SCHEMA}"."first_table" (id INT);\n'
        f'CREATE TABLE "{SCHEMA}"."first_table" (id INT);',
    )

    result = _migrate_as_schema_owner(migrations_dir)

    assert result.success is False
    assert "first_table" not in _tables(admin)


def test_transactional_guarantee_survives_an_earlier_autocommit_migration(
    pg_schema, tmp_path
) -> None:
    """Running one migration in autocommit must not leave the session autocommitting.

    Without restoring the connection afterwards the *next* migration silently
    loses its rollback: its first statement stays committed after the second
    one fails.
    """
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_docs",
        f'CREATE TABLE "{SCHEMA}"."docs" (id INT PRIMARY KEY, body TEXT);',
    )
    create_versioned_migration(
        migrations_dir,
        "2.0.0",
        "index_docs",
        f'CREATE INDEX CONCURRENTLY "ix_docs_body" ON "{SCHEMA}"."docs" (body);',
    )
    create_versioned_migration(
        migrations_dir,
        "3.0.0",
        "half_applied",
        f'CREATE TABLE "{SCHEMA}"."later_table" (id INT);\n'
        f'CREATE TABLE "{SCHEMA}"."later_table" (id INT);',
    )

    result = _migrate_as_schema_owner(migrations_dir)

    assert result.success is False
    assert "ix_docs_body" in _indexes(admin)
    assert "later_table" not in _tables(admin)


def test_dialect_without_non_transactional_patterns_is_unaffected(tmp_path) -> None:
    """SQLite declares no non-transactional patterns; its rollback must be untouched."""
    db_path = tmp_path / "ac_test.db"
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_docs",
        "CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT);",
    )
    create_versioned_migration(
        migrations_dir,
        "2.0.0",
        "half_applied",
        "CREATE TABLE later_table (id INTEGER);\nCREATE TABLE later_table (id INTEGER);",
    )

    config = DbliftConfig(database=SQLiteConfig(type="sqlite", path=str(db_path)))
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
    try:
        result = client.migrate()

        assert result.success is False
        names = {
            row["name"]
            for row in provider.execute_query("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert "docs" in names
        assert "later_table" not in names
    finally:
        provider.close()
