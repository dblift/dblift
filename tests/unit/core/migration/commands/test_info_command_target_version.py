"""Info passes target_version into build_state as label context only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from core.migration.commands.info_command import InfoCommand
from core.migration.state.migration_state import MigrationState

pytestmark = pytest.mark.unit


def _make_info_command(*, config_target_version=None):
    config = SimpleNamespace(
        database=SimpleNamespace(schema="public"),
        target_version=config_target_version,
    )
    state_manager = MagicMock()
    state_manager.build_state.return_value = MigrationState(
        applied_objects=[],
        pending_objects=[],
    )
    state_manager.get_current_version.return_value = None

    command = InfoCommand(
        config=config,
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=MagicMock(get_migration_scripts=MagicMock(return_value=[])),
        history_manager=MagicMock(get_applied_migrations=MagicMock(return_value=[])),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=MagicMock(get_migration_data=MagicMock(return_value=[])),
        migration_rules=MagicMock(),
    )

    def run_lifecycle(_name, result, body, **_kwargs):
        body()
        return result

    command._run_command_lifecycle = run_lifecycle  # type: ignore[method-assign]
    command._log_current_schema_version = MagicMock()
    command._run_preflight = MagicMock(return_value=None)
    return command


class TestInfoCommandTargetVersion:
    def test_build_state_receives_explicit_target_version(self):
        cmd = _make_info_command(config_target_version="9")
        cmd.execute(Path("/tmp"), target_version="4")

        kwargs = cmd.state_manager.build_state.call_args.kwargs
        assert kwargs.get("target_version") == "4"

    def test_build_state_falls_back_to_config_target_version(self):
        cmd = _make_info_command(config_target_version="4")
        cmd.execute(Path("/tmp"), target_version=None)

        kwargs = cmd.state_manager.build_state.call_args.kwargs
        assert kwargs.get("target_version") == "4"

    def test_explicit_target_version_wins_over_config(self):
        cmd = _make_info_command(config_target_version="9")
        cmd.execute(Path("/tmp"), target_version="4")

        kwargs = cmd.state_manager.build_state.call_args.kwargs
        assert kwargs.get("target_version") == "4"


class TestExecutorInfoForwardsTargetVersion:
    def test_info_forwards_target_version_to_command_execute(self):
        from core.migration.executor.migration_executor import MigrationExecutor

        executor = MigrationExecutor.__new__(MigrationExecutor)
        executor._make_command_context = MagicMock(return_value=MagicMock())

        with patch("core.migration.commands.info_command.InfoCommand") as mock_cmd_cls:
            command = mock_cmd_cls.return_value
            command.execute.return_value = MagicMock()
            executor.info(Path("/tmp"), target_version="4")

        kwargs = command.execute.call_args.kwargs
        assert kwargs.get("target_version") == "4"
