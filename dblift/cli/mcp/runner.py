"""Run one CLI command in-process and hand back its ``--format json`` payload.

This is the seam every MCP tool goes through. It replays the four phases of
:func:`dblift.cli.main.main` for a single command — argv split, config load,
logging, client, handler — but never :func:`execute_single_command`, whose
``SystemExit`` on a capability denial would terminate the stdio server on the
first unlicensed call. Everything that would exit the CLI process becomes a
:class:`CommandInvocationError` carrying the exit code, and stdout is
redirected for the whole call: the JSON-RPC transport owns the real stream.

Stderr is captured too (so a failed command's detail can be quoted in the
raised error) but is *mirrored* rather than swallowed: the command's log
lines still reach the real stderr, which is where a stdio MCP server's own
diagnostics belong, leaving only stdout reserved for the JSON-RPC channel.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from typing import Any, Dict, Optional, Sequence

from dblift.cli._constants import EXIT_LICENSE_REQUIRED
from dblift.cli.handlers._shared import CliCommandContext
from dblift.core.seams.capabilities import CapabilityDeniedError
from dblift.core.seams.tier_resolver import resolve_tier

JSON_FORMAT_ARGV: tuple[str, ...] = ("--format", "json")
_LICENSE_FALLBACK = "This command requires a license that is not available."
_TAIL = 2000


class CommandInvocationError(Exception):
    """A command did not produce a payload; ``exit_code`` is what the CLI would have returned."""

    def __init__(self, message: str, exit_code: int) -> None:
        """Store *message* as the exception text and *exit_code* for the caller."""
        super().__init__(message)
        self.exit_code = exit_code


class _TeeStream:
    """A write target that both records text and mirrors it to another stream.

    Used for stderr: :func:`run_command` needs the text to build a detailed
    :class:`CommandInvocationError`, but the lines themselves must still
    reach the real stderr rather than vanish, unlike stdout.
    """

    def __init__(self, buffer: io.StringIO, mirror: Optional[Any]) -> None:
        """Record writes into *buffer* and, when *mirror* is set, forward them to it too."""
        self._buffer = buffer
        self._mirror = mirror

    def write(self, text: str) -> int:
        """Append *text* to the buffer and forward it to the mirror stream."""
        self._buffer.write(text)
        if self._mirror is not None:
            self._mirror.write(text)
        return len(text)

    def flush(self) -> None:
        """Flush the mirror stream, if any."""
        if self._mirror is not None:
            self._mirror.flush()


def run_command(
    global_argv: Sequence[str],
    command: str,
    argv: Sequence[str],
    *,
    json_argv: Optional[Sequence[str]] = JSON_FORMAT_ARGV,
) -> Dict[str, Any]:
    """Run ``dblift <global_argv> <command> <argv> [json_argv]`` and return its payload.

    With *json_argv* (default ``--format json``) the return value is the parsed
    stdout document. With ``json_argv=None`` the command has no machine format;
    the return value is ``{"success": <handler result>, "output": <stdout>}``.
    """
    from dblift.cli import main as cli_main
    from dblift.cli._command_handlers import _COMMAND_HANDLERS, _validate_migrate_options

    full_argv = [*global_argv, command, *argv, *(json_argv or ())]
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    stderr_tee = _TeeStream(stderr_buf, sys.stderr)
    log: Any = None
    success = False
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_tee):
            ctx = cli_main._parse_argv_and_load_config(full_argv)
            cli_main._setup_logging_and_output(ctx)
            log = ctx.log
            scripts_dir, additional_dirs, recursive, dir_map = (
                cli_main._resolve_scripts_directories(
                    ctx.args, ctx.config, ctx.parser, ctx.commands
                )
            )
            client = cli_main._build_command_client(ctx)
            placeholders = cli_main._collect_placeholders(ctx.args, ctx.config)
            if command == "migrate":
                _validate_migrate_options(ctx.args, ctx.parser)
            cli_main._ensure_connection(client, ctx.log, command)
            handler = _COMMAND_HANDLERS[command]
            success, _result = handler(
                CliCommandContext(
                    client=client,
                    args=ctx.args,
                    log=ctx.log,
                    scripts_dir=scripts_dir,
                    additional_scripts_dirs=additional_dirs,
                    recursive=recursive,
                    placeholders=placeholders,
                    dir_recursive_map=dir_map,
                    license_tier=resolve_tier(ctx.args),
                )
            )
    except CapabilityDeniedError as exc:
        message = str(exc).strip() or _LICENSE_FALLBACK
        raise CommandInvocationError(
            f"{message} (exit code {EXIT_LICENSE_REQUIRED})", EXIT_LICENSE_REQUIRED
        ) from exc
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        detail = stderr_buf.getvalue().strip()[-_TAIL:]
        raise CommandInvocationError(
            f"dblift {command} exited with code {code}: {detail}", code
        ) from exc
    finally:
        if log is not None:
            cli_main._close_logs(log)

    stdout = stdout_buf.getvalue()
    if json_argv is None:
        return {"success": bool(success), "output": stdout.strip()}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CommandInvocationError(
            f"dblift {command} produced no JSON on stdout: {stdout.strip()[-_TAIL:]}", 1
        ) from exc
    if not isinstance(payload, dict):
        return {"success": True, "result": payload}
    return payload
