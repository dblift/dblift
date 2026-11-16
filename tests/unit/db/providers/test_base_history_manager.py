"""Tests for db/plugins/base_history_manager.py."""

import unittest
from unittest.mock import MagicMock


def _make_concrete():
    """Create a minimal concrete BaseHistoryManager subclass."""
    from dblift.db.plugins.base_history_manager import BaseHistoryManager

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
        from dblift.core.logger import NullLog
        from dblift.db.plugins.base_history_manager import BaseHistoryManager

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


class TestUndoScriptName(unittest.TestCase):
    def test_returns_undo_script_name(self):
        mgr = _make_concrete()
        name = mgr._undo_script_name("1.0", None)
        self.assertIn("1.0", name)

    def test_uses_provided_script_name(self):
        mgr = _make_concrete()
        name = mgr._undo_script_name("1.0", "U1__my_undo.sql")
        self.assertEqual(name, "U1__my_undo.sql")
