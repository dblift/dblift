"""Unit tests for info_command, snapshot_command, and undo_command — uncovered branches.

Targets:
- core/migration/commands/info_command.py  (69% → 80%+)
- core/migration/commands/snapshot_command.py (71% → 80%+)
- core/migration/commands/undo_command.py (70% → 80%+)
"""

from __future__ import annotations

import datetime
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

# ===========================================================================
# Helpers
# ===========================================================================


def _make_info_command(
    script_objects=None,
    applied_objects=None,
    migration_data=None,
    all_applied_migrations=None,
    state_manager_raises=False,
):
    """Build an InfoCommand with minimal mocked collaborators."""
    from core.migration.commands.info_command import InfoCommand
    from core.migration.state.migration_state import MigrationState

    config = SimpleNamespace(database=SimpleNamespace(schema="public"))
    log = MagicMock()
    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = script_objects or []
    state_manager = MagicMock()

    if state_manager_raises:
        state_manager.build_state.side_effect = RuntimeError("build failed")
    else:
        state_manager.build_state.return_value = MigrationState(
            applied_objects=applied_objects or [],
            pending_objects=[],
        )

    state_manager.get_current_version.return_value = "1"

    history_manager = MagicMock()
    history_manager.get_applied_migrations.return_value = all_applied_migrations or []

    migration_ui = MagicMock()
    migration_ui.get_migration_data.return_value = migration_data or []

    command = InfoCommand(
        config=config,
        log=log,
        provider=MagicMock(),
        script_manager=script_manager,
        history_manager=history_manager,
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=migration_ui,
        migration_rules=MagicMock(),
    )

    # Bypass lifecycle to exercise body directly
    def run_lifecycle(_name, result, body, **_kwargs):
        body()
        return result

    command._run_command_lifecycle = run_lifecycle  # type: ignore[method-assign]
    command._log_current_schema_version = MagicMock()
    command._run_preflight = MagicMock(return_value=None)
    return command, log


def _make_undo_command(applied_migrations, *, rules_return=None, provider=None, has_scripts=None):
    """Build an UndoCommand with minimal mocked collaborators."""
    from core.migration.commands.undo_command import UndoCommand
    from core.migration.migration import MigrationType

    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = applied_migrations
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None

    migration_rules = MagicMock()
    migration_rules.should_undo_version.return_value = rules_return or (True, None)

    executor_factory = MagicMock()
    executor_factory.get_executor.return_value = None

    execution_engine = MagicMock()
    execution_engine.executor_factory = executor_factory

    history_manager = MagicMock()
    history_manager.record_undo.return_value = True

    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = has_scripts or []

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=provider or MagicMock(),
        script_manager=script_manager,
        history_manager=history_manager,
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


def _make_migration(version, mtype, success=True, has_undo_fn=False, tags=None):
    from core.migration.migration import MigrationType

    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = success
    m.script_name = f"V{version}__test.sql"
    m.description = "test"
    m.checksum = "abc"
    if tags is not None:
        m.tags = tags
    if mtype == MigrationType.PYTHON:
        m.content = "def migrate(ctx): pass" if has_undo_fn else "def migrate(ctx): pass"
    else:
        m.content = None
    return m


# ===========================================================================
# normalize_migration_info_status
# ===========================================================================


class TestNormalizeMigrationInfoStatus(unittest.TestCase):
    """Test the free-function normalize_migration_info_status."""

    def setUp(self):
        from core.migration.commands.info_command import normalize_migration_info_status

        self.fn = normalize_migration_info_status

    def test_success_maps_to_SUCCESS(self):
        self.assertEqual(self.fn("Success"), "SUCCESS")

    def test_applied_maps_to_SUCCESS(self):
        self.assertEqual(self.fn("APPLIED"), "SUCCESS")

    def test_failed_maps_to_FAILED(self):
        self.assertEqual(self.fn("failed"), "FAILED")

    def test_pending_maps_to_PENDING(self):
        self.assertEqual(self.fn("Pending"), "PENDING")

    def test_undone_maps_to_UNDONE(self):
        self.assertEqual(self.fn("undone"), "UNDONE")

    def test_baseline_maps_to_BASELINE(self):
        self.assertEqual(self.fn("Baseline"), "BASELINE")

    def test_unknown_state_passthrough_uppercase(self):
        self.assertEqual(self.fn("CustomState"), "CUSTOMSTATE")

    def test_none_maps_to_UNKNOWN(self):
        self.assertEqual(self.fn(None), "UNKNOWN")

    def test_empty_string_maps_to_UNKNOWN(self):
        self.assertEqual(self.fn(""), "UNKNOWN")


