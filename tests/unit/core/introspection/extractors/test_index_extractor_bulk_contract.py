"""Contract tests for the bulk-index return value.

``IndexExtractor.get_all_indexes`` has three distinguishable outcomes and the
caller must be able to tell them apart:

* ``None``  — "I cannot answer in bulk, ask me table by table."  Either the
  dialect ships no vendor queries at all, or its
  :meth:`VendorMetadataQueries.get_all_indexes_query` declines by returning
  ``None``.
* ``[]``    — "I ran the bulk query and the schema genuinely has no indexes."
* ``[...]`` — the indexes.

Collapsing the first two into ``[]`` makes a caller with a working per-table
fallback skip it and record "no indexes" as fact.  Collapsing an *empty*
result into ``None`` is the opposite mistake: it forces a needless per-table
sweep over every index-free schema.

These tests use real :class:`VendorMetadataQueries` subclasses and a real
:class:`IndexExtractor`; only the database itself is stubbed, at the
``query_executor.execute_query`` boundary.
"""

from typing import Any, List, Optional

import pytest

from dblift.core.introspection.extractors.index_extractor import IndexExtractor
from dblift.core.introspection.vendor_queries_base import VendorMetadataQueries

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Real collaborators
# ---------------------------------------------------------------------------


class _BaseTestQueries(VendorMetadataQueries):
    """Concrete vendor queries implementing only the abstract surface.

    ``get_all_indexes_query`` is deliberately *not* overridden, so it keeps
    the base-class behaviour of returning ``None`` — which is what 11 of the
    12 shipped query classes do.
    """

    def get_check_constraints_query(self, schema: str, table: str):
        return ("SELECT 1", [])

    def get_sequences_query(self, schema: str):
        return ("SELECT 1", [])

    def get_views_query(self, schema: str):
        return ("SELECT 1", [])

    def get_view_definition_query(self, schema: str, view_name: str):
        return ("SELECT 1", [])

    def get_indexes_query(self, schema: str, table: str):
        return ("SELECT per-table", [schema, table])


class _BulkCapableQueries(_BaseTestQueries):
    """Vendor queries that *do* support bulk index retrieval."""

    def get_all_indexes_query(self, schema: str) -> Optional[tuple[str, List[Any]]]:
        return ("SELECT bulk", [schema])


class _StubQueryExecutor:
    """Stands in for the database. Records calls, replays canned rows."""

    def __init__(self, rows: Optional[List[Any]] = None) -> None:
        self.rows = rows if rows is not None else []
        self.calls: List[tuple] = []

    def execute_query(self, connection, query, params):
        self.calls.append((query, params))
        return self.rows


class _StubProvider:
    def __init__(self, rows: Optional[List[Any]] = None) -> None:
        self.query_executor = _StubQueryExecutor(rows)

    def create_connection(self):  # pragma: no cover - never reached in these tests
        raise AssertionError("get_all_indexes must not open a connection here")


class _OpenConnection:
    closed = False


def _make_extractor(dialect: str, vendor_queries: Any, rows: Optional[List[Any]] = None):
    provider = _StubProvider(rows)
    return IndexExtractor(
        provider=provider,
        connection=_OpenConnection(),
        metadata=object(),
        vendor_queries=vendor_queries,
        dialect=dialect,
    )


# ---------------------------------------------------------------------------
# None means "ask per table"
# ---------------------------------------------------------------------------


class TestBulkUnavailableReturnsNone:
    def test_dialect_without_bulk_query_returns_none(self):
        """A dialect declining bulk retrieval must not look like an empty schema."""
        ext = _make_extractor("mysql", _BaseTestQueries())

        result = ext.get_all_indexes("myschema")

        assert result is None
        # Nothing was asked of the database, so nothing was learned.
        assert ext.provider.query_executor.calls == []

    def test_no_vendor_queries_returns_none(self):
        """The CosmosDB path: VendorQueriesFactory.create() returned None.

        This branch short-circuits before the query-result check, so it needs
        its own coverage — a fix applied only to the other branch leaves every
        dialect without vendor queries silently reporting "no indexes".
        """
        ext = _make_extractor("cosmosdb", None)

        assert ext.get_all_indexes("myschema") is None


# ---------------------------------------------------------------------------
# [] still means "genuinely no indexes"
# ---------------------------------------------------------------------------


class TestBulkAvailableReturnsList:
    def test_bulk_query_with_no_rows_returns_empty_list_not_none(self):
        """An index-free schema is an answer, not a refusal.

        If this returned ``None`` the caller would fall back to a per-table
        sweep of every table in a schema we already know has no indexes.
        """
        ext = _make_extractor("sqlserver", _BulkCapableQueries(), rows=[])

        result = ext.get_all_indexes("dbo")

        assert result == []
        assert result is not None
        # The bulk query really was executed — that is what makes [] authoritative.
        assert ext.provider.query_executor.calls == [("SELECT bulk", ["dbo"])]

    def test_bulk_query_with_rows_returns_indexes(self):
        rows = [
            {
                "table_name": "orders",
                "index_name": "idx_orders_customer",
                "column_name": "customer_id",
                "ordinal_position": 1,
                "is_unique": "N",
                "index_type": "NONCLUSTERED",
                "is_descending": "N",
            },
            {
                "table_name": "users",
                "index_name": "idx_users_email",
                "column_name": "email",
                "ordinal_position": 1,
                "is_unique": "Y",
                "index_type": "NONCLUSTERED",
                "is_descending": "N",
            },
        ]
        ext = _make_extractor("sqlserver", _BulkCapableQueries(), rows=rows)

        result = ext.get_all_indexes("dbo")

        assert result is not None
        assert {idx.name for idx in result} == {"idx_orders_customer", "idx_users_email"}
        by_name = {idx.name: idx for idx in result}
        assert by_name["idx_users_email"].unique is True
        assert by_name["idx_orders_customer"].unique is False
        assert by_name["idx_orders_customer"].columns == ["customer_id"]


# ---------------------------------------------------------------------------
# The introspector must propagate the distinction, not flatten it
# ---------------------------------------------------------------------------


class TestBaseIntrospectorPropagatesContract:
    def _introspector(self, extractor):
        from dblift.core.introspection.base_introspector import BaseIntrospector

        class _Introspector(BaseIntrospector):
            def _get_index_extractor(self):
                return extractor

        return _Introspector.__new__(_Introspector)

    def test_none_is_propagated(self):
        ext = _make_extractor("mysql", _BaseTestQueries())
        introspector = self._introspector(ext)

        assert introspector.get_all_indexes("myschema") is None

    def test_empty_list_is_propagated(self):
        ext = _make_extractor("sqlserver", _BulkCapableQueries(), rows=[])
        introspector = self._introspector(ext)

        assert introspector.get_all_indexes("dbo") == []
