"""A login mapped to the fixed ``dbo`` database user cannot get a non-``dbo`` schema.

SQL Server's ``dbo`` user is always ``principal_id = 1`` and its
``DEFAULT_SCHEMA`` is permanently ``dbo`` -- ``ALTER USER [dbo] WITH
DEFAULT_SCHEMA = ...`` is rejected by the server (error 15150, "Cannot alter
the user 'dbo'"). Any sysadmin login (``sa``) and a database's owner map to
``dbo``, so connecting with such a login while ``schema:`` names anything else
cannot place unqualified objects in that schema.

By default dblift logs a warning and continues, the same outcome as 4.8.0:
the unqualified ``CREATE TABLE`` lands in ``dbo`` and the run is reported
successful. ``fail_on_fixed_dbo: true`` fails the run before any migration
or callback statement executes, and that failure must not leave a history
row.

These tests exercise both outcomes against a REAL SQL Server container (not a
mock): the ``sa`` login is exactly the "maps to dbo" case in the wild. The
general integration harness connects as a non-``dbo`` user instead; see
``tests/integration/conftest.py``.

Prerequisites: a running SQL Server instance reachable at localhost:1433,
``sa`` / the container's SA password (see tests/integration/conftest.py's
db_configs for the general-purpose container fixtures; this module creates
its own throwaway database directly with ``sa`` rather than depending on how
that container happened to be provisioned).
"""

import uuid

import pymssql
import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.sqlserver.config import SqlServerConfig
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import (
    create_migration,
    create_undo_migration,
    create_versioned_migration,
)

pytestmark = [pytest.mark.integration, pytest.mark.sqlserver]

HOST = "localhost"
PORT = 1433
USERNAME = "sa"
PASSWORD = "YourStrong@Passw0rd"


def _connect(database: str) -> "pymssql.Connection":
    """A raw, autocommit connection -- CREATE/DROP DATABASE cannot run in a transaction."""
    return pymssql.connect(
        server=HOST,
        port=PORT,
        user=USERNAME,
        password=PASSWORD,
        database=database,
        autocommit=True,
    )


@pytest.fixture
def throwaway_database():
    """Create a throwaway database for this test only, and always drop it after."""
    db_name = f"dblift_dbo_guard_{uuid.uuid4().hex[:8]}"
    conn = _connect("master")
    try:
        conn.cursor().execute(f"CREATE DATABASE [{db_name}]")
    finally:
        conn.close()

    try:
        yield db_name
    finally:
        conn = _connect("master")
        try:
            conn.cursor().execute(
                f"IF EXISTS (SELECT 1 FROM sys.databases WHERE name = '{db_name}') "
                "BEGIN "
                f"ALTER DATABASE [{db_name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE [{db_name}]; "
                "END"
            )
        finally:
            conn.close()


def _create_schema(db_name: str, schema: str) -> None:
    conn = _connect(db_name)
    try:
        conn.cursor().execute(f"CREATE SCHEMA [{schema}]")
    finally:
        conn.close()


def _table_schemas(db_name: str, table_name: str) -> list:
    """Every schema (if any) that currently holds a table with this name."""
    conn = _connect(db_name)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT TABLE_SCHEMA AS s FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = %s",
            (table_name,),
        )
        return [row["s"] for row in cur.fetchall()]
    finally:
        conn.close()


def _history_success_values(db_name: str) -> list:
    """``success`` for every row of every ``dblift_schema_history`` table."""
    conn = _connect(db_name)
    try:
        cur = conn.cursor(as_dict=True)
        cur.execute(
            "SELECT s.name AS schema_name FROM sys.tables t "
            "JOIN sys.schemas s ON t.schema_id = s.schema_id "
            "WHERE t.name = %s",
            ("dblift_schema_history",),
        )
        schemas = [row["schema_name"] for row in cur.fetchall()]
        values = []
        for schema_name in schemas:
            quoted = "[" + schema_name.replace("]", "]]") + "]"
            cur.execute(f"SELECT success FROM {quoted}.[dblift_schema_history]")
            values.extend(row["success"] for row in cur.fetchall())
        return values
    finally:
        conn.close()


def _config(db_name: str, schema: str, *, fail_on_fixed_dbo: bool = False) -> DbliftConfig:
    # Built from discrete host/port/username/password fields, not a hand-assembled
    # URL string: the SA password contains a literal '@', which a naive
    # f-string URL would misparse as the host separator. SqlServerConfig's own
    # URL builder escapes credentials correctly for this field-based form.
    database = SqlServerConfig(
        type="sqlserver",
        host=HOST,
        port=PORT,
        database=db_name,
        username=USERNAME,
        password=PASSWORD,
        schema=schema,
        encrypt=False,
        fail_on_fixed_dbo=fail_on_fixed_dbo,
    )
    return DbliftConfig(database=database)


def _run(
    db_name: str,
    schema: str,
    migrations_dir,
    *,
    operation: str = "migrate",
    fail_on_fixed_dbo: bool = False,
    warnings: list | None = None,
) -> "object":
    config = _config(db_name, schema, fail_on_fixed_dbo=fail_on_fixed_dbo)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    if warnings is not None:
        original_warning = provider.log.warning

        def _capture(message: str) -> None:
            warnings.append(message)
            original_warning(message)

        provider.log.warning = _capture  # type: ignore[method-assign]
    provider.create_connection()
    try:
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)
        if operation == "undo":
            return client.undo()
        return client.migrate()
    finally:
        provider.close()


def _migrate(
    db_name: str,
    schema: str,
    migrations_dir,
    *,
    fail_on_fixed_dbo: bool = False,
    warnings: list | None = None,
) -> "object":
    return _run(
        db_name,
        schema,
        migrations_dir,
        fail_on_fixed_dbo=fail_on_fixed_dbo,
        warnings=warnings,
    )


