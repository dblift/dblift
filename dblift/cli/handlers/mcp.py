"""Handler for the ``mcp`` command: serve dblift tools over stdio."""

from __future__ import annotations

from typing import Any, List, Tuple

from dblift.cli._output import CommandOutput
from dblift.cli.handlers._shared import CliCommandContext


def _handle_mcp(ctx: CliCommandContext) -> Tuple[bool, Any]:
    """Build the MCP server and block on stdin/stdout until the client disconnects.

    Zero-config: no project config or database is touched at start. Each tool
    call loads the config the way the CLI would, prefixed with the root flags
    this process was started with (``ctx.args.global_arguments``).
    """
    from dblift.cli.mcp.server import MissingMcpSdkError, build_server

    global_argv: List[str] = list(getattr(ctx.args, "global_arguments", None) or [])
    try:
        server = build_server(global_argv)
    except MissingMcpSdkError as exc:
        CommandOutput("console").error(str(exc))
        return (False, None)
    except Exception as exc:
        # A registrar contributed by an installed add-on package can fail the
        # build — a duplicate tool name, a signature the SDK rejects. Report
        # it as a CLI error; a traceback is not something the user can act on.
        CommandOutput("console").error(f"dblift mcp: could not start the server: {exc}")
        return (False, None)
    server.run_stdio()
    return (True, None)


_handle_mcp._dblift_zero_config_command = True  # type: ignore[attr-defined]
