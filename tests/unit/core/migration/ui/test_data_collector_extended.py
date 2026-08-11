"""Extended tests for core/migration/ui/data_collector.py."""

import datetime
import unittest
from unittest.mock import MagicMock


def _make_collector():
    from core.migration.ui.data_collector import MigrationDataCollector

    log = MagicMock()
    sm = MagicMock()
    return MigrationDataCollector(log=log, script_manager=sm), log, sm


class TestMigrationDataCollectorInit(unittest.TestCase):
    def test_stores_log(self):
        coll, log, _ = _make_collector()
        self.assertIs(coll.log, log)

    def test_null_log_default(self):
        from core.logger import NullLog
        from core.migration.ui.data_collector import MigrationDataCollector

        coll = MigrationDataCollector(log=None)
        self.assertIsInstance(coll.log, NullLog)


class TestFormatInstalledOn(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_none_returns_empty(self):
        coll = self._c()
        self.assertEqual(coll._format_installed_on(None), "")

    def test_empty_string_returns_empty(self):
        coll = self._c()
        self.assertEqual(coll._format_installed_on(""), "")

    def test_datetime_formatted(self):
        coll = self._c()
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        result = coll._format_installed_on(dt)
        self.assertIsInstance(result, str)
        self.assertIn("2024", result)

    def test_iso_string_returned_as_is(self):
        coll = self._c()
        result = coll._format_installed_on("2024-01-15T10:30:00")
        self.assertIsInstance(result, str)


class TestGetMigrationTypeString(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_sql_type(self):
        from core.migration.migration import MigrationType

        coll = self._c()
        result = coll._get_migration_type_string(MigrationType.SQL)
        self.assertIsInstance(result, str)

    def test_none_returns_string(self):
        coll = self._c()
        result = coll._get_migration_type_string(None)
        self.assertIsInstance(result, str)

    def test_string_type_passed_through(self):
        coll = self._c()
        result = coll._get_migration_type_string("SQL")
        self.assertIsInstance(result, str)


class TestIsVersionedType(unittest.TestCase):
    def _c(self):
        return _make_collector()[0]

    def test_sql_is_versioned(self):
        from core.migration.migration import MigrationType

        coll = self._c()
        self.assertTrue(coll._is_versioned_type(MigrationType.SQL))

    def test_repeatable_not_versioned(self):
        from core.migration.migration import MigrationType

        coll = self._c()
        self.assertFalse(coll._is_versioned_type(MigrationType.REPEATABLE))


