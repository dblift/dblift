"""
Unit tests for ViewExtractor.
Covers: get_views(), get_materialized_views(), _extract_view_query(),
_get_object_column_names(), _get_mysql_view_algorithm(),
dialect-specific properties, error handling.
"""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.introspection.extractors.view_extractor import ViewExtractor

pytestmark = [pytest.mark.unit]


def _make_extractor(dialect="postgresql", vendor_queries=None):
    provider = MagicMock()
    provider.query_executor = MagicMock()
    extractor = ViewExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


# --- _extract_view_query ---


class TestExtractViewQuery(unittest.TestCase):
    def _extractor(self):
        return _make_extractor()

    def test_returns_none_for_none_input(self):
        e = self._extractor()
        self.assertIsNone(e._extract_view_query(None))

    def test_returns_none_for_empty_string(self):
        e = self._extractor()
        self.assertIsNone(e._extract_view_query(""))

    def test_extracts_select_from_create_view(self):
        e = self._extractor()
        definition = "CREATE VIEW v_users AS SELECT id, name FROM users"
        result = e._extract_view_query(definition)
        self.assertEqual(result, "SELECT id, name FROM users")

    def test_extracts_select_strips_trailing_semicolon(self):
        e = self._extractor()
        definition = "CREATE VIEW v_orders AS SELECT * FROM orders;"
        result = e._extract_view_query(definition)
        self.assertEqual(result, "SELECT * FROM orders")

    def test_returns_plain_select_unchanged(self):
        e = self._extractor()
        definition = "SELECT id, name FROM users"
        result = e._extract_view_query(definition)
        self.assertEqual(result, "SELECT id, name FROM users")

    def test_prefixes_bare_expression_with_select(self):
        e = self._extractor()
        definition = "id, name FROM users"
        result = e._extract_view_query(definition)
        self.assertIn("SELECT", result)

    def test_strips_leading_comments(self):
        e = self._extractor()
        definition = "-- a comment\nCREATE VIEW v AS SELECT 1"
        result = e._extract_view_query(definition)
        self.assertIsNotNone(result)
        self.assertIn("1", result)

    def test_create_view_with_or_replace(self):
        e = self._extractor()
        definition = "CREATE OR REPLACE VIEW v AS SELECT id FROM t"
        result = e._extract_view_query(definition)
        self.assertEqual(result, "SELECT id FROM t")

    def test_with_query_returned_as_is(self):
        e = self._extractor()
        definition = "WITH cte AS (SELECT 1) SELECT * FROM cte"
        result = e._extract_view_query(definition)
        self.assertEqual(result, definition)


# --- get_views() no support ---


class TestGetViewsNoSupport(unittest.TestCase):
    def test_returns_empty_when_no_vendor_queries(self):
        extractor = _make_extractor()
        result = extractor.get_views("public")
        self.assertEqual(result, [])

    def test_returns_empty_when_views_not_supported(self):
        vq = MagicMock()
        vq.supports_views.return_value = False
        extractor = _make_extractor(vendor_queries=vq)
        result = extractor.get_views("public")
        self.assertEqual(result, [])


# --- get_views() basic ---


class TestGetViewsBasic(unittest.TestCase):
    def _make_pg_extractor(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        return extractor

    def test_single_view_basic_fields(self):
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v_users",
                "view_definition": "SELECT id, name FROM users",
                "is_updatable": "YES",
                "check_option": None,
                "column_names": None,
            }
        ]
        views = extractor.get_views("public")
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].name, "v_users")
        self.assertEqual(views[0].schema, "public")
        self.assertTrue(views[0].is_updatable)
        self.assertIsNone(views[0].check_option)
        self.assertIsNotNone(views[0].query)

    def test_empty_results_returns_empty_list(self):
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = []
        views = extractor.get_views("public")
        self.assertEqual(views, [])

    def test_multiple_views(self):
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v_a",
                "view_definition": "SELECT 1",
                "is_updatable": "NO",
                "check_option": None,
                "column_names": None,
            },
            {
                "view_name": "v_b",
                "view_definition": "SELECT 2",
                "is_updatable": "YES",
                "check_option": "LOCAL",
                "column_names": None,
            },
        ]
        views = extractor.get_views("public")
        self.assertEqual(len(views), 2)
        names = [v.name for v in views]
        self.assertIn("v_a", names)
        self.assertIn("v_b", names)

    def test_skips_view_with_none_name(self):
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": None,
                "view_definition": "SELECT 1",
                "is_updatable": "YES",
                "check_option": None,
                "column_names": None,
            }
        ]
        views = extractor.get_views("public")
        self.assertEqual(views, [])

    def test_skips_view_with_name_none_string(self):
        """Some databases return 'NONE' as view name."""
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "NONE",
                "view_definition": "SELECT 1",
                "is_updatable": "YES",
                "check_option": None,
                "column_names": None,
            }
        ]
        views = extractor.get_views("public")
        self.assertEqual(views, [])

    def test_check_option_none_string_becomes_none(self):
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v",
                "view_definition": "SELECT 1",
                "is_updatable": "YES",
                "check_option": "NONE",
                "column_names": None,
            }
        ]
        views = extractor.get_views("public")
        self.assertIsNone(views[0].check_option)

    def test_check_option_local_preserved(self):
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v",
                "view_definition": "SELECT 1",
                "is_updatable": "YES",
                "check_option": "LOCAL",
                "column_names": None,
            }
        ]
        views = extractor.get_views("public")
        self.assertEqual(views[0].check_option, "LOCAL")

    def test_not_updatable_when_no_flag(self):
        extractor = self._make_pg_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v",
                "view_definition": "SELECT 1",
                "is_updatable": "NO",
                "check_option": None,
                "column_names": None,
            }
        ]
        views = extractor.get_views("public")
        self.assertFalse(views[0].is_updatable)


