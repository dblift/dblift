"""``DbliftMcpServer`` — MCPServer wrapper, exercised through the SDK's in-memory client."""

from __future__ import annotations

import builtins
from typing import List, Optional
from unittest.mock import patch

import pytest

# Both skips must come before *any* import of the optional stack: `anyio`
# arrives with the `mcp` extra, so a plain `import anyio` at module level
# turns a skip into a collection error on an install without it.
pytest.importorskip("mcp")
anyio = pytest.importorskip("anyio")

from dblift.cli.mcp.runner import CommandInvocationError  # noqa: E402


def _server(global_argv=()):
    from dblift.cli.mcp.server import DbliftMcpServer

    return DbliftMcpServer(list(global_argv))


async def _with_client(server, fn):
    from mcp import Client

    async with Client(server.mcpserver) as client:
        return await fn(client)


@pytest.mark.unit
def test_command_tool_exposes_signature_and_read_only_annotations():
    server = _server()

    def echo_argv(*, name: str, loud: bool = False) -> list[str]:
        """Echo."""
        return ["--name", name]

    server.command_tool(name="echo", command="info", description="Echo tool", fn=echo_argv)

    async def scenario(client):
        return await client.list_tools()

    tools = anyio.run(_with_client, server, scenario).tools
    (tool,) = tools
    assert tool.name == "echo"
    assert tool.description == "Echo tool"
    assert set(tool.input_schema["properties"]) == {"name", "loud"}
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False


@pytest.mark.unit
def test_server_instructions_scope_validate_to_history_not_sql():
    """The instructions must not oversell `validate`: it checks migration
    history against scripts (checksums, ordering, missing files); it does
    not parse or check the SQL inside them."""
    from dblift.cli.mcp.server import SERVER_INSTRUCTIONS

    normalized = " ".join(SERVER_INSTRUCTIONS.split())
    assert "does not parse or check the SQL" in normalized


@pytest.mark.unit
def test_server_instructions_scope_read_only_to_built_in_tools():
    """`read_only=False` add-on tools exist, so the instructions must not
    claim the whole server is read-only or that no tool changes data; they
    must scope those claims to the built-in tools and defer to each tool's
    own read-only hint."""
    from dblift.cli.mcp.server import SERVER_INSTRUCTIONS

    normalized = " ".join(SERVER_INSTRUCTIONS.split())
    assert "(read-only)" not in normalized
    assert "built-in" in normalized
    assert "own read-only hint" in normalized


@pytest.mark.unit
def test_command_tool_read_only_false_flips_annotations():
    server = _server()

    server.command_tool(
        name="writer",
        command="info",
        description="Writes a file",
        fn=lambda: [],
        read_only=False,
    )
    server.command_tool(name="reader", command="info", description="Reads only", fn=lambda: [])

    async def scenario(client):
        return {t.name: t for t in (await client.list_tools()).tools}

    tools = anyio.run(_with_client, server, scenario)

    assert tools["writer"].annotations.read_only_hint is False
    assert tools["writer"].annotations.idempotent_hint is False
    assert tools["writer"].annotations.destructive_hint is False
    assert tools["writer"].annotations.open_world_hint is False

    assert tools["reader"].annotations.read_only_hint is True
    assert tools["reader"].annotations.idempotent_hint is True


@pytest.mark.unit
def test_command_tool_runs_command_with_global_argv_and_returns_structured_content():
    server = _server(["--config", "x.yaml"])
    server.command_tool(
        name="t", command="info", description="d", fn=lambda *, v: ["--versions", v]
    )

    with patch("dblift.cli.mcp.server.run_command", return_value={"success": True, "v": "1"}) as rc:

        async def scenario(client):
            return await client.call_tool("t", {"v": "1"})

        result = anyio.run(_with_client, server, scenario)

    rc.assert_called_once_with(
        ["--config", "x.yaml"], "info", ["--versions", "1"], json_argv=("--format", "json")
    )
    assert result.is_error is False
    assert result.structured_content == {"success": True, "v": "1"}


@pytest.mark.unit
def test_invocation_error_becomes_is_error_result_with_message():
    server = _server()
    server.command_tool(name="t", command="info", description="d", fn=lambda: [])

    with patch(
        "dblift.cli.mcp.server.run_command",
        side_effect=CommandInvocationError(
            "Feature requires a higher license tier (exit code 4)", 4
        ),
    ):

        async def scenario(client):
            return await client.call_tool("t", {})

        result = anyio.run(_with_client, server, scenario)

    assert result.is_error is True
    assert "Feature requires a higher license tier (exit code 4)" in result.content[0].text


