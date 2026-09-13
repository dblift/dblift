"""Handler for the ``mcp`` command: serve dblift tools over stdio."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from dblift.cli._output import CommandOutput
from dblift.cli.handlers._shared import CliCommandContext


def _name_list(raw: Optional[str], flag: str) -> Tuple[Optional[List[str]], bool]:
    """Split a comma-separated allowlist; the bool is False when it is empty.

    ``(None, True)`` means the flag was not passed, which is "no allowlist" —
    distinct from a flag passed with nothing usable in it, which is an
    operator error and refuses to start.
    """
    if raw is None:
        return (None, True)
    names = [name.strip() for name in raw.split(",") if name.strip()]
    if not names:
        CommandOutput("console").error(f"dblift mcp: {flag} needs at least one name")
        return (None, False)
    return (names, True)


def _handle_mcp(ctx: CliCommandContext) -> Tuple[bool, Any]:
    """Build the MCP server and block on stdin/stdout until the client disconnects.

    Zero-config: no project config or database is touched at start. Each tool
    call loads the config the way the CLI would, prefixed with the root flags
    this process was started with (``ctx.args.global_arguments``).

    ``--read-only`` builds the server write-forbidding; ``--tools`` gives it an
    allowlist and ``--resources`` gives the resources their own. A tool or
    resource the server skipped is reported on stderr and the server still
    starts; an allowlisted name nothing registered refuses to start.
    ``--offline`` skips nothing: every tool and resource that opens a database
    connection stays served and refuses at call time, and which ones those are
    is reported on stderr at start-up. ``--mode review`` withholds the same
    tools ``--read-only`` does and says the session is for review; the mode is
    forwarded as it stands rather than translated into ``allow_writes``, so the
    skip reason on stderr names the flag that withheld each tool.
    """
    from dblift.cli.mcp.server import MissingMcpSdkError, build_server

    global_argv: List[str] = list(getattr(ctx.args, "global_arguments", None) or [])
    read_only = bool(getattr(ctx.args, "read_only", False))
    offline = bool(getattr(ctx.args, "offline", False))
    mode = str(getattr(ctx.args, "mode", None) or "author")
    allowed_tools, tools_ok = _name_list(getattr(ctx.args, "tools", None), "--tools")
    allowed_resources, resources_ok = _name_list(
        getattr(ctx.args, "resources", None), "--resources"
    )
    if not tools_ok or not resources_ok:
        return (False, None)
    try:
        server = build_server(
            global_argv,
            allow_writes=not read_only,
            allowed_tools=allowed_tools,
            allowed_resources=allowed_resources,
            offline=offline,
            mode=mode,
        )
    except MissingMcpSdkError as exc:
        CommandOutput("console").error(str(exc))
        return (False, None)
    except Exception as exc:
        # A registrar contributed by an installed add-on package can fail the
        # build — a duplicate tool name, a signature the SDK rejects. Report
        # it as a CLI error; a traceback is not something the user can act on.
        CommandOutput("console").error(f"dblift mcp: could not start the server: {exc}")
        return (False, None)
    # Both allowlists are checked before refusing, so a typo in each is
    # reported once rather than one restart at a time.
    unknown_names = False
    unmatched = list(server.unmatched_allowed_tools())
    if unmatched:
        # Name what this install offers, registered or skipped, so the
        # operator can correct the list without reading the docs.
        offered = sorted(
            set(server.tool_names()) | {name for name, _reason in server.skipped_tools()}
        )
        CommandOutput("console").error(
            f"dblift mcp: unknown tool(s) in --tools: {', '.join(unmatched)}. "
            f"Tools this install offers: {', '.join(offered)}. "
            "(Resources are fenced by --resources, not --tools.)"
        )
        unknown_names = True
    unmatched_resources = list(server.unmatched_allowed_resources())
    if unmatched_resources:
        offered = sorted(
            set(server.resource_names()) | {name for name, _reason in server.skipped_resources()}
        )
        CommandOutput("console").error(
            f"dblift mcp: unknown resource(s) in --resources: {', '.join(unmatched_resources)}. "
            f"Resources this install offers: {', '.join(offered)} "
            "(their dblift:// URIs are accepted too)."
        )
        unknown_names = True
    if unknown_names:
        return (False, None)
    if offline:
        # Said once at start-up, on stderr: the alternative is an operator who
        # learns which tools refuse one failed agent call at a time.
        bound = list(server.connection_bound_tools())
        bound_resources = list(server.connection_bound_resources())
        # Two labelled groups, not one run-on list: a resource reads as a URI
        # and a tool as a bare name, and the operator has a flag for each.
        groups = []
        if bound:
            groups.append(f"tools: {', '.join(bound)}")
        if bound_resources:
            groups.append(f"resources: {', '.join(bound_resources)}")
        if groups:
            CommandOutput("console").error(
                "dblift mcp: --offline: these open a database connection and will "
                f"refuse every call: {'; '.join(groups)}"
            )
    for name, reason in server.skipped_tools():
        # `.error()` on purpose: `.status()` routes to stdout in human mode and
        # stdout is the JSON-RPC channel; `.error()` is the only method that
        # always goes to stderr.
        CommandOutput("console").error(f"dblift mcp: skipped tool {name}: {reason}")
    for name, reason in server.skipped_resources():
        CommandOutput("console").error(f"dblift mcp: skipped resource {name}: {reason}")
    server.run_stdio()
    return (True, None)


_handle_mcp._dblift_zero_config_command = True  # type: ignore[attr-defined]
