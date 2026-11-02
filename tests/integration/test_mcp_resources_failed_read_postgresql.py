"""``dblift://history`` and ``dblift://pending`` report a failed read instead of ``[]``.

A reader role holding USAGE on the schema but no SELECT on the history table, and a
missing migrations directory, both make the command fail. The tools return that as
``success: false``; the resources must raise an error naming the cause.
"""

from __future__ import annotations

import json
import uuid

import pytest
import yaml

pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")

from sqlalchemy import create_engine, text  # noqa: E402

from dblift.cli.mcp.runner import run_command  # noqa: E402

pytestmark = pytest.mark.integration

URIS = ("dblift://history", "dblift://pending")


def _write_config(path, config: dict, schema, username, password, migrations_dir) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "database": {
                    "type": "postgresql",
                    "host": config["host"],
                    "port": config["port"],
                    "database": config["database"],
                    "username": username,
                    "password": password,
                    "schema": schema,
                },
                "migrations": {"directory": str(migrations_dir)},
            }
        )
    )


async def _reads(config_path) -> dict:
    """Read both resources; the text on success, the MCP error message on failure."""
    from mcp import Client
    from mcp.shared.exceptions import MCPError

    from dblift.cli.mcp.server import build_server

    server = build_server(["--config", str(config_path)])
    out = {}
    async with Client(server.mcpserver) as client:
        for uri in URIS:
            try:
                out[uri] = ("rows", json.loads((await client.read_resource(uri)).contents[0].text))
            except MCPError as exc:
                out[uri] = ("error", str(exc))
    return out


def run_scenario(config: dict, tmp_path) -> dict:
    """Owner reads rows; a reader without SELECT and a missing directory read errors."""
    uid = uuid.uuid4().hex[:8]
    schema, role, password = f"q3a_{uid}", f"q3a_r_{uid}", f"Pw{uid}x1"
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in (1, 2):
        (migrations / f"V{version}__t{version}.sql").write_text(
            f"CREATE TABLE t{version} (id int);"
        )

    url = (
        f"postgresql+psycopg://{config['username']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    transcript: dict = {}
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    try:
        owner = tmp_path / "owner.yaml"
        _write_config(owner, config, schema, config["username"], config["password"], migrations)
        run_command(["--config", str(owner)], "migrate", [])
        (migrations / "V3__t3.sql").write_text("CREATE TABLE t3 (id int);")

        transcript["owner"] = anyio.run(_reads, owner)
        history, pending = (transcript["owner"][uri] for uri in URIS)
        assert history[0] == "rows" and [r["script"] for r in history[1] if r["version"]][:2] == [
            "V1__t1.sql",
            "V2__t2.sql",
        ]
        assert pending == ("rows", [pending[1][0]]) and pending[1][0]["script"] == "V3__t3.sql"

        reader = tmp_path / "reader.yaml"
        _write_config(reader, config, schema, role, password, migrations)
        transcript["reader"] = anyio.run(_reads, reader)
        for uri in URIS:
            kind, message = transcript["reader"][uri]
            assert kind == "error" and "permission denied" in message, transcript["reader"]

        missing = tmp_path / "missing.yaml"
        _write_config(
            missing, config, schema, config["username"], config["password"], tmp_path / "nope"
        )
        transcript["missing_directory"] = anyio.run(_reads, missing)
        for uri in URIS:
            kind, message = transcript["missing_directory"][uri]
            assert kind == "error" and str(tmp_path / "nope") in message, transcript[
                "missing_directory"
            ]
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
    return transcript


def test_resources_report_a_failed_read_postgresql(postgresql_container, tmp_path):
    run_scenario(postgresql_container, tmp_path)
