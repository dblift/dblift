"""BUG-11 regression: command footer shows the post-operation Schema Version.

Before this fix, the Schema Version was only printed in the *header*, which
``_log_command_header_update`` emits before the command body runs. After a
state-changing operation — ``undo``, ``migrate``, ``baseline``, ``clean`` —
the banner still displayed the pre-operation version. The actual history
table was correct; the displayed value was stale.

The fix extends ``_format_command_footer`` with an optional
``schema_version`` parameter and has ``_log_command_completion`` pass the
freshly resolved version through. When resolution fails (e.g. clean just
dropped the history table), the footer gracefully omits the line.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.base_command import BaseCommand


def _make_command_stub() -> BaseCommand:
    """Build a BaseCommand without its heavy __init__ — we only exercise formatters."""
    cmd = BaseCommand.__new__(BaseCommand)
    cmd.log = MagicMock()
    return cmd


@pytest.mark.unit
class TestCommandFooterSchemaVersion:
    def test_footer_includes_schema_version_on_success(self):
        """Success footer surfaces the post-operation Schema Version."""
        cmd = _make_command_stub()
        footer = cmd._format_command_footer(
            command_name="undo",
            success=True,
            execution_time="42 ms",
            schema_version="3",
        )
        assert "Schema Version: 3" in footer
        assert "completed successfully" in footer

    def test_footer_includes_schema_version_on_failure(self):
        """Failure footer still shows the version — post-state visibility applies either way."""
        cmd = _make_command_stub()
        footer = cmd._format_command_footer(
            command_name="migrate",
            success=False,
            execution_time="100 ms",
            error_message="connection lost",
            schema_version="4",
        )
        assert "Schema Version: 4" in footer
        assert "Error: connection lost" in footer

    def test_footer_omits_version_when_none(self):
        """If resolution fails (e.g. clean dropped history), skip the line cleanly."""
        cmd = _make_command_stub()
        footer = cmd._format_command_footer(
            command_name="clean",
            success=True,
            execution_time="1 s",
            schema_version=None,
        )
        assert "Schema Version" not in footer

    def test_footer_none_sentinel_renders_as_none_when_empty_string(self):
        """Passing an empty string is treated the same as None — no line rendered."""
        cmd = _make_command_stub()
        footer = cmd._format_command_footer(
            command_name="info",
            success=True,
            execution_time="5 ms",
            schema_version="",
        )
        assert "Schema Version" not in footer

    def test_schema_version_line_position_is_before_final_divider(self):
        """Version line must appear between the status and the ``=`` divider —
        grouped with the result, not dangling below the footer box."""
        cmd = _make_command_stub()
        footer = cmd._format_command_footer(
            command_name="migrate",
            success=True,
            execution_time="1 s",
            schema_version="V7",
        )
        lines = footer.splitlines()
        version_idx = next(i for i, line in enumerate(lines) if "Schema Version" in line)
        # The footer is wrapped in a Rich Panel; the "closing divider" is the
        # last line of the panel border. Schema Version must appear inside the
        # panel body, i.e. above the final line.
        assert version_idx < len(lines) - 1, "Schema Version must appear above the closing divider"

    def test_backwards_compatible_default_omits_version(self):
        """Callers that don't pass schema_version get the prior footer shape."""
        cmd = _make_command_stub()
        footer = cmd._format_command_footer(
            command_name="validate",
            success=True,
            execution_time="10 ms",
        )
        assert "Schema Version" not in footer


@pytest.mark.unit
class TestLogCommandCompletionResolvesSchemaVersion:
    """Lifecycle test: _log_command_completion must ask the history manager
    for the current version *after* the command body has run."""

    def test_completion_queries_current_version_after_operation(self):
        """Ensures we're reading the post-state, not a stale cached value."""
        cmd = BaseCommand.__new__(BaseCommand)
        cmd.log = MagicMock()
        # Defensive resolution requires a non-None history_manager — a truthy
        # stub satisfies the guard without needing the full wiring.
        cmd.history_manager = MagicMock()
        # MultiLog/console-log detection path is out of scope here — stub the
        # writes to capture just the resolution call.
        cmd._resolve_current_schema_version = MagicMock(return_value="3")
        cmd._log_text_block = MagicMock()

        result = SimpleNamespace(
            success=True,
            execution_time=lambda: 100,
            complete=lambda: None,
            end_time=1234567890,
            error_message=None,
        )

        cmd._log_command_completion("undo", result)

        # Resolution must happen at completion — the whole point of this fix.
        cmd._resolve_current_schema_version.assert_called_once()
