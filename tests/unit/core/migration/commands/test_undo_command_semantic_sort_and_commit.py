"""Regression tests for BUG-A (lexicographic sort).

BUG-A: ``undo`` without ``--target-version`` must pick the semantically
highest version, not the lexicographically highest — so V10 beats V4, not
the other way around.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.migration.migration import MigrationType


def _make_migration(version: str, mtype):
    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = True
    m.script_name = f"V{version}__test"
    m.description = "test"
    m.checksum = "abc"
    m.content = None
    return m


def _make_command(applied_migrations):
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

    history_manager = MagicMock()
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
    return cmd, history_manager, execution_engine


@pytest.mark.unit
class TestVersionSortIsSemanticNotLexicographic:
    """BUG-A: the ``versioned_migrations.sort()`` at the no-target-version path."""

    def test_v10_undone_before_v4_without_target_version(self):
        v4 = _make_migration("4", MigrationType.SQL)
        v10 = _make_migration("10", MigrationType.SQL)
        # Order in applied_objects deliberately scrambled to exercise the sort.
        cmd, _, exec_engine = _make_command([v4, v10])

        cmd.execute(scripts_dir=MagicMock())

        # The SQL undo path calls execute_migration with the undo_migration —
        # but we lack real scripts in this test, so no execute_migration call
        # will actually happen. Instead, verify the rules layer was queried
        # for V10 first (the top of the sorted list) — NOT V4.
        rules_calls = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert rules_calls, "migration_rules was never consulted"
        assert rules_calls[0] == "10", (
            f"Expected V10 to be checked first (semantic sort), got {rules_calls[0]} "
            "(lexicographic sort puts '4' > '10' by char code)"
        )

    def test_dotted_versions_sorted_semantically(self):
        v19 = _make_migration("1.9", MigrationType.SQL)
        v110 = _make_migration("1.10", MigrationType.SQL)
        cmd, _, _ = _make_command([v19, v110])

        cmd.execute(scripts_dir=MagicMock())

        rules_calls = [
            call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
        ]
        assert rules_calls[0] == "1.10", f"1.10 should sort after 1.9, got {rules_calls[0]}"
