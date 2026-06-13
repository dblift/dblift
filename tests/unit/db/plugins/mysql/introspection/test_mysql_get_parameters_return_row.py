"""BUG-02 regression: MySQL parameters query must exclude the return row.

``information_schema.PARAMETERS`` stores one row with ``ORDINAL_POSITION=0``
and ``PARAMETER_MODE=NULL`` for every FUNCTION (representing the return
value, not a real parameter). Before the fix, that row bled into snapshots
as a ghost ``param_0`` column with an empty mode, which corrupted round-trip
diffs and confused reviewers.

The fix adds ``AND PARAMETER_MODE IS NOT NULL`` to the WHERE clause so the
return-row is filtered out while IN/OUT/INOUT parameters survive.
"""

from __future__ import annotations

import pytest

from db.plugins.mysql.introspection.mysql_queries import MySQLMetadataQueries


@pytest.mark.unit
class TestMysqlGetParametersReturnRowFilter:
    def test_query_excludes_null_parameter_mode(self):
        q = MySQLMetadataQueries()
        sql, params = q.get_parameters_query("test_schema", "fn_greet")
        # The return-row filter must be present.
        assert "PARAMETER_MODE IS NOT NULL" in sql

    def test_query_still_orders_by_position(self):
        q = MySQLMetadataQueries()
        sql, _ = q.get_parameters_query("test_schema", "fn_greet")
        assert "ORDER BY ORDINAL_POSITION" in sql

    def test_query_binds_schema_and_routine(self):
        q = MySQLMetadataQueries()
        sql, params = q.get_parameters_query("test_schema", "fn_greet")
        assert params == ["test_schema", "fn_greet"]
        assert "SPECIFIC_SCHEMA = ?" in sql
        assert "SPECIFIC_NAME = ?" in sql

    def test_filter_placed_in_where_clause(self):
        """The filter must be ANDed into the existing WHERE, not a new WHERE."""
        q = MySQLMetadataQueries()
        sql, _ = q.get_parameters_query("s", "r")
        # Exactly one WHERE, and the new filter is part of it.
        assert sql.count("WHERE") == 1
        # The AND is inside the WHERE block before ORDER BY.
        where_start = sql.index("WHERE")
        order_start = sql.index("ORDER BY")
        assert "PARAMETER_MODE IS NOT NULL" in sql[where_start:order_start]
