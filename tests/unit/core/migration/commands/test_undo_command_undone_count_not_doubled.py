"""Regression test for issue #855.

``UndoResult.undone_count`` was incremented twice per undone migration:
once inside ``add_undone_migration()`` (which sets it to
``len(undone_migrations)``) and again by a redundant standalone
``result.undone_count += 1`` in ``undo_command.py``. After undoing
multiple migrations, ``undone_count`` no longer matched
``len(undone_migrations)``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.migration.migration import MigrationType


def _make_applied_migration(version: str, mtype):
    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = True
    m.script_name = f"V{version}__test"
    m.description = "test"
    m.checksum = "abc"
    m.content = None
    m.tags = []
    return m


def _make_undo_script(version: str):
    s = MagicMock()
    s.version = version
    s.type = MigrationType.UNDO_SQL
    s.script_name = f"U{version}__test"
    s.description = "undo test"
    s.tags = []
    return s


def _make_command(applied_migrations, undo_scripts):
    from core.migration.commands.undo_command import UndoCommand

    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = applied_migrations
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None

    migration_rules = MagicMock()
    migration_rules.should_undo_version.return_value = (True, None)

    executor_factory = MagicMock()
    executor_factory.get_executor.return_value = None

    execution_engine = MagicMock()
    execution_engine.executor_factory = executor_factory
    # execute_migration is a no-op mock: it must not touch result.error_message,
    # so every migration in this test takes the "successful undo" path.

    history_manager = MagicMock()
    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = undo_scripts

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
class TestUndoneCountNotDoubled:
    """Issue #855: undone_count must equal len(undone_migrations)."""

    def test_undone_count_matches_undone_migrations_after_multiple_undos(self):
        v1 = _make_applied_migration("1", MigrationType.SQL)
        v2 = _make_applied_migration("2", MigrationType.SQL)
        applied_migrations = [v1, v2]
        undo_scripts = [_make_undo_script("1"), _make_undo_script("2")]

        cmd = _make_command(applied_migrations, undo_scripts)

        result = cmd.execute(scripts_dir=MagicMock(), target_version="0")

        assert len(result.undone_migrations) == 2, (
            f"Expected both migrations to be undone, got {len(result.undone_migrations)}"
        )
        assert result.undone_count == len(result.undone_migrations), (
            f"undone_count ({result.undone_count}) must equal "
            f"len(undone_migrations) ({len(result.undone_migrations)})"
        )
