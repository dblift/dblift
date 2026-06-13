"""BUG-03A Oracle: ``get_clean_preview`` mirrors ``clean_schema`` enumeration.

Dry-run on Oracle previously fell through to ``SchemaIntrospector.get_tables()``
which hides dblift-internal tables. With this hook implemented, dry-run hits
``get_clean_preview``, which enumerates all 8 categories that ``clean_schema``
processes without executing any DROP.
"""

import unittest
from unittest.mock import MagicMock

from db.plugins.oracle.oracle.schema_operations import OracleSchemaOperations


def _qx_with_rows(rows_by_keyword):
    qx = MagicMock()

    def _execute_query(connection, query, params=None):
        for keyword, rows in rows_by_keyword.items():
            if keyword in query:
                return rows
        return []

    qx.execute_query.side_effect = _execute_query
    qx.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
    return qx


class TestOracleGetCleanPreview(unittest.TestCase):
    def test_preview_lists_all_categories_no_execute(self):
        qx = _qx_with_rows(
            {
                "ALL_DB_LINKS": [{"DB_LINK": "REPORTING_LINK"}],
                "ALL_VIEWS": [{"VIEW_NAME": "ACTIVE_USERS_V"}],
                "ALL_MVIEWS": [{"MVIEW_NAME": "SALES_SUMMARY_MV"}],
                "ALL_TABLES": [
                    {"TABLE_NAME": "DBLIFT_SCHEMA_HISTORY"},
                    {"TABLE_NAME": "DBLIFT_SCHEMA_SNAPSHOTS"},
                    {"TABLE_NAME": "DBLIFT_MIGRATION_LOCK"},
                    {"TABLE_NAME": "USERS"},
                ],
                "ALL_SEQUENCES": [{"SEQUENCE_NAME": "USERS_SEQ"}],
                "DECODE": [
                    {"OBJECT_NAME": "CALC_TOTAL", "OBJECT_TYPE": "FUNCTION"},
                    {"OBJECT_NAME": "PKG_UTIL", "OBJECT_TYPE": "PACKAGE"},
                ],
                "ALL_SYNONYMS": [{"SYNONYM_NAME": "EXT_REPORTS"}],
            }
        )
        ops = OracleSchemaOperations(query_executor=qx, log=MagicMock())
        # is_system_generated_sequence requires schema lookups; stub it.
        ops.is_system_generated_sequence = MagicMock(return_value=False)

        summary = ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        qx.execute_statement.assert_not_called()

        names = {(o.object_type, o.name) for o in summary.objects}
        self.assertIn(("database_link", "REPORTING_LINK"), names)
        self.assertIn(("view", "ACTIVE_USERS_V"), names)
        self.assertIn(("materialized_view", "SALES_SUMMARY_MV"), names)
        self.assertIn(("table", "DBLIFT_SCHEMA_HISTORY"), names)
        self.assertIn(("table", "DBLIFT_SCHEMA_SNAPSHOTS"), names)
        self.assertIn(("table", "DBLIFT_MIGRATION_LOCK"), names)
        self.assertIn(("table", "USERS"), names)
        self.assertIn(("sequence", "USERS_SEQ"), names)
        self.assertIn(("function", "CALC_TOTAL"), names)
        self.assertIn(("package", "PKG_UTIL"), names)
        self.assertIn(("synonym", "EXT_REPORTS"), names)

    def test_preview_skips_system_generated_sequences(self):
        qx = _qx_with_rows(
            {
                "ALL_SEQUENCES": [
                    {"SEQUENCE_NAME": "ISEQ$$_12345"},
                    {"SEQUENCE_NAME": "MY_SEQ"},
                ],
            }
        )
        ops = OracleSchemaOperations(query_executor=qx, log=MagicMock())
        ops.is_system_generated_sequence = MagicMock(
            side_effect=lambda c, s, n: n.startswith("ISEQ$$_")
        )

        summary = ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        names = {o.name for o in summary.objects}
        self.assertIn("MY_SEQ", names)
        self.assertNotIn("ISEQ$$_12345", names)

    def test_preview_includes_dblift_internal_tables(self):
        qx = _qx_with_rows(
            {
                "ALL_TABLES": [
                    {"TABLE_NAME": "DBLIFT_SCHEMA_HISTORY"},
                    {"TABLE_NAME": "DBLIFT_SCHEMA_SNAPSHOTS"},
                    {"TABLE_NAME": "DBLIFT_MIGRATION_LOCK"},
                ],
            }
        )
        ops = OracleSchemaOperations(query_executor=qx, log=MagicMock())
        ops.is_system_generated_sequence = MagicMock(return_value=False)

        summary = ops.get_clean_preview(MagicMock(), "MYSCHEMA")

        names = {o.name for o in summary.objects}
        self.assertIn("DBLIFT_SCHEMA_HISTORY", names)
        self.assertIn("DBLIFT_SCHEMA_SNAPSHOTS", names)
        self.assertIn("DBLIFT_MIGRATION_LOCK", names)

    def test_preview_empty_schema(self):
        ops = OracleSchemaOperations(query_executor=_qx_with_rows({}), log=MagicMock())
        ops.is_system_generated_sequence = MagicMock(return_value=False)
        summary = ops.get_clean_preview(MagicMock(), "MYSCHEMA")
        self.assertEqual(summary.statements, [])
        self.assertEqual(summary.objects, [])


if __name__ == "__main__":
    unittest.main()