@pytest.mark.unit
def test_duplicate_tool_name_is_rejected():
    server = _server()
    server.command_tool(name="t", command="info", description="d", fn=lambda: [])

    with pytest.raises(ValueError, match="Duplicate MCP tool: t"):
        server.command_tool(name="t", command="validate", description="d", fn=lambda: [])


@pytest.mark.unit
def test_command_resource_reads_through_run_command():
    server = _server()
    server.command_resource(
        uri="dblift://history",
        name="history",
        description="d",
        command="info",
        argv=[],
        pick=lambda payload: payload["migrations"],
    )

    with patch(
        "dblift.cli.mcp.server.run_command", return_value={"migrations": [{"script": "V1"}]}
    ):

        async def scenario(client):
            return await client.read_resource("dblift://history")

        result = anyio.run(_with_client, server, scenario)

    assert '"script": "V1"' in result.contents[0].text


@pytest.mark.unit
def test_raw_tool_uses_signature_of_and_calls_fn_directly():
    server = _server()

    def shape(*, snapshot: str, fail_on: str = "error") -> list[str]:
        """Shape only."""
        return []

    calls = []
    server.raw_tool(
        name="report",
        description="d",
        fn=lambda **kw: calls.append(kw) or {"success": True, "kw": kw},
        signature_of=shape,
    )

    async def scenario(client):
        tools = (await client.list_tools()).tools
        result = await client.call_tool("report", {"snapshot": "s.json"})
        return tools, result

    tools, result = anyio.run(_with_client, server, scenario)

    assert set(tools[0].input_schema["properties"]) == {"snapshot", "fail_on"}
    assert tools[0].annotations.read_only_hint is True
    assert result.structured_content == {
        "success": True,
        "kw": {"snapshot": "s.json", "fail_on": "error"},
    }
    assert calls == [{"snapshot": "s.json", "fail_on": "error"}]


@pytest.mark.unit
def test_build_server_loads_feature_extensions_first():
    from dblift.cli.mcp.server import build_server

    with (
        patch("dblift.cli.mcp.server.load_feature_extensions") as load,
        patch("dblift.cli.mcp.server.load_mcp_tool_registrars", return_value=[]),
    ):
        build_server([])

    load.assert_called_once_with()


@pytest.mark.unit
def test_build_server_registers_oss_tools_then_registrars():
    from dblift.cli.mcp.server import build_server

    seen = []

    def registrar(server):
        seen.append([t for t in server.tool_names()])
        server.command_tool(name="extra", command="info", description="d", fn=lambda: [])

    with patch("dblift.cli.mcp.server.load_mcp_tool_registrars", return_value=[registrar]):
        server = build_server([])

    assert seen == [["info", "validate", "migrate_dry_run"]]
    assert server.tool_names() == ["info", "validate", "migrate_dry_run", "extra"]


