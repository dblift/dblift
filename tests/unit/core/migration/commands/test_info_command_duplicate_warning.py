from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.migration.commands.info_command import InfoCommand, _normalize_filter
from core.migration.migration import MigrationType
from core.migration.state.migration_state import MigrationState


def _make_command(script_objects, applied_objects=None):
    config = SimpleNamespace(database=SimpleNamespace(schema="public"))
    log = MagicMock()
    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = script_objects
    state_manager = MagicMock()
    state_manager.build_state.return_value = MigrationState(
        applied_objects=applied_objects or [],
        pending_objects=[],
    )
    state_manager.get_current_version.return_value = "1"

    command = InfoCommand(
        config=config,
        log=log,
        provider=MagicMock(),
        script_manager=script_manager,
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
    return command, log


@pytest.mark.unit
def test_info_duplicate_warning_ignores_synthetic_baseline_history(tmp_path: Path):
    versioned_script = SimpleNamespace(
        script_name="V1__init.sql", version="1", type=MigrationType.SQL
    )
    baseline_history_row = SimpleNamespace(
        script_name="B1__.sql", version="1", type=MigrationType.BASELINE
    )
    command, log = _make_command([versioned_script], applied_objects=[baseline_history_row])

    command.execute(tmp_path)

    warnings = [call.args[0] for call in log.warning.call_args_list]
    assert not any("Duplicate version" in warning for warning in warnings)


@pytest.mark.unit
def test_info_duplicate_warning_still_reports_duplicate_filesystem_versions(tmp_path: Path):
    command, log = _make_command(
        [
            SimpleNamespace(script_name="V1__init.sql", version="1", type=MigrationType.SQL),
            SimpleNamespace(
                script_name="nested/V1__other.sql", version="1", type=MigrationType.SQL
            ),
        ]
    )

    command.execute(tmp_path)

    warnings = [call.args[0] for call in log.warning.call_args_list]
    assert any("Duplicate version 1" in warning for warning in warnings)


@pytest.mark.unit
def test_execute_display_human_false_skips_display(tmp_path: Path):
    """display_migration_info must NOT be called when display_human=False."""
    command, _ = _make_command([])
    command.execute(tmp_path, display_human=False)
    command.migration_ui.display_migration_info.assert_not_called()


@pytest.mark.unit
def test_execute_display_human_true_calls_display(tmp_path: Path):
    """display_migration_info IS called when display_human=True (default)."""
    command, _ = _make_command([])
    command.execute(tmp_path, display_human=True)
    command.migration_ui.display_migration_info.assert_called_once()


@pytest.mark.unit
def test_normalize_filter_splits_and_strips_comma_separated_values():
    """A comma-separated filter value is split into a stripped, non-empty list."""
    assert _normalize_filter("a, b ,c") == ["a", "b", "c"]
