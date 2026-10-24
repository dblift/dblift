"""``migrate`` must say so when it cannot take the migration lock.

When ``acquire_migration_lock`` returned False the command set the error on
its result and returned without logging anything, so a command-line run that
gave up waiting for another migrator ended with a non-zero exit code and no
message at all.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.migration_state import (
    CatalogMigration,
    MigrationEligibility,
    MigrationState,
)
from tests.unit.core.migration.commands._plan_migrate_wiring import wire_plan_migrate

REFUSAL = "Could not acquire migration lock - another migration may be running"


def _cmd(pending, execute_side_effect=None):
    """Build a MigrateCommand wired to reach the lock and execute path."""
    provider = MagicMock()
    provider.acquire_migration_lock.return_value = True
    provider.release_migration_lock.return_value = None

    history_manager = MagicMock()
    history_manager.create_schema_and_history_table.return_value = None
    history_manager.get_applied_migrations.return_value = []

    state = MigrationState(
        applied_objects=[],
        catalog=tuple(CatalogMigration(obj, MigrationEligibility.PENDING) for obj in pending),
    )

    state_manager = wire_plan_migrate(MagicMock())
    state_manager.build_state.return_value = state
    state_manager.get_current_version.return_value = None
    state_manager.apply_filters_to_migrations.side_effect = lambda migrations, **kwargs: list(
        migrations
    )

    migration_helpers = MagicMock()
    migration_helpers.setup_migration_parameters.return_value = (True, None)
    migration_helpers.validate_migrations_for_migrate.return_value = (True, None, 0.0)

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
        validator=MagicMock(),
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


def _run_without_completion_patch(cmd):
    with patch.object(cmd, "_run_preflight"):
        with patch.object(cmd, "_log_command_header_update"):
            with patch.object(cmd, "_log_current_schema_version"):
                with patch.object(cmd, "_log_command_completion") as completion:
                    result = cmd.execute(Path("/migrations"))
    return result, completion


def test_refused_lock_is_logged_and_fails_the_command() -> None:
    cmd = _cmd([_repeatable()])
    cmd.provider.acquire_migration_lock.return_value = False

    result, completion = _run_without_completion_patch(cmd)

    assert result.success is False
    assert result.error_message == REFUSAL
    cmd.log.error.assert_any_call(REFUSAL)
    completion.assert_called_once_with("migrate", result)
    cmd.execution_engine.execute_migration.assert_not_called()
    cmd.provider.release_migration_lock.assert_not_called()
