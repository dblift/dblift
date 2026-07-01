"""No-target-version undo: should_undo_version() returning (False, message) for the
newest migration must log-and-continue to the next candidate, not fail the command
(unlike the target-version path in test_undo_command_missing_undo_script.py, which
fails fast). This is the "most recent undoable migration" scan at the top of
UndoCommand.execute() when no --target-version is given.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.migration.commands.undo_command import UndoCommand
from core.migration.migration import MigrationType


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


def _make_command(applied_migrations, *, rules_side_effect):
    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = applied_migrations
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None

    migration_rules = MagicMock()
    migration_rules.should_undo_version.side_effect = rules_side_effect

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

    return cmd


@pytest.mark.unit
def test_no_target_version_skips_past_message_to_next_undoable_migration():
    """V2 can't be undone (already undone); the scan must fall through to V1
    instead of failing the whole command — the no-target scan only fails hard
    when NOTHING can be undone at all."""
    v2 = _make_migration(2)
    v1 = _make_migration(1)

    def rules(version, applied):
        if version == "2":
            return (False, "Version 2 has already been undone. Please specify version 1.")
        return (True, "")

    cmd = _make_command([v1, v2], rules_side_effect=rules)
    result = cmd.execute(scripts_dir=MagicMock())

    assert cmd.log.info.call_args_list
    logged = [call.args[0] for call in cmd.log.info.call_args_list]
    assert any("already been undone" in msg for msg in logged)
    # V1 was still picked up as the fallback candidate to undo.
    checked_versions = [
        call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
    ]
    assert checked_versions == ["2", "1"]
