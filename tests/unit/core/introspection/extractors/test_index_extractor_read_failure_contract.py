"""Read-failure contract for ``IndexExtractor.get_indexes``.

A failure to *read* a table's indexes (permission denied, connection drop,
a catalog view that isn't reachable, etc.) must not be indistinguishable
from a table that genuinely has no indexes. Before this fix, ``get_indexes``
caught every exception raised while running the vendor query, logged a
warning, and returned ``[]`` -- the same value a real empty result
produces. A caller building a schema export saw a clean, complete-looking
result with every index on that table silently missing.

There is no dialect-legitimate exception that means "this table has no
indexes": that outcome is represented by the vendor query running
successfully and returning zero rows, not by raising. So the fix removes
the swallow entirely -- any exception raised while running the vendor
query now propagates out of ``get_indexes`` rather than being narrowed to
a specific "safe" exception type, because no such type exists.

These tests use a real :class:`IndexExtractor` (and, for the last case, a
real :class:`~core.introspection.base_introspector.BaseIntrospector`
subclass) together with a real :class:`VendorMetadataQueries` subclass;
only the database round trip (``query_executor.execute_query``) is
stubbed, matching the style of ``test_index_extractor_bulk_contract.py``.
"""

from typing import Any, List, Optional

import pytest

from core.introspection.extractors.index_extractor import IndexExtractor
from core.introspection.vendor_queries_base import VendorMetadataQueries

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Real collaborators
# ---------------------------------------------------------------------------


class _TestQueries(VendorMetadataQueries):
    """Concrete vendor queries implementing only the abstract surface."""

    def get_check_constraints_query(self, schema: str, table: str):
        return ("SELECT 1", [])

    def get_sequences_query(self, schema: str):
        return ("SELECT 1", [])

    def get_views_query(self, schema: str):
        return ("SELECT 1", [])

    def get_view_definition_query(self, schema: str, view_name: str):
        return ("SELECT 1", [])

    def get_indexes_query(self, schema: str, table: str):
        return (
            "SELECT * FROM pg_indexes WHERE schemaname = %s AND tablename = %s",
            [schema, table],
        )


class _RaisingQueryExecutor:
    """Stands in for the database driver: every call raises."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def execute_query(self, connection, query, params):
        raise self._exc


class _RowsQueryExecutor:
    """Stands in for the database driver: replays canned rows."""

    def __init__(self, rows: Optional[List[Any]] = None) -> None:
        self.rows = rows if rows is not None else []

    def execute_query(self, connection, query, params):
        return self.rows


class _StubProvider:
    def __init__(self, query_executor: Any) -> None:
        self.query_executor = query_executor


class _OpenConnection:
    closed = False


def _make_extractor(query_executor: Any, dialect: str = "postgresql") -> IndexExtractor:
    return IndexExtractor(
        provider=_StubProvider(query_executor),
        connection=_OpenConnection(),
        metadata=object(),
        vendor_queries=_TestQueries(),
        dialect=dialect,
    )


# ---------------------------------------------------------------------------
# A read failure must not present as an empty result
# ---------------------------------------------------------------------------


class TestReadFailurePropagates:
    def test_permission_denied_is_not_swallowed_into_empty_list(self):
        """A restricted role that can SELECT a table but not read pg_indexes
        must not look like a table that has no indexes."""
        exc = RuntimeError("permission denied for relation pg_indexes")
        ext = _make_extractor(_RaisingQueryExecutor(exc))

        with pytest.raises(RuntimeError, match="permission denied"):
            ext.get_indexes("public", "my_table")

    def test_connection_failure_is_not_swallowed_into_empty_list(self):
        exc = ConnectionError("server closed the connection unexpectedly")
        ext = _make_extractor(_RaisingQueryExecutor(exc))

        with pytest.raises(ConnectionError):
            ext.get_indexes("public", "my_table")

    def test_no_exception_type_is_treated_as_meaning_no_indexes(self):
        """There is no dialect-legitimate exception meaning "this table has
        no indexes" -- that outcome is an empty row set, not a raise. Any
        exception, of any type, must propagate rather than being narrowed
        away."""
        for exc in (RuntimeError("x"), ValueError("x"), KeyError("x"), OSError("x")):
            ext = _make_extractor(_RaisingQueryExecutor(exc))
            with pytest.raises(type(exc)):
                ext.get_indexes("public", "my_table")


# ---------------------------------------------------------------------------
# An object genuinely without indexes must still return [] cleanly
# ---------------------------------------------------------------------------


class TestGenuinelyEmptyResultStillReturnsEmptyList:
    def test_zero_rows_from_a_successful_query_returns_empty_list(self):
        """A table that really has no indexes: the query runs fine and
        returns zero rows. That is a clean ``[]``, not an exception."""
        ext = _make_extractor(_RowsQueryExecutor(rows=[]))

        assert ext.get_indexes("public", "my_table") == []

    def test_rows_from_a_successful_query_are_still_parsed(self):
        rows = [
            {
                "index_name": "my_table_pkey",
                "column_name": "id",
                "ordinal_position": 1,
                "is_unique": "Y",
                "index_type": "btree",
                "is_descending": False,
            }
        ]
        ext = _make_extractor(_RowsQueryExecutor(rows=rows))

        result = ext.get_indexes("public", "my_table")

        assert len(result) == 1
        assert result[0].name == "my_table_pkey"


class TestNoVendorQueriesIsNotAReadFailure:
    def test_dialect_without_vendor_queries_returns_empty_list(self):
        """A dialect with no index-introspection support at all declines up
        front -- unrelated to the read-failure contract above, since no
        query is ever attempted."""
        ext = IndexExtractor(
            provider=_StubProvider(_RaisingQueryExecutor(RuntimeError("must not be called"))),
            connection=_OpenConnection(),
            metadata=object(),
            vendor_queries=None,
            dialect="cosmosdb",
        )

        assert ext.get_indexes("public", "my_table") == []


# ---------------------------------------------------------------------------
# The introspector must not flatten the distinction either
# ---------------------------------------------------------------------------


class TestBaseIntrospectorPropagatesReadFailures:
    """End-to-end through a real BaseIntrospector, not just the extractor."""

    def _introspector(self, extractor):
        from core.introspection.base_introspector import BaseIntrospector

        class _Introspector(BaseIntrospector):
            def _get_index_extractor(self):
                return extractor

        return _Introspector.__new__(_Introspector)

    def test_get_indexes_read_failure_propagates_through_introspector(self):
        exc = RuntimeError("permission denied for relation pg_indexes")
        ext = _make_extractor(_RaisingQueryExecutor(exc))
        introspector = self._introspector(ext)

        with pytest.raises(RuntimeError, match="permission denied"):
            introspector.get_indexes("public", "my_table")