# ===========================================================================
# InfoCommand
# ===========================================================================


class TestInfoCommandMigrationData(unittest.TestCase):
    """Test InfoCommand.execute population of migrations list."""

    def test_migrations_empty_when_no_data(self):
        cmd, _ = _make_info_command(migration_data=[])
        result = cmd.execute(Path("/tmp"))
        self.assertEqual(result.migrations, [])

    def test_migrations_populated_from_migration_data(self):
        data = [
            {
                "state": "Success",
                "script": "V1__init.sql",
                "version": "1",
                "description": "Init",
                "type": "SQL",
                "checksum": "abc",
                "installed_on": None,
                "execution_time": 200,
                "installed_by": "user",
            }
        ]
        cmd, _ = _make_info_command(migration_data=data)
        result = cmd.execute(Path("/tmp"))
        self.assertEqual(len(result.migrations), 1)
        self.assertEqual(result.migrations[0].script, "V1__init.sql")
        self.assertEqual(result.migrations[0].status, "SUCCESS")

    def test_migration_data_non_iterable_handled_gracefully(self):
        """get_migration_data returning a non-iterable is handled without crash."""
        cmd, _ = _make_info_command()
        cmd.migration_ui.get_migration_data.return_value = 42  # not iterable
        result = cmd.execute(Path("/tmp"))
        self.assertEqual(result.migrations, [])

    def test_migration_data_not_list_but_iterable_is_handled(self):
        """Generator-like objects are accepted and consumed."""
        data = (
            {
                "state": "Pending",
                "script": "V2__add.sql",
                "version": "2",
                "description": "Add",
                "type": "SQL",
            }
            for _ in range(1)
        )
        cmd, _ = _make_info_command()
        cmd.migration_ui.get_migration_data.return_value = data
        result = cmd.execute(Path("/tmp"))
        self.assertEqual(len(result.migrations), 1)
        self.assertEqual(result.migrations[0].status, "PENDING")


class TestInfoCommandBuildStateFailure(unittest.TestCase):
    """Test InfoCommand.execute when build_state raises."""

    def test_falls_back_to_empty_state_on_build_state_failure(self):
        cmd, log = _make_info_command(state_manager_raises=True)
        result = cmd.execute(Path("/tmp"))
        # Command must complete without raising
        self.assertIsNotNone(result)
        log.debug.assert_called()

    def test_target_schema_set_even_on_failure(self):
        cmd, _ = _make_info_command(state_manager_raises=True)
        result = cmd.execute(Path("/tmp"))
        self.assertEqual(result.target_schema, "public")


class TestInfoCommandScriptScanFailure(unittest.TestCase):
    """Test InfoCommand when script scanning raises."""

    def test_script_scan_failure_handled_gracefully(self):
        cmd, log = _make_info_command()
        cmd.script_manager.get_migration_scripts.side_effect = RuntimeError("scan error")
        result = cmd.execute(Path("/tmp"))
        self.assertIsNotNone(result)
        log.debug.assert_called()


