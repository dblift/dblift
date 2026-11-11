"""How ``migrate`` ends when marking fails or an error escapes the locked section.

* Marking a migration as executed fails: nothing is committed and the final
  schema version is not read.
* An error escapes after the run already recorded its failure (an error
  callback that itself fails): the recorded failure is kept, not logged again,
  and the error callbacks still fire.
* An error escapes a run that only marks migrations as executed: no script
  ran, so no error callback fires.
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
from dblift.db.provider_interfaces import TransactionalProvider
from tests.unit.core.migration.commands._plan_migrate_wiring import wire_plan_migrate


def _cmd():
    """Build a MigrateCommand with one pending versioned migration."""
    provider = MagicMock()
    provider.__class__ = TransactionalProvider
    provider.acquire_migration_lock.return_value = True
    provider.release_migration_lock.return_value = None

    history_manager = MagicMock()
    history_manager.get_applied_migrations.return_value = []

    pending = SimpleNamespace(
        script_name="V1__init.sql",
        version="1",
        description="init",
        type=MigrationType.SQL,
        checksum=123,
    )
    state_manager = wire_plan_migrate(MagicMock())
    state_manager.build_state.return_value = MigrationState(
        applied_objects=[],
        catalog=(CatalogMigration(pending, MigrationEligibility.PENDING),),
    )
    state_manager.get_current_version.return_value = None
    state_manager.apply_filters_to_migrations.side_effect = lambda migrations, **kwargs: list(
        migrations
    )

    migration_helpers = MagicMock()
    migration_helpers.setup_migration_parameters.return_value = (True, None)
    migration_helpers.validate_migrations_for_migrate.return_value = (True, None, 0.0)

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
        execution_engine=MagicMock(),
        migration_helpers=migration_helpers,
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


def _run(cmd, **kwargs):
    with (
        patch.object(cmd, "_run_preflight"),
        patch.object(cmd, "_log_command_header_update"),
        patch.object(cmd, "_log_current_schema_version"),
        patch.object(cmd, "_log_command_completion"),
        patch.object(cmd, "_update_final_state") as final_state,
        patch.object(cmd, "_fire") as fire,
    ):
        result = cmd.execute(Path("/migrations"), **kwargs)
    return result, final_state, fire


def _logged_errors(cmd):
    return [call.args[0] for call in cmd.log.error.call_args_list]


def test_a_failed_mark_commits_nothing_and_does_not_read_the_final_version():
    cmd = _cmd()
    cmd.history_manager.record_migration.side_effect = RuntimeError("history write failed")

    result, final_state, fire = _run(cmd, mark_as_executed=True)

    assert result.success is False
    assert result.error_message == "Failed to mark migration as executed: history write failed"
    cmd.provider.commit_transaction.assert_not_called()
    final_state.assert_not_called()
    fire.assert_not_called()


def test_an_error_escaping_after_the_failure_was_recorded_keeps_it_and_fires_error_callbacks():
    cmd = _cmd()

    def fail_then_raise(pending, result):
        result.set_error("Migration failed: V1 broke")
        raise RuntimeError("afterMigrateError callback failed")

    with patch.object(cmd, "_execute_migration_loop", side_effect=fail_then_raise):
        result, final_state, fire = _run(cmd)

    assert result.error_message == "Migration failed: V1 broke"
    assert not any(
        message.startswith("Exception during migration execution")
        for message in _logged_errors(cmd)
    )
    assert [call.args for call in fire.call_args_list] == [
        ("beforeMigrate",),
        ("beforeVersioned",),
        ("afterMigrateError",),
    ]
    final_state.assert_called_once_with(result)


def test_an_error_escaping_a_mark_as_executed_run_fires_no_error_callback():
    cmd = _cmd()
    cmd.provider.acquire_migration_lock.side_effect = RuntimeError("lock table unreadable")

    result, final_state, fire = _run(cmd, mark_as_executed=True)

    assert result.error_message == "Migration execution failed: lock table unreadable"
    assert "Exception during migration execution: lock table unreadable" in _logged_errors(cmd)
    fire.assert_not_called()
    final_state.assert_called_once_with(result)
