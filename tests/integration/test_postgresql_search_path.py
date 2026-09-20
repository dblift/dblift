"""PostgreSQL ``search_path`` must keep ``public`` resolvable.

PostgreSQL extensions install their callable API into ``public``: pgcrypto
(``gen_salt``, ``digest``), PostGIS (``ST_MakePoint``), uuid-ossp
(``uuid_generate_v4``), hstore. A migration that calls one of those unqualified
resolves under ``psql``, whose server-default ``search_path`` ends in
``public``. dblift used to set a *schema-only* ``search_path``, so the very same
statement failed with ``function ... does not exist`` — a file dblift itself
exported could not be replayed through dblift.

These tests use ``gen_salt``/``crypt`` rather than ``gen_random_uuid``: on
PostgreSQL 13+ ``gen_random_uuid`` is also in ``pg_catalog``, which is always
implicitly on the search path, so it cannot detect the bug.
"""

import uuid

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_versioned_migration

pytestmark = [pytest.mark.integration, pytest.mark.postgresql]

#: Schema owned by this test module; created and torn down per test.
SCHEMA = "sp_test"


def _postgres_config(schema: str = SCHEMA) -> DbliftConfig:
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


@pytest.fixture
def pg_provider():
    """A connected provider on a freshly recreated ``sp_test`` schema.

    ``pgcrypto`` is installed into ``public`` so an extension function exists
    outside the target schema, which is the whole point of these tests.
    """
    provider = ProviderRegistry.create_provider(_postgres_config())
    provider.create_connection()
    try:
        provider.execute_statement("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        provider.execute_statement(f'CREATE SCHEMA "{SCHEMA}"')
        provider.close()

        # Reconnect so the connection is built with the schema in place, the
        # way a real run connects.
        provider = ProviderRegistry.create_provider(_postgres_config())
        provider.create_connection()
        yield provider
    finally:
        try:
            provider.create_connection()
            provider.execute_statement(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        finally:
            provider.close()


def test_migration_resolves_unqualified_public_extension_function(pg_provider, tmp_path) -> None:
    """A migration calling an unqualified ``public`` extension function applies.

    This is the reported failure: the exported statement runs under ``psql``
    but not under ``dblift migrate``.
    """
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_tokens",
        f"""
        CREATE TABLE "{SCHEMA}"."tokens" (id INT PRIMARY KEY, salt TEXT NOT NULL);
        INSERT INTO "{SCHEMA}"."tokens" (id, salt) VALUES (1, gen_salt('bf'));
        """,
    )

    config = _postgres_config()
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

        result = client.migrate()

        assert result.success, result.error_message
        rows = provider.execute_query(f'SELECT salt FROM "{SCHEMA}"."tokens" WHERE id = 1')
        assert rows and rows[0]["salt"].startswith("$2a$")
    finally:
        provider.close()


def test_callback_resolves_unqualified_public_extension_function(pg_provider, tmp_path) -> None:
    """Callbacks resolve ``public`` too.

    Callbacks do not inherit the connection's search path by accident: the
    execution engine issues an explicit ``SET search_path`` before running
    them, which is a second place the schema-only path was built.
    """
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_audit",
        f'CREATE TABLE "{SCHEMA}"."audit" (id INT PRIMARY KEY, digest BYTEA);',
    )
    (migrations_dir / "afterMigrate__seed_audit.sql").write_text(
        f"""INSERT INTO "{SCHEMA}"."audit" (id, digest) VALUES (1, digest('x', 'sha256'));"""
    )

    config = _postgres_config()
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

        result = client.migrate()

        assert result.success, result.error_message
        rows = provider.execute_query(f'SELECT digest FROM "{SCHEMA}"."audit" WHERE id = 1')
        assert rows and rows[0]["digest"]
    finally:
        provider.close()


def test_target_schema_function_shadows_same_named_public_function(pg_provider) -> None:
    """The target schema resolves before ``public``, so it still shadows it.

    Order matters: ``search_path = <schema>, public`` must not become
    ``public, <schema>``, which would silently swap an object in ``public``
    for the one the migration meant.
    """
    probe = f"sp_probe_{uuid.uuid4().hex[:8]}"
    pg_provider.execute_statement(
        f"CREATE FUNCTION public.{probe}() RETURNS TEXT "
        "LANGUAGE SQL IMMUTABLE AS $$ SELECT 'public'::TEXT $$"
    )
    try:
        pg_provider.execute_statement(
            f'CREATE FUNCTION "{SCHEMA}".{probe}() RETURNS TEXT '
            "LANGUAGE SQL IMMUTABLE AS $$ SELECT 'target'::TEXT $$"
        )

        rows = pg_provider.execute_query(f"SELECT {probe}() AS origin")

        assert rows == [{"origin": "target"}]
    finally:
        pg_provider.execute_statement(f"DROP FUNCTION IF EXISTS public.{probe}()")


