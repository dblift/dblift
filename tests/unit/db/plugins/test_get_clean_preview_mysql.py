"""BUG-03A MySQL: ``get_clean_preview`` mirrors ``clean_schema`` enumeration.

Dry-run on MySQL previously fell through to ``SchemaIntrospector.get_tables()``
which hides dblift-internal tables (history/snapshots/lock). With this hook
implemented, dry-run hits ``get_clean_preview``, which enumerates the same
six kinds ``clean_schema`` drops (triggers, views, tables, functions,
procedures, events) without executing any DROP.
"""

import unittest
from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError

from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations
from dblift.db.plugins.mysql.provider import MySqlProvider


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

    def test_preview_query_failure_propagates(self):
        # A failed catalog query must not read as "no objects of this kind":
        # clean would then report success having dropped nothing.
        qx = MagicMock()

        def _execute_query(connection, query, params=None):
            if "information_schema.VIEWS" in query:
                raise RuntimeError("Lost connection to MySQL server during query")
            if "TABLES" in query:
                return [{"TABLE_NAME": "users"}]
            return []

        qx.execute_query.side_effect = _execute_query
        qx.get_schema_qualified_name.side_effect = lambda s, n: f"`{s}`.`{n}`"
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        with self.assertRaisesRegex(RuntimeError, "Lost connection"):
            ops.get_clean_preview(MagicMock(), "testdb")
        qx.execute_statement.assert_not_called()

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

    def _qx_without_event_privilege(self):
        # MySQL/MariaDB filter information_schema.EVENTS rows by the EVENT
        # privilege instead of failing; only SHOW EVENTS raises.
        qx = _qx_with_rows({"TABLES": [{"TABLE_NAME": "users"}]})
        default = qx.execute_query.side_effect

        def _execute_query(connection, query, params=None):
            if query.startswith("SHOW EVENTS"):
                raise OperationalError(
                    query, None, Exception("(1044, \"Access denied for user 'app'@'%'\")")
                )
            return default(connection, query, params)

        qx.execute_query.side_effect = _execute_query
        qx.get_quoted_schema_name.side_effect = lambda s: f"`{s}`"
        return qx

    def test_preview_checks_events_are_listable(self):
        qx = _qx_with_rows({})
        qx.get_quoted_schema_name.side_effect = lambda s: f"`{s}`"
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        ops.get_clean_preview(MagicMock(), "testdb")

        queries = [c.args[1] for c in qx.execute_query.call_args_list]
        self.assertEqual(queries[0], "SHOW EVENTS FROM `testdb`")

    def test_preview_fails_without_event_privilege(self):
        qx = self._qx_without_event_privilege()
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        with self.assertRaisesRegex(RuntimeError, "EVENT privilege.*Access denied"):
            ops.get_clean_preview(MagicMock(), "testdb")
        # Fails before any object is enumerated, so nothing is listed.
        self.assertEqual(qx.execute_query.call_count, 1)
        qx.execute_statement.assert_not_called()

    def test_clean_schema_fails_without_event_privilege_before_dropping(self):
        qx = self._qx_without_event_privilege()
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        with self.assertRaisesRegex(RuntimeError, "EVENT privilege"):
            ops.clean_schema(MagicMock(), "testdb")
        executed = [c.args[1] for c in qx.execute_statement.call_args_list]
        self.assertFalse(any("DROP" in sql for sql in executed))

    def test_category_query_failure_propagates(self):
        # A failed catalog query must not read as "no objects of this kind".
        qx = _qx_with_rows({"TABLES": [{"TABLE_NAME": "users"}]})
        default = qx.execute_query.side_effect

        def _execute_query(connection, query, params=None):
            if "information_schema.VIEWS" in query:
                raise RuntimeError("Lost connection to MySQL server during query")
            return default(connection, query, params)

        qx.execute_query.side_effect = _execute_query
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        with self.assertRaisesRegex(RuntimeError, "Lost connection"):
            ops.get_clean_preview(MagicMock(), "testdb")
        qx.execute_statement.assert_not_called()


if __name__ == "__main__":
    unittest.main()
