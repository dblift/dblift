"""Live PostgreSQL check: clean removes every kind of routine and range types.

Routine discovery used ``information_schema.routines``, which does not list
aggregates, so an aggregate survived a clean that reported success and the
next migrate failed with "already exists". Routines were also dropped by bare
name, so two overloads made each DROP ambiguous, and range types were missing
from the type query.
"""

from pathlib import Path
from typing import Any, Dict

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider

pytestmark = pytest.mark.integration

SCHEMA = "dblift_clean_routines"

MIGRATION = """
CREATE TYPE float_range AS RANGE (subtype = float8);
CREATE DOMAIN positive_int AS integer CHECK (VALUE > 0);
CREATE TYPE order_status AS ENUM ('new', 'paid');
CREATE TABLE orders (
    id positive_int PRIMARY KEY,
    status order_status NOT NULL,
    price_band float_range
);
CREATE AGGREGATE my_sum(integer) (SFUNC = int4pl, STYPE = integer);
CREATE AGGREGATE my_tally(*) (SFUNC = int8inc, STYPE = int8, INITCOND = '0');
CREATE FUNCTION overloaded(a integer) RETURNS integer LANGUAGE sql AS 'SELECT 1';
CREATE FUNCTION overloaded(b text) RETURNS integer LANGUAGE sql AS 'SELECT 2';
CREATE PROCEDURE bump(INOUT n integer) LANGUAGE plpgsql AS 'BEGIN n := n + 1; END';
CREATE EXTENSION IF NOT EXISTS moddatetime SCHEMA dblift_clean_routines;
"""


def _config(schema: str) -> DbliftConfig:
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
def admin() -> Any:
    provider = PostgreSqlProvider(_config("public"))
    provider.create_connection()
    provider.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    provider.execute_statement(f'CREATE SCHEMA "{SCHEMA}"')
    try:
        yield provider
    finally:
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        provider.close()


def _object_counts(admin: PostgreSqlProvider) -> Dict[str, int]:
    rows = admin.execute_query(
        """
        SELECT
            (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
              WHERE n.nspname = ?) AS routines,
            (SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
              WHERE n.nspname = ?) AS types,
            (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = ?) AS relations
        """,
        [SCHEMA, SCHEMA, SCHEMA],
    )
    return {key: int(value) for key, value in rows[0].items()}


def _client(tmp_path: Path) -> Any:
    migrations = tmp_path / "migrations"
    migrations.mkdir(exist_ok=True)
    (migrations / "V1__objects.sql").write_text(MIGRATION)
    provider = PostgreSqlProvider(_config(SCHEMA))
    return provider, DBLiftClient(provider=provider, migrations_dir=migrations)


def test_clean_empties_schema_and_migrate_runs_again(admin, tmp_path) -> None:
    provider, client = _client(tmp_path)
    try:
        migrated = client.migrate()
        assert migrated.success is True, migrated.error_message
        before = _object_counts(admin)
        assert before["routines"] > 0 and before["types"] > 0

        preview = {(o.object_type, o.name) for o in provider.list_droppable_objects(SCHEMA)}
        routines = {(kind, name) for kind, name in preview if "(" in name}
        # Extension members and range constructors go with their owner.
        assert routines == {
            ("aggregate", "my_sum(integer)"),
            ("aggregate", "my_tally(*)"),
            ("function", "overloaded(a integer)"),
            ("function", "overloaded(b text)"),
            ("procedure", "bump(INOUT n integer)"),
        }
        assert ("type", "float_range") in preview

        result = client.clean(clean_enabled=True)

        assert result.success is True, result.error_message
        assert result.get_objects_by_type()["function"] == {
            "overloaded(a integer)",
            "overloaded(b text)",
        }
        assert _object_counts(admin) == {"routines": 0, "types": 0, "relations": 0}

        assert client.migrate().success is True
    finally:
        provider.close()
