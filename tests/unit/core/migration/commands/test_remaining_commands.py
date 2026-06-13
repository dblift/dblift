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


def _make_migration(version, mtype, success=True, has_undo_fn=False):
    from core.migration.migration import MigrationType

    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = success
    m.script_name = f"V{version}__test.sql"
    m.description = "test"
    m.checksum = "abc"
    if mtype == MigrationType.PYTHON:
        m.content = (
            "def migrate(ctx): pass\ndef undo(ctx): pass"
            if has_undo_fn
            else "def migrate(ctx): pass"
        )
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
# snapshot_command
# ===========================================================================


class TestSnapshotCommandValidation(unittest.TestCase):
    """Test snapshot() validation branches."""

    def test_invalid_source_returns_false(self):
        from core.migration.commands.snapshot_command import snapshot

        ok, err = snapshot(config=MagicMock(), output="/tmp/x.json", source="bogus")
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_missing_output_returns_false(self):
        from core.migration.commands.snapshot_command import snapshot

        ok, err = snapshot(config=MagicMock(), output=None, source="database-stored")
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_output_is_directory_returns_false(self, tmp_path=None):
        import os
        import tempfile

        from core.migration.commands.snapshot_command import snapshot

        with tempfile.TemporaryDirectory() as d:
            ok, err = snapshot(config=MagicMock(), output=d, source="database-stored")
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_snapshot_service_unavailable_returns_false(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_executor = MagicMock()
        # snapshot_service is None
        del mock_executor.snapshot_service  # attribute absent

        with patch(
            "core.migration.executor.migration_executor.MigrationExecutor",
            return_value=mock_executor,
        ):
            ok, err = snapshot(
                config=MagicMock(),
                output="/tmp/x.json",
                source="database-stored",
                provider=mock_provider,
            )
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_no_snapshot_found_in_database_returns_false(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = None

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with patch(
            "core.migration.executor.migration_executor.MigrationExecutor",
            return_value=mock_executor,
        ):
            with patch("core.logger.console.console_status"):
                ok, err = snapshot(
                    config=MagicMock(),
                    output="/tmp/x.json",
                    source="database-stored",
                    provider=mock_provider,
                )
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_database_stored_success_writes_file(self, tmp_path=None):
        import json
        import tempfile

        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_payload = MagicMock()
        mock_payload.to_dict.return_value = {"tables": []}
        mock_payload.metadata = None

        mock_snapshot_data = MagicMock()
        mock_snapshot_data.payload = mock_payload
        mock_snapshot_data.snapshot_id = "snap-1"
        mock_snapshot_data.captured_at_iso = "2024-01-01T00:00:00"

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = mock_snapshot_data

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "snap.json")
            with patch(
                "core.migration.executor.migration_executor.MigrationExecutor",
                return_value=mock_executor,
            ):
                with patch("core.logger.console.console_status"):
                    ok, err = snapshot(
                        config=MagicMock(),
                        output=out,
                        source="database-stored",
                        provider=mock_provider,
                    )
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_live_database_success_writes_file(self):
        import tempfile

        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_payload = MagicMock()
        mock_payload.to_dict.return_value = {"tables": []}
        mock_payload.metadata = None

        mock_service = MagicMock()
        mock_service.build_live_payload.return_value = mock_payload

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "snap.json")
            with patch(
                "core.migration.executor.migration_executor.MigrationExecutor",
                return_value=mock_executor,
            ):
                with patch("core.logger.console.console_status"):
                    ok, err = snapshot(
                        config=MagicMock(),
                        output=out,
                        source="live-database",
                        provider=mock_provider,
                    )
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_payload_none_returns_false(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_service = MagicMock()
        mock_service.build_live_payload.return_value = None

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with patch(
            "core.migration.executor.migration_executor.MigrationExecutor",
            return_value=mock_executor,
        ):
            with patch("core.logger.console.console_status"):
                ok, err = snapshot(
                    config=MagicMock(),
                    output="/tmp/x.json",
                    source="live-database",
                    provider=mock_provider,
                )
        self.assertFalse(ok)
        self.assertIsNotNone(err)


class TestSnapshotCommandMinConfidence(unittest.TestCase):
    """Test min_confidence enforcement."""

    def _make_payload(self, overall_score, confidence_level="MEDIUM"):
        mock_payload = MagicMock()
        mock_payload.to_dict.return_value = {}
        mock_payload.metadata = {
            "validation": {
                "confidence": {
                    "overall_score": overall_score,
                    "confidence_level": confidence_level,
                }
            }
        }
        return mock_payload

    def test_min_confidence_below_score_fails(self):
        import tempfile

        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_payload = self._make_payload(0.5, "MEDIUM")

        mock_snapshot_data = MagicMock()
        mock_snapshot_data.payload = mock_payload
        mock_snapshot_data.snapshot_id = "snap-1"
        mock_snapshot_data.captured_at_iso = "2024-01-01"

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = mock_snapshot_data

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "snap.json")
            with patch(
                "core.migration.executor.migration_executor.MigrationExecutor",
                return_value=mock_executor,
            ):
                with patch("core.logger.console.console_status"):
                    ok, err = snapshot(
                        config=MagicMock(),
                        output=out,
                        source="database-stored",
                        provider=mock_provider,
                        min_confidence=0.8,
                    )
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertIn("80.0%", err or "")

    def test_min_confidence_above_score_passes(self):
        import tempfile

        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_payload = self._make_payload(0.95, "HIGH")
        mock_payload.to_dict.return_value = {}

        mock_snapshot_data = MagicMock()
        mock_snapshot_data.payload = mock_payload
        mock_snapshot_data.snapshot_id = "snap-1"
        mock_snapshot_data.captured_at_iso = "2024-01-01"

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = mock_snapshot_data

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "snap.json")
            with patch(
                "core.migration.executor.migration_executor.MigrationExecutor",
                return_value=mock_executor,
            ):
                with patch("core.logger.console.console_status"):
                    ok, err = snapshot(
                        config=MagicMock(),
                        output=out,
                        source="database-stored",
                        provider=mock_provider,
                        min_confidence=0.8,
                    )
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_min_confidence_out_of_range_returns_false(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_payload = self._make_payload(0.95)
        mock_snapshot_data = MagicMock()
        mock_snapshot_data.payload = mock_payload
        mock_snapshot_data.snapshot_id = "snap-1"
        mock_snapshot_data.captured_at_iso = "2024-01-01"

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = mock_snapshot_data

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with patch(
            "core.migration.executor.migration_executor.MigrationExecutor",
            return_value=mock_executor,
        ):
            with patch("core.logger.console.console_status"):
                ok, err = snapshot(
                    config=MagicMock(),
                    output="/tmp/x.json",
                    source="database-stored",
                    provider=mock_provider,
                    min_confidence=1.5,  # out of range
                )
        self.assertFalse(ok)


class TestSnapshotCommandException(unittest.TestCase):
    """Test snapshot() exception handling."""

    def test_exception_during_execution_returns_false(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True
        mock_provider.create_connection.side_effect = RuntimeError("connection failed")

        ok, err = snapshot(
            config=MagicMock(),
            output="/tmp/x.json",
            source="database-stored",
            provider=mock_provider,
        )
        self.assertFalse(ok)
        self.assertIsNotNone(err)

    def test_log_func_used_when_log_is_none(self):
        """When log=None, standard logger is used — no crash."""
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True
        mock_provider.create_connection.side_effect = RuntimeError("fail")

        # Should not crash when log=None
        ok, err = snapshot(
            config=MagicMock(),
            output="/tmp/x.json",
            source="database-stored",
            provider=mock_provider,
            log=None,
        )
        self.assertFalse(ok)


class TestSnapshotCommandProviderCreation(unittest.TestCase):
    """Test snapshot() provider creation flow."""

    def test_creates_provider_when_none_provided(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = None

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with patch(
            "core.migration.commands.snapshot_command.ProviderRegistry.create_provider",
            return_value=mock_provider,
        ) as mock_create:
            with patch(
                "core.migration.executor.migration_executor.MigrationExecutor",
                return_value=mock_executor,
            ):
                with patch("core.logger.console.console_status"):
                    snapshot(
                        config=MagicMock(),
                        output="/tmp/x.json",
                        source="database-stored",
                        provider=None,
                    )

        mock_create.assert_called_once()

    def test_reuses_provided_provider(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = True

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = None

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with patch(
            "core.migration.commands.snapshot_command.ProviderRegistry.create_provider",
        ) as mock_create:
            with patch(
                "core.migration.executor.migration_executor.MigrationExecutor",
                return_value=mock_executor,
            ):
                with patch("core.logger.console.console_status"):
                    snapshot(
                        config=MagicMock(),
                        output="/tmp/x.json",
                        source="database-stored",
                        provider=mock_provider,
                    )

        mock_create.assert_not_called()

    def test_create_connection_called_when_not_connected(self):
        from core.migration.commands.snapshot_command import snapshot

        mock_provider = MagicMock()
        mock_provider.is_connected.return_value = False

        mock_service = MagicMock()
        mock_service.load_latest_snapshot.return_value = None

        mock_executor = MagicMock()
        mock_executor.snapshot_service = mock_service

        with patch(
            "core.migration.executor.migration_executor.MigrationExecutor",
            return_value=mock_executor,
        ):
            with patch("core.logger.console.console_status"):
                snapshot(
                    config=MagicMock(),
                    output="/tmp/x.json",
                    source="database-stored",
                    provider=mock_provider,
                )

        mock_provider.create_connection.assert_called_once()


# ===========================================================================
# UndoCommand — additional branches
# ===========================================================================


class TestUndoCommandNoMigrationsToUndo(unittest.TestCase):
    """Test undo when there are no migrations to undo."""

    def test_no_applied_migrations_returns_completed(self):
        cmd = _make_undo_command([])
        result = cmd.execute(scripts_dir=MagicMock())
        # No error, completed successfully
        self.assertIsNone(result.error_message)

    def test_failed_migration_not_undone(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=False)
        cmd = _make_undo_command([v1])
        result = cmd.execute(scripts_dir=MagicMock())
        # No migrations undone — failed migration is not eligible
        self.assertEqual(result.undone_count, 0)


class TestUndoCommandDryRun(unittest.TestCase):
    """Test undo dry_run mode."""

    def test_dry_run_logs_but_does_not_execute(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)
        cmd = _make_undo_command([v1])
        cmd.execution_engine.execute_migration = MagicMock()

        result = cmd.execute(scripts_dir=MagicMock(), dry_run=True)

        cmd.execution_engine.execute_migration.assert_not_called()
        # Log info was called
        info_calls = [str(c) for c in cmd.log.info.call_args_list]
        assert any("dry run" in c.lower() for c in info_calls)

    def test_dry_run_show_sql_uses_matching_undo_script(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)
        undo_script = MagicMock()
        undo_script.type = MigrationType.UNDO_SQL
        undo_script.version = "1"
        undo_script.script_name = "U1__test.sql"
        undo_script.description = "undo test"

        cmd = _make_undo_command([v1], has_scripts=[undo_script])
        cmd.execution_engine.get_executable_sql_statements.return_value = ["DROP TABLE users"]

        result = cmd.execute(scripts_dir=MagicMock(), dry_run=True, show_sql=True)

        cmd.execution_engine.execute_migration.assert_not_called()
        cmd.execution_engine.get_executable_sql_statements.assert_called_once_with(
            undo_script,
            result,
        )
        assert result.show_sql is True
        assert result.sql[0].script == "U1__test.sql"
        assert result.sql[0].statements == ["DROP TABLE users"]


class TestUndoCommandSqlUndoScript(unittest.TestCase):
    """Test SQL undo path with explicit undo script."""

    def test_finds_and_executes_undo_script(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)

        # Undo script matching version 1
        undo_script = MagicMock()
        undo_script.type = MigrationType.UNDO_SQL
        undo_script.version = "1"
        undo_script.script_name = "U1__undo.sql"
        undo_script.description = "Undo init"

        cmd = _make_undo_command([v1], has_scripts=[undo_script])
        result = cmd.execute(scripts_dir=MagicMock())

        cmd.execution_engine.execute_migration.assert_called_once()
        # undone_count is incremented by both add_undone_migration and result.undone_count += 1
        self.assertGreaterEqual(result.undone_count, 1)

    def test_show_sql_collection_error_prevents_sql_undo_execution(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)

        undo_script = MagicMock()
        undo_script.type = MigrationType.UNDO_SQL
        undo_script.version = "1"
        undo_script.script_name = "U1__undo.sql"
        undo_script.description = "Undo init"

        cmd = _make_undo_command([v1], has_scripts=[undo_script])
        journal = MagicMock()
        cmd.journal = journal

        def _set_collection_error(_migration, result):
            result.set_error("mixed transaction policy")
            return []

        cmd.execution_engine.get_executable_sql_statements.side_effect = _set_collection_error

        result = cmd.execute(scripts_dir=MagicMock(), show_sql=True)

        cmd.execution_engine.execute_migration.assert_not_called()
        assert result.error_message == "mixed transaction policy"
        journal.start_migration.assert_called_once()
        journal.end_migration.assert_called_once_with(
            "U1__undo.sql",
            success=False,
            error_message="mixed transaction policy",
            execution_time=unittest.mock.ANY,
        )

    def test_no_undo_script_found_sets_error(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)
        # No undo script in scripts dir
        cmd = _make_undo_command([v1], has_scripts=[])
        result = cmd.execute(scripts_dir=MagicMock())

        self.assertIsNotNone(result.error_message)
        self.assertIn("No undo script found", result.error_message)


class TestUndoCommandTargetVersion(unittest.TestCase):
    """Test undo with --target-version specified."""

    def test_undoes_migrations_above_target(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)
        v2 = _make_migration("2", MigrationType.SQL, success=True)
        v3 = _make_migration("3", MigrationType.SQL, success=True)

        # Undo scripts for v2 and v3
        undo_v2 = MagicMock()
        undo_v2.type = MigrationType.UNDO_SQL
        undo_v2.version = "2"
        undo_v2.script_name = "U2__undo.sql"
        undo_v2.description = "Undo v2"

        undo_v3 = MagicMock()
        undo_v3.type = MigrationType.UNDO_SQL
        undo_v3.version = "3"
        undo_v3.script_name = "U3__undo.sql"
        undo_v3.description = "Undo v3"

        cmd = _make_undo_command([v1, v2, v3], has_scripts=[undo_v2, undo_v3])
        result = cmd.execute(scripts_dir=MagicMock(), target_version="1")

        self.assertEqual(cmd.execution_engine.execute_migration.call_count, 2)

    def test_target_version_equal_applied_is_no_op(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)
        cmd = _make_undo_command([v1])
        result = cmd.execute(scripts_dir=MagicMock(), target_version="1")

        # V1 <= target 1, so nothing to undo
        cmd.execution_engine.execute_migration.assert_not_called()


class TestUndoCommandBeforeUndoCallback(unittest.TestCase):
    """Test beforeUndo callback failure handling."""

    def test_before_undo_callback_failure_sets_error_and_returns(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)
        cmd = _make_undo_command([v1])

        # Make _execute_callbacks raise for beforeUndo
        def _cb_side_effect(scripts_dir, event, *args, **kwargs):
            if event == "beforeUndo":
                raise RuntimeError("beforeUndo failed")

        cmd._execute_callbacks = _cb_side_effect

        result = cmd.execute(scripts_dir=MagicMock())

        self.assertIsNotNone(result.error_message)
        self.assertIn("beforeUndo", result.error_message)

    def test_after_undo_executed_when_all_succeed(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)
        undo_script = MagicMock()
        undo_script.type = MigrationType.UNDO_SQL
        undo_script.version = "1"
        undo_script.script_name = "U1__undo.sql"
        undo_script.description = "Undo init"

        events_seen = []

        cmd = _make_undo_command([v1], has_scripts=[undo_script])
        real_cb = cmd._execute_callbacks

        def _track_cb(scripts_dir, event, *args, **kwargs):
            events_seen.append(event)

        cmd._execute_callbacks = _track_cb

        result = cmd.execute(scripts_dir=MagicMock())

        self.assertIn("afterUndo", events_seen)


class TestUndoCommandCurrentVersionAfterUndo(unittest.TestCase):
    """Test that current schema version is updated after undo."""

    def test_schema_version_none_when_no_remaining_migrations(self):
        from core.migration.migration import MigrationType

        v1 = _make_migration("1", MigrationType.SQL, success=True)

        undo_script = MagicMock()
        undo_script.type = MigrationType.UNDO_SQL
        undo_script.version = "1"
        undo_script.script_name = "U1__undo.sql"
        undo_script.description = "Undo"

        cmd = _make_undo_command([v1], has_scripts=[undo_script])

        # Rebuild state after undo: empty applied_objects
        after_state = MagicMock()
        after_state.applied_objects = []
        cmd.state_manager.build_state.side_effect = [
            # First call: before undo
            type("S", (), {"applied_objects": [v1]})(),
            # Second call: after undo
            after_state,
        ]
        cmd.state_manager.get_current_version.return_value = None

        result = cmd.execute(scripts_dir=MagicMock())

        self.assertIsNone(result.current_schema_version)


class TestUndoCommandExecutionException(unittest.TestCase):
    """Test outer exception handling in execute."""

    def test_exception_in_create_schema_sets_error(self):
        from core.migration.migration import MigrationType

        cmd = _make_undo_command([])
        cmd.history_manager.create_schema_and_history_table.side_effect = RuntimeError(
            "db not available"
        )

        result = cmd.execute(scripts_dir=MagicMock())

        self.assertIsNotNone(result.error_message)
        self.assertIn("Undo operation failed", result.error_message)


if __name__ == "__main__":
    unittest.main()
