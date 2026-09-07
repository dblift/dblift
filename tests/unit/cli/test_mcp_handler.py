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

    build.assert_called_once_with(["--config", "x.yaml"])
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