class TestGetViewsColumnNames(unittest.TestCase):
    def test_column_names_from_json_array(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v",
                "view_definition": "SELECT id, name FROM t",
                "is_updatable": "YES",
                "check_option": None,
                "column_names": '["id", "name"]',
            }
        ]
        views = extractor.get_views("public")
        self.assertEqual(views[0].columns, ["id", "name"])


class TestGetViewsDB2LowercaseName(unittest.TestCase):
    def test_db2_view_name_lowercased(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="db2", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "V_ORDERS",
                "view_definition": "SELECT * FROM ORDERS",
                "is_updatable": "Y",
                "check_option": None,
                "column_names": None,
            }
        ]
        views = extractor.get_views("myschema")
        self.assertEqual(views[0].name, "v_orders")


class TestGetViewsMysqlDialect(unittest.TestCase):
    def _make_mysql_extractor(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="mysql", vendor_queries=vq)
        return extractor

    def test_mysql_view_definer_set(self):
        from unittest.mock import patch as _patch

        extractor = self._make_mysql_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v_products",
                "view_definition": "SELECT * FROM products",
                "is_updatable": "YES",
                "check_option": None,
                "column_names": None,
                "definer": "root@localhost",
                "sql_security": "DEFINER",
            }
        ]
        # Suppress the SHOW CREATE VIEW call (moved into MysqlQuirks).
        with _patch(
            "db.plugins.mysql.quirks.MysqlQuirks.fetch_view_algorithm",
            return_value=None,
        ):
            views = extractor.get_views("mydb")
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0].definer, "root@localhost")
        self.assertEqual(views[0].sql_security, "DEFINER")

    def test_mysql_view_algorithm_set(self):
        from unittest.mock import patch as _patch

        extractor = self._make_mysql_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "v",
                "view_definition": "SELECT 1",
                "is_updatable": "YES",
                "check_option": None,
                "column_names": None,
                "definer": None,
                "sql_security": None,
            }
        ]
        with _patch(
            "db.plugins.mysql.quirks.MysqlQuirks.fetch_view_algorithm",
            return_value="MERGE",
        ):
            views = extractor.get_views("mydb")
        self.assertEqual(views[0].algorithm, "MERGE")


class TestGetViewsPostgresqlDialect(unittest.TestCase):
    def test_postgresql_security_definer_set(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "view_name": "secure_view",
                "view_definition": "SELECT * FROM sensitive",
                "is_updatable": "NO",
                "check_option": None,
                "column_names": None,
                "security_definer": True,
                "security_invoker": False,
            }
        ]
        views = extractor.get_views("public")
        self.assertTrue(views[0].security_definer)
        self.assertFalse(views[0].security_invoker)


