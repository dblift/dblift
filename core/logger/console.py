"""Shared Rich console and theme for human-facing CLI output.

The Rich Console is used only by the console sink (ConsoleLog).
File / JSON / HTML formatters keep raw plain text — markup must not leak
into those sinks. ADR-0008: machine payloads go to stdout, human output
goes to stderr.
"""

import contextlib
import sys
from typing import Any, ContextManager, Dict, List, Literal, Optional, Tuple, cast

from rich import box
from rich.console import Console, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme
from rich.tree import Tree

DBLIFT_THEME = Theme(
    {
        "log.debug": "dim",
        "log.info": "default",
        "log.warn": "yellow",
        "log.error": "bold red",
        "log.notice": "bold green",
    }
)

ColumnJustify = Literal["default", "left", "center", "right", "full"]

# Shared state-color palette (relocated from core/migration/ui/table_renderer.py
# so plugin commands and migration UI share one source of truth).
_STATE_STYLE: Dict[str, str] = {
    "success": "bold green",
    "applied": "bold green",
    "failed": "bold red",
    "missing": "bold red",
    "mismatch": "bold red",
    "pending": "yellow",
    "undone": "yellow",
    "warning": "yellow",
    "baseline": "dim",
    "ignored": "dim",
    "skipped": "dim",
    "future": "dim",
    "superseded": "dim",
    "available": "cyan",
}


def state_text(state: str) -> Text:
    """Return a rich ``Text`` for a state string, styled per the shared palette.

    Unknown states render unstyled. Callers pass the result as a table cell so
    the same colors are used everywhere (migration tables, data tables, ...).
    Lookup is case-insensitive; the original casing is preserved in the rendered
    text. An empty string is treated as unknown and renders unstyled.
    """
    style = _STATE_STYLE.get(state.lower(), "")
    text = Text(state)
    if style:
        text.stylize(style)
    return text


_stderr_console: "Console | None" = None
_stdout_console: "Console | None" = None
_progress_disabled_override: "bool | None" = None


def set_progress_disabled(disabled: bool) -> None:
    """Process-local override for progress suppression.

    Set by ``cli/_config_helpers.py`` when the operator passes
    ``--no-progress``. Kept off ``os.environ`` so the CLI does not
    permanently mutate the environment of the host process or leak
    the flag into unrelated subprocesses spawned later in the run.
    Pass ``False`` to clear and fall back to the env-var / tty check.
    """
    global _progress_disabled_override
    _progress_disabled_override = disabled if disabled else None


def is_progress_disabled() -> bool:
    """Return True when progress bars / status spinners must stay silent.

    Resolution order:
        1. process-local override (set by CLI ``--no-progress``)
        2. ``DBLIFT_NO_PROGRESS`` env var (operators / CI configs that
           pre-set the environment)
        3. non-tty stderr (CI logs, file redirection, capsys)
    """
    import os
    import sys

    if _progress_disabled_override is True:
        return True
    if os.environ.get("DBLIFT_NO_PROGRESS"):
        return True
    isatty = getattr(sys.stderr, "isatty", lambda: False)
    try:
        return not isatty()
    except Exception:
        return True


def get_stderr_console() -> Console:
    """Return the shared Rich Console writing to stderr.

    Singleton — same Console instance across ConsoleLog, Progress,
    rich.traceback, etc. Rich's redraw logic relies on a single Console
    owning the terminal state; multiple instances writing concurrently
    cause flicker and corrupted bars. Console resolves sys.stderr
    lazily at write time, so pytest capsys monkeypatching still works.
    ANSI codes are auto-disabled when stderr is not a tty.
    """
    global _stderr_console
    if _stderr_console is None:
        _stderr_console = Console(
            stderr=True,
            theme=DBLIFT_THEME,
            highlight=False,
            soft_wrap=True,
            emoji=False,
            markup=False,
        )
    return _stderr_console