def _widgets_migration(tmp_path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_widgets",
        "CREATE TABLE widgets (id INT PRIMARY KEY, name NVARCHAR(50));",
    )
    return migrations_dir


def test_sa_login_with_non_dbo_schema_warns_and_continues(throwaway_database, tmp_path):
    """``sa`` maps to the fixed ``dbo`` user. The default has the same outcome as 4.8.0.

    The run warns and reports success, and the unqualified table lands in
    ``dbo``. The message must not suggest switching ``schema`` to ``dbo``.
    """
    db_name = throwaway_database
    schema = f"guard_{uuid.uuid4().hex[:8]}"
    _create_schema(db_name, schema)
    warnings: list = []

    result = _migrate(db_name, schema, _widgets_migration(tmp_path), warnings=warnings)

    assert result.success, result.error_message
    assert _table_schemas(db_name, "widgets") == ["dbo"]
    text = " ".join(warnings).lower()
    assert "cannot be changed" in text
    assert "fail_on_fixed_dbo" in text
    assert "set the schema" not in text
    assert "set schema" not in text


def test_sa_login_with_non_dbo_schema_fails_when_opted_in(throwaway_database, tmp_path):
    """``fail_on_fixed_dbo`` fails before the migration's DDL, with no history row.

    A ``FAILED`` schema-history row would make the next run look like a
    migration that started and did not finish. The guard has to fire before
    anything is recorded.
    """
    db_name = throwaway_database
    schema = f"guard_{uuid.uuid4().hex[:8]}"
    _create_schema(db_name, schema)

    result = _migrate(db_name, schema, _widgets_migration(tmp_path), fail_on_fixed_dbo=True)

    assert not result.success
    assert result.error_message
    error = result.error_message.lower()
    assert "cannot be changed" in error or "dbo" in error
    assert "set the schema" not in error
    assert "set schema" not in error

    assert _table_schemas(db_name, "widgets") == []
    assert _history_success_values(db_name) == []


def test_opt_in_undo_writes_no_history_row(throwaway_database, tmp_path):
    """Undo with the guard enabled must not record a history row.

    The migration is applied first with the default (warn and continue) so
    there is something to undo. The opt-in failure happens inside the undo
    script, before its statements, and the original success row stays the
    only row.
    """
    db_name = throwaway_database
    schema = f"guard_{uuid.uuid4().hex[:8]}"
    _create_schema(db_name, schema)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_widgets",
        "CREATE TABLE widgets (id INT PRIMARY KEY, name NVARCHAR(50));",
    )
    create_undo_migration(
        migrations_dir,
        "1.0.0",
        "create_widgets",
        "DROP TABLE widgets;",
    )

    applied = _migrate(db_name, schema, migrations_dir)
    assert applied.success, applied.error_message
    assert _history_success_values(db_name) == [True]

    undone = _run(db_name, schema, migrations_dir, operation="undo", fail_on_fixed_dbo=True)

    assert not undone.success
    assert undone.error_message
    assert "no history row is written" in undone.error_message
    assert _history_success_values(db_name) == [True]
    assert _table_schemas(db_name, "widgets") == ["dbo"]


def test_opt_in_before_migrate_callback_writes_no_history_row(throwaway_database, tmp_path):
    """A ``beforeMigrate`` callback hits the guard before its own SQL.

    The pending versioned migration must not run, and the history table
    stays empty.
    """
    db_name = throwaway_database
    schema = f"guard_{uuid.uuid4().hex[:8]}"
    _create_schema(db_name, schema)
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_migration(
        migrations_dir,
        "beforeMigrate__marker.sql",
        "CREATE TABLE callback_marker (id INT PRIMARY KEY);",
    )
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_widgets",
        "CREATE TABLE widgets (id INT PRIMARY KEY, name NVARCHAR(50));",
    )

    result = _migrate(db_name, schema, migrations_dir, fail_on_fixed_dbo=True)

    assert not result.success
    assert result.error_message
    assert "no history row is written" in result.error_message
    assert _history_success_values(db_name) == []
    assert _table_schemas(db_name, "callback_marker") == []
    assert _table_schemas(db_name, "widgets") == []


def test_sa_login_with_dbo_schema_succeeds(throwaway_database, tmp_path):
    """The same ``sa`` login with ``schema: dbo`` is the one case that legitimately works."""
    db_name = throwaway_database

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_widgets",
        "CREATE TABLE widgets (id INT PRIMARY KEY, name NVARCHAR(50));",
    )

    result = _migrate(db_name, "dbo", migrations_dir)

    assert result.success, result.error_message
    assert _table_schemas(db_name, "widgets") == ["dbo"]


@pytest.mark.parametrize("schema", ["DBO", "Dbo"])
def test_sa_login_with_case_variant_of_dbo_succeeds(throwaway_database, tmp_path, schema):
    """SQL Server identifiers are case-insensitive: ``DBO``/``Dbo`` name the
    same schema as ``dbo``. The guard must return before ``ALTER USER [dbo]``,
    which the server rejects (error 15150) and which otherwise warns on every
    statement."""
    db_name = throwaway_database

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "create_widgets",
        "CREATE TABLE widgets (id INT PRIMARY KEY, name NVARCHAR(50));",
    )

    warnings: list = []
    result = _migrate(db_name, schema, migrations_dir, warnings=warnings)

    assert result.success, result.error_message
    assert _table_schemas(db_name, "widgets") == ["dbo"]
    text = " ".join(warnings).lower()
    assert "15150" not in text
    assert "could not set the connecting user's default schema" not in text