class TestGetViewsErrorHandling(unittest.TestCase):
    def test_query_exception_returns_empty_list(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("DB error")
        views = extractor.get_views("public")
        self.assertEqual(views, [])

    def test_error_tracked_when_result_tracker_set(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        tracker = MagicMock()
        extractor.result_tracker = tracker
        views = extractor.get_views("public")
        self.assertEqual(views, [])
        tracker._track_error.assert_called_once()


# --- get_materialized_views() ---


class TestGetMaterializedViews(unittest.TestCase):
    def _make_pg_mv_extractor(self):
        vq = MagicMock()
        vq.supports_materialized_views.return_value = True
        vq.get_materialized_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        return extractor

    def test_returns_empty_when_no_vendor_queries(self):
        extractor = _make_extractor()
        result = extractor.get_materialized_views("public")
        self.assertEqual(result, [])

    def test_returns_empty_when_not_supported(self):
        vq = MagicMock()
        vq.supports_materialized_views.return_value = False
        extractor = _make_extractor(vendor_queries=vq)
        result = extractor.get_materialized_views("public")
        self.assertEqual(result, [])

    def test_returns_empty_when_sql_is_none(self):
        vq = MagicMock()
        vq.supports_materialized_views.return_value = True
        vq.get_materialized_views_query.return_value = (None, [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        result = extractor.get_materialized_views("public")
        self.assertEqual(result, [])

    def test_single_materialized_view(self):
        extractor = self._make_pg_mv_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "materialized_view_name": "mv_sales",
                "view_definition": "SELECT sum(amount) FROM orders",
                "column_names": None,
                "is_populated": "YES",
                "is_unlogged": "NO",
                "last_refresh": None,
                "refresh_method": None,
                "refresh_mode": None,
                "fast_refreshable": None,
                "clustered_index_name": None,
                "clustered_index_columns": None,
            }
        ]
        mvs = extractor.get_materialized_views("public")
        self.assertEqual(len(mvs), 1)
        self.assertEqual(mvs[0].name, "mv_sales")
        self.assertTrue(mvs[0].materialized)
        self.assertTrue(mvs[0].is_populated)

    def test_empty_results(self):
        extractor = self._make_pg_mv_extractor()
        extractor.provider.query_executor.execute_query.return_value = []
        mvs = extractor.get_materialized_views("public")
        self.assertEqual(mvs, [])

    def test_skips_row_with_no_name(self):
        extractor = self._make_pg_mv_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "materialized_view_name": None,
                "view_definition": "SELECT 1",
                "column_names": None,
                "is_populated": "NO",
                "is_unlogged": "NO",
                "last_refresh": None,
                "refresh_method": None,
                "refresh_mode": None,
                "fast_refreshable": None,
                "clustered_index_name": None,
                "clustered_index_columns": None,
            }
        ]
        mvs = extractor.get_materialized_views("public")
        self.assertEqual(mvs, [])

    def test_postgresql_unlogged_set(self):
        extractor = self._make_pg_mv_extractor()
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "materialized_view_name": "mv_unlogged",
                "view_definition": "SELECT 1",
                "column_names": None,
                "is_populated": "YES",
                "is_unlogged": "YES",
                "last_refresh": None,
                "refresh_method": None,
                "refresh_mode": None,
                "fast_refreshable": None,
                "clustered_index_name": None,
                "clustered_index_columns": None,
            }
        ]
        mvs = extractor.get_materialized_views("public")
        self.assertTrue(mvs[0].unlogged)

    def test_oracle_refresh_metadata(self):
        vq = MagicMock()
        vq.supports_materialized_views.return_value = True
        vq.get_materialized_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "materialized_view_name": "MV_SALES",
                "view_definition": "SELECT * FROM SALES",
                "column_names": None,
                "is_populated": "YES",
                "is_unlogged": None,
                "last_refresh": "2024-01-01 00:00:00",
                "refresh_method": "FORCE",
                "refresh_mode": "DEMAND",
                "fast_refreshable": "YES",
                "clustered_index_name": None,
                "clustered_index_columns": None,
            }
        ]
        mvs = extractor.get_materialized_views("MYSCHEMA")
        self.assertEqual(len(mvs), 1)
        self.assertEqual(mvs[0].last_refresh, "2024-01-01 00:00:00")
        self.assertEqual(mvs[0].refresh_method, "FORCE")
        self.assertEqual(mvs[0].refresh_mode, "DEMAND")
        self.assertEqual(mvs[0].fast_refreshable, "YES")

    def test_sqlserver_clustered_index(self):
        vq = MagicMock()
        vq.supports_materialized_views.return_value = True
        vq.get_materialized_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "materialized_view_name": "idx_view",
                "view_definition": "SELECT id, sum(val) FROM t GROUP BY id",
                "column_names": None,
                "is_populated": "YES",
                "is_unlogged": None,
                "last_refresh": None,
                "refresh_method": None,
                "refresh_mode": None,
                "fast_refreshable": None,
                "clustered_index_name": "IX_idx_view",
                "clustered_index_columns": "id, val",
            }
        ]
        mvs = extractor.get_materialized_views("dbo")
        self.assertEqual(mvs[0].clustered_index_name, "IX_idx_view")
        self.assertEqual(mvs[0].clustered_index_columns, ["id", "val"])

    def test_error_returns_empty_list(self):
        extractor = self._make_pg_mv_extractor()
        extractor.provider.query_executor.execute_query.side_effect = Exception("DB fail")
        mvs = extractor.get_materialized_views("public")
        self.assertEqual(mvs, [])


