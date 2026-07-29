"""Tests for CleanCommand silent except blocks logging (story 20-2, NEW-BUG-40)."""

from unittest.mock import MagicMock

import pytest

from core.migration.commands.clean_command import CleanCommand


@pytest.mark.unit
class TestCleanCommandEnsureConnectionLogging:
    """Verify that except blocks around _ensure_connection and set_current_schema
    emit log.debug instead of silently passing."""

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
        # Ensure clean_schema returns a simple list so execute() doesn't crash
        provider.clean_schema.return_value = []
        provider.commit_transaction.return_value = None
        return cmd, provider, log

    def test_ensure_connection_exception_logs_debug(self):
        """AC#3.1: _ensure_connection raises → log.debug called with '_ensure_connection skipped'.

        ``_ensure_connected`` now formats connection failures via
        ``db.error.format_connection_error`` before re-raising (so every
        command reports connection errors the same friendly way), so the
        debug log carries that formatted message rather than the raw
        driver text.
        """
        cmd, provider, log = self._make_command()
        provider._ensure_connection.side_effect = RuntimeError("conn refused")

        cmd.execute()

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("_ensure_connection skipped" in c for c in debug_calls)
        assert any("Connection failed" in c for c in debug_calls)

    def test_ensure_connection_exception_does_not_raise(self):
        """AC#3.2: _ensure_connection raises → execute() does not propagate."""
        cmd, provider, log = self._make_command()
        provider._ensure_connection.side_effect = Exception("timeout")

        result = cmd.execute()

        assert result is not None
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("_ensure_connection skipped" in c for c in debug_calls)

    def test_set_current_schema_exception_logs_debug(self):
        """AC#3.3: set_current_schema raises → log.debug called with 'set_current_schema skipped'."""
        cmd, provider, log = self._make_command()
        provider.set_current_schema.side_effect = RuntimeError("unsupported")

        cmd.execute()

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("set_current_schema skipped" in c for c in debug_calls)
        assert any("unsupported" in c for c in debug_calls)

    def test_set_current_schema_exception_does_not_raise(self):
        """AC#3.4: set_current_schema raises → execute() does not propagate."""
        cmd, provider, log = self._make_command()
        provider.set_current_schema.side_effect = Exception("schema not supported")

        result = cmd.execute()

        assert result is not None
        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert any("set_current_schema skipped" in c for c in debug_calls)

    def test_ensure_connection_success_no_debug_log(self):
        """AC#3.5: _ensure_connection succeeds → no 'skipped' debug log for this block."""
        cmd, provider, log = self._make_command()
        provider._ensure_connection.return_value = None

        cmd.execute()

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert not any("_ensure_connection skipped" in c for c in debug_calls)

    def test_set_current_schema_success_no_debug_log(self):
        """set_current_schema succeeds → no 'set_current_schema skipped' debug log."""
        cmd, provider, log = self._make_command()
        provider.set_current_schema.return_value = None

        cmd.execute()

        debug_calls = [str(c) for c in log.debug.call_args_list]
        assert not any("set_current_schema skipped" in c for c in debug_calls)
