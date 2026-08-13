"""Read-failure contract for the view, sequence, trigger and routine extractors.

Companion to ``test_index_extractor_read_failure_contract.py``. The same
defect shape existed in :class:`ViewExtractor`, :class:`SequenceExtractor`,
:class:`TriggerExtractor` and :class:`ProcedureExtractor`: the whole
schema-level extract was wrapped in a handler that logged and returned
``[]``, so a failure to *read* an object type produced the same value as a
schema that genuinely contains none of it. A schema export completed
"successfully" with every view, sequence, trigger, procedure or function
silently missing.

Unlike indexes, these object types are genuinely absent from some engines.
That is not what the handlers protected, though: an engine without an
object type is declined *before* the query runs. What does the declining
differs per object type, and the tests below pin each one separately
rather than asserting a single rule for all six:

* ``vendor_queries is None`` — no catalog-query bundle registered for the
  dialect. This is the gate that actually fires in this repository, for
  every object type.
* ``supports_*()`` returning ``False`` — an extension point. The base
  class default is ``False`` for triggers, materialized views, procedures
  and functions, so those decline by not opting in. It is ``True`` for
  views and sequences, and no bundle here overrides it, so for those two
  the predicate is a documented hook rather than a route any shipped
  dialect currently takes.
* ``get_*_query()`` returning ``(None, [])`` — documented in
  :class:`~core.introspection.vendor_queries_base.VendorMetadataQueries`
  as the "not supported" return for the four optional queries. For views
  and sequences the ABC declares a non-optional query, so ``None`` there
  is out of contract; both methods guard it anyway rather than hand
  ``None`` to the driver.

Only once every one of those has passed does a query run, and only then
can an exception mean anything — at which point it can only mean the read
failed. It is recorded on the result tracker (``enable_result_tracking``
is a public extension point on the introspector) and then re-raised, so
callers that track keep an honest quality verdict and callers that do not
still see the failure.

Per-object and per-property helpers are a different case and keep their
handlers: losing one view's column list, or one routine's parameter list,
degrades a single property of an object that is still exported. Those
boundaries are pinned by ``TestNarrowHelperDegradation``.

These tests drive real extractor instances against real
:class:`VendorMetadataQueries` subclasses; only the driver round trip
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

    The four optional queries keep the base ``(None, [])``; every
    ``supports_*`` keeps its base default.
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


class _RealQueryQueries(_BaseQueries):
    """Every query returns real SQL. ``supports_*`` stay at base defaults.

    This is what makes the capability tests below non-vacuous: with a real
    query available for every object type, the ``if not sql`` guard cannot
    stand in for the predicate, so the predicate is the only thing that
    can decline.
    """

    def get_triggers_query(self, schema: str, table: Optional[str] = None):
        return ("SELECT * FROM information_schema.triggers WHERE trigger_schema = ?", [schema])

    def get_materialized_views_query(self, schema: str):
        return ("SELECT * FROM pg_matviews WHERE schemaname = ?", [schema])

    def get_procedures_query(self, schema: str):
        return ("SELECT * FROM information_schema.routines WHERE routine_schema = ?", [schema])

    def get_functions_query(self, schema: str):
        return ("SELECT * FROM information_schema.routines WHERE routine_schema = ?", [schema])


class _FullSupportQueries(_RealQueryQueries):
    """A dialect that declares support for every object type under test."""

    def supports_triggers(self) -> bool:
        return True

    def supports_materialized_views(self) -> bool:
        return True

    def supports_procedures(self) -> bool:
        return True

    def supports_functions(self) -> bool:
        return True

    def get_function_arguments_query(self, schema: str, function_name: str):
        # Not on the base class -- ``get_functions`` probes for it with
        # ``hasattr``, so declaring it here is what makes the per-function
        # argument lookup actually run.
        return ("SELECT * FROM pg_proc WHERE proname = ?", [function_name])


class _NullQueryQueries(_FullSupportQueries):
    """Declares support for everything but has no catalog query to offer.

    ``(None, [])`` is the documented "not supported" return for the four
    optional queries; views and sequences are overridden to the same shape
    to prove their guards hold too.
    """

    def get_views_query(self, schema: str):
        return (None, [])

    def get_sequences_query(self, schema: str):
        return (None, [])

    def get_triggers_query(self, schema: str, table: Optional[str] = None):
        return (None, [])

    def get_materialized_views_query(self, schema: str):
        return (None, [])

    def get_procedures_query(self, schema: str):
        return (None, [])

    def get_functions_query(self, schema: str):
        return (None, [])


def _declining(predicate: str) -> VendorMetadataQueries:
    """A dialect identical to ``_FullSupportQueries`` except that one
    capability predicate returns ``False``.

    Every query still returns real SQL and every other predicate is still
    ``True``, so the named predicate is the only thing that can produce an
    empty result -- which is what makes the assertion bite when it is
    removed.
    """

    class _Declining(_FullSupportQueries):
        pass

    setattr(_Declining, predicate, lambda self: False)
    return _Declining()


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


class _RecordingTracker:
    """Minimal stand-in for the introspector's result-tracking surface."""

    def __init__(self) -> None:
        self.errors: List[str] = []

    def _track_error(
        self, message, object_type=None, object_name=None, property_name=None, exception=None
    ):
        self.errors.append(f"{object_type}:{object_name}:{property_name}:{message}")

    def _track_warning(self, *args, **kwargs):
        pass

    def _track_object_status(self, *args, **kwargs):
        return None


