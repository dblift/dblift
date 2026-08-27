"""Tests for core/migration/executor/migration_helpers.py."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock


class TestMigrationHelpersInit(unittest.TestCase):
    def _make(self):
        from core.migration.executor.migration_helpers import MigrationHelpers

        config = MagicMock()
        log = MagicMock()
        return MigrationHelpers(config, log), config, log

    def test_stores_config_log(self):
        helpers, config, log = self._make()
        self.assertIs(helpers.config, config)
        self.assertIs(helpers.log, log)

    def test_null_log_default(self):
        from core.logger import NullLog
        from core.migration.executor.migration_helpers import MigrationHelpers

        config = MagicMock()
        helpers = MigrationHelpers(config, None)
        self.assertIsInstance(helpers.log, NullLog)


class TestSetupMigrationParameters(unittest.TestCase):
    def _make(self):
        from core.migration.executor.migration_helpers import MigrationHelpers

        config = MagicMock()
        config.migrations.recursive = True
        config.migrations.directories = []
        log = MagicMock()
        return MigrationHelpers(config, log), config

    def test_uses_provided_recursive(self):
        helpers, _ = self._make()
        ps = MagicMock()
        recursive, dirs = helpers.setup_migration_parameters(None, False, None, ps)
        self.assertFalse(recursive)

    def test_uses_config_recursive_when_none(self):
        helpers, config = self._make()
        config.migrations.recursive = True
        ps = MagicMock()
        recursive, dirs = helpers.setup_migration_parameters(None, None, None, ps)
        self.assertTrue(recursive)

    def test_adds_placeholders(self):
        helpers, _ = self._make()
        ps = MagicMock()
        helpers.setup_migration_parameters({"key": "val"}, None, None, ps)
        ps.add_placeholders.assert_called_once_with({"key": "val"})

    def test_uses_provided_additional_dirs(self):
        helpers, _ = self._make()
        ps = MagicMock()
        extra = [Path("/tmp/extra")]
        _, dirs = helpers.setup_migration_parameters(None, None, extra, ps)
        self.assertEqual(dirs, extra)

    def test_uses_config_dirs_when_none(self):
        helpers, config = self._make()
        config.migrations.directories = ["/tmp/dir1", "/tmp/dir2"]
        ps = MagicMock()
        _, dirs = helpers.setup_migration_parameters(None, None, None, ps)
        self.assertEqual(len(dirs), 2)

    def test_config_dirs_accept_directory_config(self):
        from config.dblift_config import DirectoryConfig

        helpers, config = self._make()
        config.migrations.directories = [
            DirectoryConfig(path="/tmp/dir1", recursive=False),
            "/tmp/dir2",
        ]
        ps = MagicMock()
        _, dirs = helpers.setup_migration_parameters(None, None, None, ps)
        self.assertEqual(dirs, [Path("/tmp/dir1"), Path("/tmp/dir2")])

    def test_sets_command_type_on_log(self):
        helpers, _ = self._make()
        ps = MagicMock()
        helpers.setup_migration_parameters(None, None, None, ps)
        helpers.log.set_command_type.assert_called_with("MIGRATE")


class TestValidateMigrationsForMigrate(unittest.TestCase):
    def _make(self):
        from core.migration.executor.migration_helpers import MigrationHelpers

        config = MagicMock()
        log = MagicMock()
        return MigrationHelpers(config, log)

    def test_success_returns_true(self):
        helpers = self._make()
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = True
        validation_result.error_message = ""
        validator.validate_migrations.return_value = validation_result
        ok, msg, t = helpers.validate_migrations_for_migrate(validator, Path("/tmp"), True, [])
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_failure_returns_false(self):
        helpers = self._make()
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = False
        validation_result.error_message = "Missing migrations"
        validation_result.issues = ["issue1"]
        validator.validate_migrations.return_value = validation_result
        ok, msg, t = helpers.validate_migrations_for_migrate(validator, Path("/tmp"), True, [])
        self.assertFalse(ok)
        self.assertIn("Missing", msg)

    def test_checksum_error_continues(self):
        helpers = self._make()
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = False
        validation_result.error_message = "modified migration scripts found"
        validator.validate_migrations.return_value = validation_result
        ok, msg, t = helpers.validate_migrations_for_migrate(validator, Path("/tmp"), True, [])
        # Checksum errors are NOT fatal - returns success=False but continues
        self.assertFalse(ok)

    def test_passes_filters(self):
        helpers = self._make()
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = True
        validation_result.error_message = ""
        validator.validate_migrations.return_value = validation_result
        helpers.validate_migrations_for_migrate(
            validator,
            Path("/tmp"),
            True,
            [],
            target_version="1.0",
            tags=["tag1"],
            exclude_tags=["skip"],
        )
        validator.validate_migrations.assert_called_once()
        call_kwargs = validator.validate_migrations.call_args[1]
        self.assertEqual(call_kwargs.get("target_version"), "1.0")
