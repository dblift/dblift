"""Handler for the ``mcp`` command: serve dblift tools over stdio."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from dblift.cli._output import CommandOutput
from dblift.cli.handlers._shared import CliCommandContext


def _handle_mcp(ctx: CliCommandContext) -> Tuple[bool, Any]:
    """Build the MCP server and block on stdin/stdout until the client disconnects.

    Zero-config: no project config or database is touched at start. Each tool
    call loads the config the way the CLI would, prefixed with the root flags
    this process was started with (``ctx.args.global_arguments``).

    ``--read-only`` builds the server write-forbidding; ``--tools`` gives it an
    allowlist. A tool the server skipped is reported on stderr and the server
    still starts; an allowlisted name nothing registered refuses to start.
    """
    from dblift.cli.mcp.server import MissingMcpSdkError, build_server

    global_argv: List[str] = list(getattr(ctx.args, "global_arguments", None) or [])
    read_only = bool(getattr(ctx.args, "read_only", False))
    raw_tools = getattr(ctx.args, "tools", None)
    allowed_tools: Optional[List[str]] = None
    if raw_tools is not None:
        allowed_tools = [name.strip() for name in raw_tools.split(",") if name.strip()]
        if not allowed_tools:
            CommandOutput("console").error("dblift mcp: --tools needs at least one tool name")
            return (False, None)
    try:
        server = build_server(global_argv, allow_writes=not read_only, allowed_tools=allowed_tools)
    except MissingMcpSdkError as exc:
        CommandOutput("console").error(str(exc))
        return (False, None)
    except Exception as exc:
        # A registrar contributed by an installed add-on package can fail the
        # build — a duplicate tool name, a signature the SDK rejects. Report
        # it as a CLI error; a traceback is not something the user can act on.
        CommandOutput("console").error(f"dblift mcp: could not start the server: {exc}")
        return (False, None)
    unmatched = list(server.unmatched_allowed_tools())
    if unmatched:
        CommandOutput("console").error(
            f"dblift mcp: unknown tool(s) in --tools: {', '.join(unmatched)}"
        )
        return (False, None)
    for name, reason in server.skipped_tools():
        # `.error()` on purpose: `.status()` routes to stdout in human mode and
        # stdout is the JSON-RPC channel; `.error()` is the only method that
        # always goes to stderr.
        CommandOutput("console").error(f"dblift mcp: skipped tool {name}: {reason}")
    server.run_stdio()
    return (True, None)


_handle_mcp._dblift_zero_config_command = True  # type: ignore[attr-defined]