class _StubProvider:
    def __init__(self, query_executor: Any) -> None:
        self.query_executor = query_executor


class _OpenConnection:
    closed = False


def _make(extractor_cls, query_executor, queries=None, dialect="postgresql", tracker=None):
    return extractor_cls(
        provider=_StubProvider(query_executor),
        connection=_OpenConnection(),
        metadata=object(),
        vendor_queries=_FullSupportQueries() if queries is None else queries,
        dialect=dialect,
        result_tracker=tracker,
    )


#: ``(extractor class, method name, capability predicate)`` for the six
#: schema-level extract methods this contract covers.
ALL_METHODS = [
    (ViewExtractor, "get_views", "supports_views"),
    (ViewExtractor, "get_materialized_views", "supports_materialized_views"),
    (SequenceExtractor, "get_sequences", "supports_sequences"),
    (TriggerExtractor, "get_triggers", "supports_triggers"),
    (ProcedureExtractor, "get_procedures", "supports_procedures"),
    (ProcedureExtractor, "get_functions", "supports_functions"),
]
_METHOD_IDS = [m for _, m, _ in ALL_METHODS]

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

    @pytest.mark.parametrize("extractor_cls, method, _pred", ALL_METHODS, ids=_METHOD_IDS)
    @pytest.mark.parametrize("exc", _READ_FAILURES, ids=lambda e: type(e).__name__)
    def test_read_failure_propagates(self, extractor_cls, method, _pred, exc):
        ext = _make(extractor_cls, _RaisingQueryExecutor(exc))

        with pytest.raises(type(exc)):
            getattr(ext, method)("public")

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


class TestReadFailureIsRecordedBeforeReRaising:
    """Propagating must not cost callers that enabled result tracking the
    error they used to get. ``enable_result_tracking()`` is a public
    extension point on the introspector; a caller using it needs the
    failure counted in its quality verdict *and* surfaced, so the handler
    records and then re-raises rather than doing one or the other."""

    @pytest.mark.parametrize(
        "extractor_cls, method, object_type",
        [
            (ViewExtractor, "get_views", "views"),
            (SequenceExtractor, "get_sequences", "sequences"),
            (TriggerExtractor, "get_triggers", "triggers"),
            (ProcedureExtractor, "get_procedures", "procedures"),
            (ProcedureExtractor, "get_functions", "functions"),
        ],
        ids=["views", "sequences", "triggers", "procedures", "functions"],
    )
    def test_error_is_tracked_and_the_exception_still_escapes(
        self, extractor_cls, method, object_type
    ):
        tracker = _RecordingTracker()
        exc = RuntimeError("permission denied")
        ext = _make(extractor_cls, _RaisingQueryExecutor(exc), tracker=tracker)

        with pytest.raises(RuntimeError, match="permission denied"):
            getattr(ext, method)("public")

        assert len(tracker.errors) == 1, "the failure must still reach the result tracker"
        assert object_type in tracker.errors[0]

    def test_materialized_views_records_nothing_by_design(self):
        """``get_materialized_views`` is the one method whose handler never
        had a result-tracker call. It is left that way rather than gaining
        one as a side effect of this change -- noted here so the asymmetry
        is deliberate and visible instead of looking like an oversight."""
        tracker = _RecordingTracker()
        ext = _make(ViewExtractor, _RaisingQueryExecutor(RuntimeError("boom")), tracker=tracker)

        with pytest.raises(RuntimeError):
            ext.get_materialized_views("public")

        assert tracker.errors == []


