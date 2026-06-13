"""Regression tests for mark-as-executed transaction handling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.migration.commands.migrate_command import MigrateCommand
from core.migration.migration import MigrationType


def _command_with_pending_migration(monkeypatch, provider: MagicMock) -> MigrateCommand:
    monkeypatch.setattr("core.licensing._guard._refresh_state", lambda: None)

    command = MigrateCommand.__new__(MigrateCommand)
    command.config = SimpleNamespace(database=SimpleNamespace(schema="public"))
    command.provider = provider
    command.log = MagicMock()
    command.journal = None
    command.history_manager = MagicMock()
    command.execution_engine = MagicMock()
    command._initialize_migration_execution = MagicMock(return_value=(True, True, None))
    command._update_final_state = MagicMock()
    command._log_command_completion = MagicMock()
    command.state_manager = MagicMock()
    command.state_manager.get_current_version.return_value = None
    command.state_manager.build_state.return_value = SimpleNamespace(
        applied_objects=[],
        pending_objects=[
            SimpleNamespace(
                script_name="V2__second.sql",
                version="2",
                description="second",
                type=MigrationType.SQL,
                checksum=123,
                content="CREATE TABLE ${TABLE_NAME} (id INT);",
            )
        ],
    )
    return command


@pytest.mark.unit
def test_mark_as_executed_commits_history_records(monkeypatch):
    provider = MagicMock()
    command = _command_with_pending_migration(monkeypatch, provider)

    result = command.execute(Path("migrations"), mark_as_executed=True)

    assert result.success is True
    command.history_manager.record_migration.assert_called_once()
    provider.commit_transaction.assert_called_once()
    command._update_final_state.assert_called_once()


@pytest.mark.unit
def test_mark_as_executed_commit_failure_fails_result(monkeypatch):
    provider = MagicMock()
    provider.commit_transaction.side_effect = Exception("commit failed")
    command = _command_with_pending_migration(monkeypatch, provider)

    result = command.execute(Path("migrations"), mark_as_executed=True)

    assert result.success is False
    assert "Failed to commit mark-as-executed history records" in result.error_message
    provider.commit_transaction.assert_called_once()
    command._update_final_state.assert_not_called()


@pytest.mark.unit
def test_dry_run_lists_pending_placeholder_migration_without_execution_parse(monkeypatch):
    provider = MagicMock()
    command = _command_with_pending_migration(monkeypatch, provider)

    result = command.execute(Path("migrations"), dry_run=True)

    assert result.success is True
    command.execution_engine.execute_migration.assert_not_called()
    provider.commit_transaction.assert_not_called()
    command._log_command_completion.assert_called_once()
