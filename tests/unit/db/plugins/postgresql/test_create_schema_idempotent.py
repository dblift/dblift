"""BUG-01: PG ``create_schema_if_not_exists`` skips DDL when schema exists.

Pre-fix: ``CREATE SCHEMA IF NOT EXISTS`` ran unconditionally even when the
pre-check confirmed the schema was present. PostgreSQL parses and
ACL-checks the statement regardless of the no-op semantics, so every
read-only command (info / validate / diff / check-connection) required
CREATE privilege on the database. Post-fix: early-return on existence;
no ``execute_statement`` call.
"""

import unittest
from unittest.mock import MagicMock

from dblift.db.plugins.postgresql.postgresql.schema_operations import PostgreSqlSchemaOperations


class TestPgCreateSchemaIdempotent(unittest.TestCase):
    def test_existing_schema_skips_create_ddl(self):
        qx = MagicMock()
        qx.execute_query.return_value = [{"?column?": 1}]  # row present → exists
        qx.get_quoted_schema_name.return_value = '"foo"'
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        ops.create_schema_if_not_exists(MagicMock(), "foo")

        qx.execute_statement.assert_not_called()

    def test_missing_schema_creates_and_warns(self):
        qx = MagicMock()
        qx.execute_query.return_value = []  # pg_namespace empty → not present
        qx.get_quoted_schema_name.return_value = '"foo"'
        log = MagicMock()
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=log)

        ops.create_schema_if_not_exists(MagicMock(), "foo")

        exec_calls = " ".join(str(c) for c in qx.execute_statement.call_args_list)
        self.assertIn("CREATE SCHEMA IF NOT EXISTS", exec_calls)
        warn_calls = " ".join(str(c) for c in log.warning.call_args_list)
        self.assertIn("did not exist", warn_calls)


if __name__ == "__main__":
    unittest.main()
