"""Regression tests for P1.1 snapshot capture removal."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.migration.executor.migration_executor import MigrationExecutor

pytestmark = pytest.mark.unit


def _minimal_executor() -> MigrationExecutor:
    executor = MigrationExecutor.__new__(MigrationExecutor)
    executor._make_command_context = MagicMock(return_value=SimpleNamespace())
    return executor


def test_executor_does_not_expose_auto_capture_hook():
    assert not hasattr(MigrationExecutor, "_capture_snapshot")


def test_executor_does_not_expose_snapshot_service_attribute():
    executor = _minimal_executor()

    assert not hasattr(executor, "snapshot_service")


def test_migrate_does_not_pass_snapshot_service_to_command():
    executor = _minimal_executor()

    with patch("core.migration.commands.migrate_command.MigrateCommand") as command_cls:
        command = command_cls.return_value
        command.execute.return_value = SimpleNamespace(success=True)

        result = MigrationExecutor.migrate(executor, Path("/migrations"))

    assert result.success is True
    command_cls.assert_called_once_with(executor._make_command_context.return_value)
    assert "snapshot_service" not in command_cls.call_args.kwargs


def test_executor_does_not_expose_paid_diff_method():
    assert not hasattr(MigrationExecutor, "diff")