# --- _get_object_column_names() ---


class TestGetObjectColumnNames(unittest.TestCase):
    def test_returns_empty_without_query_executor(self):
        provider = MagicMock()
        del provider.query_executor  # no attribute
        extractor = ViewExtractor(provider=provider, dialect="postgresql")
        extractor.ensure_metadata = MagicMock()
        result = extractor._get_object_column_names("public", "v_users")
        self.assertEqual(result, [])

    def test_caches_results(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"column_name": "id"},
            {"column_name": "name"},
        ]
        result1 = extractor._get_object_column_names("public", "v_users")
        result2 = extractor._get_object_column_names("public", "v_users")
        # Second call uses cache, execute_query should only be called once
        self.assertEqual(result1, ["id", "name"])
        self.assertEqual(result2, ["id", "name"])
        self.assertEqual(extractor.provider.query_executor.execute_query.call_count, 1)

    def test_returns_column_names_from_query(self):
        vq = MagicMock()
        vq.supports_views.return_value = True
        vq.get_views_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="postgresql", vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [
            {"column_name": "col_a"},
            {"column_name": "col_b"},
        ]
        cols = extractor._get_object_column_names("public", "v_test")
        self.assertEqual(cols, ["col_a", "col_b"])

    def test_query_exception_returns_empty(self):
        extractor = _make_extractor(dialect="postgresql")
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        result = extractor._get_object_column_names("public", "v_bad")
        self.assertEqual(result, [])


# --- MysqlQuirks.fetch_view_algorithm (moved from extractor) ---


class TestMysqlViewAlgorithm(unittest.TestCase):
    """``_get_mysql_view_algorithm`` migrated into
    :meth:`MysqlQuirks.fetch_view_algorithm` during the H.2 follow-up
    enrichers refactor; tests target the new home directly."""

    @staticmethod
    def _quirks():
        from db.plugins.mysql.quirks import MysqlQuirks

        return MysqlQuirks()

    def test_non_mysql_default_returns_none(self):
        from db.base_quirks import BaseQuirks

        extractor = _make_extractor(dialect="postgresql")
        self.assertIsNone(BaseQuirks().fetch_view_algorithm(extractor, "public", "v"))

    def test_no_query_executor_returns_none(self):
        provider = MagicMock()
        del provider.query_executor
        extractor = ViewExtractor(provider=provider, dialect="mysql")
        extractor.ensure_metadata = MagicMock()
        self.assertIsNone(self._quirks().fetch_view_algorithm(extractor, "mydb", "v"))

    def test_extracts_algorithm_from_show_create(self):
        extractor = _make_extractor(dialect="mysql")
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "Create View": "CREATE ALGORITHM=MERGE DEFINER=`root`@`localhost` VIEW `v` AS SELECT 1"
            }
        ]
        result = self._quirks().fetch_view_algorithm(extractor, "mydb", "v")
        self.assertEqual(result, "MERGE")

    def test_returns_none_when_no_rows(self):
        extractor = _make_extractor(dialect="mysql")
        extractor.provider.query_executor.execute_query.return_value = []
        self.assertIsNone(self._quirks().fetch_view_algorithm(extractor, "mydb", "v"))

    def test_returns_none_when_no_algorithm_in_statement(self):
        extractor = _make_extractor(dialect="mysql")
        extractor.provider.query_executor.execute_query.return_value = [
            {"Create View": "CREATE VIEW `v` AS SELECT 1"}
        ]
        self.assertIsNone(self._quirks().fetch_view_algorithm(extractor, "mydb", "v"))

    def test_query_exception_returns_none(self):
        extractor = _make_extractor(dialect="mysql")
        extractor.provider.query_executor.execute_query.side_effect = Exception("fail")
        self.assertIsNone(self._quirks().fetch_view_algorithm(extractor, "mydb", "v"))

    def test_backtick_in_name_escaped(self):
        """Backtick in view name is escaped to prevent SQL injection."""
        extractor = _make_extractor(dialect="mysql")
        extractor.provider.query_executor.execute_query.return_value = []
        self._quirks().fetch_view_algorithm(extractor, "my`db", "v`evil")
        call_args = extractor.provider.query_executor.execute_query.call_args
        sql = call_args[0][1]
        self.assertIn("``", sql)