class TestInfoCommandDatabaseInfo(unittest.TestCase):
    """Test InfoCommand.execute database info population."""

    def test_db_version_populated_from_provider(self):
        cmd, _ = _make_info_command()
        cmd.provider.get_database_version.return_value = "PostgreSQL 14.5"
        result = cmd.execute(Path("/tmp"))
        self.assertEqual(result.db_version, "PostgreSQL 14.5")

    def test_native_driver_set_for_cosmosdb_provider(self):
        cmd, _ = _make_info_command()
        cmd.config.database.type = "cosmosdb"
        cmd.provider.connection = None
        # Patch get_provider_display_url to return a URL
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="https://cosmos.documents.azure.com",
        ):
            result = cmd.execute(Path("/tmp"))
        # CosmosDB driver name is set
        self.assertEqual(result.native_driver, "Azure Cosmos DB SDK for Python")

    def test_native_driver_set_for_postgresql_provider(self):
        cmd, _ = _make_info_command()
        cmd.config.database.type = "postgresql"
        cmd.provider.connection = None
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="postgresql+psycopg://localhost/db",
        ):
            result = cmd.execute(Path("/tmp"))
        self.assertEqual("psycopg", result.native_driver)

    def test_native_driver_set_for_mysql_provider(self):
        cmd, _ = _make_info_command()
        cmd.config.database.type = "mysql"
        cmd.provider.connection = None
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="mysql+pymysql://localhost/db",
        ):
            result = cmd.execute(Path("/tmp"))
        self.assertIn("mysql", result.native_driver.lower())

    def test_native_driver_set_for_oracle_provider(self):
        cmd, _ = _make_info_command()
        cmd.config.database.type = "oracle"
        cmd.provider.connection = None
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="oracle+oracledb://localhost:1521?service_name=ORCL",
        ):
            result = cmd.execute(Path("/tmp"))
        self.assertIn("oracle", result.native_driver.lower())

    def test_native_driver_set_for_sqlserver_provider(self):
        cmd, _ = _make_info_command()
        cmd.config.database.type = "sqlserver"
        cmd.provider.connection = None
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="mssql+pymssql://localhost:1433/db",
        ):
            result = cmd.execute(Path("/tmp"))
        self.assertEqual("pymssql", result.native_driver)

    def test_native_driver_is_none_for_unknown_provider(self):
        cmd, _ = _make_info_command()
        cmd.config.database.type = "unknown"
        cmd.provider.connection = None
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="some://url",
        ):
            result = cmd.execute(Path("/tmp"))
        self.assertIsNone(result.native_driver)

    def test_database_url_masked_set_when_url_available(self):
        cmd, _ = _make_info_command()
        cmd.provider.connection = None
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="postgresql+psycopg://user:secret@host/db",
        ):
            result = cmd.execute(Path("/tmp"))
        self.assertIsNotNone(result.database_url_masked)
        self.assertNotIn("secret", result.database_url_masked or "")

    def test_connection_info_error_handled_gracefully(self):
        cmd, log = _make_info_command()
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            side_effect=RuntimeError("network error"),
        ):
            result = cmd.execute(Path("/tmp"))
        # Should not raise — db_version may or may not be set
        self.assertIsNotNone(result)
        log.debug.assert_called()

    def test_plugin_driver_display_used_when_connection_available(self):
        cmd, _ = _make_info_command()
        cmd.config.database.type = "postgresql"
        cmd.provider.connection = MagicMock()
        with patch(
            "core.migration.commands.info_command.get_provider_display_url",
            return_value="postgresql+psycopg://localhost/db",
        ):
            result = cmd.execute(Path("/tmp"))
        self.assertEqual("psycopg", result.native_driver)

    def test_current_schema_version_populated_from_state_manager(self):
        from types import SimpleNamespace

        from core.migration.migration import MigrationType

        applied = [SimpleNamespace(version="3", type=MigrationType.SQL, success=True)]
        cmd, _ = _make_info_command(applied_objects=applied)
        cmd.state_manager.get_current_version.return_value = "3"
        result = cmd.execute(Path("/tmp"))
        self.assertEqual(result.current_schema_version, "3")


class TestInfoCommandDisplayHuman(unittest.TestCase):
    """Test display_human parameter routing."""

    def test_display_human_false_skips_display_migration_info(self):
        cmd, _ = _make_info_command()
        cmd.execute(Path("/tmp"), display_human=False)
        cmd.migration_ui.display_migration_info.assert_not_called()

    def test_display_human_true_calls_display_migration_info(self):
        cmd, _ = _make_info_command()
        cmd.execute(Path("/tmp"), display_human=True)
        cmd.migration_ui.display_migration_info.assert_called_once()


# ===========================================================================
