"""Tests for CleanCommand afterCleanError callback silent except block logging (story 20-3)."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.migration.commands.clean_command import CleanCommand


@pytest.mark.unit
class TestCleanCommandAfterCleanErrorLogging:
    """Verify that the except block around afterCleanError callback
    emits log.debug instead of silently passing."""

    def _make_command(self):
        provider = MagicMock()
        config = MagicMock()
        config.database.schema = "myschema"
        log = MagicMock()
        cmd = CleanCommand(
            config=config,
            log=log,
            provider=provider,
            script_manager=MagicMock(),
            history_manager=MagicMock(),
            validator=MagicMock(),
            execution_engine=MagicMock(),
            migration_helpers=MagicMock(),
            state_manager=MagicMock(),
            migration_ui=MagicMock(),
            migration_rules=MagicMock(),
        )
        provider.list_droppable_objects.side_effect = RuntimeError("clean failed")
        return cmd, provider, log

    @staticmethod
    def _after_clean_error_raises(*args, **kwargs):
        """Side effect that only raises for afterCleanError callbacks."""
        if args[1] == "afterCleanError":
            raise RuntimeError("callback failed")

    def test_after_clean_error_callback_exception_logs_debug(self):
        """AC#2.1: clean raises + _execute_callbacks(afterCleanError) raises → log.debug called."""
        cmd, provider, log = self._make_command()
        with patch.object(cmd, "_execute_callbacks", side_effect=self._after_clean_error_raises):
            cmd.execute(scripts_dir="/some/dir")

        log.debug.assert_any_call("afterCleanError callback skipped: callback failed")

    def test_after_clean_error_callback_exception_does_not_raise(self):
        """AC#2.2: _execute_callbacks(afterCleanError) raises → execute() does not propagate."""
        cmd, provider, log = self._make_command()
        with patch.object(cmd, "_execute_callbacks", side_effect=self._after_clean_error_raises):
            result = cmd.execute(scripts_dir="/some/dir")

        assert result is not None

    def test_after_clean_error_callback_success_no_extra_debug(self):
        """AC#2.3: _execute_callbacks(afterCleanError) succeeds → no 'afterCleanError callback skipped' debug."""
        cmd, provider, log = self._make_command()
        with patch.object(cmd, "_execute_callbacks", return_value=None):
            cmd.execute(scripts_dir="/some/dir")

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert not any("afterCleanError callback skipped" in c for c in debug_calls)
