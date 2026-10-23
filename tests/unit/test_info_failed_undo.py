"""``info`` lists a failed undo history row, like it lists a failed migration row.

A failed undo leaves a ``success = 0`` ``UNDO_SQL`` row that ``validate``,
``migrate`` and ``undo`` refuse to proceed past. ``info`` used to drop every
``UNDO_SQL`` row, failed or not, and so reported a clean schema.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
import yaml

from dblift.api.client import DBLiftClient

pytestmark = pytest.mark.unit


@pytest.fixture(params=["sqlite", "duckdb"])
def project(request, tmp_path, monkeypatch):
    if request.param == "duckdb":
        pytest.importorskip("duckdb")
    for key in list(os.environ):
        if key.startswith("DBLIFT_"):
            monkeypatch.delenv(key)
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER);")
    (migrations / "V2__b.sql").write_text("CREATE TABLE b (id INTEGER);")
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": request.param, "path": str(tmp_path / "t.db")},
                "migrations": {"directory": str(migrations)},
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _client(project):
    return DBLiftClient.from_config_file(str(project / "dblift.yaml"), relative_to_config=True)


def _apply_and_fail_undo(project):
    (project / "migrations" / "U2__b.sql").write_text(
        "DROP TABLE b;\nDROP TABLE no_such_table_zzz;\n"
    )
    with _client(project) as client:
        assert client.migrate().success
        assert not client.undo(target_version="1").success


def _apply_and_undo(project):
    (project / "migrations" / "U2__b.sql").write_text("DROP TABLE b;\n")
    with _client(project) as client:
        assert client.migrate().success
        assert client.undo(target_version="1").success


def _cli(project, *args):
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", "--config", str(project / "dblift.yaml"), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _undo_rows(migrations):
    return [m for m in migrations if m.type == "UNDO_SQL"]


def test_api_info_exposes_the_failed_undo_row(project):
    _apply_and_fail_undo(project)

    with _client(project) as client:
        result = client.info()

    undo = _undo_rows(result.migrations)
    assert [(m.script, m.status) for m in undo] == [("U2__b.sql", "FAILED")]
    assert result.failed_count == 1


def test_json_info_lists_the_failed_undo_row(project):
    _apply_and_fail_undo(project)

    proc = _cli(project, "info", "--format", "json")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout[proc.stdout.index("{") :])
    undo = _undo_rows_json(payload["migrations"])
    assert [(m["script"], m["status"]) for m in undo] == [("U2__b.sql", "FAILED")]


def _undo_rows_json(migrations):
    return [m for m in migrations if m["type"] == "UNDO_SQL"]


def test_console_info_lists_the_failed_undo_row_and_counts_it(project):
    _apply_and_fail_undo(project)

    proc = _cli(project, "info")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    output = proc.stdout + proc.stderr
    assert "Failed Migrations: 1" in output
    row = next(line for line in output.splitlines() if line.startswith("│ Undo"))
    assert "Failed" in row and "b" in row


def test_mcp_info_tool_includes_the_failed_undo_row(project):
    pytest.importorskip("mcp")
    anyio = pytest.importorskip("anyio")
    _apply_and_fail_undo(project)

    async def scenario():
        from mcp import Client

        from dblift.cli.mcp.server import build_server

        async with Client(build_server([]).mcpserver) as client:
            return await client.call_tool("info", {})

    result = anyio.run(scenario)

    assert result.is_error is False
    undo = _undo_rows_json(result.structured_content["migrations"])
    assert [(m["script"], m["status"]) for m in undo] == [("U2__b.sql", "FAILED")]


def test_info_after_a_successful_undo_is_unchanged(project):
    _apply_and_undo(project)

    with _client(project) as client:
        result = client.info()

    assert _undo_rows(result.migrations) == []
    assert [(m.version, m.status) for m in result.migrations] == [
        ("1", "SUCCESS"),
        ("2", "UNDONE"),
        ("2", "PENDING"),
    ]
    assert result.failed_count == 0

    output = _cli(project, "info")
    output = output.stdout + output.stderr
    assert "Failed Migrations: 0" in output
    assert not any(line.startswith("│ Undo") for line in output.splitlines())
