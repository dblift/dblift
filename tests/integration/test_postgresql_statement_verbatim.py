"""End-to-end proof: a migration's SQL reaches PostgreSQL exactly as written.

The statement splitter used to reassemble a statement by joining token text
with heuristic spacing instead of slicing the original source. Two adjacent
string literals ('a ' 'b') are one PostgreSQL literal by concatenation; the
join dropped the whitespace between them and produced a different string
than ``psql`` would store for the identical file.

Requires PostgreSQL on localhost:5432 (same server as
tests/integration/test_postgresql_native.py / test_autocommit_ddl_execution.py).
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

SCHEMA = "verbatim_stmt_test"


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


def test_comment_on_with_adjacent_string_literals_stores_correct_text(pg_schema, tmp_path) -> None:
    """Standard SQL concatenates two adjacent string literals separated only
    by whitespace; losing that whitespace turns 'first part ' 'second part'
    into the single literal "first part 'second part" instead of
    "first part second part"."""
    admin = pg_schema
    migrations_dir = tmp_path / "migrations"
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "commented_table",
        f'CREATE TABLE "{SCHEMA}"."t" (id INT);\n'
        f'COMMENT ON TABLE "{SCHEMA}"."t" IS \'first part \'\n'
        "    'second part';\n",
    )

    result = _migrate(migrations_dir)

    assert result.success, result.error_message
    rows = admin.execute_query(f'SELECT obj_description(\'"{SCHEMA}"."t"\'::regclass) AS c')
    assert rows[0]["c"] == "first part second part"


def test_with_delete_returning_insert_writes_correct_row(pg_schema) -> None:
    """A CTE feeding DELETE ... RETURNING into INSERT must not gain spaces
    around operators like ``||`` and ``=`` — PostgreSQL lexes operator runs
    greedily, so an inserted or dropped space changes meaning.

    Executed through ``StatementSplitter`` + the provider directly (not the
    full ``migrate()`` path): a CTE-prefixed INSERT is a separate, pre-existing
    statement-type misclassification in ``SqlAnalyzer`` unrelated to this fix,
    and is not what this test is proving.
    """
    from dblift.core.migration.sql.statement_splitter import StatementSplitter

    admin = pg_schema
    admin.execute_statement(f'CREATE TABLE "{SCHEMA}"."src" (id INT PRIMARY KEY)')
    admin.execute_statement(f'CREATE TABLE "{SCHEMA}"."app_logs" (msg TEXT)')
    admin.execute_statement(f'INSERT INTO "{SCHEMA}"."src" VALUES (1)')

    sql = (
        f'WITH deleted AS (DELETE FROM "{SCHEMA}"."src" WHERE id = 1 RETURNING id)\n'
        f'INSERT INTO "{SCHEMA}"."app_logs"(msg) SELECT \'removed \' || id FROM deleted;\n'
    )
    statements = StatementSplitter("postgresql").split_statements(sql)
    assert len(statements) == 1
    for stmt in statements:
        admin.execute_statement(stmt)

    rows = admin.execute_query(f'SELECT msg FROM "{SCHEMA}"."app_logs"')
    assert rows == [{"msg": "removed 1"}]
    rows = admin.execute_query(f'SELECT count(*) AS n FROM "{SCHEMA}"."src"')
    assert rows[0]["n"] == 0
