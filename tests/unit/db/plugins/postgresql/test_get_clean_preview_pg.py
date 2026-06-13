"""BUG-03A PG: ``get_clean_preview`` mirrors ``clean_schema`` enumeration.

Dry-run on PG previously fell through to ``SchemaIntrospector.get_tables()``
which hides dblift-internal tables (history/snapshots/lock). With the
provider hook implemented, dry-run hits this method, which enumerates
the same objects ``clean_schema`` drops without executing any DROP.
"""

import unittest
from unittest.mock import MagicMock

from db.plugins.postgresql.postgresql.schema_operations import PostgreSqlSchemaOperations


def _qx_with_results(results_by_query):
    """Build a query_executor mock whose execute_query returns rows matching
    the query keyword (e.g. 'pg_tables', 'pg_views', 'pg_extension')."""
    qx = MagicMock()

    def _execute_query(connection, query, params=None):
        for keyword, rows in results_by_query.items():
            if keyword in query:
                return rows
        return []

    qx.execute_query.side_effect = _execute_query
    qx.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
    return qx


class TestPgGetCleanPreview(unittest.TestCase):
    def test_preview_lists_all_object_types_no_execute(self):
        qx = _qx_with_results(
            {
                "pg_extension": [{"extension_name": "pg_trgm"}],
                "pg_views": [{"view_name": "user_view"}],
                "pg_tables": [
                    {"table_name": "dblift_schema_history"},
                    {"table_name": "dblift_schema_snapshots"},
                    {"table_name": "dblift_migration_lock"},
                    {"table_name": "users"},
                ],
                "information_schema.sequences": [
                    {"sequence_name": "dblift_schema_history_installed_rank_seq"},
                    {"sequence_name": "users_id_seq"},
                ],
                "information_schema.routines": [
                    {"routine_name": "calc_total", "routine_type": "FUNCTION"},
                    {"routine_name": "do_thing", "routine_type": "PROCEDURE"},
                ],
                "pg_type": [
                    {"type_name": "status_enum", "typtype": "e"},
                    {"type_name": "address_t", "typtype": "c"},
                    {"type_name": "pos_int", "typtype": "d"},
                ],
            }
        )
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "public")

        # No DROP executed.
        qx.execute_statement.assert_not_called()

        # Recorded objects cover every category.
        names = {(o.object_type, o.name) for o in summary.objects}
        self.assertIn(("extension", "pg_trgm"), names)
        self.assertIn(("view", "user_view"), names)
        self.assertIn(("table", "dblift_schema_history"), names)
        self.assertIn(("table", "dblift_schema_snapshots"), names)
        self.assertIn(("table", "dblift_migration_lock"), names)
        self.assertIn(("table", "users"), names)
        self.assertIn(("sequence", "dblift_schema_history_installed_rank_seq"), names)
        self.assertIn(("function", "calc_total"), names)
        self.assertIn(("procedure", "do_thing"), names)
        self.assertIn(("type", "status_enum"), names)
        self.assertIn(("type", "address_t"), names)
        self.assertIn(("domain", "pos_int"), names)

    def test_preview_includes_dblift_internal_tables(self):
        # Core BUG-03 assertion: dry-run must surface dblift-internal tables.
        qx = _qx_with_results(
            {
                "pg_tables": [
                    {"table_name": "dblift_schema_history"},
                    {"table_name": "dblift_schema_snapshots"},
                    {"table_name": "dblift_migration_lock"},
                ],
            }
        )
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "public")

        names = {o.name for o in summary.objects}
        self.assertIn("dblift_schema_history", names)
        self.assertIn("dblift_schema_snapshots", names)
        self.assertIn("dblift_migration_lock", names)

    def test_preview_empty_schema_yields_empty_summary(self):
        qx = _qx_with_results({})
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "public")

        self.assertEqual(summary.statements, [])
        self.assertEqual(summary.objects, [])

    def test_preview_ignores_table_row_types(self):
        qx = _qx_with_results(
            {
                "pg_tables": [{"table_name": "users"}],
                "pg_type": [
                    {"type_name": "users", "typtype": "c"},
                    {"type_name": "address_t", "typtype": "c"},
                    {"type_name": "status_enum", "typtype": "e"},
                    {"type_name": "pos_int", "typtype": "d"},
                ],
            }
        )
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "public")

        names = {(o.object_type, o.name) for o in summary.objects}
        self.assertIn(("table", "users"), names)
        self.assertNotIn(("type", "users"), names)
        self.assertIn(("type", "address_t"), names)
        self.assertIn(("type", "status_enum"), names)
        self.assertIn(("domain", "pos_int"), names)

    def test_preview_ignores_view_and_matview_row_types(self):
        qx = _qx_with_results(
            {
                "pg_views": [{"view_name": "v_paid_orders"}],
                "pg_matviews": [{"matviewname": "mv_order_totals"}],
                "pg_type": [
                    {"type_name": "v_paid_orders", "typtype": "c"},
                    {"type_name": "mv_order_totals", "typtype": "c"},
                    {"type_name": "address_t", "typtype": "c"},
                ],
            }
        )
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "public")

        names = {(o.object_type, o.name) for o in summary.objects}
        self.assertIn(("view", "v_paid_orders"), names)
        self.assertIn(("materialized_view", "mv_order_totals"), names)
        self.assertNotIn(("type", "v_paid_orders"), names)
        self.assertNotIn(("type", "mv_order_totals"), names)
        self.assertIn(("type", "address_t"), names)


if __name__ == "__main__":
    unittest.main()
