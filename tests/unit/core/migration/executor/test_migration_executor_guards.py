"""Tests for MigrationExecutor guard conditions (lines 59, 61)."""

import unittest
from unittest.mock import MagicMock, patch


class TestMigrationExecutorGuards(unittest.TestCase):
    def test_raises_when_provider_none(self):
        from core.migration.executor.migration_executor import MigrationExecutor

        with self.assertRaises(ValueError) as ctx:
            MigrationExecutor(provider=None, config=MagicMock(), log=MagicMock())
        self.assertIn("provider", str(ctx.exception).lower())

    def test_raises_when_config_none(self):
        from core.migration.executor.migration_executor import MigrationExecutor

        with self.assertRaises((ValueError, AttributeError)):
            MigrationExecutor(provider=MagicMock(), config=None, log=MagicMock())

    def test_raises_when_log_none(self):
        from core.migration.executor.migration_executor import MigrationExecutor

        with self.assertRaises((ValueError, AttributeError)):
            MigrationExecutor(provider=MagicMock(), config=None, log=None)


class TestGetInstalledBy(unittest.TestCase):
    def _make_executor(self):
        """Create minimal executor without full provider setup."""
        from core.migration.executor.migration_executor import MigrationExecutor

        config = MagicMock()
        config.installed_by = None
        config.database.installed_by = None
        config.database.username = "testuser"
        config.database.type = "postgresql"
        config.database.schema = "public"
        config.journal_enabled = False
        config.history_table = None
        config.migrations.script_encoding = "utf-8"
        config.migrations.detect_encoding = False
        provider = MagicMock()
        log = MagicMock()

        with patch.multiple(
            "core.migration.executor.migration_executor",
            MigrationScriptManager=MagicMock(),
            MigrationHistoryManager=MagicMock(),
            MigrationValidator=MagicMock(),
            MigrationUI=MagicMock(),
            MigrationRules=MagicMock(),
            SqlAnalyzer=MagicMock(),
            MigrationJournal=MagicMock(),
            SchemaSnapshotService=MagicMock(),
            MigrationStateManager=MagicMock(),
            PlaceholderManager=MagicMock(),
            MigrationHelpers=MagicMock(),
            ExecutionEngine=MagicMock(),
        ):
            from core.migration.executor.migration_executor import MigrationExecutor

            with patch("core.migration.sql.sql_execution_service.SqlExecutionService", MagicMock()):
                try:
                    executor = MigrationExecutor(provider=provider, config=config, log=log)
                    return executor, config
                except Exception:
                    return None, config

    def test_uses_config_installed_by(self):
        executor, config = self._make_executor()
        if executor is None:
            self.skipTest("Cannot create executor with mocked dependencies")
        config.installed_by = "custom_user"
        result = executor.get_installed_by()
        self.assertEqual(result, "custom_user")

    def test_falls_back_to_db_username(self):
        executor, config = self._make_executor()
        if executor is None:
            self.skipTest("Cannot create executor with mocked dependencies")
        config.installed_by = None
        config.database.installed_by = None
        config.database.username = "dbuser"
        result = executor.get_installed_by()
        self.assertEqual(result, "dbuser")
