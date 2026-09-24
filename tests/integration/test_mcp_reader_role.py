"""Pin the ``dblift mcp`` built-in tools under a SELECT-only PostgreSQL role.

The operator's real lock against a coding agent using ``dblift mcp`` is a
database role that can only ``SELECT`` — never ``CREATE``. These tests run
the three built-in tools and the two resources through the in-memory MCP
client against such a role, once with a pre-existing history table (the
happy path) and once without one (the role must fail closed rather than
create it).
"""

from __future__ import annotations

import uuid

import pytest
import yaml

# Before any import of the optional stack: `anyio` ships with the `mcp`
# extra, so a module-level `import anyio` would make this a collection
# error rather than a skip on an install without it.
pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")

from dblift.cli.mcp.runner import run_command  # noqa: E402
from dblift.config import DbliftConfig  # noqa: E402
from dblift.db.plugins.postgresql.config import PostgreSqlConfig  # noqa: E402
from dblift.db.provider_registry import ProviderRegistry  # noqa: E402

pytestmark = pytest.mark.integration


def _admin_config(schema: str) -> DbliftConfig:
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


def _write_config(path, *, schema, username, password, migrations_dir):
    path.write_text(
        yaml.safe_dump(
            {
                "database": {
                    "type": "postgresql",
                    "host": "localhost",
                    "port": 5432,
                    "database": "testdb",
                    "username": username,
                    "password": password,
                    "schema": schema,
                },
                "migrations": {"directory": str(migrations_dir)},
            }
        )
    )


def _write_migrations(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    (migrations / "V2__more.sql").write_text("CREATE TABLE gadgets (id INTEGER PRIMARY KEY);")
    return migrations


async def _session(config_path, fn):
    from mcp import Client

    from dblift.cli.mcp.server import build_server

    server = build_server(["--config", str(config_path)])
    async with Client(server.mcpserver) as client:
        return await fn(client)


def test_reader_role_serves_every_built_in_tool_once_history_table_exists(tmp_path):
    """A SELECT-only role serves info/validate/migrate_dry_run once the admin
    has applied at least one migration: the read-only tools never need to
    write, they only need to read a history table that already exists."""
    schema = f"mcp_reader_{uuid.uuid4().hex[:8]}"
    role = f"mcp_reader_{uuid.uuid4().hex[:8]}"
    password = "ReaderPass123"
    migrations = _write_migrations(tmp_path)

    admin = ProviderRegistry.create_provider(_admin_config(schema))
    admin.create_connection()
    try:
        admin.execute_statement(f'CREATE SCHEMA "{schema}"')
        admin.execute_statement(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
        admin.execute_statement(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')

        admin_yaml = tmp_path / "admin.yaml"
        _write_config(
            admin_yaml,
            schema=schema,
            username="postgres",
            password="postgres",
            migrations_dir=migrations,
        )
        # V1 only: this leaves the history table in `schema` with one applied
        # row and V2 still pending.
        run_command(["--config", str(admin_yaml)], "migrate", ["--target-version", "1"])

        admin.execute_statement(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"')

        reader_yaml = tmp_path / "reader.yaml"
        _write_config(
            reader_yaml,
            schema=schema,
            username=role,
            password=password,
            migrations_dir=migrations,
        )

        async def scenario(client):
            info = await client.call_tool("info", {})
            validate = await client.call_tool("validate", {})
            dry_run = await client.call_tool("migrate_dry_run", {})
            history = await client.read_resource("dblift://history")
            pending = await client.read_resource("dblift://pending")
            return info, validate, dry_run, history, pending

        info, validate, dry_run, history, pending = anyio.run(_session, reader_yaml, scenario)

        for result in (info, validate, dry_run):
            assert result.is_error is False
            assert result.structured_content["success"] is True

        info_status_by_script = {
            m["script"]: m["status"] for m in info.structured_content["migrations"]
        }
        assert info_status_by_script["V1__init.sql"] == "SUCCESS"
        assert info_status_by_script["V2__more.sql"] == "PENDING"

        dry_run_scripts = {m["script"] for m in dry_run.structured_content["migrations"]}
        assert dry_run_scripts == {"V2__more.sql"}

        assert '"V2__more.sql"' in pending.contents[0].text
        assert '"V1__init.sql"' in history.contents[0].text

        # The dry run applied nothing: as admin, prove it through the catalog.
        assert admin.table_exists(schema, "gadgets") is False
        assert len(admin.get_applied_migrations(schema)) == 1
    finally:
        try:
            admin.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            admin.execute_statement(f'DROP OWNED BY "{role}"')
            admin.execute_statement(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            admin.close()


def test_reader_role_on_schema_with_no_history_table_fails_closed(tmp_path):
    """A reader role with no CREATE on its schema must not be able to make a
    history table materialise as a side effect of a read-only tool call."""
    schema = f"mcp_reader_{uuid.uuid4().hex[:8]}"
    role = f"mcp_reader_{uuid.uuid4().hex[:8]}"
    password = "ReaderPass123"
    migrations = _write_migrations(tmp_path)

    admin = ProviderRegistry.create_provider(_admin_config(schema))
    admin.create_connection()
    try:
        admin.execute_statement(f'CREATE SCHEMA "{schema}"')
        admin.execute_statement(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'")
        admin.execute_statement(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"')
        # No admin migrate: this schema has no history table, and the role
        # has no CREATE, so nothing can make one appear.

        reader_yaml = tmp_path / "reader2.yaml"
        _write_config(
            reader_yaml,
            schema=schema,
            username=role,
            password=password,
            migrations_dir=migrations,
        )

        async def scenario(client):
            validate = await client.call_tool("validate", {})
            info = await client.call_tool("info", {})
            return validate, info

        validate, info = anyio.run(_session, reader_yaml, scenario)

        # `validate` catches the history-table failure itself
        # (`ValidateCommand.execute`'s own try/except) and reports it as a
        # result, so it is a verdict to the runner, not a crash.
        assert validate.is_error is False
        assert validate.structured_content["success"] is False
        assert "permission denied" in validate.structured_content["error"]

        # `info` raises the same denial from preflight instead of catching
        # it, so the runner never gets a result object and it surfaces as an
        # MCP error result. It still routes through
        # dblift.db.error.format_connection_error, but an AUTHORIZATION-category
        # error now keeps the engine's own text instead of being folded into
        # "invalid credentials" — so `validate` and `info` now carry the same
        # engine message on different channels: `validate` as a result,
        # `info` as an error result.
        assert info.is_error is True
        assert "permission denied" in info.content[0].text

        assert admin.table_exists(schema, "dblift_schema_history") is False
    finally:
        try:
            admin.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            admin.execute_statement(f'DROP OWNED BY "{role}"')
            admin.execute_statement(f'DROP ROLE IF EXISTS "{role}"')
        finally:
            admin.close()
