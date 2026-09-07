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
        side_effect=CommandInvocationError("Plan requires an ENTERPRISE license (exit code 4)", 4),
    ):

        async def scenario(client):
            return await client.call_tool("t", {})

        result = anyio.run(_with_client, server, scenario)

    assert result.is_error is True
    assert "Plan requires an ENTERPRISE license (exit code 4)" in result.content[0].text


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
