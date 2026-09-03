"""BUG-01 regression: command footer must render ``result.error_message``.

Before this PR, ``_format_command_footer`` produced ``"Command X failed
(Execution time: Y)"`` regardless of whether the command layer had set an
explanatory ``error_message`` on the result — the CLI printed the generic
failure footer and the operator was left with no explanation.

These tests pin the new contract: the failure footer includes
``result.error_message`` when set, and the success footer stays unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.base_command import BaseCommand


def _make_base_command_stub() -> BaseCommand:
    """Build a BaseCommand bypassing __init__ (we only need its methods)."""
    cmd = BaseCommand.__new__(BaseCommand)
    cmd.log = MagicMock()
    return cmd


@pytest.mark.unit
class TestFormatCommandFooterRendersErrorMessage:
    def test_failure_footer_includes_error_message_when_set(self):
        cmd = _make_base_command_stub()
        footer = cmd._format_command_footer(
            "clean",
            success=False,
            execution_time="0 ms",
            error_message="Database connection refused; clean cannot proceed.",
        )
        assert "Command CLEAN failed" in footer
        assert "Database connection refused" in footer

    def test_failure_footer_without_error_message_stays_minimal(self):
        """No error_message provided (legacy path) → footer unchanged in shape."""
        cmd = _make_base_command_stub()
        footer = cmd._format_command_footer(
            "migrate", success=False, execution_time="12 s", error_message=None
        )
        assert "Command MIGRATE failed" in footer
        assert "Execution time: 12 s" in footer

    def test_success_footer_ignores_error_message(self):
        """Success path: even if error_message is accidentally passed, it's not rendered."""
        cmd = _make_base_command_stub()
        footer = cmd._format_command_footer(
            "info",
            success=True,
            execution_time="5 ms",
            error_message="should not appear",
        )
        assert "Command INFO completed successfully" in footer
        assert "should not appear" not in footer

    def test_log_command_completion_propagates_error_message(self):
        """End-to-end: _log_command_completion must pull error_message from the result."""
        import io
        import sys

        from dblift.core.logger.console import reset_stdout_console

        cmd = _make_base_command_stub()

        result = SimpleNamespace(
            success=False,
            error_message="Database connection refused",
            end_time=None,
            complete=lambda: None,
            execution_time=lambda: 42,
        )

        from dblift.core.logger.log import ConsoleLog

        cmd.log = ConsoleLog.__new__(ConsoleLog)
        cmd._log_text_block = lambda _b: None  # type: ignore[assignment]

        reset_stdout_console()
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            cmd._log_command_completion("migrate", result)
        finally:
            sys.stdout = old_stdout
            reset_stdout_console()

        assert "Database connection refused" in buf.getvalue()
