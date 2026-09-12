"""Run one CLI command in-process and hand back its ``--format json`` payload.

This is the seam every MCP tool goes through. It replays the four phases of
:func:`dblift.cli.main.main` for a single command — argv split, config load,
logging, client, handler — but never :func:`execute_single_command`, whose
``SystemExit`` on a capability denial would terminate the stdio server on the
first unlicensed call. Everything that would exit the CLI process becomes a
:class:`CommandInvocationError` carrying the exit code, and stdout is
redirected for the whole call: the JSON-RPC transport owns the real stream.

Stderr is captured too: a command's content may render through the stdout
console or through the console logger, which writes to stderr, and a
text-mode call joins both so the logger's lines are not lost. Capture also
lets a failed command's detail be quoted in the raised error. It is
*mirrored* rather than swallowed: the command's log lines still reach the
real stderr, which is where a stdio MCP server's own diagnostics belong —
only stdout is reserved outright for the JSON-RPC channel.

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
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from dblift.cli._constants import EXIT_LICENSE_REQUIRED
from dblift.cli.handlers._shared import CliCommandContext
from dblift.core.logger import LogFactory
from dblift.core.seams.capabilities import CapabilityDeniedError
from dblift.core.seams.tier_resolver import resolve_tier

JSON_FORMAT_ARGV: tuple[str, ...] = ("--format", "json")
_LICENSE_FALLBACK = "This command requires a license that is not available."
_TAIL = 2000
_CALL_LOCK = threading.Lock()

#: The text log file the first call of this server's lifetime opened. Later
#: calls log into it instead of opening a new timestamped file each time.
_LOG_FILE: Optional[Path] = None


def _pinned_log_file() -> Optional[Path]:
    """The file earlier calls opened, or ``None`` to open a fresh one.

    A file that has disappeared (rotated away, tmpdir cleaned) unpins itself
    so the next call opens a new one. Dropping the pin is only half of that:
    the caller must also clear the factory's pattern, which still holds the
    deleted path, or the logger built while the config loads would write the
    file back.
    """
    global _LOG_FILE
    if _LOG_FILE is not None and not _LOG_FILE.exists():
        _LOG_FILE = None
    return _LOG_FILE


def _writes_one_text_file(args: Any) -> bool:
    """Whether this call's only file sink is a TEXT one, which appends.

    Read off ``args.log_format`` rather than ``LogFactory._log_format``
    because the decision is needed *before* logging is configured, so one
    check governs both pinning the file and reusing it — and it needs no
    private factory state. Only TEXT appends: HTML rewrites the whole file on
    every result and JSON writes the complete document on close, so sharing a
    file across calls would make the second call erase the first. A second,
    additional format (``--log-format text,html``) also opens a file sink,
    and both sinks take the same pattern, so that combination is left alone
    too.
    """
    raw = getattr(args, "log_format", None) or "text"
    return [fmt.strip().lower() for fmt in raw.split(",")] == ["text"]


def _remember_log_file(log: Any) -> None:
    """Pin the file sink's path off *log* so later calls reuse it.

    ``log.logs`` is the sink list :func:`dblift.cli._config_helpers._close_logs`
    walks; the file sink is the entry carrying a ``log_file``. The path is
    resolved so it is absolute and has a directory component, which is what
    makes ``FileLog._get_log_file`` hand it back verbatim instead of
    re-expanding a pattern or nesting it under the log directory.
    """
    global _LOG_FILE
    for sink in getattr(log, "logs", []):
        log_file = getattr(sink, "log_file", None)
        if log_file is not None:
            _LOG_FILE = Path(log_file).resolve()
            return


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
    stripped, joined with a newline, empty parts omitted). A command's content
    may land on either console — some commands render through the stdout
    console, others through the console logger, which writes to stderr — so
    both are joined rather than risk losing whichever one carried it.

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
            pinned = _pinned_log_file()
            # Config loading builds a logger of its own before the call's own
            # configuration lands, so the pattern has to be stated before the
            # parse and not only on ``args`` — and stated on every call, pin
            # or no pin, because the factory still carries the previous
            # call's. An empty pattern is the factory's "no pattern": it is
            # the falsy branch in ``FileLog._get_log_file``, its only reader.
            # Without it a call whose pin has just been dropped would build
            # that logger from the deleted path and write the file back.
            # ``_configure_logging`` overwrites the pattern from
            # ``args.log_file`` moments later; a call that fails before then
            # leaves the value set here in place until the next call sets it
            # again, which is why it is re-stated rather than restored.
            LogFactory.set_log_file_pattern(str(pinned) if pinned is not None else "")
            ctx = cli_main._parse_argv_and_load_config(full_argv)
            if pinned is not None:
                # ``_configure_logging`` passes this straight through as the
                # file pattern, and an absolute path with no placeholders is
                # used verbatim: the TEXT sink reopens it in append mode.
                ctx.args.log_file = str(pinned)
            cli_main._setup_logging_and_output(ctx)
            log = ctx.log
            if pinned is None and _writes_one_text_file(ctx.args):
                _remember_log_file(ctx.log)
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
        # A text-mode command's content may land on either console: some
        # commands render through the stdout console, others through the
        # console logger, which writes to stderr. Join both, stdout first,
        # so the caller gets the actual output regardless of which stream
        # carried it.
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
