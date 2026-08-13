"""Issue #811: repeatable migrations must be re-checked against the
post-lock history snapshot, the same way versioned migrations already are.

The losing side of a concurrent ``migrate()`` race correctly re-checks and
skips VERSIONED migrations already applied by the winning process (see
``test_migrate_command_bug01_post_lock_filter.py``), but never re-checked
REPEATABLE migrations — ``_filter_already_applied`` explicitly skipped past
non-VERSIONED history rows. That meant a repeatable already applied (with
unchanged content) by the winner got unconditionally re-executed by the
loser: a non-idempotent script fails outright, an idempotent one silently
double-applies.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.migration.commands.migrate_command import MigrateCommand
from core.migration.migration import AppliedMigration, MigrationType
from core.migration.state.migration_display_state import MigrationDisplayState
from core.migration.state.migration_state import MigrationEntry, MigrationState


def _cmd(pending, applied_after_lock, execute_side_effect=None):
    """Build a MigrateCommand wired to reach the post-lock filter/execute path."""
    provider = MagicMock()
    provider.acquire_migration_lock.return_value = True
    provider.release_migration_lock.return_value = None

    history_manager = MagicMock()
    history_manager.create_schema_and_history_table.return_value = None
    history_manager.get_applied_migrations.return_value = []
    # This is what _filter_already_applied is called with post-lock —
    # simulates the winning process's committed history.
    history_manager.get_applied_migration_records.return_value = applied_after_lock

    state = MigrationState()
    state.applied_objects = []
    state.pending_objects = pending
    state.pending = [
        MigrationEntry(
            getattr(obj, "script_name", ""),
            str(getattr(obj, "version", "") or "") or None,
            getattr(obj, "description", None),
            getattr(getattr(obj, "type", None), "name", None),
            MigrationDisplayState.PENDING.value,
            None,
        )
        for obj in pending
    ]

    state_manager = MagicMock()
    state_manager.build_state.return_value = state
    state_manager.get_current_version.return_value = None
    state_manager.apply_filters_to_migrations.side_effect = (
        lambda migrations, **kwargs: list(migrations)
    )

    migration_helpers = MagicMock()
    migration_helpers.setup_migration_parameters.return_value = (True, None)

    execution_engine = MagicMock()
    if execute_side_effect is not None:
        execution_engine.execute_migration.side_effect = execute_side_effect

    config = MagicMock()
    config.database.schema = "public"
    config.database.type = "postgresql"

    return MigrateCommand(
        config=config,
        log=MagicMock(),
        provider=provider,
        script_manager=MagicMock(),
        history_manager=history_manager,
        validator=None,
        execution_engine=execution_engine,
        migration_helpers=migration_helpers,
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


def _repeatable(script_name="R__view.sql", checksum=999):
    return SimpleNamespace(
        script_name=script_name,
        version=None,
        description="view",
        type=MigrationType.REPEATABLE,
        checksum=checksum,
    )


def _run(cmd):
    with patch.object(cmd, "_run_preflight"):
        with patch.object(cmd, "_log_command_header_update"):
            with patch.object(cmd, "_log_current_schema_version"):
                with patch.object(cmd, "_log_command_completion"):
                    with patch.object(cmd, "_update_final_state"):
                        return cmd.execute(Path("/migrations"))


class TestRepeatableReCheckedAfterLock(unittest.TestCase):
    def test_repeatable_already_applied_by_winner_is_skipped(self):
        """A repeatable with unchanged content already applied (successfully)
        by the process that won the lock race must be skipped, not
        re-executed — mirrors the existing VERSIONED post-lock re-check.
        """
        pending = [_repeatable(checksum=999)]
        applied_after_lock = [
            AppliedMigration(
                script_name="R__view.sql",
                version=None,
                description="view",
                type=MigrationType.REPEATABLE,
                checksum=999,
                success=True,
                installed_rank=1,
            )
        ]

        def _fail_if_reexecuted(migration, result):
            # A genuinely non-idempotent repeatable would fail for real if
            # re-run after the winner already applied it (e.g. "object
            # already exists"). Any call here proves the bug: the migration
            # should have been skipped instead.
            result.set_error("object already exists")

        cmd = _cmd(pending, applied_after_lock, execute_side_effect=_fail_if_reexecuted)

        result = _run(cmd)

        cmd.execution_engine.execute_migration.assert_not_called()
        self.assertTrue(result.success)
        self.assertIsNone(result.error_message)

    def test_repeatable_with_changed_checksum_still_executes(self):
        """A repeatable whose content genuinely changed (checksum differs
        from the post-lock history row) must still be executed — the
        post-lock re-check must not over-skip.
        """
        pending = [_repeatable(checksum=999)]
        applied_after_lock = [
            AppliedMigration(
                script_name="R__view.sql",
                version=None,
                description="view",
                type=MigrationType.REPEATABLE,
                checksum=111,
                success=True,
                installed_rank=1,
            )
        ]

        cmd = _cmd(pending, applied_after_lock)

        result = _run(cmd)

        cmd.execution_engine.execute_migration.assert_called_once()
        self.assertTrue(result.success)

    def test_repeatable_not_yet_applied_still_executes(self):
        """A repeatable with no matching history row at all (never applied
        by anyone) must still be executed."""
        pending = [_repeatable(checksum=999)]

        cmd = _cmd(pending, applied_after_lock=[])

        result = _run(cmd)

        cmd.execution_engine.execute_migration.assert_called_once()
        self.assertTrue(result.success)


if __name__ == "__main__":
    unittest.main()
