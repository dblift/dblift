"""Extended unit tests for TableExtractor targeting branches not exercised by
test_table_extractor.py and test_table_extractor_config_skip.py: get_view_tables,
_preload_materialized_view_names, _coerce_bool, the column/constraint fallback
paths (no extractor injected), result-tracker status updates, and exception
handling in get_tables()."""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from core.introspection.extractors.table_extractor import TableExtractor

pytestmark = [pytest.mark.unit]


def _make_extractor(
    dialect="postgresql", vendor_queries=None, col_extractor=None, con_extractor=None
):
    provider = MagicMock()
    provider.query_executor = MagicMock()
    if vendor_queries is None:
        vendor_queries = MagicMock()
        vendor_queries.get_tables_query.return_value = ("SELECT tables", [])
        vendor_queries.get_view_names_query.return_value = None
    extractor = TableExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
        column_extractor=col_extractor,
        constraint_extractor=con_extractor,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


def _make_full_extractor(dialect="postgresql", vendor_queries=None, table_rows=None):
    col_ext = MagicMock()
    col_ext.get_columns.return_value = []
    con_ext = MagicMock()
    con_ext.get_constraints.return_value = []

    extractor = _make_extractor(
        dialect=dialect,
        vendor_queries=vendor_queries,
        col_extractor=col_ext,
        con_extractor=con_ext,
    )
    extractor.provider.query_executor.execute_query.return_value = table_rows or []
    return extractor


def _patch_si():
    return patch("core.introspection.schema_introspector.SchemaIntrospector")


class TestGetTablesVendorQueriesMissing(unittest.TestCase):
    def test_raises_when_vendor_queries_not_set(self):
        extractor = _make_extractor()
        extractor.vendor_queries = None
        with self.assertRaises(RuntimeError):
            extractor.get_tables("public")


