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

Any exception the handler raises — not just :class:`SystemExit` and
:class:`~dblift.core.seams.capabilities.CapabilityDeniedError` — becomes a
:class:`CommandInvocationError`; only :class:`KeyboardInterrupt` and other
non-:class:`Exception` signals still propagate. The client built for the
call is closed afterward when it exposes a callable ``close`` (some
handlers get a config-only stand-in with none), so a long-lived server
making many calls does not leak one connection per call.

Calls are serialised by a module-level lock. A client may issue several
tool calls at once and the SDK runs synchronous tool bodies in worker
threads, but everything a call reaches for is process-global: ``sys.argv``
(rewritten while the argv is parsed), ``sys.stdout`` and ``sys.stderr``
(redirected here), the ``LogFactory`` class attributes and the console
header flag. Concurrent calls therefore dismantle each other's redirects
and namespaces — one command's payload can be returned for another, and
bytes meant for a tool result escape to the real stdout, which is the
JSON-RPC channel. One command at a time is the only safe reading of that
shared state.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
from typing import Any, Dict, Optional, Sequence

from dblift.cli._constants import EXIT_LICENSE_REQUIRED
from dblift.cli.handlers._shared import CliCommandContext
from dblift.core.seams.capabilities import CapabilityDeniedError
from dblift.core.seams.tier_resolver import resolve_tier

JSON_FORMAT_ARGV: tuple[str, ...] = ("--format", "json")
_LICENSE_FALLBACK = "This command requires a license that is not available."
_TAIL = 2000
_CALL_LOCK = threading.Lock()


class CommandInvocationError(Exception):
    """A command did not produce a payload; ``exit_code`` is what the CLI would have returned."""

    def __init__(self, message: str, exit_code: int) -> None:
        """Store *message* as the exception text and *exit_code* for the caller."""
        super().__init__(message)
        self.exit_code = exit_code


class _TeeStream(io.TextIOBase):
    """A write target that both records text and mirrors it to another stream.

    Used for stderr: :func:`run_command` needs the text to build a detailed
    :class:`CommandInvocationError`, but the lines themselves must still
    reach the real stderr rather than vanish, unlike stdout.

    Subclasses :class:`io.TextIOBase` so a command reaching past ``write`` —
    ``writelines``, ``isatty``, ``fileno`` — meets a real text stream rather
    than an :class:`AttributeError`.
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

    def writable(self) -> bool:
        """Report the stream as writable — that is the only thing it is for."""
        return True

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
    the return value is ``{"success": <handler result>, "output": <text>}``,
    where *text* is the captured stdout followed by the captured stderr (each
    stripped, joined with a newline, empty parts omitted) — a command's real
    content is rendered through the console logger, which writes to stderr,
    so stdout alone would only ever carry the "DBLIFT COMMAND" banner.

    One call at a time: the module docstring lists the process-global state a
    call rewrites. A second caller waits rather than corrupting the first.
    """
    with _CALL_LOCK:
        return _run_command_locked(global_argv, command, argv, json_argv=json_argv)


def _run_command_locked(
    global_argv: Sequence[str],
    command: str,
    argv: Sequence[str],
    *,
    json_argv: Optional[Sequence[str]],
) -> Dict[str, Any]:
    """Body of :func:`run_command`; the caller must hold :data:`_CALL_LOCK`."""
    from dblift.cli import main as cli_main
    from dblift.cli._command_handlers import _COMMAND_HANDLERS, _validate_migrate_options

    full_argv = [*global_argv, command, *argv, *(json_argv or ())]
    stdout_buf, stderr_buf = io.StringIO(), io.StringIO()
    stderr_tee = _TeeStream(stderr_buf, sys.stderr)
    log: Any = None
    client: Any = None
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
    except Exception as exc:
        raise CommandInvocationError(f"{type(exc).__name__}: {exc}", 1) from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:  # a failed close must not mask the result
                if log is not None:
                    log.debug(f"Closing the client for '{command}' failed: {exc}")
        if log is not None:
            cli_main._close_logs(log)

    stdout = stdout_buf.getvalue()
    if json_argv is None:
        # A text-mode command's real content is rendered through the console
        # logger, which writes to stderr — only the "DBLIFT COMMAND" banner
        # (if any) reaches stdout. Join both, stdout first, so the caller
        # gets the actual output rather than just the banner.
        parts = [part.strip() for part in (stdout, stderr_buf.getvalue()) if part.strip()]
        return {"success": bool(success), "output": "\n".join(parts)}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CommandInvocationError(
            f"dblift {command} produced no JSON on stdout: {stdout.strip()[-_TAIL:]}", 1
        ) from exc
    if not isinstance(payload, dict):
        return {"success": True, "result": payload}
    return payload
