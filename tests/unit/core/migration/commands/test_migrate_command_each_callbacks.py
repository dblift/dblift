"""Tests for per-migration callback dispatch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.logger.results import MigrateResult
from core.migration.commands.migrate_command import MigrateCommand


@pytest.mark.unit
def test_migrate_dispatches_generic_and_command_specific_each_callbacks():
    command = MigrateCommand.__new__(MigrateCommand)
    command.journal = None
    command.execution_engine = MagicMock()
    command.log = MagicMock()
    command._execute_callbacks = MagicMock()
    migration = SimpleNamespace(
        script_name="V1__init.sql",
        version="1",
        description="init",
        type=SimpleNamespace(value="SQL"),
        checksum=123,
    )
    result = MigrateResult()

    assert command._execute_single_migration(
        migration=migration,
        scripts_dir=Path("migrations"),
        use_recursive=True,
        use_additional_dirs=None,
        dir_recursive_map=None,
        result=result,
    )

    events = [call.args[1] for call in command._execute_callbacks.call_args_list]
    assert events == ["beforeEach", "beforeEachMigrate", "afterEachMigrate", "afterEach"]


@pytest.mark.unit
def test_failing_beforeEachMigrate_callback_surfaces_its_own_error():
    """A beforeEachMigrate callback that raises must report its own failure.

    Regression test: start_time was assigned after the beforeEach/beforeEachMigrate
    callback dispatch, but read in the except block that a callback failure unwinds
    through, so a failing callback surfaced as UnboundLocalError instead of the
    callback's real error.
    """
    command = MigrateCommand.__new__(MigrateCommand)
    command.journal = None
    command.execution_engine = MagicMock()
    command.log = MagicMock()

    def _execute_callbacks(scripts_dir, event, *args, **kwargs):
        if event == "beforeEachMigrate":
            raise RuntimeError("no such table: err_log")

    command._execute_callbacks = MagicMock(side_effect=_execute_callbacks)
    migration = SimpleNamespace(
        script_name="V1__init.sql",
        version="1",
        description="init",
        type=SimpleNamespace(value="SQL"),
        checksum=123,
    )
    result = MigrateResult()

    success = command._execute_single_migration(
        migration=migration,
        scripts_dir=Path("migrations"),
        use_recursive=True,
        use_additional_dirs=None,
        dir_recursive_map=None,
        result=result,
    )

    assert success is False
    assert result.error_message is not None
    assert "no such table: err_log" in result.error_message
    assert "start_time" not in result.error_message
