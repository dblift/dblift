"""Unit tests for core.logger.console — Rich rendering helpers and singleton."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from dblift.core.logger.console import (
    DBLIFT_THEME,
    get_stderr_console,
    install_rich_traceback,
    render_panel_to_str,
    render_table_to_str,
    render_to_str,
    render_tree_to_str,
    reset_stderr_console,
)


@pytest.mark.unit
class TestGetStderrConsole:
    """Singleton stderr Console behaviour."""

    def setup_method(self):
        reset_stderr_console()

    def teardown_method(self):
        reset_stderr_console()

    def test_returns_console_instance(self):
        c = get_stderr_console()
        assert isinstance(c, Console)

    def test_writes_to_stderr(self):
        c = get_stderr_console()
        assert c.stderr is True

    def test_singleton_returns_same_instance(self):
        a = get_stderr_console()
        b = get_stderr_console()
        assert a is b

    def test_reset_clears_singleton(self):
        a = get_stderr_console()
        reset_stderr_console()
        b = get_stderr_console()
        assert a is not b

    def test_uses_dblift_theme(self):
        get_stderr_console()  # ensures it's instantiated
        # Theme styles are looked up via the Console renderer; verify
        # by writing a tagged style and confirming it is recognised.
        c = get_stderr_console()
        for key in ("log.error", "log.warn", "log.notice", "log.debug"):
            style = c.get_style(key, default=None)
            assert style is not None, f"theme missing style {key}"

    def test_markup_disabled_by_default(self):
        c = get_stderr_console()
        # Console exposes options for default state; we wrote ``[red]error[/red]``
        # and expect it to come through as literal text in non-tty mode.
        with c.capture() as cap:
            c.print("[red]error[/red]")
        assert "[red]error[/red]" in cap.get()


@pytest.mark.unit
class TestRenderTableToStr:
    def test_renders_header_and_rows(self):
        t = Table()
        t.add_column("Version")
        t.add_column("State")
        t.add_row("1.0.0", "Success")
        t.add_row("2.0.0", "Pending")
        out = render_table_to_str(t)
        assert "1.0.0" in out
        assert "Success" in out
        assert "2.0.0" in out
        assert "Pending" in out

    def test_no_ansi_escape_codes(self):
        t = Table()
        t.add_column("X", style="red bold")
        t.add_row("value")
        out = render_table_to_str(t)
        assert "\x1b[" not in out

    def test_returns_str(self):
        t = Table()
        t.add_column("col")
        t.add_row("v")
        assert isinstance(render_table_to_str(t), str)


@pytest.mark.unit
class TestRenderTreeToStr:
    def test_renders_tree_structure(self):
        t = Tree("root")
        a = t.add("branch_a")
        a.add("leaf_a1")
        a.add("leaf_a2")
        t.add("branch_b")
        out = render_tree_to_str(t)
        assert "root" in out
        assert "branch_a" in out
        assert "leaf_a1" in out
        assert "leaf_a2" in out
        assert "branch_b" in out

    def test_uses_unicode_connectors(self):
        t = Tree("root")
        t.add("child")
        out = render_tree_to_str(t)
        # Default Rich tree uses box-drawing characters
        assert "─" in out or "└" in out or "├" in out

    def test_no_ansi_escape_codes(self):
        t = Tree("root", style="red bold")
        t.add("child", style="yellow")
        out = render_tree_to_str(t)
        assert "\x1b[" not in out


@pytest.mark.unit
class TestRenderPanelToStr:
    def test_renders_with_title_and_body(self):
        p = Panel("body content", title="MY_TITLE")
        out = render_panel_to_str(p, width=80)
        assert "body content" in out
        assert "MY_TITLE" in out

    def test_no_ansi_escape_codes(self):
        p = Panel("body", title="T", border_style="red bold")
        out = render_panel_to_str(p, width=60)
        assert "\x1b[" not in out

    def test_width_caps_panel_width(self):
        p = Panel("x" * 200, title="T")
        out = render_panel_to_str(p, width=40)
        # Each rendered line of the panel should fit inside the requested width
        for line in out.splitlines():
            assert len(line) <= 40


@pytest.mark.unit
class TestRenderToStrGeneric:
    def test_handles_table(self):
        t = Table()
        t.add_column("c")
        t.add_row("r")
        out = render_to_str(t)
        assert "r" in out

    def test_handles_tree(self):
        t = Tree("root")
        t.add("child")
        out = render_to_str(t)
        assert "root" in out and "child" in out

    def test_handles_panel(self):
        p = Panel("hello", title="hi")
        out = render_to_str(p, width=40)
        assert "hello" in out


@pytest.mark.unit
class TestInstallRichTraceback:
    def test_installs_excepthook(self):
        original_excepthook = __import__("sys").excepthook
        try:
            install_rich_traceback()
            import sys

            assert sys.excepthook is not original_excepthook
        finally:
            import sys

            sys.excepthook = original_excepthook

    def test_install_accepts_suppress_arg(self):
        # Should not raise
        install_rich_traceback(suppress=())


@pytest.mark.unit
class TestThemeKeys:
    def test_required_severity_styles_present(self):
        styles = DBLIFT_THEME.styles
        for key in ("log.debug", "log.info", "log.warn", "log.error", "log.notice"):
            assert key in styles


@pytest.mark.unit
class TestConsoleLogConsolePrintLevelFilter:
    """ConsoleLog.console_print must honour the severity threshold.

    Regression guard: before the level-filter fix, ``--quiet`` raised
    the console threshold to WARN, suppressing the textual header
    ("Generated N SQL statement(s):") emitted via ``log.info`` while
    leaving the syntax-highlighted SQL body emitted via
    ``console_print`` visible. The user saw the body without context.
    """

    def setup_method(self):
        reset_stderr_console()

    def teardown_method(self):
        reset_stderr_console()

    def test_console_print_suppressed_below_threshold(self):
        from dblift.core.logger.log import ConsoleLog, LogLevel

        log = ConsoleLog("test", log_level=LogLevel.WARN)
        log._console = MagicMock()
        from rich.text import Text

        log.console_print(Text("info-tier renderable"), level=LogLevel.INFO)
        log._console.print.assert_not_called()

    def test_console_print_emitted_at_or_above_threshold(self):
        from dblift.core.logger.log import ConsoleLog, LogLevel

        log = ConsoleLog("test", log_level=LogLevel.INFO)
        log._console = MagicMock()
        from rich.text import Text

        log.console_print(Text("info-tier renderable"), level=LogLevel.INFO)
        log._console.print.assert_called_once()

    def test_console_print_warn_passes_when_threshold_warn(self):
        from dblift.core.logger.log import ConsoleLog, LogLevel

        log = ConsoleLog("test", log_level=LogLevel.WARN)
        log._console = MagicMock()
        from rich.text import Text

        log.console_print(Text("warn-tier"), level=LogLevel.WARN)
        log._console.print.assert_called_once()

    def test_console_print_default_level_is_info(self):
        from dblift.core.logger.log import ConsoleLog, LogLevel

        # No level kwarg → defaults to INFO → suppressed at WARN threshold.
        log = ConsoleLog("test", log_level=LogLevel.WARN)
        log._console = MagicMock()
        from rich.text import Text

        log.console_print(Text("default level"))
        log._console.print.assert_not_called()


@pytest.mark.unit
class TestRenderTrailingNewline:
    """All render_* helpers must strip the trailing newline so callers
    can safely concatenate. Regression guard: log.info(render_X) +
    log.info(...) must not insert a blank line."""

    def test_table_no_trailing_newline(self):
        t = Table()
        t.add_column("c")
        t.add_row("r")
        assert not render_table_to_str(t).endswith("\n")

    def test_tree_no_trailing_newline(self):
        t = Tree("root")
        t.add("child")
        assert not render_tree_to_str(t).endswith("\n")

    def test_panel_no_trailing_newline(self):
        p = Panel("body", title="T")
        assert not render_panel_to_str(p, width=60).endswith("\n")
