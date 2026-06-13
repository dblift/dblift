"""Guardrails for the command lifecycle skeleton.

The private lifecycle runner is intentionally incremental: it should make the
common preflight/header/body/footer order explicit without forcing every
command into the same shape before its current behavior is pinned.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.migration.commands.base_command import BaseCommand


def _make_command_stub() -> BaseCommand:
    command = BaseCommand.__new__(BaseCommand)
    command.log = MagicMock()
    command._log_command_header_update = MagicMock()
    command._log_command_completion = MagicMock()
    return command


def _make_result() -> SimpleNamespace:
    result = SimpleNamespace(success=True, error_message="", end_time=None)

    def set_error(message: str) -> None:
        result.success = False
        result.error_message = message

    result.set_error = set_error
    return result


@pytest.mark.unit
class TestCommandLifecycleRunner:
    def test_runner_orders_preflight_header_body_and_completion(self):
        command = _make_command_stub()
        result = _make_result()
        calls: list[str] = []

        command._log_command_header_update.side_effect = lambda *_a, **_k: calls.append("header")
        command._log_command_completion.side_effect = lambda *_a, **_k: calls.append("completion")

        returned = command._run_command_lifecycle(
            "info",
            result,
            body=lambda: calls.append("body"),
            preflight=lambda: calls.append("preflight"),
            before_body=lambda: calls.append("before_body"),
        )

        assert returned is result
        assert calls == ["preflight", "header", "before_body", "body", "completion"]
        command._log_command_header_update.assert_called_once_with("info")
        command._log_command_completion.assert_called_once_with("info", result)

    def test_body_exception_is_converted_to_result_error_and_footer(self):
        command = _make_command_stub()
        result = _make_result()

        def body() -> None:
            raise RuntimeError("boom")

        command._run_command_lifecycle(
            "info",
            result,
            body=body,
            error_message_prefix="Info operation failed",
        )

        assert result.success is False
        assert result.error_message == "Info operation failed: boom"
        command.log.error.assert_called_once_with("Info operation failed: boom")
        command._log_command_completion.assert_called_once_with("info", result)

    def test_preflight_exception_still_propagates_without_footer(self):
        command = _make_command_stub()
        result = _make_result()

        with pytest.raises(RuntimeError, match="connect failed"):
            command._run_command_lifecycle(
                "info",
                result,
                body=lambda: None,
                preflight=lambda: (_ for _ in ()).throw(RuntimeError("connect failed")),
            )

        command._log_command_header_update.assert_not_called()
        command._log_command_completion.assert_not_called()


@pytest.mark.unit
class TestCommandLifecycleIntentionalDeviations:
    """Source-level guardrails for commands not migrated to the runner yet."""

    def _source(self, relative_path: str) -> str:
        return Path(relative_path).read_text(encoding="utf-8")

    def test_clean_retains_custom_dry_run_connection_handling(self):
        source = self._source("core/migration/commands/clean_command.py")
        assert "dry_run" in source
        assert "get_clean_preview" in source
        assert "_run_command_lifecycle" not in source

    def test_diff_retains_snapshot_specific_early_completion_paths(self):
        source = self._source("core/migration/commands/diff_command.py")
        assert "snapshot_model" in source
        assert '_log_command_completion("diff"' in source
        assert "_run_command_lifecycle" not in source

    def test_undo_retains_multiple_early_completion_paths(self):
        source = self._source("core/migration/commands/undo_command.py")
        assert "should_undo_version" in source
        assert source.count('_log_command_completion("undo"') >= 3
        assert "_run_command_lifecycle" not in source


@pytest.mark.unit
class TestDryRunFooterMessage:
    """BUG-02: dry-run footer must say 'N migration(s) would be applied', not
    'No pending migrations found'."""

    def _run_log_completion(self, result):
        from core.migration.commands.base_command import BaseCommand

        cmd = BaseCommand.__new__(BaseCommand)
        cmd.log = MagicMock()
        cmd._log_command_header_update = MagicMock()
        cmd._has_own_console_footer = True  # suppress Rich panel output in unit tests
        cmd._log_text_block = MagicMock()
        cmd._build_footer_panel = MagicMock()
        cmd._format_command_footer = MagicMock(return_value="")
        cmd._log_command_completion("migrate", result)
        # Return the applied_scripts that were built inside the method by
        # capturing what _format_command_footer was called with.
        call_kwargs = cmd._format_command_footer.call_args
        return call_kwargs[1].get("applied_scripts") if call_kwargs else None

    def test_dry_run_shows_count_not_no_pending(self):
        from core.logger.results import MigrateResult

        result = MigrateResult()
        result.dry_run_count = 3
        applied_scripts = self._run_log_completion(result)
        assert applied_scripts is not None
        assert len(applied_scripts) == 1
        assert "3" in applied_scripts[0]
        assert "would be applied" in applied_scripts[0]
        assert "No pending" not in applied_scripts[0]

    def test_no_pending_message_when_truly_empty(self):
        from core.logger.results import MigrateResult

        result = MigrateResult()
        applied_scripts = self._run_log_completion(result)
        assert applied_scripts == ["No pending migrations found"]


@pytest.mark.unit
class TestPrintMainHeaderOnceRouting:
    """OBS-01: _print_main_header_once must emit to stderr, not stdout."""

    def _make_command_with_console_log(self):
        from core.logger.log import ConsoleLog
        from core.migration.commands.base_command import BaseCommand

        cmd = BaseCommand.__new__(BaseCommand)
        cmd.log = MagicMock(spec=ConsoleLog)
        cmd.config = MagicMock()
        cmd.config.database.database_name = "testdb"
        cmd.config.database.database = "testdb"
        cmd.config.database.schema = "public"
        return cmd

    def test_banner_fallback_goes_to_stderr(self, capsys):
        import core.migration.commands.base_command as cmd_mod

        cmd = self._make_command_with_console_log()
        # Reset the flag so the header is actually printed
        original = getattr(cmd_mod, "_console_main_header_printed", None)
        cmd_mod._console_main_header_printed = False
        try:
            with patch(
                "core.logger.log.TextFormatter.format_header",
                return_value="DBLIFT v1.4.1 — testdb",
            ):
                cmd._print_main_header_once()
        finally:
            if original is not None:
                cmd_mod._console_main_header_printed = original
            else:
                del cmd_mod._console_main_header_printed

        captured = capsys.readouterr()
        assert captured.out == "", "banner must NOT appear on stdout"
        assert "DBLIFT" in captured.err, "banner must appear on stderr"
