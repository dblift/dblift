"""Tests for db/plugins/base_history_manager.py."""

import datetime
import unittest
from unittest.mock import MagicMock


def _make_concrete():
    """Create a minimal concrete BaseHistoryManager subclass."""
    from db.plugins.base_history_manager import BaseHistoryManager

    class ConcreteHistoryManager(BaseHistoryManager):
        def create_migration_history_table_if_not_exists(
            self, conn, schema, create_schema=False, table_name="dblift_schema_history"
        ):
            pass

        def record_migration(self, conn, schema, migration_info, table_name=None):
            pass

        def get_applied_migrations(self, conn, schema, table_name=None):
            return []

        def create_history_table(self, schema, table_name):
            return "CREATE TABLE ..."

    qe = MagicMock()
    so = MagicMock()
    config = MagicMock()
    log = MagicMock()
    mgr = ConcreteHistoryManager(qe, so, config, log)
    return mgr


class TestBaseHistoryManagerInit(unittest.TestCase):
    def test_stores_components(self):
        mgr = _make_concrete()
        self.assertIsNotNone(mgr.query_executor)
        self.assertIsNotNone(mgr.log)

    def test_null_log_default(self):
        from core.logger import NullLog
        from db.plugins.base_history_manager import BaseHistoryManager

        class Minimal(BaseHistoryManager):
            def create_migration_history_table_if_not_exists(self, c, s, cs=False, tn="t"):
                pass

            def record_migration(self, c, s, i, tn=None):
                pass

            def get_applied_migrations(self, c, s, tn=None):
                return []

            def create_history_table(self, s, tn):
                return ""

        mgr = Minimal(MagicMock(), MagicMock(), MagicMock(), None)
        self.assertIsInstance(mgr.log, NullLog)

    def test_default_table_name(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._get_default_table_name(), "dblift_schema_history")


class TestValidateMigrationInfo(unittest.TestCase):
    def test_valid_info_passes(self):
        mgr = _make_concrete()
        info = {"version": "1", "description": "test", "type": "SQL", "script": "V1.sql"}
        mgr._validate_migration_info(info)  # no raise

    def test_missing_version_raises(self):
        mgr = _make_concrete()
        with self.assertRaises(ValueError) as ctx:
            mgr._validate_migration_info({"description": "t", "type": "SQL", "script": "s"})
        self.assertIn("version", str(ctx.exception))

    def test_missing_multiple_raises(self):
        mgr = _make_concrete()
        with self.assertRaises(ValueError):
            mgr._validate_migration_info({})


class TestNormalizeMigrationResults(unittest.TestCase):
    def test_normalizes_lowercase_keys(self):
        mgr = _make_concrete()
        results = [
            {
                "INSTALLED_RANK": 1,
                "VERSION": "1.0",
                "TYPE": "SQL",
                "SCRIPT": "V1.sql",
                "SUCCESS": 1,
                "DESCRIPTION": "d",
                "CHECKSUM": "123",
                "INSTALLED_BY": "user",
                "INSTALLED_ON": None,
                "EXECUTION_TIME": 500,
            }
        ]
        norm = mgr._normalize_migration_results(results)
        self.assertEqual(len(norm), 1)
        self.assertEqual(norm[0]["installed_rank"], 1)
        self.assertEqual(norm[0]["version"], "1.0")
        self.assertTrue(norm[0]["success"])

    def test_handles_alternate_key_names(self):
        mgr = _make_concrete()
        results = [
            {
                "installedrank": 2,
                "scriptname": "V2.sql",
                "installedby": "admin",
                "installedon": None,
                "executiontime": 100,
                "type": "SQL",
                "version": "2",
                "description": "d2",
                "checksum": "0",
                "success": "1",
            }
        ]
        norm = mgr._normalize_migration_results(results)
        self.assertEqual(norm[0]["installed_rank"], 2)
        self.assertEqual(norm[0]["script"], "V2.sql")
        self.assertEqual(norm[0]["installed_by"], "admin")

    def test_empty_results_returns_empty(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._normalize_migration_results([]), [])

    def test_unknown_keys_preserved(self):
        mgr = _make_concrete()
        results = [
            {
                "custom_field": "value",
                "version": "1",
                "type": "SQL",
                "description": "d",
                "script": "s",
                "checksum": "0",
                "installed_by": "u",
                "installed_on": None,
                "execution_time": 0,
                "success": True,
                "installed_rank": 1,
            }
        ]
        norm = mgr._normalize_migration_results(results)
        self.assertEqual(norm[0]["custom_field"], "value")


class TestToInt(unittest.TestCase):
    def test_none_returns_zero(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._to_int(None), 0)

    def test_int_value(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._to_int(42), 42)

    def test_float_value(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._to_int(3.7), 3)

    def test_string_value(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._to_int("100"), 100)

    def test_decimal_string(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._to_int("3.14"), 3)

    def test_empty_string_returns_zero(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._to_int(""), 0)

    def test_invalid_string_returns_zero(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._to_int("abc"), 0)


class TestToBoolean(unittest.TestCase):
    def test_none_false(self):
        mgr = _make_concrete()
        self.assertFalse(mgr._to_boolean(None))

    def test_int_zero_false(self):
        mgr = _make_concrete()
        self.assertFalse(mgr._to_boolean(0))

    def test_int_one_true(self):
        mgr = _make_concrete()
        self.assertTrue(mgr._to_boolean(1))

    def test_true_string(self):
        mgr = _make_concrete()
        self.assertTrue(mgr._to_boolean("true"))
        self.assertTrue(mgr._to_boolean("1"))
        self.assertTrue(mgr._to_boolean("YES"))

    def test_false_string(self):
        mgr = _make_concrete()
        self.assertFalse(mgr._to_boolean("false"))
        self.assertFalse(mgr._to_boolean("0"))
        self.assertFalse(mgr._to_boolean("no"))


class TestConvertTimestamp(unittest.TestCase):
    def test_none_returns_none(self):
        mgr = _make_concrete()
        self.assertIsNone(mgr._convert_timestamp(None))

    def test_datetime_returned_as_is(self):
        mgr = _make_concrete()
        dt = datetime.datetime(2024, 1, 1, 12, 0, 0)
        self.assertIs(mgr._convert_timestamp(dt), dt)

    def test_string_returned_as_is(self):
        mgr = _make_concrete()
        self.assertEqual(mgr._convert_timestamp("2024-01-01"), "2024-01-01")


class TestBuildMigrationParams(unittest.TestCase):
    def test_builds_params_list(self):
        mgr = _make_concrete()
        info = {
            "version": "1.0",
            "description": "test",
            "type": "SQL",
            "script": "V1__test.sql",
            "checksum": 123,
            "installed_by": "user",
            "execution_time": 100,
        }
        params = mgr._build_migration_params(info, 1)
        self.assertIsInstance(params, list)
        self.assertIn("1.0", params)
        self.assertIn("test", params)


class TestUndoScriptName(unittest.TestCase):
    def test_returns_undo_script_name(self):
        mgr = _make_concrete()
        name = mgr._undo_script_name("1.0", None)
        self.assertIn("1.0", name)

    def test_uses_provided_script_name(self):
        mgr = _make_concrete()
        name = mgr._undo_script_name("1.0", "U1__my_undo.sql")
        self.assertEqual(name, "U1__my_undo.sql")
