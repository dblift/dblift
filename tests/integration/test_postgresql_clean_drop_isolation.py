"""Live PostgreSQL check: one failing DROP must not cancel the rest of clean.

PostgreSQL aborts the whole transaction on any statement error, so before
per-drop isolation a single undroppable object turned ``clean`` into a total
no-op — every later DROP failed with ``InFailedSqlTransaction``, including
dblift's own ``dblift_schema_history`` and ``dblift_migration_lock`` tables,
leaving a schema that could not be cleaned again without manual repair.

The undroppable object here is a contrib extension installed into the test
schema by the superuser: ``DROP EXTENSION`` requires extension ownership,
which the schema owner does not have. Nothing about the failure is specific
to extensions — a permission-denied table or an unsupported drop verb aborts
the transaction the same way — but it is the cheapest failure that stock
PostgreSQL reproduces, and clean enumerates extensions first, so every other
object in the schema is downstream of it.
"""

from typing import Any, List

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider

pytestmark = pytest.mark.integration

SCHEMA = "dblift_clean_iso"
ROLE = "dblift_clean_iso"
EXTENSION = "moddatetime"


def _config(username: str, password: str, schema: str) -> DbliftConfig:
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


def _drop_fixture(admin: PostgreSqlProvider) -> None:
    admin.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    admin.execute_statement(f'DROP OWNED BY "{ROLE}" CASCADE')
    admin.execute_statement(f'DROP ROLE IF EXISTS "{ROLE}"')


@pytest.fixture
def failing_drop_schema() -> Any:
    """A schema whose first enumerated object cannot be dropped by its owner."""
    admin = PostgreSqlProvider(_config("postgres", "postgres", "public"))
    admin.create_connection()

    admin.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    admin.execute_statement(f'DROP ROLE IF EXISTS "{ROLE}"')
    admin.execute_statement(f"CREATE ROLE \"{ROLE}\" LOGIN PASSWORD '{ROLE}'")
    admin.execute_statement(f'CREATE SCHEMA "{SCHEMA}" AUTHORIZATION "{ROLE}"')
    # Owned by postgres, so the schema owner cannot drop it. Enumerated first.
    admin.execute_statement(f'CREATE EXTENSION "{EXTENSION}" SCHEMA "{SCHEMA}"')
    # Relations: the schema owner may drop these even though postgres owns
    # them, so each one is a drop that *should* still happen after the failure.
    admin.execute_statement(f'CREATE TABLE "{SCHEMA}"."app_users" (id int PRIMARY KEY)')
    admin.execute_statement(
        f'CREATE TABLE "{SCHEMA}"."dblift_schema_history" (installed_rank int PRIMARY KEY)'
    )
    admin.execute_statement(
        f'CREATE TABLE "{SCHEMA}"."dblift_migration_lock" (lock_name varchar(255) PRIMARY KEY)'
    )
    admin.execute_statement(
        f'CREATE VIEW "{SCHEMA}"."app_users_v" AS SELECT id FROM "{SCHEMA}"."app_users"'
    )

    try:
        yield admin
    finally:
        _drop_fixture(admin)
        admin.close()


def _relations(admin: PostgreSqlProvider) -> List[str]:
    rows = admin.execute_query(
        """
        SELECT c.relname AS name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = ?
          AND c.relkind IN ('r', 'v', 'm', 'S', 'p')
        ORDER BY c.relname
        """,
        [SCHEMA],
    )
    return [row["name"] for row in rows]


def _extensions(admin: PostgreSqlProvider) -> List[str]:
    rows = admin.execute_query(
        """
        SELECT e.extname AS name
        FROM pg_extension e
        JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE n.nspname = ?
        """,
        [SCHEMA],
    )
    return [row["name"] for row in rows]


def _clean_as_schema_owner(tmp_path: Any) -> Any:
    provider = PostgreSqlProvider(_config(ROLE, ROLE, SCHEMA))
    client = DBLiftClient(provider=provider, migrations_dir=tmp_path)
    try:
        return client.clean(clean_enabled=True)
    finally:
        provider.close()


def test_one_failing_drop_does_not_cancel_the_others(failing_drop_schema, tmp_path) -> None:
    """Every droppable relation is gone even though the first drop failed."""
    admin = failing_drop_schema
    assert sorted(_relations(admin)) == [
        "app_users",
        "app_users_v",
        "dblift_migration_lock",
        "dblift_schema_history",
    ]

    _clean_as_schema_owner(tmp_path)

    assert _relations(admin) == []


def test_dblift_tracking_tables_are_dropped(failing_drop_schema, tmp_path) -> None:
    """History and lock tables must not survive an unrelated object's failure."""
    admin = failing_drop_schema

    _clean_as_schema_owner(tmp_path)

    remaining = _relations(admin)
    assert "dblift_schema_history" not in remaining
    assert "dblift_migration_lock" not in remaining


def test_clean_still_reports_failure(failing_drop_schema, tmp_path) -> None:
    """A partial clean is a failure — the undroppable object is still there."""
    admin = failing_drop_schema

    result = _clean_as_schema_owner(tmp_path)

    assert result.success is False
    assert _extensions(admin) == [EXTENSION]
