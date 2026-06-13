from unittest.mock import MagicMock

import pytest

from core.introspection.extractors.index_extractor import IndexExtractor
from db.plugins.sqlserver.introspection.sqlserver_queries import SQLServerMetadataQueries


def _make_provider():
    provider = MagicMock()
    return provider


@pytest.mark.unit
class TestIndexExtractorNativeBulkFallback:
    def test_get_all_indexes_returns_empty_when_no_vendor_queries(self):
        provider = _make_provider()
        metadata = MagicMock()

        extractor = IndexExtractor(
            provider=provider,
            connection=MagicMock(),
            metadata=metadata,
            vendor_queries=None,
            dialect="sqlserver",
        )
        extractor.ensure_metadata = MagicMock()

        indexes = extractor.get_all_indexes("dblift_test")

        assert indexes == []
        metadata.getTables.assert_not_called()
        metadata.getIndexInfo.assert_not_called()


@pytest.mark.unit
class TestSqlServerBulkIndexQuery:
    def test_get_all_indexes_query_includes_indexed_views(self):
        query, params = SQLServerMetadataQueries().get_all_indexes_query("dblift_test")

        assert params == ["dblift_test"]
        assert "sys.objects" in query
        assert "o.type IN ('U', 'V')" in query
        assert "o.name AS table_name" in query

    def test_get_all_indexes_parses_table_and_view_indexes(self):
        provider = _make_provider()
        provider.query_executor.execute_query.return_value = [
            {
                "table_name": "orders",
                "index_name": "idx_orders_user_id",
                "column_name": "user_id",
                "ordinal_position": 1,
                "is_descending": "N",
                "is_unique": "N",
                "index_type": "NONCLUSTERED",
                "filter_condition": None,
                "is_included": "N",
                "is_expression": "N",
                "include_columns": None,
            },
            {
                "table_name": "order_summary",
                "index_name": "idx_order_summary",
                "column_name": "user_id",
                "ordinal_position": 1,
                "is_descending": "N",
                "is_unique": "Y",
                "index_type": "CLUSTERED",
                "filter_condition": None,
                "is_included": "N",
                "is_expression": "N",
                "include_columns": None,
            },
        ]
        extractor = IndexExtractor(
            provider=provider,
            connection=MagicMock(),
            metadata=MagicMock(),
            vendor_queries=SQLServerMetadataQueries(),
            dialect="sqlserver",
        )

        indexes = extractor.get_all_indexes("dblift_test")

        by_name = {index.name: index for index in indexes}
        assert by_name["idx_orders_user_id"].table_name == "orders"
        assert by_name["idx_order_summary"].table_name == "order_summary"
        assert by_name["idx_order_summary"].unique is True
        assert by_name["idx_order_summary"].columns == ["user_id"]
