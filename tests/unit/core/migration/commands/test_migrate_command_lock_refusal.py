"""``migrate`` must say so when it cannot take the migration lock.

When ``acquire_migration_lock`` returned False the command set the error on
its result and returned without logging anything, so a command-line run that
gave up waiting for another migrator ended with a non-zero exit code and no
message at all.
"""

from pathlib import Path
from unittest.mock import patch

from tests.unit.core.migration.commands.test_migrate_command_repeatable_lock_race import (
    _cmd,
    _repeatable,
)

REFUSAL = "Could not acquire migration lock - another migration may be running"


def _run_without_completion_patch(cmd):
    with patch.object(cmd, "_run_preflight"):
        with patch.object(cmd, "_log_command_header_update"):
            with patch.object(cmd, "_log_current_schema_version"):
                with patch.object(cmd, "_log_command_completion") as completion:
                    result = cmd.execute(Path("/migrations"))
    return result, completion


def test_refused_lock_is_logged_and_fails_the_command() -> None:
    cmd = _cmd([_repeatable()], applied_after_lock=[])
    cmd.provider.acquire_migration_lock.return_value = False

    result, completion = _run_without_completion_patch(cmd)

    assert result.success is False
    assert result.error_message == REFUSAL
    cmd.log.error.assert_any_call(REFUSAL)
    completion.assert_called_once_with("migrate", result)
    cmd.execution_engine.execute_migration.assert_not_called()
    cmd.provider.release_migration_lock.assert_not_called()