class TestGetTablesPatternFilter(unittest.TestCase):
    def test_table_pattern_filters_out_non_matching_table(self):
        with _patch_si() as mock_si:
            mock_si.return_value = MagicMock()
            extractor = _make_full_extractor(
                table_rows=[
                    {
                        "TABLE_NAME": "orders",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            tables = extractor.get_tables("public", table_pattern="users%")
            self.assertEqual(tables, [])


class TestGetTablesIncludeViews(unittest.TestCase):
    def test_include_views_appends_views(self):
        with _patch_si() as mock_si:
            mock_si.return_value = MagicMock()
            vq = MagicMock()
            vq.get_tables_query.return_value = ("SELECT tables", [])
            vq.get_view_names_query.return_value = ("SELECT views", [])

            extractor = _make_full_extractor(vendor_queries=vq, table_rows=None)
            extractor.provider.query_executor.execute_query.side_effect = [
                [],
                [{"VIEW_NAME": "v1"}],
            ]

            tables = extractor.get_tables("public", include_views=True)

            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0].name, "v1")


class TestGetTablesOuterException(unittest.TestCase):
    def test_execute_query_exception_is_tracked_and_reraised(self):
        extractor = _make_extractor()
        extractor.provider.query_executor.execute_query.side_effect = RuntimeError("db down")
        result_tracker = MagicMock()
        extractor.result_tracker = result_tracker

        with self.assertRaises(RuntimeError):
            extractor.get_tables("public")

        result_tracker._track_error.assert_called_once()


class TestGetTablesPartitionSchemeEnrichmentException(unittest.TestCase):
    def test_partition_scheme_exception_does_not_propagate(self):
        with _patch_si() as mock_si:
            mock_si.return_value = MagicMock()
            extractor = _make_full_extractor(
                table_rows=[
                    {
                        "TABLE_NAME": "orders",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            extractor._enrich_partition_scheme = MagicMock(side_effect=RuntimeError("boom"))

            tables = extractor.get_tables("public")

            self.assertEqual(len(tables), 1)


class TestGetTablesNoColumnOrConstraintExtractor(unittest.TestCase):
    def test_falls_back_to_schema_introspector_for_columns_and_constraints(self):
        with _patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst._get_columns.return_value = ["col1"]
            mock_inst._get_constraints.return_value = ["pk1"]
            mock_si.return_value = mock_inst

            extractor = _make_extractor()
            extractor.provider.query_executor.execute_query.return_value = [
                {
                    "TABLE_NAME": "orders",
                    "TABLE_TYPE": "TABLE",
                    "REMARKS": None,
                    "TABLE_SCHEM": "public",
                }
            ]

            tables = extractor.get_tables("public")

            self.assertEqual(tables[0].columns, ["col1"])
            self.assertEqual(tables[0].constraints, ["pk1"])


class TestGetTablesResultTrackerStatus(unittest.TestCase):
    def test_columns_success_and_constraints_failure_tracked(self):
        with _patch_si() as mock_si:
            mock_si.return_value = MagicMock()
            result_tracker = MagicMock()
            status = MagicMock()
            result_tracker._track_object_status.return_value = status

            extractor = _make_full_extractor(
                dialect="mysql",
                table_rows=[
                    {
                        "TABLE_NAME": "orders",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            extractor.result_tracker = result_tracker
            extractor.constraint_extractor.get_constraints.side_effect = Exception("boom")

            tables = extractor.get_tables("public")

            status.add_property_status.assert_any_call("columns", True)
            status.add_property_status.assert_any_call("constraints", False)
            result_tracker._track_warning.assert_called_once()
            self.assertEqual(tables[0].constraints, [])

    def test_columns_failure_tracked(self):
        with _patch_si() as mock_si:
            mock_si.return_value = MagicMock()
            result_tracker = MagicMock()
            status = MagicMock()
            result_tracker._track_object_status.return_value = status

            extractor = _make_full_extractor(
                dialect="mysql",
                table_rows=[
                    {
                        "TABLE_NAME": "orders",
                        "TABLE_TYPE": "TABLE",
                        "REMARKS": None,
                        "TABLE_SCHEM": "public",
                    }
                ],
            )
            extractor.result_tracker = result_tracker
            extractor.column_extractor.get_columns.side_effect = Exception("boom")

            tables = extractor.get_tables("public")

            status.add_property_status.assert_any_call("columns", False)
            result_tracker._track_error.assert_called_once()
            self.assertEqual(tables[0].columns, [])


class TestCoerceBool(unittest.TestCase):
    def test_bool_input_returned_as_is(self):
        self.assertTrue(TableExtractor._coerce_bool(True))
        self.assertFalse(TableExtractor._coerce_bool(False))

    def test_string_yes_variants_return_true(self):
        for value in ("1", "Y", "yes", "TRUE", "t"):
            self.assertTrue(TableExtractor._coerce_bool(value))

    def test_string_other_returns_false(self):
        self.assertFalse(TableExtractor._coerce_bool("maybe"))

    def test_non_bool_non_str_uses_bool(self):
        self.assertTrue(TableExtractor._coerce_bool(1))
        self.assertFalse(TableExtractor._coerce_bool(0))
        self.assertFalse(TableExtractor._coerce_bool(None))


class TestGetViewTables(unittest.TestCase):
    def test_no_view_names_query_returns_empty(self):
        vq = MagicMock()
        vq.get_view_names_query.return_value = None
        extractor = _make_extractor(vendor_queries=vq)

        self.assertEqual(extractor._get_view_tables("public"), [])

    def test_skips_view_with_no_name(self):
        vq = MagicMock()
        vq.get_view_names_query.return_value = ("SELECT views", [])
        extractor = _make_extractor(vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [{"VIEW_NAME": None}]

        self.assertEqual(extractor._get_view_tables("public"), [])

    def test_table_pattern_filters_views(self):
        vq = MagicMock()
        vq.get_view_names_query.return_value = ("SELECT views", [])
        extractor = _make_extractor(vendor_queries=vq)
        extractor.provider.query_executor.execute_query.return_value = [{"VIEW_NAME": "v_orders"}]

        self.assertEqual(extractor._get_view_tables("public", table_pattern="users%"), [])

    def test_column_extractor_populates_view_columns(self):
        vq = MagicMock()
        vq.get_view_names_query.return_value = ("SELECT views", [])
        col_ext = MagicMock()
        col_ext.get_columns.return_value = ["col1"]
        extractor = _make_extractor(vendor_queries=vq, col_extractor=col_ext)
        extractor.provider.query_executor.execute_query.return_value = [{"VIEW_NAME": "v1"}]

        views = extractor._get_view_tables("public")

        self.assertEqual(views[0].columns, ["col1"])

    def test_column_extractor_exception_leaves_columns_empty(self):
        vq = MagicMock()
        vq.get_view_names_query.return_value = ("SELECT views", [])
        col_ext = MagicMock()
        col_ext.get_columns.side_effect = Exception("boom")
        extractor = _make_extractor(vendor_queries=vq, col_extractor=col_ext)
        extractor.provider.query_executor.execute_query.return_value = [{"VIEW_NAME": "v1"}]

        views = extractor._get_view_tables("public")

        self.assertEqual(views[0].columns, [])


class TestPreloadMaterializedViewNames(unittest.TestCase):
    def test_returns_uppercased_view_names(self):
        with _patch_si() as mock_si:
            mv = MagicMock()
            mv.name = "mv_sales"
            mock_inst = MagicMock()
            mock_inst.get_materialized_views.return_value = [mv]
            mock_si.return_value = mock_inst

            extractor = _make_extractor(dialect="oracle")

            self.assertEqual(extractor._preload_materialized_view_names("public"), {"MV_SALES"})

    def test_exception_returns_empty_set_and_tracks_warning(self):
        with _patch_si() as mock_si:
            mock_inst = MagicMock()
            mock_inst.get_materialized_views.side_effect = RuntimeError("boom")
            mock_si.return_value = mock_inst

            result_tracker = MagicMock()
            extractor = _make_extractor(dialect="oracle")
            extractor.result_tracker = result_tracker

            self.assertEqual(extractor._preload_materialized_view_names("public"), set())
            result_tracker._track_warning.assert_called_once()
