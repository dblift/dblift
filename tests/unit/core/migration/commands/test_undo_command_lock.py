"""``undo`` takes the migration lock, as ``migrate`` does.

An undo runs DDL and writes history, so it must not overlap a migration on the
same schema. The lock is taken before the undo plan is read, so the plan cannot
be stale, and it is released on every exit.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.migration import MigrationType
from tests.unit.core.migration.commands.test_undo_command_undone_count_not_doubled import (
    _make_applied_migration,
    _make_command,
    _make_undo_script,
)

REFUSAL = "Could not acquire migration lock - another migration may be running"


def _two_script_command():
    applied = [
        _make_applied_migration("1", MigrationType.SQL),
        _make_applied_migration("2", MigrationType.SQL),
    ]
    undo_scripts = [_make_undo_script("1"), _make_undo_script("2")]
    return _make_command(applied, undo_scripts), undo_scripts


def _record_calls(cmd) -> list:
    """Record the order of lock, state and execution calls in one list."""
    calls: list = []
    state = cmd.state_manager.build_state.return_value

    def acquire(*args, **kwargs):
        calls.append("acquire")
        return True

    def release(*args, **kwargs):
        calls.append("release")
        return True

    def build_state(*args, **kwargs):
        calls.append("build_state")
        return state

    def execute(*args, **kwargs):
        calls.append("execute")

    cmd.provider.acquire_migration_lock.side_effect = acquire
    cmd.provider.release_migration_lock.side_effect = release
    cmd.state_manager.build_state.side_effect = build_state
    cmd.execution_engine.execute_migration.side_effect = execute
    return calls


@pytest.mark.unit
class TestUndoMigrationLock:
    def test_undo_locks_before_reading_state(self):
        cmd, _ = _two_script_command()
        calls = _record_calls(cmd)

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert result.success, result.error_message
        assert calls.index("acquire") < calls.index("build_state")
        assert calls.count("release") == 1
        last_execute = len(calls) - 1 - calls[::-1].index("execute")
        assert calls.index("release") > last_execute
        cmd.provider.acquire_migration_lock.assert_called_once_with("test", wait_timeout_seconds=60)
        cmd.provider.release_migration_lock.assert_called_once_with("test")

    def test_refused_lock_fails_without_reading_state(self):
        cmd, _ = _two_script_command()
        cmd.provider.acquire_migration_lock.return_value = False
        cmd._log_command_completion = MagicMock()

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert result.error_message == REFUSAL
        cmd.log.error.assert_any_call(REFUSAL)
        cmd.state_manager.build_state.assert_not_called()
        cmd.execution_engine.execute_migration.assert_not_called()
        cmd.provider.release_migration_lock.assert_not_called()
        cmd._log_command_completion.assert_called_once_with("undo", result)

    def test_dry_run_does_not_lock(self):
        cmd, _ = _two_script_command()

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0", dry_run=True)

        assert result.error_message is None
        cmd.provider.acquire_migration_lock.assert_not_called()
        cmd.provider.release_migration_lock.assert_not_called()

    def test_lock_lost_stops_before_next_undo(self):
        cmd, undo_scripts = _two_script_command()
        cmd.provider.migration_lock_lost.side_effect = [False, True]

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert cmd.execution_engine.execute_migration.call_count == 1
        # Undo runs newest first, so the second script is the one for V1.
        assert result.error_message.endswith(f"stopping before {undo_scripts[0].script_name}")
        assert "The migration lock was lost" in result.error_message
        cmd.provider.release_migration_lock.assert_called_once_with("test")

    def test_lock_released_when_undo_raises(self):
        cmd, _ = _two_script_command()
        cmd.execution_engine.execute_migration.side_effect = RuntimeError("boom")

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert not result.success
        cmd.provider.release_migration_lock.assert_called_once_with("test")

    def test_lock_released_when_state_rebuild_raises(self):
        cmd, _ = _two_script_command()
        first_state = cmd.state_manager.build_state.return_value
        cmd.state_manager.build_state.side_effect = [first_state, RuntimeError("rebuild failed")]

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert result.error_message == "Undo operation failed: rebuild failed"
        cmd.provider.release_migration_lock.assert_called_once_with("test")

    def test_no_history_table_skips_lock(self):
        cmd, _ = _two_script_command()
        cmd.history_manager.has_history_table = False

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert result.success
        cmd.provider.acquire_migration_lock.assert_not_called()
        cmd.state_manager.build_state.assert_not_called()
        cmd.log.info.assert_any_call("No migrations to undo")

    def test_undo_error_callback_runs_while_lock_held(self):
        cmd, _ = _two_script_command()
        cmd.history_manager.has_history_table = True
        cmd._log_command_completion = MagicMock()
        calls = _record_calls(cmd)
        cmd.state_manager.build_state.side_effect = RuntimeError("x")
        cmd._fire = MagicMock(side_effect=lambda event: calls.append(event))

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert result.error_message == "Undo operation failed: x"
        assert calls.count("afterUndoError") == 1
        assert calls.index("afterUndoError") < calls.index("release")
        cmd._log_command_completion.assert_called_once_with("undo", result)