@pytest.mark.unit
def test_missing_sdk_is_reported_with_the_extra_name(monkeypatch):
    from dblift.cli.mcp import server as server_mod

    real_import = builtins.__import__

    def no_mcp(name, *args, **kwargs):
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("No module named 'mcp'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mcp)

    with pytest.raises(server_mod.MissingMcpSdkError, match='pip install "dblift\\[mcp\\]"'):
        server_mod.build_server([])


@pytest.mark.unit
def test_tool_registration_resolves_string_annotations():
    """A registrar written with ``typing`` names under PEP 563 must still register.

    This module has ``from __future__ import annotations``, so ``Optional[str]``
    reaches the SDK as the *string* ``"Optional[str]"`` unless the server
    resolves it. The SDK cannot build a schema from an unresolved name and
    rejects the tool at registration — which aborts ``build_server``, so
    ``dblift mcp`` never starts.
    """
    server = _server()

    def shape(*, snapshot: Optional[str] = None, tags: List[str] = []) -> list[str]:
        """Shape only."""
        return []

    server.raw_tool(name="report", description="d", fn=lambda **kw: {}, signature_of=shape)

    async def scenario(client):
        return (await client.list_tools()).tools

    (tool,) = anyio.run(_with_client, server, scenario)
    properties = tool.input_schema["properties"]
    assert set(properties) == {"snapshot", "tags"}
    assert properties["tags"]["type"] == "array"
    assert properties["tags"]["items"] == {"type": "string"}


@pytest.mark.unit
def test_resource_failure_carries_the_cli_message():
    """A failing resource must report the CLI's own message, like a tool does."""
    server = _server()
    server.command_resource(
        uri="dblift://history",
        name="history",
        description="d",
        command="info",
        argv=[],
        pick=lambda payload: payload["migrations"],
    )

    with patch(
        "dblift.cli.mcp.server.run_command",
        side_effect=CommandInvocationError("no config here", 1),
    ):

        async def scenario(client):
            from mcp.shared.exceptions import MCPError

            with pytest.raises(MCPError) as exc_info:
                await client.read_resource("dblift://history")
            return str(exc_info.value)

        message = anyio.run(_with_client, server, scenario)

    assert "no config here" in message


# --- v2: destructive=, the write boundary, the allowlist ---------------------


@pytest.mark.unit
def test_destructive_true_sets_destructive_hint_on_a_writing_tool():
    """A tool that overwrites a caller-named path must be able to say so.

    ``destructive_hint`` is only meaningful when ``read_only_hint`` is
    False (MCP spec); a writing tool that does not pass ``destructive=``
    stays additive (False), so an honest registrar has to opt in.
    """
    server = _server()

    server.command_tool(
        name="overwriter",
        command="info",
        description="Replaces a file",
        fn=lambda: [],
        read_only=False,
        destructive=True,
    )
    server.command_tool(
        name="appender",
        command="info",
        description="Adds a file",
        fn=lambda: [],
        read_only=False,
    )
    server.raw_tool(
        name="raw_overwriter",
        description="Replaces a file",
        fn=lambda **kw: {},
        signature_of=lambda: [],
        read_only=False,
        destructive=True,
    )

    async def scenario(client):
        return {t.name: t for t in (await client.list_tools()).tools}

    tools = anyio.run(_with_client, server, scenario)

    assert tools["overwriter"].annotations.read_only_hint is False
    assert tools["overwriter"].annotations.destructive_hint is True
    assert tools["overwriter"].annotations.idempotent_hint is False
    assert tools["raw_overwriter"].annotations.destructive_hint is True
    assert tools["appender"].annotations.destructive_hint is False


@pytest.mark.unit
def test_destructive_requires_read_only_false():
    """A read-only destructive tool is a contradiction, and a registrar bug."""
    server = _server()

    with pytest.raises(ValueError, match="destructive=True requires read_only=False"):
        server.command_tool(
            name="nonsense",
            command="info",
            description="d",
            fn=lambda: [],
            destructive=True,
        )
    with pytest.raises(ValueError, match="destructive=True requires read_only=False"):
        server.raw_tool(
            name="nonsense",
            description="d",
            fn=lambda **kw: {},
            signature_of=lambda: [],
            destructive=True,
        )
    assert server.tool_names() == []


@pytest.mark.unit
def test_write_forbidding_server_skips_writing_tools_and_logs_each(caplog):
    """The extension boundary: a registrar declaring ``read_only=False`` on a
    server that forbids writes has that tool skipped — not raised, which would
    abort ``build_server`` and leave the operator with no server at all."""
    import logging

    from dblift.cli.mcp.server import DbliftMcpServer

    server = DbliftMcpServer([], allow_writes=False)
    assert server.allow_writes is False

    with caplog.at_level(logging.WARNING, logger="dblift.cli.mcp.server"):
        server.command_tool(
            name="writer", command="info", description="Writes", fn=lambda: [], read_only=False
        )
        server.raw_tool(
            name="raw_writer",
            description="Writes",
            fn=lambda **kw: {},
            signature_of=lambda: [],
            read_only=False,
            destructive=True,
        )
        server.command_tool(name="reader", command="info", description="Reads", fn=lambda: [])

    async def scenario(client):
        return [t.name for t in (await client.list_tools()).tools]

    assert anyio.run(_with_client, server, scenario) == ["reader"]
    assert server.tool_names() == ["reader"]

    skipped = dict(server.skipped_tools())
    assert set(skipped) == {"writer", "raw_writer"}
    assert "read_only=False" in skipped["writer"]
    logged = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("writer" in line for line in logged)
    assert any("raw_writer" in line for line in logged)


@pytest.mark.unit
def test_a_permissive_server_records_no_skips():
    server = _server()
    server.command_tool(
        name="writer", command="info", description="Writes", fn=lambda: [], read_only=False
    )

    assert server.allow_writes is True
    assert server.skipped_tools() == []
    assert server.unmatched_allowed_tools() == []


@pytest.mark.unit
def test_skipped_tool_names_are_still_reserved():
    """A skipped registration must not free its name for a later registrar —
    the tool list would otherwise depend on install order (see registry)."""
    from dblift.cli.mcp.server import DbliftMcpServer

    server = DbliftMcpServer([], allow_writes=False)
    server.command_tool(
        name="writer", command="info", description="Writes", fn=lambda: [], read_only=False
    )

    with pytest.raises(ValueError, match="Duplicate MCP tool: writer"):
        server.command_tool(name="writer", command="info", description="Reads", fn=lambda: [])


@pytest.mark.unit
def test_allowlist_admits_only_the_named_tools():
    """The restricted mode is an allowlist (D3): a tool a registrar forgot to
    describe — or described dishonestly — is not admitted by omission."""
    from dblift.cli.mcp.server import build_server

    def registrar(server):
        server.command_tool(name="extra", command="info", description="d", fn=lambda: [])
        server.command_tool(
            name="writer", command="info", description="d", fn=lambda: [], read_only=False
        )

    with patch("dblift.cli.mcp.server.load_mcp_tool_registrars", return_value=[registrar]):
        server = build_server([], allowed_tools=["info", "writer"])

    async def scenario(client):
        return sorted(t.name for t in (await client.list_tools()).tools)

    assert anyio.run(_with_client, server, scenario) == ["info", "writer"]
    assert {name for name, _reason in server.skipped_tools()} == {
        "validate",
        "migrate_dry_run",
        "extra",
    }
    assert server.unmatched_allowed_tools() == []


@pytest.mark.unit
def test_allowlist_names_nothing_offered_are_reported_not_ignored():
    """A typo in the allowlist must not silently produce a smaller server."""
    from dblift.cli.mcp.server import build_server

    with patch("dblift.cli.mcp.server.load_mcp_tool_registrars", return_value=[]):
        server = build_server([], allowed_tools=["info", "nope", "export_schema"])

    assert server.tool_names() == ["info"]
    assert server.unmatched_allowed_tools() == ["export_schema", "nope"]


@pytest.mark.unit
def test_allowlist_and_write_boundary_compose():
    """``--read-only --tools writer``: the allowlist admits the name, the
    boundary still refuses the declaration. Both reasons are visible."""
    from dblift.cli.mcp.server import build_server

    def registrar(server):
        server.command_tool(
            name="writer", command="info", description="d", fn=lambda: [], read_only=False
        )

    with patch("dblift.cli.mcp.server.load_mcp_tool_registrars", return_value=[registrar]):
        server = build_server([], allow_writes=False, allowed_tools=["info", "writer"])

    assert server.tool_names() == ["info"]
    skipped = dict(server.skipped_tools())
    assert "writer" in skipped and "read_only=False" in skipped["writer"]
    assert server.unmatched_allowed_tools() == []


@pytest.mark.unit
def test_build_server_defaults_are_permissive():
    """No flag, no restriction: the v1 behaviour is unchanged."""
    from dblift.cli.mcp.server import build_server

    with patch("dblift.cli.mcp.server.load_mcp_tool_registrars", return_value=[]):
        server = build_server([])

    assert server.allow_writes is True
    assert server.tool_names() == ["info", "validate", "migrate_dry_run"]
    assert server.skipped_tools() == []


@pytest.mark.unit
def test_instructions_tell_a_restricted_session_to_trust_tools_list():
    """The instructions name `validate`, `migrate_dry_run` and `info` as the
    workflow. Under `--tools` or `--read-only` some of those may not be served,
    so a restricted server must say so and point the agent at `tools/list`;
    an unrestricted server keeps the instructions unchanged."""
    from dblift.cli.mcp.server import SERVER_INSTRUCTIONS, DbliftMcpServer

    async def scenario(client):
        return client.instructions

    plain = anyio.run(_with_client, DbliftMcpServer([]), scenario)
    assert plain == SERVER_INSTRUCTIONS

    allowlisted = anyio.run(_with_client, DbliftMcpServer([], allowed_tools=["info"]), scenario)
    assert allowlisted.startswith(SERVER_INSTRUCTIONS)
    assert "tools/list" in allowlisted
    assert "restricted" in allowlisted

    write_forbidding = anyio.run(_with_client, DbliftMcpServer([], allow_writes=False), scenario)
    assert write_forbidding.startswith(SERVER_INSTRUCTIONS)
    assert "tools/list" in write_forbidding
