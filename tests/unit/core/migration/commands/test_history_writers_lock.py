"""``repair`` and ``baseline`` take the migration lock, as ``migrate`` and ``undo`` do.

Both write the schema history, so a real run must not overlap a migration on the
same schema. ``baseline`` re-checks under the lock that the history is still
empty. Dry runs write nothing and do not lock.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.baseline_command import BaselineCommand
from dblift.core.migration.commands.repair_command import RepairCommand
from dblift.db.provider_interfaces import TransactionalProvider
from tests.unit.core.migration.commands._plan_repairs_wiring import wire_plan_repairs

REFUSAL = "Could not acquire migration lock - another migration may be running"


def _make_provider(calls: list, *, acquired: bool = True):
    provider = MagicMock()
    provider.__class__ = TransactionalProvider

    def acquire(*args, **kwargs):
        calls.append("acquire")
        return acquired

    def release(*args, **kwargs):
        calls.append("release")
        return True

    provider.acquire_migration_lock.side_effect = acquire
    provider.release_migration_lock.side_effect = release
    provider.commit_transaction.side_effect = lambda *a, **k: calls.append("commit")
    return provider


def _make_command(command_cls, provider, history_manager=None):
    config = SimpleNamespace(database=SimpleNamespace(schema="public", type="postgresql"))
    return command_cls(
        config=config,
        log=MagicMock(),
        provider=provider,
        script_manager=MagicMock(),
        history_manager=history_manager or MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


def _repair_command(calls: list, *, acquired: bool = True):
    cmd = _make_command(RepairCommand, _make_provider(calls, acquired=acquired))

    def build_state(*args, **kwargs):
        calls.append("build_state")
        return MagicMock(applied_objects=[], failed_objects=[], missing_applied=())

    cmd.state_manager.build_state.side_effect = build_state
    wire_plan_repairs(cmd.state_manager)
    cmd.state_manager.get_applied_migration_records.return_value = []
    return cmd


def _baseline_command(calls: list, *, acquired: bool = True, existing_under_lock=None):
    history_manager = MagicMock()
    history_manager.has_history_table = True
    history_manager.record_migration.side_effect = lambda *a, **k: calls.append("record")
    cmd = _make_command(BaselineCommand, _make_provider(calls, acquired=acquired), history_manager)

    def applied_records(*args, **kwargs):
        # Empty while preflight looks, populated once the lock is held.
        return list(existing_under_lock) if "acquire" in calls and existing_under_lock else []

    cmd.state_manager.get_applied_migration_records.side_effect = applied_records
    return cmd


@pytest.mark.unit
class TestRepairLock:
    def test_repair_locks_before_reading_state(self):
        calls: list = []
        cmd = _repair_command(calls)

        result = cmd.execute(scripts_dir=MagicMock())

        assert result.error_message is None
        assert calls.index("acquire") < calls.index("build_state")
        assert calls.count("release") == 1
        assert calls.index("release") > calls.index("build_state")
        cmd.provider.acquire_migration_lock.assert_called_once_with(
            "public", wait_timeout_seconds=60
        )
        cmd.provider.release_migration_lock.assert_called_once_with("public")

    def test_repair_lock_refused(self):
        calls: list = []
        cmd = _repair_command(calls, acquired=False)
        cmd._log_command_completion = MagicMock()

        result = cmd.execute(scripts_dir=MagicMock())

        assert result.error_message == REFUSAL
        cmd.log.error.assert_any_call(REFUSAL)
        assert "build_state" not in calls
        assert "release" not in calls
        cmd._log_command_completion.assert_called_once_with("repair", result)


@pytest.mark.unit
class TestBaselineLock:
    def test_baseline_locks_around_write(self):
        calls: list = []
        cmd = _baseline_command(calls)

        result = cmd.execute("1.0", "initial")

        assert result.error_message is None
        assert result.baseline_version == "1.0"
        assert calls.index("acquire") < calls.index("record")
        assert calls.index("release") > calls.index("commit") > calls.index("record")
        assert calls.count("release") == 1

    def test_baseline_lock_refused(self):
        calls: list = []
        cmd = _baseline_command(calls, acquired=False)
        cmd._log_command_completion = MagicMock()

        result = cmd.execute("1.0", "initial")

        assert result.error_message == REFUSAL
        cmd.log.error.assert_any_call(REFUSAL)
        assert "record" not in calls
        assert "release" not in calls
        cmd._log_command_completion.assert_called_once_with("baseline", result)

    def test_baseline_rechecks_history_under_lock(self):
        calls: list = []
        cmd = _baseline_command(calls, existing_under_lock=[object()])

        result = cmd.execute("1.0", "initial")

        assert result.error_message == (
            "Baseline operation failed: Schema public already contains a migration "
            "history table with 1 migration(s). Baseline cannot be applied to a "
            "schema with existing migrations."
        )
        assert "record" not in calls
        assert calls.count("release") == 1


@pytest.mark.unit
@pytest.mark.parametrize("command", ["repair", "baseline"])
def test_dry_runs_do_not_lock(command):
    calls: list = []
    if command == "repair":
        cmd = _repair_command(calls)
        cmd.execute(scripts_dir=MagicMock(), dry_run=True)
    else:
        cmd = _baseline_command(calls)
        cmd.execute("1.0", "initial", dry_run=True)

    cmd.provider.acquire_migration_lock.assert_not_called()
    cmd.provider.release_migration_lock.assert_not_called()