def get_stdout_console() -> Console:
    """Return the shared Rich Console writing to stdout.

    Used for command headers and footers (ADR-0008: machine payloads go to
    stdout, human banners also go to stdout). ANSI codes are auto-disabled
    when stdout is not a tty (pipes, CI, capsys).
    """
    global _stdout_console
    if _stdout_console is None:
        _stdout_console = Console(
            stderr=False,
            theme=DBLIFT_THEME,
            highlight=False,
            soft_wrap=True,
            emoji=False,
            markup=False,
        )
    return _stdout_console


def reset_stdout_console() -> None:
    """Reset the cached stdout Console. For tests only."""
    global _stdout_console
    _stdout_console = None


def reset_stderr_console() -> None:
    """Reset the cached stderr Console. For tests only."""
    global _stderr_console
    _stderr_console = None


def _plain_renderer(width: int = 200) -> Console:
    """Build a Rich Console that emits plain text (no ANSI)."""
    return Console(
        force_terminal=False,
        no_color=True,
        width=width,
        emoji=False,
        markup=False,
        highlight=False,
    )


def render_to_str(renderable: RenderableType, width: int = 200) -> str:
    """Render any Rich renderable (Table, Tree, Panel, ...) to plain text.

    Used when the output must flow through the existing logger pipeline
    (ConsoleLog + FileLog text/JSON/HTML) or be returned to callers that
    print to stdout. Plain text only — no ANSI — so the same string is
    safe for files and pipes.
    """
    renderer = _plain_renderer(width=width)
    with renderer.capture() as capture:
        renderer.print(renderable)
    captured: str = capture.get()
    return captured.rstrip("\n")


def render_table_to_str(table: Table, width: int = 200) -> str:
    """Render a Rich Table to plain text. Backwards-compatible wrapper."""
    return render_to_str(table, width=width)


def render_tree_to_str(tree: Tree, width: int = 200) -> str:
    """Render a Rich Tree to plain text."""
    return render_to_str(tree, width=width)


def render_panel_to_str(panel: Panel, width: int = 200) -> str:
    """Render a Rich Panel to plain text."""
    return render_to_str(panel, width=width)


def render_records_table(
    columns: List[Tuple[str, str]],
    rows: List[List[Any]],
    *,
    title: Optional[str] = None,
    width: int = 200,
    color: bool = False,
) -> str:
    """Render tabular records as plain text (ANSI-safe) using the shared theme.

    Generic and command-agnostic: ``columns`` is a list of ``(header, justify)``
    pairs (justify in left|center|right), ``rows`` is a list of cell lists where
    each cell is a ``str`` or a rich ``Text`` (e.g. ``state_text(...)``). Returns
    a plain-text table string suitable for stdout, pipes, and log files.
    When ``color=True`` the table is rendered through a tty-aware console so ANSI
    colors appear on a real terminal and are auto-stripped when piped/redirected.
    """
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold", title=title)
    for header, justify in columns:
        table.add_column(header, justify=cast(ColumnJustify, justify))
    for row in rows:
        table.add_row(*[cell if isinstance(cell, Text) else str(cell) for cell in row])
    if color:
        console = Console(
            file=sys.stdout, highlight=False, markup=False, soft_wrap=True, emoji=False
        )
        with console.capture() as capture:
            console.print(table)
        return capture.get().rstrip("\n")
    return render_table_to_str(table, width=width)


def console_status(message: str) -> "ContextManager[Any]":
    """Return a Rich ``Console.status`` context manager, or a no-op
    when progress is disabled (``--no-progress`` / non-tty).

    Long-running command paths wrap their
    blocking service calls with this so the spinner respects the
    same suppression rules as ``rich.progress.Progress``.
    """
    if is_progress_disabled():
        return contextlib.nullcontext()
    status: ContextManager[Any] = get_stderr_console().status(message)
    return status


def install_rich_traceback(*, suppress: Any = ()) -> None:
    """Install Rich's pretty traceback handler for uncaught exceptions.

    Writes to stderr only (ADR-0008). ``suppress`` accepts modules whose
    frames should be hidden in the traceback (e.g. third-party glue).
    """
    from rich.traceback import install

    install(
        console=get_stderr_console(),
        show_locals=False,
        suppress=suppress,
        word_wrap=False,
        width=None,
    )
