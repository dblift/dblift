"""A crashed command is an MCP error result; a negative verdict stays a normal one."""

from __future__ import annotations

import os

import pytest
import yaml

# Before any import of the optional stack: `anyio` ships with the `mcp`
# extra, so a module-level `import anyio` would make this a collection
# error rather than a skip on an install without it.
pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")


@pytest.fixture
def project(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    (tmp_path / "dblift.yaml").write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(tmp_path / "t.sqlite")},
                "migrations": {"directory": str(migrations)},
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


async def _session(fn):
    from mcp import Client

    from dblift.cli.mcp.server import build_server

    server = build_server([])
    async with Client(server.mcpserver) as client:
        return await fn(client)


def _make_database_read_only(project):
    """Make ``t.sqlite`` a read-only file with no history table.

    A malformed-but-existing history table (wrong columns) does *not* crash
    `info` at the runner's level: `InfoCommand`'s own body-level try/except
    (`_run_command_lifecycle`) catches that failure and returns a normal
    `InfoResult(success=False, error_message=...)` — a result object, hence a
    verdict, not a crash. A read-only file fails earlier, in preflight
    (`create_schema_and_history_table`, trying to create the table), which
    `_run_command_lifecycle` does *not* wrap — the exception propagates all
    the way to `run_json_guarded`'s own handler, which is the only path that
    returns `(False, None)`.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is not None and geteuid() == 0:
        # CAP_DAC_OVERRIDE (root) ignores the write-permission bit, so the
        # table would be created anyway and the dependent test would see a
        # normal verdict instead of the crash it means to force.
        pytest.skip("cannot force a read-only-file crash while running as root")
    db_path = project / "t.sqlite"
    db_path.touch()
    db_path.chmod(0o444)


@pytest.mark.unit
def test_crashed_command_is_an_error_result_with_its_payload(project):
    """`info` fails in preflight (a read-only database file, no history
    table) before building a result: `run_json_guarded` returns `(False,
    None)`, so the runner raises instead of returning that payload. The
    SDK's `ToolError` path carries the CLI's message as text; there is no
    `structured_content` to assert on — the exception payload had nothing
    else worth keeping."""
    _make_database_read_only(project)

    async def scenario(client):
        return await client.call_tool("info", {})

    result = anyio.run(_session, scenario)

    assert result.is_error is True
    assert "readonly database" in result.content[0].text


@pytest.mark.unit
def test_negative_verdict_stays_a_normal_result(project):
    """A validation that finds a checksum mismatch runs to a result object —
    `run_json_guarded` returns `(result.success, result)`, never `(False,
    None)` — so it is a verdict to the runner, not a crash, and must stay a
    normal MCP result even though `success` is `False`. `error` mirrors
    `issues[0]` (the domain code's own doing, not the runner's); this pins
    that fact so a payload-shape predicate keyed on `error` is not
    reintroduced. Passes before and after the change."""
    from dblift.cli.mcp.runner import run_command

    run_command([], "migrate", [])
    (project / "migrations" / "V1__init.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY); -- checksum changed"
    )

    async def scenario(client):
        return await client.call_tool("validate", {})

    result = anyio.run(_session, scenario)

    assert result.is_error is False
    assert result.structured_content["success"] is False
    assert result.structured_content["issues"] or result.structured_content["failed_migrations"]
    assert result.structured_content["error"]
    assert result.structured_content["error"] == result.structured_content["issues"][0]


@pytest.mark.unit
def test_text_mode_success_false_is_not_an_error():
    """A text-mode tool's own `success: false` never carries the `error` key
    `run_json_guarded` uses for a command failure, so it must stay a normal
    result."""
    from dblift.cli.mcp.server import DbliftMcpServer

    server = DbliftMcpServer([])
    server.raw_tool(
        name="fake",
        description="d",
        fn=lambda: {"success": False, "output": "x"},
        signature_of=lambda: None,
    )

    async def scenario():
        from mcp import Client

        async with Client(server.mcpserver) as client:
            return await client.call_tool("fake", {})

    result = anyio.run(scenario)

    assert result.is_error is False


@pytest.mark.unit
def test_resource_over_a_crashed_command_refuses(project):
    """`dblift://history` over a crashed `info` must raise the SDK's
    client-side error, carrying the CLI's message, instead of quietly
    returning `[]` — which would read as "no history"."""
    from mcp.shared.exceptions import MCPError

    _make_database_read_only(project)

    async def scenario(client):
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("dblift://history")
        return str(exc_info.value)

    message = anyio.run(_session, scenario)

    assert "readonly database" in message