def test_migration_set_search_path_persists_for_rest_of_migration(pg_provider, tmp_path) -> None:
    """A migration's own ``SET search_path`` must survive to later statements.

    ``pg_dump`` (pre-10.3) and every hand-maintained file derived from one
    emits ``SET search_path = <schema>, pg_catalog;`` before unqualified DDL.
    dblift re-applied its own configured schema before every statement,
    silently overriding this and landing unqualified objects in the
    configured schema instead of the one the migration asked for.
    """
    scratch_schema = f"sp_scratch_{uuid.uuid4().hex[:8]}"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "search_path_probe",
        f"""
        CREATE SCHEMA "{scratch_schema}";
        CREATE TABLE "{SCHEMA}".probe (step text, val text);
        SET search_path = "{scratch_schema}", pg_catalog;
        INSERT INTO "{SCHEMA}".probe VALUES ('after SET', current_setting('search_path'));
        CREATE TABLE lands_where (id int);
        SET statement_timeout = '7s';
        INSERT INTO "{SCHEMA}".probe VALUES ('statement_timeout', current_setting('statement_timeout'));
        """,
    )

    config = _postgres_config()
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

        result = client.migrate()

        assert result.success, result.error_message

        rows = provider.execute_query(f'SELECT step, val FROM "{SCHEMA}".probe ORDER BY step')
        values = {row["step"]: row["val"] for row in rows}
        assert values["after SET"] == f"{scratch_schema}, pg_catalog"
        assert values["statement_timeout"] == "7s"

        lands_where_schema = provider.execute_query(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = 'lands_where'"
        )
        assert [r["table_schema"] for r in lands_where_schema] == [scratch_schema]
    finally:
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{scratch_schema}" CASCADE')
        provider.close()


def test_second_migration_does_not_inherit_previous_search_path(pg_provider, tmp_path) -> None:
    """One migration's ``SET search_path`` must not leak into the next migration.

    Session state a migration sets is scoped to that migration; the next
    migration must start from dblift's configured schema again.
    """
    scratch_schema = f"sp_scratch_{uuid.uuid4().hex[:8]}"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "change_search_path",
        f'CREATE SCHEMA "{scratch_schema}"; SET search_path = "{scratch_schema}", pg_catalog;',
    )
    create_versioned_migration(
        migrations_dir,
        "2.0.0",
        "unqualified_table",
        "CREATE TABLE v2_lands_where (id int);",
    )

    config = _postgres_config()
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

        result = client.migrate()

        assert result.success, result.error_message

        table_schema = provider.execute_query(
            "SELECT table_schema FROM information_schema.tables WHERE table_name = 'v2_lands_where'"
        )
        assert [r["table_schema"] for r in table_schema] == [SCHEMA]
    finally:
        provider.execute_statement(f'DROP SCHEMA IF EXISTS "{scratch_schema}" CASCADE')
        provider.execute_statement("DROP TABLE IF EXISTS v2_lands_where")
        provider.close()


def test_history_table_resolves_in_target_schema_not_public(pg_provider, tmp_path) -> None:
    """dblift's own history table is schema-qualified, so ``public`` cannot win.

    A decoy ``public.dblift_schema_history`` must be left untouched while the
    real history is written into the target schema.
    """
    pg_provider.execute_statement(
        "CREATE TABLE public.dblift_schema_history (decoy INT PRIMARY KEY)"
    )
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_widgets",
        f'CREATE TABLE "{SCHEMA}"."widgets" (id INT PRIMARY KEY);',
    )

    config = _postgres_config()
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

        result = client.migrate()

        assert result.success, result.error_message
        applied = provider.get_applied_migrations(SCHEMA)
        assert [row["script"] for row in applied] == ["V1_0_0__create_widgets.sql"]

        decoy_columns = provider.execute_query("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'dblift_schema_history'
            """)
        assert [row["column_name"] for row in decoy_columns] == ["decoy"]
    finally:
        provider.execute_statement("DROP TABLE IF EXISTS public.dblift_schema_history")
        provider.close()
