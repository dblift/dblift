"""Regression tests for Python versioned migrations and versioned callbacks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.migration.commands.migrate_command import MigrateCommand
from core.migration.migration import MigrationType


@pytest.mark.unit
def test_python_migrations_trigger_versioned_callbacks(monkeypatch):
    monkeypatch.setattr("core.licensing._guard._refresh_state", lambda: None)

    command = MigrateCommand.__new__(MigrateCommand)
    command.config = SimpleNamespace(database=SimpleNamespace(schema="public"))
    command.provider = MagicMock()
    command.provider.acquire_migration_lock.return_value = True
    command.log = MagicMock()
    command.journal = None
    command._initialize_migration_execution = MagicMock(return_value=(True, True, None))
    command._execute_before_callbacks = MagicMock()
    command._execute_migration_loop = MagicMock()
    command._execute_after_callbacks = MagicMock()
    command._update_final_state = MagicMock()
    command._log_command_completion = MagicMock()
    command.state_manager = MagicMock()
    command.history_manager = MagicMock()
    command.history_manager.get_applied_migration_records.return_value = []
    python_migration = SimpleNamespace(
        script_name="V1__create_containers.py",
        version="1",
        type=MigrationType.PYTHON,
    )
    command.state_manager.build_state.return_value = SimpleNamespace(
        applied_objects=[],
        pending_objects=[python_migration],
    )
    command.state_manager.get_current_version.return_value = None

    result = command.execute(Path("migrations"))

    assert result.success is True
    before_args = command._execute_before_callbacks.call_args.args
    after_args = command._execute_after_callbacks.call_args.args
    assert before_args[1] == [python_migration]
    assert after_args[1] == [python_migration]
