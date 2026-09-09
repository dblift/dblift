"""Built-in tools: argv shape, and real round trips against SQLite through the in-memory client."""

from __future__ import annotations

import pytest
import yaml

# Before any import of the optional stack: `anyio` ships with the `mcp`
# extra, so a module-level `import anyio` would make this a collection
# error rather than a skip on an install without it.
pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")

from dblift.cli._parser_setup import create_parser  # noqa: E402
from dblift.cli.mcp.tools import info_argv, migrate_dry_run_argv, validate_argv  # noqa: E402


def _parse_like_cli(command, argv):
    """Parse ``[command, *argv]`` the way ``main()`` does: root-only flags may follow the command."""
    from dblift.cli._config_helpers import _GLOBAL_BOOLEAN_FLAGS, _extract_commands_from_argv
    from dblift.cli.main import _AVAILABLE_COMMANDS, _GLOBAL_ONLY_ARGS

    commands, global_args, sub_args = _extract_commands_from_argv(
        [command, *argv], list(_AVAILABLE_COMMANDS), list(_GLOBAL_ONLY_ARGS), _GLOBAL_BOOLEAN_FLAGS
    )
    return create_parser(exit_on_error=False).parse_args([*global_args, *commands, *sub_args])


@pytest.mark.unit
@pytest.mark.parametrize(
    "builder, command",
    [(info_argv, "info"), (validate_argv, "validate"), (migrate_dry_run_argv, "migrate")],
)
def test_argv_parses_through_the_real_parser(builder, command):
    argv = builder(
        target_version="2", tags="core", exclude_tags=None, versions=None, exclude_versions="9"
    )

    ns = _parse_like_cli(command, [*argv, "--format", "json"])

    assert ns.target_version == "2" and ns.tags == "core" and ns.exclude_versions == "9"
    if command == "migrate":
        assert ns.dry_run is True


@pytest.mark.unit
def test_info_argv_accepts_a_list_for_tags():
    argv = info_argv(tags=["a", "b"])

    assert argv == ["--tags", "a,b"]


@pytest.mark.unit
def test_info_argv_still_accepts_a_csv_string_for_tags():
    argv = info_argv(tags="a,b")

    assert argv == ["--tags", "a,b"]


@pytest.mark.unit
def test_migrate_dry_run_argv_always_carries_dry_run():
    argv = migrate_dry_run_argv()

    assert "--dry-run" in argv


@pytest.mark.unit
def test_migrate_dry_run_argv_placeholders():
    argv = migrate_dry_run_argv(placeholders={"env": "dev", "owner": "app"})

    ns = _parse_like_cli("migrate", argv)
    # `--placeholders` is `nargs="+"` + `action="append"` (see
    # `_make_filter_parent` in `_parser_setup.py`), so argparse yields a
    # list-of-lists: one inner list per `--placeholders` occurrence.
    assert ns.placeholders == [["env=dev"], ["owner=app"]]


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


@pytest.mark.unit
def test_list_tools_is_exactly_the_oss_three(project):
    async def scenario(client):
        return sorted(t.name for t in (await client.list_tools()).tools)

    assert anyio.run(_session, scenario) == ["info", "migrate_dry_run", "validate"]


@pytest.mark.unit
def test_call_tool_info_accepts_a_list_for_tags(project):
    async def scenario(client):
        return await client.call_tool("info", {"tags": ["x"]})

    result = anyio.run(_session, scenario)

    assert result.is_error is False


@pytest.mark.unit
def test_info_and_history_resource_agree(project):
    async def scenario(client):
        info = await client.call_tool("info", {})
        history = await client.read_resource("dblift://history")
        return info, history

    info, history = anyio.run(_session, scenario)

    assert info.is_error is False
    assert info.structured_content["migrations"][0]["status"] == "PENDING"
    assert '"V1__init.sql"' in history.contents[0].text


@pytest.mark.unit
def test_migrate_dry_run_applies_nothing(project):
    async def scenario(client):
        dry = await client.call_tool("migrate_dry_run", {})
        after = await client.call_tool("info", {})
        return dry, after

    dry, after = anyio.run(_session, scenario)

    assert dry.structured_content["dry_run"] is True
    assert dry.structured_content["dry_run_count"] == 1
    assert after.structured_content["migrations"][0]["status"] == "PENDING"

    dry_migrations = dry.structured_content["migrations"]
    assert len(dry_migrations) == 1
    assert dry_migrations[0]["script"] == "V1__init.sql"
    assert dry_migrations[0]["status"] == "PENDING"


@pytest.mark.unit
def test_validate_reports_success(project):
    async def scenario(client):
        return await client.call_tool("validate", {})

    result = anyio.run(_session, scenario)

    assert result.structured_content["success"] is True


@pytest.mark.unit
def test_concurrent_tool_calls_do_not_corrupt_each_other(project, capsys):
    """Two tools called in parallel must each get their own payload, and leave stdout alone.

    The runner rewrites process-global state — ``sys.argv`` while parsing, and
    ``sys.stdout`` for the whole call — and the SDK runs sync tool bodies in
    worker threads. Without serialisation one call's redirect is torn down
    under the other: a result carries the wrong command's JSON, payload bytes
    escape to the real stdout (the JSON-RPC channel), and ``sys.stdout`` is
    left as a dead buffer.
    """
    import sys

    stdout_before = sys.stdout

    async def scenario(client):
        results = {}

        async def call(name):
            results[name] = await client.call_tool(name, {})

        async with anyio.create_task_group() as group:
            group.start_soon(call, "info")
            group.start_soon(call, "migrate_dry_run")
        return results

    for _ in range(5):
        results = anyio.run(_session, scenario)

        info, dry = results["info"], results["migrate_dry_run"]
        assert info.is_error is False, info.content[0].text
        assert dry.is_error is False, dry.content[0].text
        assert "migrations" in info.structured_content
        assert "dry_run" not in info.structured_content
        assert dry.structured_content["dry_run"] is True
        assert sys.stdout is stdout_before
        assert capsys.readouterr().out == ""
