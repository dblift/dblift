"""``migrate`` stops when its migration lock lease is lost.

Once the heartbeat reports the lease lost (reclaimed by another process, or
unrefreshable for a whole lease window), another ``migrate`` may already be
running. The migration in flight cannot be interrupted safely, but no further
migration may start.
"""

from types import SimpleNamespace

from dblift.core.migration.migration import MigrationType
from tests.unit.core.migration.commands.test_migrate_command_repeatable_lock_race import (
    _cmd,
    _run,
)


def _versioned(version: str) -> SimpleNamespace:
    return SimpleNamespace(
        script_name=f"V{version}__step.sql",
        version=version,
        description="step",
        type=MigrationType.SQL,
        checksum=int(version),
    )


def test_lost_lease_stops_before_the_next_migration() -> None:
    cmd = _cmd([_versioned("1"), _versioned("2")], applied_after_lock=[])
    cmd.provider.migration_lock_lost.side_effect = [False, True, True]

    result = _run(cmd)

    executed = [call.args[0].version for call in cmd.execution_engine.execute_migration.mock_calls]
    assert executed == ["1"]
    assert result.success is False
    assert "lock" in (result.error_message or "").lower()
    cmd.provider.release_migration_lock.assert_called_once()


def test_held_lease_runs_every_migration() -> None:
    cmd = _cmd([_versioned("1"), _versioned("2")], applied_after_lock=[])
    cmd.provider.migration_lock_lost.return_value = False

    result = _run(cmd)

    executed = [call.args[0].version for call in cmd.execution_engine.execute_migration.mock_calls]
    assert executed == ["1", "2"]
    assert result.error_message is None
