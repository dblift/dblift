"""Read-failure contract for the view, sequence, trigger and routine extractors.

Companion to ``test_index_extractor_read_failure_contract.py``. The same
defect shape existed in :class:`ViewExtractor`, :class:`SequenceExtractor`,
:class:`TriggerExtractor` and :class:`ProcedureExtractor`: the whole
schema-level extract was wrapped in ``except Exception: log; return []``,
so a failure to *read* an object type produced the same value as a schema
that genuinely contains none of it. A schema export completed
"successfully" with every view, sequence, trigger, procedure or function
silently missing.

Unlike indexes, these object types are genuinely absent from some
engines -- SQLite and MySQL have no sequences, several engines have no
materialized views or stored procedures. That is *not* what the removed
handlers protected, though: an engine without an object type never
reaches the query at all. It is declined earlier, by a capability
predicate (``supports_sequences()``, ``supports_triggers()``, ...) or by
the vendor query method returning ``(None, [])`` -- both plain return
values checked before any round trip, and both documented as the way to
express "not supported" in
:class:`~core.introspection.vendor_queries_base.VendorMetadataQueries`.
So the only thing an exception from the round trip could ever mean is a
read failure, and it now propagates.

Per-object and per-property helpers are a different case and keep their
handlers: losing one view's column list, or one routine's parameter
list, degrades a single property of an object that is still exported,
and the object itself still appears in the result. Those boundaries are
pinned by ``TestNarrowHelperDegradation`` below so the next reader can
see exactly which failures are still absorbed and which are not.

These tests drive real extractor instances against a real
:class:`VendorMetadataQueries` subclass; only the driver round trip
(``query_executor.execute_query``) is faked.
"""

from typing import Any, List, Optional

import pytest

from core.introspection.extractors.procedure_extractor import ProcedureExtractor
from core.introspection.extractors.sequence_extractor import SequenceExtractor
from core.introspection.extractors.trigger_extractor import TriggerExtractor
from core.introspection.extractors.view_extractor import ViewExtractor
from core.introspection.vendor_queries_base import VendorMetadataQueries

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Real collaborators
# ---------------------------------------------------------------------------


class _BaseQueries(VendorMetadataQueries):
    """Concrete vendor queries implementing only the abstract surface.

    Everything optional keeps the base-class default, which is exactly the
    "this dialect does not support it" answer the extractors gate on.
    """

    def get_check_constraints_query(self, schema: str, table: str):
        return ("SELECT 1", [])

    def get_sequences_query(self, schema: str):
        return ("SELECT * FROM information_schema.sequences WHERE sequence_schema = ?", [schema])

    def get_views_query(self, schema: str):
        return ("SELECT * FROM information_schema.views WHERE table_schema = ?", [schema])

    def get_view_definition_query(self, schema: str, view_name: str):
        return ("SELECT 1", [])

    def get_indexes_query(self, schema: str, table: str):
        return ("SELECT 1", [])


class _FullSupportQueries(_BaseQueries):
    """A dialect that declares support for every object type under test."""

    def supports_triggers(self) -> bool:
        return True

    def supports_materialized_views(self) -> bool:
        return True

    def supports_procedures(self) -> bool:
        return True

    def supports_functions(self) -> bool:
        return True

    def get_triggers_query(self, schema: str, table: Optional[str] = None):
        return ("SELECT * FROM information_schema.triggers WHERE trigger_schema = ?", [schema])

    def get_materialized_views_query(self, schema: str):
        return ("SELECT * FROM pg_matviews WHERE schemaname = ?", [schema])

    def get_procedures_query(self, schema: str):
        return ("SELECT * FROM information_schema.routines WHERE routine_schema = ?", [schema])

    def get_functions_query(self, schema: str):
        return ("SELECT * FROM information_schema.routines WHERE routine_schema = ?", [schema])

    def get_function_arguments_query(self, schema: str, function_name: str):
        # Not on the base class -- ``get_functions`` probes for it with
        # ``hasattr``, so declaring it here is what makes the per-function
        # argument lookup actually run.
        return ("SELECT * FROM pg_proc WHERE proname = ?", [function_name])


class _NoSequencesQueries(_BaseQueries):
    """A SQLite/MySQL-shaped dialect: no sequence objects exist at all.

    Neither engine has ``CREATE SEQUENCE``, so ``get_sequences`` must
    return ``[]`` without ever issuing a query -- and must reach that
    answer through the capability predicate, not by catching whatever the
    catalog lookup would have raised.
    """

    def supports_sequences(self) -> bool:
        return False


class _NullQueryQueries(_BaseQueries):
    """Declares support but has no catalog query to offer.

    ``VendorMetadataQueries`` documents ``(None, [])`` as the "not
    supported" return for triggers, materialized views, procedures and
    functions. That path must also short-circuit before any round trip.
    """

    def supports_triggers(self) -> bool:
        return True

    def supports_materialized_views(self) -> bool:
        return True

    def supports_procedures(self) -> bool:
        return True

    def supports_functions(self) -> bool:
        return True


