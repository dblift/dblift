"""A MariaDB system-versioned table is listed, dropped and enumerated like any table.

MariaDB reports ``CREATE TABLE ... WITH SYSTEM VERSIONING`` as
``TABLE_TYPE = 'SYSTEM VERSIONED'`` in ``information_schema.TABLES``, so a
``'BASE TABLE'``-only filter never saw it and ``clean`` left it behind while
reporting success.
"""

import re
import unittest
from unittest.mock import MagicMock

from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations

_CATALOG = [
    ("orders", "BASE TABLE"),
    ("prices", "SYSTEM VERSIONED"),
    ("seq_a", "SEQUENCE"),
    ("v_orders", "VIEW"),
]


def _qx():
    """Stub executor filtering the catalog by the TABLE_TYPE values in the query."""
    qx = MagicMock()

    def _execute_query(connection, query, params=None):
        if "information_schema.TABLES" not in query:
            return []
        types = set(re.findall(r"'([A-Z ]+)'", query))
        return [{"TABLE_NAME": n, "table_name": n} for n, t in _CATALOG if t in types]

    qx.execute_query.side_effect = _execute_query
    qx.get_schema_qualified_name.side_effect = lambda s, n: f"`{s}`.`{n}`"
    qx.get_quoted_schema_name.side_effect = lambda s: f"`{s}`"
    return qx


class TestMariadbCleanSystemVersioned(unittest.TestCase):
    def test_preview_lists_system_versioned_table(self):
        ops = MySqlSchemaOperations(query_executor=_qx(), log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "testdb")

        self.assertEqual(
            [(o.object_type, o.name) for o in summary.objects],
            [("table", "orders"), ("table", "prices"), ("sequence", "seq_a")],
        )
        self.assertIn("DROP TABLE IF EXISTS `testdb`.`prices`", summary.statements)

    def test_clean_schema_drops_system_versioned_table(self):
        ops = MySqlSchemaOperations(query_executor=_qx(), log=MagicMock())

        summary = ops.clean_schema(MagicMock(), "testdb")

        drops = [s for s in summary.statements if s.startswith("DROP")]
        self.assertEqual(
            drops,
            [
                "DROP TABLE IF EXISTS `testdb`.`orders`",
                "DROP TABLE IF EXISTS `testdb`.`prices`",
                "DROP SEQUENCE IF EXISTS `testdb`.`seq_a`",
            ],
        )

    def test_get_tables_includes_system_versioned_table(self):
        ops = MySqlSchemaOperations(query_executor=_qx(), log=MagicMock())

        self.assertEqual(ops.get_tables(MagicMock(), "testdb"), ["orders", "prices"])


if __name__ == "__main__":
    unittest.main()
