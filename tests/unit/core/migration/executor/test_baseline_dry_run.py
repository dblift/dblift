"""Regression tests for baseline dry-run plumbing."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from dblift.core.migration.executor.migration_executor import MigrationExecutor


def test_baseline_forwards_dry_run_and_skips_snapshot():
    executor = MigrationExecutor.__new__(MigrationExecutor)
    executor._make_command_context = MagicMock(return_value=SimpleNamespace())

    with patch("dblift.core.migration.commands.baseline_command.BaselineCommand") as command_cls:
        command = command_cls.return_value
        command.execute.return_value = SimpleNamespace(success=True)

        result = MigrationExecutor.baseline(executor, "1.0.0", dry_run=True)

    assert result.success is True
    command.execute.assert_called_once_with(
        baseline_version="1.0.0",
        baseline_description="",
        dry_run=True,
    )