# ---------------------------------------------------------------------------
# Genuinely empty is still a clean empty list
# ---------------------------------------------------------------------------


class TestGenuinelyEmptySchemaReturnsEmptyList:
    """The query runs and returns zero rows -- that, not an exception, is
    how "this schema has none of these" is represented."""

    @pytest.mark.parametrize("extractor_cls, method, _pred", ALL_METHODS, ids=_METHOD_IDS)
    def test_zero_rows_returns_empty_list(self, extractor_cls, method, _pred):
        executor = _RowsQueryExecutor([])
        ext = _make(extractor_cls, executor)

        assert getattr(ext, method)("public") == []
        assert executor.calls, "the query should actually have been attempted"


# ---------------------------------------------------------------------------
# Each decline route, pinned separately
# ---------------------------------------------------------------------------


class TestCapabilityPredicateIsHonoured:
    """A dialect whose ``supports_*()`` says ``False`` must be declined by
    that predicate alone.

    Each case uses a queries class with a real, non-``None`` query for
    every object type, so the ``if not sql`` guard cannot substitute for
    the predicate: delete the predicate check and the raising executor is
    reached. For triggers, materialized views, procedures and functions
    ``False`` is the base-class default and how an engine lacking the
    object type declines. For views and sequences the default is ``True``
    and no bundle in this repository overrides it -- the predicate is a
    documented extension point there, and this pins that it is honoured
    if a bundle ever uses it."""

    @pytest.mark.parametrize("extractor_cls, method, predicate", ALL_METHODS, ids=_METHOD_IDS)
    def test_declining_predicate_short_circuits_before_any_round_trip(
        self, extractor_cls, method, predicate
    ):
        executor = _RaisingQueryExecutor(RuntimeError("must not be reached"))
        ext = _make(extractor_cls, executor, queries=_declining(predicate))

        assert getattr(ext, method)("public") == []
        assert executor.calls == []


class TestNullVendorQueryIsHonoured:
    """The other decline route: the dialect claims the capability but has
    no catalog query, so ``(None, [])`` comes back.

    ``get_views`` and ``get_sequences`` are included deliberately. The ABC
    declares a non-optional query for those two, so ``None`` is out of
    contract -- but before this contract existed they reached the driver
    with ``sql=None`` and the resulting ``TypeError`` was absorbed into
    ``[]`` by the removed handler. With the handler gone they would have
    started raising, so both now guard explicitly."""

    @pytest.mark.parametrize("extractor_cls, method, _pred", ALL_METHODS, ids=_METHOD_IDS)
    def test_null_query_short_circuits_before_any_round_trip(self, extractor_cls, method, _pred):
        executor = _RaisingQueryExecutor(RuntimeError("must not be reached"))
        ext = _make(extractor_cls, executor, queries=_NullQueryQueries())

        assert getattr(ext, method)("public") == []
        assert executor.calls == []


class TestNoVendorQueriesIsHonoured:
    """No catalog-query bundle registered for the dialect at all.

    This is the gate that actually fires in this repository: no plugin
    ships a concrete ``VendorMetadataQueries``, so every dialect declines
    here until an installed package registers one."""

    @pytest.mark.parametrize("extractor_cls, method, _pred", ALL_METHODS, ids=_METHOD_IDS)
    def test_dialect_without_vendor_queries_declines(self, extractor_cls, method, _pred):
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

        assert len(executor.calls) >= 2, "the per-view column query must have been attempted"
        assert [v.name for v in views] == ["v_orders"]
        assert views[0].columns == []

    def test_materialized_view_survives_a_failed_column_lookup(self):
        executor = _RowsQueryExecutor(
            [{"materialized_view_name": "mv_orders", "view_definition": "SELECT 1"}],
            RuntimeError("permission denied for information_schema.columns"),
        )
        ext = _make(ViewExtractor, executor)

        mviews = ext.get_materialized_views("public")

        assert len(executor.calls) >= 2, "the per-view column query must have been attempted"
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
