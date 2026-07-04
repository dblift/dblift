"""CLI output abstraction — one place to route machine vs human text.

Problem this module addresses
=============================

Every command handler in ``cli/_command_handlers.py`` and the top-level
dispatch in ``cli/main.py`` re-derive the same predicate:

    output_format = getattr(args, "format", "console")
    is_machine_format = output_format in MACHINE_READABLE_FORMATS
    if is_machine_format:
        print(payload)                 # stdout
    else:
        ctx.log.info(payload)          # routed through ConsoleLog

That duplication has already caused two regressions (PR 158 banner fix
+ PR-01 machine-format scope). ADR-0005 added the
`MACHINE_READABLE_FORMATS` set as a single source of truth; this
module does the same for the *routing* decision itself.

Contract
========

``CommandOutput`` has three methods:

  * ``.machine(payload)`` — emit the machine-readable payload. Writes
    to stdout; JSON-serialises dicts/lists. Calling in human mode is a
    no-op (handlers fall back to their normal human formatters).

  * ``.status(message)`` — emit a human-facing status line. In machine
    mode, routed to **stderr** so it cannot contaminate the stdout
    contract but is still visible to a human running the command in a
    terminal. In human mode, routed to stdout (current UX preserved).

  * ``.banner(text)`` — emit the startup / header banner. Same
    routing policy as ``.status`` but kept separate so callers can
    suppress it without affecting mid-command status lines.

Relationship to ADR-0005 / ADR-0008
===================================

ADR-0005 decided to *suppress* the banner in machine mode because
stdout was the only sink; anything extra broke JSON parsing. With
``CommandOutput``, the banner is routed to stderr instead of being
dropped. See ``docs/adr/0008-command-output-abstraction.md`` for the
updated decision and why full logger-level stderr routing is deferred.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional, TextIO

from cli._constants import MACHINE_READABLE_FORMATS


class CommandOutput:
    """Single routing point for CLI output.

    Constructed once per command invocation from the parsed ``args``.
    Handler code then calls ``.machine()`` / ``.status()`` / ``.banner()``
    instead of printing directly.
    """

    def __init__(
        self,
        output_format: Optional[str],
        *,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
    ) -> None:
        """Initialise the router.

        Args:
            output_format: The ``--format`` value (``"json"``, ``"table"``,
                ``"console"``, ``"sarif"``, ...). ``None`` and unknown
                values are treated as human format.
            stdout / stderr: Injectable streams. Default to the real
                ``sys.stdout`` / ``sys.stderr`` at call time (not at
                import time — reassigning them in tests works).
        """
        self._output_format = output_format
        self._stdout = stdout
        self._stderr = stderr
        self._is_machine = (_primary_output_format(output_format) or "") in MACHINE_READABLE_FORMATS

    @property
    def is_machine_format(self) -> bool:
        """``True`` iff the command should treat stdout as a parser contract."""
        return self._is_machine

    @property
    def output_format(self) -> Optional[str]:
        """The raw ``--format`` value (for handlers that need to branch)."""
        return self._output_format

    # --- emit methods -------------------------------------------------------

    def machine(self, payload: Any) -> None:
        """Emit the machine-readable payload to stdout.

        Serialises ``payload`` to JSON if it is a ``dict`` or ``list``;
        otherwise, writes the pre-formatted string directly. Callers
        that produce a format-specific serialisation (SARIF, GitHub
        Actions annotations) should pass a pre-rendered string.

        In human format, this is a no-op — handlers are expected to
        fall back to the human formatter path.
        """
        if not self._is_machine:
            return
        if isinstance(payload, (dict, list)):
            rendered = json.dumps(payload, indent=2)
        else:
            rendered = str(payload)
        print(rendered, file=self._resolve_stdout())  # lint: allow-print  machine payload

    def status(self, message: str) -> None:
        """Emit a human-facing status line.

        Machine mode → stderr (visible to humans, invisible to piped
        JSON consumers). Human mode → stdout (preserves the current UX
        where a user running ``dblift info`` sees status in the same
        stream as the table).
        """
        self._emit_human(message)

    def banner(self, text: str) -> None:
        """Emit the session banner (version, license, database).

        Same routing as ``.status``. Kept separate so a future policy
        can suppress banners while keeping status visible (or vice
        versa) without call-site churn.
        """
        self._emit_human(text)

    def error(self, message: str) -> None:
        """Emit an error message — always to stderr regardless of mode.

        Errors are a stream contract orthogonal to the machine/human
        routing handled by ``.status`` / ``.banner``: they must reach
        the user even when stdout is being parsed by another process,
        and they must not contaminate a JSON payload either. This
        replaces the recurring ``print(..., file=sys.stderr)`` pattern
        in cli handlers.
        """
        print(message, file=self._resolve_stderr())  # lint: allow-print  error stream

    # --- internals ----------------------------------------------------------

    def _emit_human(self, text: str) -> None:
        stream = self._resolve_stderr() if self._is_machine else self._resolve_stdout()
        print(text, file=stream, flush=True)  # lint: allow-print  routed stream

    def _resolve_stdout(self) -> TextIO:
        return self._stdout if self._stdout is not None else sys.stdout

    def _resolve_stderr(self) -> TextIO:
        return self._stderr if self._stderr is not None else sys.stderr


def from_args(args: Any, **kwargs: Any) -> CommandOutput:
    """Construct a :class:`CommandOutput` from an argparse ``Namespace``.

    Convenience entry point used by :mod:`cli.main` and handlers. Falls
    back to ``"console"`` when the command has no ``--format`` flag.
    """
    fmt = getattr(args, "format", None)
    if not isinstance(fmt, str) or not fmt:
        fmt = "console"
    return CommandOutput(fmt, **kwargs)


def _primary_output_format(output_format: Optional[str]) -> Optional[str]:
    if output_format is None:
        return None
    primary = output_format.split(",", 1)[0].strip().lower()
    return "text" if primary == "console" else primary
