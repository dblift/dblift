"""SQL Server DEFAULT_SCHEMA is catalog-level login state, not connection-scoped.

Every other supported dialect's ``set_current_schema`` mechanism (PostgreSQL's
``SET search_path``, MySQL's ``USE``, Oracle's ``ALTER SESSION SET
CURRENT_SCHEMA``, DB2's ``SET SCHEMA``) dies with the connection. SQL Server's
``ALTER USER ... WITH DEFAULT_SCHEMA`` does not: it is a persistent property of
the *login* (``sys.database_principals``), visible to and overwritable by any
other connection authenticating as that same login.

``--db-schema`` is one fixed value for an entire dblift process run, so after
the first ``set_current_schema`` call, every later call (i.e. every subsequent
statement in a migration script) asks for the *same* schema again. These tests
exercise that steady state against a REAL second connection to the same live
SQL Server login — not a mock — to confirm a concurrent process silently
overwriting DEFAULT_SCHEMA between two identical calls is actually detected
(issue #806 review follow-up: the first cut of this fix only re-read the
catalog when the requested schema itself changed, so it never noticed
interference in exactly this steady-state scenario).

Prerequisites: a running SQL Server instance reachable at localhost:1433 with
the ``dblift_test`` login (see tests/integration/conftest.py's db_configs for
the general-purpose container fixtures; this module connects directly with
dblift_test's own credentials rather than the shared ``sa`` fixture so it
doesn't depend on how that container happened to be provisioned).
"""

import uuid

import pymssql
import pytest

from dblift.config.dblift_config import DbliftConfig
from dblift.db.plugins.sqlserver.config import SqlServerConfig
from dblift.db.plugins.sqlserver.provider import SqlServerProvider
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider

pytestmark = [pytest.mark.integration, pytest.mark.sqlserver]

HOST = "localhost"
PORT = 1433
DATABASE = "dblift_test"
USERNAME = "dblift_test"
PASSWORD = "Dblift_Test1!"


def _config(schema: str) -> DbliftConfig:
    database = SqlServerConfig(
        type="sqlserver",
        url=f"mssql+pymssql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}?encryption=off",
        schema=schema,
    )
    return DbliftConfig(database=database)


def _second_login_connection() -> "pymssql.Connection":
    """A REAL, independent second connection to the same login.

    Simulates a concurrent dblift process sharing this login with a
    different ``--db-schema`` — exactly the scenario the interference check
    exists to catch.
    """
    return pymssql.connect(
        server=HOST,
        port=PORT,
        user=USERNAME,
        password=PASSWORD,
        database=DATABASE,
        autocommit=True,
    )


@pytest.fixture
def provider():
    """A connected, native ``SqlServerProvider`` against the live container.

    Restores the login's DEFAULT_SCHEMA to whatever it was before the test
    and drops any schema this test created, so concurrent test runs / other
    agents sharing this login and container are not disturbed.
    """
    p = ProviderRegistry.create_provider(_config("dbo"))
    assert isinstance(p, SqlServerProvider)
    p.create_connection()

    original_rows = p.execute_query(
        "SELECT DEFAULT_SCHEMA_NAME AS s FROM sys.database_principals WHERE name = ?",
        [USERNAME],
    )
    original_default_schema = original_rows[0]["s"] if original_rows else "dbo"

    created_schemas: list[str] = []
    p.created_schemas = created_schemas  # type: ignore[attr-defined]

    try:
        yield p
    finally:
        try:
            p.execute_statement(
                f"ALTER USER [{USERNAME}] WITH DEFAULT_SCHEMA = [{original_default_schema}]"
            )
            for schema in created_schemas:
                rows = p.execute_query(
                    "SELECT t.name AS n FROM sys.tables t "
                    "JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE s.name = ?",
                    [schema],
                )
                for row in rows:
                    p.execute_statement(f"DROP TABLE [{schema}].[{row['n']}]")
                p.execute_statement(
                    f"IF EXISTS (SELECT 1 FROM sys.schemas WHERE name = '{schema}') "
                    f"EXEC('DROP SCHEMA [{schema}]')"
                )
        finally:
            p.close()


def _unique_schema(label: str) -> str:
    return f"sqltest_{label}_{uuid.uuid4().hex[:8]}"


