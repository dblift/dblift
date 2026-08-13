"""BUG-10 regression: undo --target-version fails fast when undo script is missing.

Before this fix, UndoCommand.execute() called self.log.info(message) and
continued the loop when should_undo_version() returned (False, message).
This caused the command to exit with "No migrations to undo" (success) even
though reaching the target version was impossible without the missing script.

The fix replaces the log-and-continue with result.set_error(message) + early
return so callers get a hard error.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.migration.commands.undo_command import UndoCommand
from core.migration.migration import MigrationType
from core.migration.state.migration_state_manager import MigrationStateManager


def _make_migration(version, mtype=MigrationType.SQL, success=True):
    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = success
    m.script_name = f"V{version}__test.sql"
    m.description = "test"
    m.checksum = "abc"
    m.content = None
    return m


def _make_command(applied_migrations, *, rules_side_effect=None):
    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = applied_migrations
    migration_state.all_applied_objects = list(applied_migrations)
    migration_state.pending_objects = []
    migration_state.pending = []
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None
    _filter_mgr = MigrationStateManager.__new__(MigrationStateManager)
    state_manager.apply_filters_to_migrations.side_effect = (
        lambda migrations, **kwargs: _filter_mgr.apply_filters_to_migrations(migrations, **kwargs)
    )

    migration_rules = MagicMock()
    if rules_side_effect:
        migration_rules.should_undo_version.side_effect = rules_side_effect
    else:
        migration_rules.should_undo_version.return_value = (True, None)

    executor_factory = MagicMock()
    executor_factory.get_executor.return_value = None

    execution_engine = MagicMock()
    execution_engine.executor_factory = executor_factory

    history_manager = MagicMock()
    history_manager.record_undo.return_value = True

    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = []

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=script_manager,
        history_manager=history_manager,
        validator=MagicMock(),
        execution_engine=execution_engine,
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=migration_rules,
    )
    cmd.journal = None
    cmd.placeholder_service = MagicMock()
    cmd.migration_helpers.setup_migration_parameters.return_value = (True, None)

    return cmd, migration_rules


@pytest.mark.unit
class TestUndoCommandMissingUndoScript:
    def test_missing_undo_script_above_target_returns_error(self):
        """V3 has no undo script; targeting V1 must fail, not silently skip."""
        v3 = _make_migration(3)
        v2 = _make_migration(2)
        v1 = _make_migration(1)

        error_msg = "No undo script found for V3__test.sql"

        def rules(version, applied):
            if version == "3":
                return (False, error_msg)
            return (True, None)

        cmd, _ = _make_command([v1, v2, v3], rules_side_effect=rules)
        result = cmd.execute(scripts_dir=MagicMock(), target_version=1)

        assert not result.success
        assert result.error_message == error_msg

    def test_missing_undo_script_above_target_does_not_undo_lower(self):
        """When V3 has no undo script, V2 and V1 must NOT be undone."""
        v3 = _make_migration(3)
        v2 = _make_migration(2)
        v1 = _make_migration(1)

        def rules(version, applied):
            if version == "3":
                return (False, "No undo script for V3")
            return (True, None)

        cmd, _ = _make_command([v1, v2, v3], rules_side_effect=rules)
        cmd.provider.execute_script = MagicMock()
        result = cmd.execute(scripts_dir=MagicMock(), target_version=1)

        # Provider should never execute anything
        cmd.provider.execute_script.assert_not_called()
        assert not result.success

    def test_missing_script_without_message_does_not_fail_fast(self):
        """(False, None) from rules means 'no message' — must NOT trigger fail-fast."""
        v3 = _make_migration(3)

        def rules(version, applied):
            return (False, None)  # no message means unknown / skip-silently

        cmd, _ = _make_command([v3], rules_side_effect=rules)
        result = cmd.execute(scripts_dir=MagicMock(), target_version=2)

        # With no message, no error is set — falls through to "No migrations to undo"
        # which is a completed (success) result, not a failure
        assert result.error_message is None