class _RaisingQueryExecutor:
    """Stands in for the database driver: every call raises."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls: List[Any] = []

    def execute_query(self, connection, query, params=None):
        self.calls.append(query)
        raise self._exc


class _RowsQueryExecutor:
    """Stands in for the database driver: replays canned row batches.

    Each element of *batches* answers one call, in order. A batch that is
    an exception instance is raised instead of returned, so a test can say
    "the object list read fine, the follow-up property lookup did not".
    """

    def __init__(self, *batches: Any) -> None:
        self._batches = list(batches) or [[]]
        self.calls: List[Any] = []

    def execute_query(self, connection, query, params=None):
        self.calls.append(query)
        batch = self._batches[min(len(self.calls) - 1, len(self._batches) - 1)]
        if isinstance(batch, Exception):
            raise batch
        return batch


class _StubProvider:
    def __init__(self, query_executor: Any) -> None:
        self.query_executor = query_executor


class _OpenConnection:
    closed = False


def _make(extractor_cls, query_executor, queries=None, dialect="postgresql"):
    return extractor_cls(
        provider=_StubProvider(query_executor),
        connection=_OpenConnection(),
        metadata=object(),
        vendor_queries=_FullSupportQueries() if queries is None else queries,
        dialect=dialect,
    )


_READ_FAILURES = [
    RuntimeError("permission denied for relation pg_class"),
    ConnectionError("server closed the connection unexpectedly"),
    OSError("connection reset by peer"),
    ValueError("could not decode catalog row"),
]


# ---------------------------------------------------------------------------
# A read failure must not present as an empty result
# ---------------------------------------------------------------------------


class TestReadFailurePropagates:
    """The whole point of the fix: a failed read is not an empty schema."""

    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_get_views_read_failure_propagates(self, exc):
        ext = _make(ViewExtractor, _RaisingQueryExecutor(exc))

        with pytest.raises(type(exc)):
            ext.get_views("public")

    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_get_materialized_views_read_failure_propagates(self, exc):
        ext = _make(ViewExtractor, _RaisingQueryExecutor(exc))

        with pytest.raises(type(exc)):
            ext.get_materialized_views("public")

    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_get_sequences_read_failure_propagates(self, exc):
        ext = _make(SequenceExtractor, _RaisingQueryExecutor(exc))

        with pytest.raises(type(exc)):
            ext.get_sequences("public")

    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_get_triggers_read_failure_propagates(self, exc):
        ext = _make(TriggerExtractor, _RaisingQueryExecutor(exc))

        with pytest.raises(type(exc)):
            ext.get_triggers("public")

    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_get_procedures_read_failure_propagates(self, exc):
        ext = _make(ProcedureExtractor, _RaisingQueryExecutor(exc))

        with pytest.raises(type(exc)):
            ext.get_procedures("public")

    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_get_functions_read_failure_propagates(self, exc):
        ext = _make(ProcedureExtractor, _RaisingQueryExecutor(exc))

        with pytest.raises(type(exc)):
            ext.get_functions("public")

    def test_a_restricted_role_does_not_look_like_an_empty_schema(self):
        """The motivating scenario, stated once in full.

        A role with ``USAGE`` on a schema but no read access to the
        routine catalog used to get a clean export whose ``procedures``
        list was empty -- indistinguishable from a schema with no
        procedures. It must now fail loudly instead."""
        exc = RuntimeError("permission denied for view information_schema.routines")
        ext = _make(ProcedureExtractor, _RaisingQueryExecutor(exc))

        with pytest.raises(RuntimeError, match="permission denied"):
            ext.get_procedures("finance")


# ---------------------------------------------------------------------------
# Genuinely empty is still a clean empty list
# ---------------------------------------------------------------------------


class TestGenuinelyEmptySchemaReturnsEmptyList:
    """The query runs and returns zero rows -- that, not an exception, is
    how "this schema has none of these" is represented."""

    @pytest.mark.parametrize(
        "extractor_cls, method",
        [
            (ViewExtractor, "get_views"),
            (ViewExtractor, "get_materialized_views"),
            (SequenceExtractor, "get_sequences"),
            (TriggerExtractor, "get_triggers"),
            (ProcedureExtractor, "get_procedures"),
            (ProcedureExtractor, "get_functions"),
        ],
    )
    def test_zero_rows_returns_empty_list(self, extractor_cls, method):
        executor = _RowsQueryExecutor([])
        ext = _make(extractor_cls, executor)

        assert getattr(ext, method)("public") == []
        assert executor.calls, "the query should actually have been attempted"


# ---------------------------------------------------------------------------
# An engine without the object type declines before any round trip
# ---------------------------------------------------------------------------


class TestUnsupportedObjectTypeNeverReachesTheQuery:
    """A dialect that has no such object type is answered by a capability
    predicate or a ``(None, [])`` query, never by catching an error."""

    def test_sqlite_and_mysql_have_no_sequences(self):
        """Neither engine has ``CREATE SEQUENCE``. ``get_sequences`` must
        return ``[]`` without touching the driver -- if it had relied on
        the removed handler, the driver would have been called first."""
        executor = _RaisingQueryExecutor(RuntimeError("must not be reached"))
        ext = _make(SequenceExtractor, executor, queries=_NoSequencesQueries(), dialect="sqlite")

        assert ext.get_sequences("main") == []
        assert executor.calls == []

    @pytest.mark.parametrize(
        "extractor_cls, method",
        [
            (ViewExtractor, "get_materialized_views"),
            (TriggerExtractor, "get_triggers"),
            (ProcedureExtractor, "get_procedures"),
            (ProcedureExtractor, "get_functions"),
        ],
    )
    def test_capability_predicate_declines_without_a_round_trip(self, extractor_cls, method):
        """``supports_*`` defaults to ``False`` for every optional object
        type, which is how an engine without materialized views, triggers,
        procedures or functions is meant to answer."""
        executor = _RaisingQueryExecutor(RuntimeError("must not be reached"))
        ext = _make(extractor_cls, executor, queries=_BaseQueries())

        assert getattr(ext, method)("public") == []
        assert executor.calls == []

    @pytest.mark.parametrize(
        "extractor_cls, method",
        [
            (ViewExtractor, "get_materialized_views"),
            (TriggerExtractor, "get_triggers"),
            (ProcedureExtractor, "get_procedures"),
            (ProcedureExtractor, "get_functions"),
        ],
    )
    def test_null_vendor_query_declines_without_a_round_trip(self, extractor_cls, method):
        """The other documented "not supported" answer: the dialect claims
        the capability but has no catalog query, so ``(None, [])`` comes
        back and no query is issued."""
        executor = _RaisingQueryExecutor(RuntimeError("must not be reached"))
        ext = _make(extractor_cls, executor, queries=_NullQueryQueries())

        assert getattr(ext, method)("public") == []
        assert executor.calls == []

    @pytest.mark.parametrize(
        "extractor_cls, method",
        [
            (ViewExtractor, "get_views"),
            (ViewExtractor, "get_materialized_views"),
            (SequenceExtractor, "get_sequences"),
            (TriggerExtractor, "get_triggers"),
            (ProcedureExtractor, "get_procedures"),
            (ProcedureExtractor, "get_functions"),
        ],
    )
    def test_dialect_without_vendor_queries_declines(self, extractor_cls, method):
        """No catalog-query bundle registered for the dialect at all."""
        executor = _RaisingQueryExecutor(RuntimeError("must not be reached"))
        ext = extractor_cls(
            provider=_StubProvider(executor),
            connection=_OpenConnection(),
            metadata=object(),
            vendor_queries=None,
            dialect="postgresql",
        )

        assert getattr(ext, method)("public") == []
        assert executor.calls == []


# ---------------------------------------------------------------------------
# Handlers deliberately kept: per-property degradation, not object loss
# ---------------------------------------------------------------------------


class TestNarrowHelperDegradation:
    """These handlers survive the fix. Each absorbs a failure in a
    *supplementary* lookup for one already-discovered object, leaves the
    object in the result, and blanks only the property it could not read.
    Pinned here so the boundary is visible rather than implied."""

    def test_view_survives_a_failed_column_lookup(self):
        """The views query succeeded, so the view exists and is exported.
        Only the follow-up column lookup failed, so ``columns`` is empty
        and the view is still returned."""
        executor = _RowsQueryExecutor(
            [{"view_name": "v_orders", "view_definition": "SELECT 1"}],
            RuntimeError("permission denied for information_schema.columns"),
        )
        ext = _make(ViewExtractor, executor)

        views = ext.get_views("public")

        assert [v.name for v in views] == ["v_orders"]
        assert views[0].columns == []

    def test_materialized_view_survives_a_failed_column_lookup(self):
        executor = _RowsQueryExecutor(
            [{"materialized_view_name": "mv_orders", "view_definition": "SELECT 1"}],
            RuntimeError("permission denied for information_schema.columns"),
        )
        ext = _make(ViewExtractor, executor)

        mviews = ext.get_materialized_views("public")

        assert [v.name for v in mviews] == ["mv_orders"]
        assert mviews[0].columns == []

    def test_function_survives_a_failed_argument_lookup(self):
        """The routine list read fine; the per-routine argument query did
        not. The function stays in the export with no parameters rather
        than the whole schema's function list disappearing."""
        executor = _RowsQueryExecutor(
            [{"function_name": "calc_total", "definition": "CREATE FUNCTION calc_total() ..."}],
            RuntimeError("permission denied for pg_proc"),
        )
        ext = _make(ProcedureExtractor, executor)

        functions = ext.get_functions("public")

        assert len(executor.calls) >= 2, "the per-function argument query must have been attempted"
        assert [f.name for f in functions] == ["calc_total"]
        assert functions[0].parameters == []
