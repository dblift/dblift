"""BUG-03A MySQL: ``get_clean_preview`` mirrors ``clean_schema`` enumeration.

Dry-run on MySQL previously fell through to ``SchemaIntrospector.get_tables()``
which hides dblift-internal tables (history/snapshots/lock). With this hook
implemented, dry-run hits ``get_clean_preview``, which enumerates the same
six kinds ``clean_schema`` drops (triggers, views, tables, functions,
procedures, events) without executing any DROP.
"""

import unittest
from unittest.mock import MagicMock

from db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations
from db.plugins.mysql.provider import MySqlProvider


def _qx_with_rows(rows_by_keyword):
    qx = MagicMock()

    def _execute_query(connection, query, params=None):
        for keyword, rows in rows_by_keyword.items():
            if keyword in query:
                return rows
        return []

    qx.execute_query.side_effect = _execute_query
    qx.get_schema_qualified_name.side_effect = lambda s, n: f"`{s}`.`{n}`"
    return qx


class TestMysqlGetCleanPreview(unittest.TestCase):
    def test_preview_lists_all_kinds_no_execute(self):
        qx = _qx_with_rows(
            {
                "TRIGGERS": [{"TRIGGER_NAME": "audit_trg"}],
                "VIEWS": [{"TABLE_NAME": "active_users_v"}],
                "TABLES": [
                    {"TABLE_NAME": "dblift_schema_history"},
                    {"TABLE_NAME": "dblift_schema_snapshots"},
                    {"TABLE_NAME": "dblift_migration_lock"},
                    {"TABLE_NAME": "users"},
                ],
                "'FUNCTION'": [{"ROUTINE_NAME": "calc_total"}],
                "'PROCEDURE'": [{"ROUTINE_NAME": "do_thing"}],
                "EVENTS": [{"EVENT_NAME": "nightly_purge"}],
            }
        )
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "testdb")

        qx.execute_statement.assert_not_called()

        names = {(o.object_type, o.name) for o in summary.objects}
        self.assertIn(("trigger", "audit_trg"), names)
        self.assertIn(("view", "active_users_v"), names)
        self.assertIn(("table", "dblift_schema_history"), names)
        self.assertIn(("table", "dblift_schema_snapshots"), names)
        self.assertIn(("table", "dblift_migration_lock"), names)
        self.assertIn(("table", "users"), names)
        self.assertIn(("function", "calc_total"), names)
        self.assertIn(("procedure", "do_thing"), names)
        self.assertIn(("event", "nightly_purge"), names)

    def test_preview_includes_dblift_internal_tables(self):
        qx = _qx_with_rows(
            {
                "TABLES": [
                    {"TABLE_NAME": "dblift_schema_history"},
                    {"TABLE_NAME": "dblift_schema_snapshots"},
                    {"TABLE_NAME": "dblift_migration_lock"},
                ],
            }
        )
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "testdb")

        names = {o.name for o in summary.objects}
        self.assertIn("dblift_schema_history", names)
        self.assertIn("dblift_schema_snapshots", names)
        self.assertIn("dblift_migration_lock", names)

    def test_preview_empty_schema(self):
        ops = MySqlSchemaOperations(query_executor=_qx_with_rows({}), log=MagicMock())
        summary = ops.get_clean_preview(MagicMock(), "testdb")
        self.assertEqual(summary.statements, [])
        self.assertEqual(summary.objects, [])

    def test_preview_query_failure_does_not_abort(self):
        qx = MagicMock()

        def _execute_query(connection, query, params=None):
            if "EVENTS" in query:
                raise RuntimeError("EVENTS table not present")
            if "TABLES" in query:
                return [{"TABLE_NAME": "users"}]
            return []

        qx.execute_query.side_effect = _execute_query
        qx.get_schema_qualified_name.side_effect = lambda s, n: f"`{s}`.`{n}`"
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "testdb")

        names = {o.name for o in summary.objects}
        self.assertIn("users", names)

    def test_native_provider_preview_delegates_to_object_enumeration(self):
        provider = object.__new__(MySqlProvider)
        provider.query_executor = _qx_with_rows({"TABLES": [{"TABLE_NAME": "users"}]})
        provider.log = MagicMock()
        provider._ensure_connection = MagicMock(return_value=MagicMock())

        summary = provider.get_clean_preview("testdb")

        names = {(o.object_type, o.name) for o in summary.objects}
        self.assertIn(("table", "users"), names)
        provider._ensure_connection.assert_called_once_with()

    def test_native_provider_clean_drops_objects_without_recreating_database(self):
        provider = object.__new__(MySqlProvider)
        provider.query_executor = _qx_with_rows({"TABLES": [{"TABLE_NAME": "users"}]})
        provider.log = MagicMock()
        provider._ensure_connection = MagicMock(return_value=MagicMock(exec_driver_sql=MagicMock()))
        provider._tx = None

        summary = provider.clean_schema("testdb")

        statements = summary.statements
        self.assertFalse(any("DROP DATABASE" in sql for sql in statements))
        self.assertFalse(any("CREATE DATABASE" in sql for sql in statements))
        self.assertTrue(any("DROP TABLE" in sql for sql in statements))
        names = {(o.object_type, o.name) for o in summary.objects}
        self.assertIn(("table", "users"), names)


if __name__ == "__main__":
    unittest.main()
