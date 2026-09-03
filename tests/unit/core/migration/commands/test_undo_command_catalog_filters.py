"""Undo selects applied Success, then resolves Available undo scripts from the catalog."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.undo_command import UndoCommand
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.migration_display_state import MigrationDisplayState
from dblift.core.migration.state.migration_state import MigrationEntry, MigrationState


def _applied(version, *, success=True, mtype=MigrationType.SQL, tags=None):
    m = SimpleNamespace(
        version=str(version),
        type=mtype,
        success=success,
        script_name=f"V{version}__test.sql",
        description="test",
        checksum="abc",
        content=None,
        tags=list(tags) if tags is not None else [],
    )
    return m


def _undo_script(version, script_name=None):
    return SimpleNamespace(
        version=str(version),
        type=MigrationType.UNDO_SQL,
        script_name=script_name or f"U{version}__test.sql",
        description="undo test",
        tags=[],
        format=SimpleNamespace(name="SQL"),
        content=None,
    )


def _entry(script, version, status, type_="UNDO_SQL"):
    return MigrationEntry(script, str(version), "test", type_, status, None)


def _make_command(state, *, scan_scripts=None):
    state_manager = MagicMock()
    state_manager.build_state.return_value = state
    state_manager.get_current_version.return_value = None
    state_manager.apply_filters_to_migrations.side_effect = lambda migrations, **kwargs: list(
        migrations
    )

    migration_rules = MagicMock()
    migration_rules.should_undo_version.return_value = (True, None)
    migration_rules._is_currently_undone.return_value = False

    execution_engine = MagicMock()
    execution_engine.executor_factory.get_executor.return_value = None
    execution_engine.get_executable_sql_statements.return_value = ["DROP TABLE t"]

    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = list(scan_scripts or [])

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=script_manager,
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=execution_engine,
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=migration_rules,
    )
    cmd.journal = None
    cmd.placeholder_service = MagicMock()
    cmd.migration_helpers.setup_migration_parameters.return_value = (True, None)
    return cmd


@pytest.mark.unit
class TestUndoResolvesAvailableFromCatalog:
    def test_available_undo_script_comes_from_catalog_not_script_scan(self):
        applied = _applied(2)
        catalog_undo = _undo_script(2, "U2__from_catalog.sql")
        scan_undo = _undo_script(2, "U2__from_scan.sql")
        state = MigrationState(
            pending=[
                _entry("U2__from_catalog.sql", "2", MigrationDisplayState.AVAILABLE.value),
            ],
            pending_objects=[catalog_undo],
            applied_objects=[applied],
            all_applied_objects=[applied],
        )
        cmd = _make_command(state, scan_scripts=[scan_undo])

        result = cmd.execute(scripts_dir=MagicMock(), dry_run=True, show_sql=True)

        assert result.success, result.error_message
        assert [row.script for row in result.sql] == ["U2__from_catalog.sql"]
        cmd.script_manager.get_migration_scripts.assert_not_called()

    def test_build_state_does_not_receive_tag_or_version_omit_filters(self):
        applied = _applied(2)
        catalog_undo = _undo_script(2)
        state = MigrationState(
            pending=[_entry(catalog_undo.script_name, "2", MigrationDisplayState.AVAILABLE.value)],
            pending_objects=[catalog_undo],
            applied_objects=[applied],
            all_applied_objects=[applied],
        )
        cmd = _make_command(state)

        cmd.execute(
            scripts_dir=MagicMock(),
            target_version="1",
            tags="feature",
            versions="2",
            exclude_versions="9",
            dry_run=True,
        )

        kwargs = cmd.state_manager.build_state.call_args.kwargs
        assert kwargs.get("target_version") == "1"
        assert kwargs.get("tags") is None
        assert kwargs.get("exclude_tags") is None
        assert kwargs.get("versions") is None
        assert kwargs.get("exclude_versions") is None

    def test_target_version_is_rollback_to_not_apply_filters_target(self):
        v1 = _applied(1)
        v2 = _applied(2)
        v3 = _applied(3)
        u2 = _undo_script(2)
        u3 = _undo_script(3)
        state = MigrationState(
            pending=[
                _entry(u2.script_name, "2", MigrationDisplayState.AVAILABLE.value),
                _entry(u3.script_name, "3", MigrationDisplayState.AVAILABLE.value),
            ],
            pending_objects=[u2, u3],
            applied_objects=[v1, v2, v3],
            all_applied_objects=[v1, v2, v3],
        )
        cmd = _make_command(state)

        result = cmd.execute(scripts_dir=MagicMock(), target_version="1", dry_run=True)

        assert result.success, result.error_message
        kwargs = cmd.state_manager.apply_filters_to_migrations.call_args.kwargs
        assert "target_version" not in kwargs
        checked = [call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list]
        assert checked == ["3", "2"]