def test_detects_interference_from_a_real_second_connection_with_unchanged_target_schema(
    provider,
):
    """Steady-state reuse against a REAL second connection to the same login.

    1. This connection sets DEFAULT_SCHEMA to its own schema (as the first
       statement of a real ``migrate`` run would).
    2. A REAL second connection, authenticating as the SAME login, silently
       changes DEFAULT_SCHEMA — simulating a concurrent dblift process
       configured with a different ``--db-schema``.
    3. This connection asks for its OWN, unchanged schema again — exactly
       what every later statement in a migration script does.

    A warning must fire, and per the accepted design (the platform
    limitation itself is not solvable) the write is still skipped on this
    cache hit, so the live catalog is asserted to still hold the OTHER
    connection's value afterward — proving detection is real, not a stub
    that happens to also silently repair the race.
    """
    schema_ours = _unique_schema("ours")
    schema_other = _unique_schema("other")
    provider.create_schema_if_not_exists(schema_ours)
    provider.create_schema_if_not_exists(schema_other)
    provider.created_schemas.extend([schema_ours, schema_other])

    # Step 1: this connection aligns DEFAULT_SCHEMA to its own schema.
    provider.set_current_schema(schema_ours)
    assert provider._current_schema_set == schema_ours

    # Step 2: a REAL second connection to the same login changes it.
    other_conn = _second_login_connection()
    try:
        other_cur = other_conn.cursor()
        other_cur.execute(f"ALTER USER [{USERNAME}] WITH DEFAULT_SCHEMA = [{schema_other}]")
    finally:
        other_conn.close()

    # Confirm the interfering write actually landed before we probe for detection.
    catalog_after_interference = provider.execute_query(
        "SELECT DEFAULT_SCHEMA_NAME AS s FROM sys.database_principals WHERE name = ?",
        [USERNAME],
    )
    assert catalog_after_interference[0]["s"] == schema_other

    warnings = []
    real_warning = provider.log.warning

    def capturing_warning(msg, *args, **kwargs):
        warnings.append(msg)
        return real_warning(msg, *args, **kwargs)

    provider.log.warning = capturing_warning

    # Step 3: our own connection re-requests its OWN, UNCHANGED schema --
    # a cache hit, exactly like every later statement in a migration.
    provider.set_current_schema(schema_ours)

    assert len(warnings) == 1, f"expected exactly one interference warning, got: {warnings}"
    assert schema_other in warnings[0]
    assert schema_ours in warnings[0]

    # The write was skipped on the cache hit (per the accepted design, only
    # the WRITE is conditioned on the cache -- the read+compare is not) --
    # so the catalog is still showing the other connection's value. This is
    # the live proof that detection does not silently repair the race.
    catalog_now = provider.execute_query(
        "SELECT DEFAULT_SCHEMA_NAME AS s FROM sys.database_principals WHERE name = ?",
        [USERNAME],
    )
    assert catalog_now[0]["s"] == schema_other


def test_alter_user_issued_once_across_repeated_calls_with_no_interference(provider, monkeypatch):
    """Against the real container: repeated calls with the same, undisturbed
    schema issue exactly one real ``ALTER USER`` round-trip, not one per
    call -- the write-frequency win this design exists to keep.
    """
    schema = _unique_schema("steady")
    provider.create_schema_if_not_exists(schema)
    provider.created_schemas.append(schema)

    alter_user_calls = []
    real_execute_statement = SqlAlchemyProvider.execute_statement

    def counting_execute_statement(self, sql, schema=None, params=None):
        if sql.strip().upper().startswith("ALTER USER"):
            alter_user_calls.append(sql)
        return real_execute_statement(self, sql, schema=schema, params=params)

    monkeypatch.setattr(SqlAlchemyProvider, "execute_statement", counting_execute_statement)

    for _ in range(4):
        provider.set_current_schema(schema)

    assert len(alter_user_calls) == 1, alter_user_calls

    catalog_now = provider.execute_query(
        "SELECT DEFAULT_SCHEMA_NAME AS s FROM sys.database_principals WHERE name = ?",
        [USERNAME],
    )
    assert catalog_now[0]["s"] == schema


def test_writes_again_and_clears_the_warning_once_asked_for_a_new_schema(provider):
    """After interference is detected, asking for a genuinely NEW schema
    still issues a real ALTER USER and correctly moves the live catalog --
    the cache-hit skip only ever applies to a request for the same schema.
    """
    schema_a = _unique_schema("a")
    schema_b = _unique_schema("b")
    provider.create_schema_if_not_exists(schema_a)
    provider.create_schema_if_not_exists(schema_b)
    provider.created_schemas.extend([schema_a, schema_b])

    provider.set_current_schema(schema_a)

    other_conn = _second_login_connection()
    try:
        other_conn.cursor().execute(f"ALTER USER [{USERNAME}] WITH DEFAULT_SCHEMA = [{schema_b}]")
    finally:
        other_conn.close()

    # Ask for a schema neither this connection's cache nor the interfering
    # write currently holds -- a genuine change, so the write must happen.
    schema_c = _unique_schema("c")
    provider.create_schema_if_not_exists(schema_c)
    provider.created_schemas.append(schema_c)

    provider.set_current_schema(schema_c)

    catalog_now = provider.execute_query(
        "SELECT DEFAULT_SCHEMA_NAME AS s FROM sys.database_principals WHERE name = ?",
        [USERNAME],
    )
    assert catalog_now[0]["s"] == schema_c
    assert provider._current_schema_set == schema_c
