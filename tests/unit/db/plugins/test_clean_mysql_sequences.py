"""MariaDB sequences are listed and dropped by clean.

A MariaDB sequence appears in ``information_schema.TABLES`` with
``TABLE_TYPE = 'SEQUENCE'``, so the ``'BASE TABLE'`` listing never sees it and
``clean`` left sequences behind. MySQL has none, so the same query returns no
rows there.
"""

import unittest
from unittest.mock import MagicMock

from dblift.db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations


def _qx():
    """Stub executor answering by TABLE_TYPE, like the real catalog."""
    qx = MagicMock()

    def _execute_query(connection, query, params=None):
        if "'SEQUENCE'" in query:
            return [{"TABLE_NAME": "seq_a"}, {"TABLE_NAME": "seq_b"}]
        if "'BASE TABLE'" in query:
            return [{"TABLE_NAME": "orders"}]
        return []

    qx.execute_query.side_effect = _execute_query
    qx.get_schema_qualified_name.side_effect = lambda s, n: f"`{s}`.`{n}`"
    qx.get_quoted_schema_name.side_effect = lambda s: f"`{s}`"
    return qx


class TestMysqlCleanSequences(unittest.TestCase):
    def test_preview_lists_sequences_after_tables(self):
        ops = MySqlSchemaOperations(query_executor=_qx(), log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "testdb")

        self.assertEqual(
            [(o.object_type, o.name) for o in summary.objects],
            [("table", "orders"), ("sequence", "seq_a"), ("sequence", "seq_b")],
        )
        self.assertIn("DROP SEQUENCE IF EXISTS `testdb`.`seq_a`", summary.statements)
        self.assertFalse(any("DROP TABLE" in s and "seq_" in s for s in summary.statements))

    def test_clean_drops_sequences_after_tables_and_views(self):
        qx = _qx()
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.clean_schema(MagicMock(), "testdb")

        drops = [s for s in summary.statements if s.startswith("DROP")]
        self.assertEqual(
            drops,
            [
                "DROP TABLE IF EXISTS `testdb`.`orders`",
                "DROP SEQUENCE IF EXISTS `testdb`.`seq_a`",
                "DROP SEQUENCE IF EXISTS `testdb`.`seq_b`",
            ],
        )

    def test_no_sequences_means_no_sequence_drops(self):
        qx = _qx()
        default = qx.execute_query.side_effect
        qx.execute_query.side_effect = lambda c, q, params=None: (
            [] if "'SEQUENCE'" in q else default(c, q, params)
        )
        ops = MySqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "testdb")

        self.assertEqual([o.object_type for o in summary.objects], ["table"])


if __name__ == "__main__":
    unittest.main()
