"""The migration lock release guard must start the moment the lock is acquired."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.base_command import BaseCommand


def _command(acquired: bool) -> BaseCommand:
    cmd = BaseCommand.__new__(BaseCommand)
    cmd.provider = MagicMock()
    cmd.config = MagicMock()
    cmd.config.database.schema = "public"
    cmd.log = MagicMock()
    cmd.provider.acquire_migration_lock.return_value = acquired
    return cmd


def test_lock_released_when_interrupted_right_after_acquire():
    cmd = _command(acquired=True)
    # A SIGTERM turned into SystemExit lands while the "acquired" line is logged.
    cmd.log.info.side_effect = SystemExit(143)

    with pytest.raises(SystemExit):
        with cmd._migration_lock():
            pass

    cmd.provider.release_migration_lock.assert_called_once_with("public")


def test_refused_lock_is_not_released():
    cmd = _command(acquired=False)

    with cmd._migration_lock() as acquired:
        assert acquired is False

    cmd.provider.release_migration_lock.assert_not_called()


def test_release_reporting_not_held_warns():
    cmd = _command(acquired=True)
    cmd.provider.release_migration_lock.return_value = False

    with cmd._migration_lock() as acquired:
        assert acquired is True

    cmd.log.warning.assert_called_once_with(
        "The migration lock was no longer held by this run "
        "(lost or already released); nothing to release"
    )


def test_release_failure_warns():
    cmd = _command(acquired=True)
    cmd.provider.release_migration_lock.side_effect = RuntimeError("boom")

    with cmd._migration_lock() as acquired:
        assert acquired is True

    cmd.log.warning.assert_called_once_with("Could not release migration lock: boom")
