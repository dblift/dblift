"""``dblift mcp`` — zero-config subcommand that serves stdio."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dblift.cli._command_handlers import _AVAILABLE_COMMANDS, _COMMAND_HANDLERS
from dblift.cli._parser_setup import create_parser
from dblift.cli.handlers._shared import CliCommandContext
from dblift.cli.handlers.mcp import _handle_mcp


@pytest.mark.unit
def test_mcp_is_a_registered_zero_config_command():
    assert "mcp" in _AVAILABLE_COMMANDS
    assert _COMMAND_HANDLERS["mcp"] is _handle_mcp
    assert getattr(_handle_mcp, "_dblift_zero_config_command", False) is True
    assert create_parser(exit_on_error=False).parse_args(["mcp"]).command == "mcp"


@pytest.mark.unit
def test_handle_mcp_builds_server_with_global_argv_and_serves():
    server = MagicMock()
    ctx = CliCommandContext(args=SimpleNamespace(global_arguments=["--config", "x.yaml"]))

    with patch("dblift.cli.mcp.server.build_server", return_value=server) as build:
        assert _handle_mcp(ctx) == (True, None)

    build.assert_called_once_with(["--config", "x.yaml"], allow_writes=True, allowed_tools=None)
    server.run_stdio.assert_called_once_with()


@pytest.mark.unit
def test_handle_mcp_reports_missing_sdk_on_stderr(capsys):
    from dblift.cli.mcp.server import SDK_HINT, MissingMcpSdkError

    with patch("dblift.cli.mcp.server.build_server", side_effect=MissingMcpSdkError(SDK_HINT)):
        assert _handle_mcp(CliCommandContext(args=SimpleNamespace())) == (False, None)

    captured = capsys.readouterr()
    assert 'pip install "dblift[mcp]"' in captured.err
    assert captured.out == ""


@pytest.mark.unit
def test_zero_config_dispatch_passes_global_arguments(monkeypatch):
    from dblift.cli import main as cli_main

    seen = {}

    def fake(ctx):
        seen["global"] = ctx.args.global_arguments
        return (True, None)

    fake._dblift_zero_config_command = True
    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {**cli_main._COMMAND_HANDLERS, "mcp": fake})

    with pytest.raises(SystemExit) as exc_info:
        cli_main._parse_argv_and_load_config(["--config", "x.yaml", "--log-level", "debug", "mcp"])

    assert exc_info.value.code == 0
    assert seen["global"] == ["--config", "x.yaml", "--log-level", "debug"]


@pytest.mark.unit
def test_handle_mcp_reports_a_failed_build_instead_of_a_traceback(capsys):
    """A registrar that raises must not reach the user as an unhandled traceback."""
    pytest.importorskip("mcp")

    def broken(server):
        raise ValueError("Duplicate MCP tool: info")

    with patch("dblift.cli.mcp.server.load_mcp_tool_registrars", return_value=[broken]):
        assert _handle_mcp(CliCommandContext(args=SimpleNamespace())) == (False, None)

    captured = capsys.readouterr()
    assert "could not start the server" in captured.err
    assert "Duplicate MCP tool: info" in captured.err
    assert captured.out == ""


# --- v2: `--read-only` and `--tools` -----------------------------------------


def _quiet_server():
    """A server double that skipped nothing and matched every allowlisted name."""
    server = MagicMock()
    server.skipped_tools.return_value = []
    server.unmatched_allowed_tools.return_value = []
    return server


@pytest.mark.unit
def test_mcp_parser_accepts_read_only_and_tools():
    parser = create_parser(exit_on_error=False)

    default = parser.parse_args(["mcp"])
    assert default.read_only is False
    assert default.tools is None

    restricted = parser.parse_args(["mcp", "--read-only", "--tools", "info,validate"])
    assert restricted.read_only is True
    assert restricted.tools == "info,validate"


@pytest.mark.unit
def test_read_only_is_a_known_subcommand_boolean_flag():
    """`_extract_commands_from_argv` looks one token ahead after an unknown
    `--flag` and treats it as the flag's value; a boolean flag must be listed
    so it never swallows what follows it."""
    from dblift.cli._config_helpers import _SUBCOMMAND_BOOLEAN_FLAGS

    assert "--read-only" in _SUBCOMMAND_BOOLEAN_FLAGS


@pytest.mark.unit
def test_zero_config_dispatch_keeps_tools_value_out_of_the_command_list(monkeypatch):
    """`--tools info` names a command; the splitter must read `info` as the
    flag's value, not as a second chained command."""
    from dblift.cli import main as cli_main

    seen = {}

    def fake(ctx):
        seen["tools"] = ctx.args.tools
        seen["read_only"] = ctx.args.read_only
        return (True, None)

    fake._dblift_zero_config_command = True
    monkeypatch.setattr(cli_main, "_COMMAND_HANDLERS", {**cli_main._COMMAND_HANDLERS, "mcp": fake})

    with pytest.raises(SystemExit) as exc_info:
        cli_main._parse_argv_and_load_config(["mcp", "--read-only", "--tools", "info,validate"])

    assert exc_info.value.code == 0
    assert seen == {"tools": "info,validate", "read_only": True}


@pytest.mark.unit
def test_handle_mcp_passes_the_restrictions_to_build_server():
    server = _quiet_server()
    ctx = CliCommandContext(
        args=SimpleNamespace(global_arguments=[], read_only=True, tools=" info, validate,,")
    )

    with patch("dblift.cli.mcp.server.build_server", return_value=server) as build:
        assert _handle_mcp(ctx) == (True, None)

    build.assert_called_once_with([], allow_writes=False, allowed_tools=["info", "validate"])
    server.run_stdio.assert_called_once_with()


@pytest.mark.unit
def test_handle_mcp_reports_each_skipped_tool_on_stderr_and_still_serves(capsys):
    """Skips are diagnostics: stderr, never stdout (the JSON-RPC channel)."""
    server = _quiet_server()
    server.skipped_tools.return_value = [
        ("export_schema", "declares read_only=False and the server was started --read-only"),
        ("validate", "not in --tools"),
    ]
    ctx = CliCommandContext(args=SimpleNamespace(global_arguments=[], read_only=True, tools=None))

    with patch("dblift.cli.mcp.server.build_server", return_value=server):
        assert _handle_mcp(ctx) == (True, None)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "export_schema" in captured.err and "read_only=False" in captured.err
    assert "validate" in captured.err
    server.run_stdio.assert_called_once_with()


@pytest.mark.unit
def test_handle_mcp_refuses_to_start_on_an_unknown_allowlisted_tool(capsys):
    """A name nothing registered is an operator error, not a quieter server."""
    server = _quiet_server()
    server.unmatched_allowed_tools.return_value = ["nope"]
    ctx = CliCommandContext(args=SimpleNamespace(global_arguments=[], read_only=False, tools="info,nope"))

    with patch("dblift.cli.mcp.server.build_server", return_value=server):
        assert _handle_mcp(ctx) == (False, None)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nope" in captured.err and "--tools" in captured.err
    server.run_stdio.assert_not_called()


@pytest.mark.unit
def test_handle_mcp_refuses_an_empty_allowlist(capsys):
    server = _quiet_server()
    ctx = CliCommandContext(args=SimpleNamespace(global_arguments=[], read_only=False, tools=" , "))

    with patch("dblift.cli.mcp.server.build_server", return_value=server) as build:
        assert _handle_mcp(ctx) == (False, None)

    build.assert_not_called()
    assert "--tools" in capsys.readouterr().err
