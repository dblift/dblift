"""Partial-result contract for :func:`introspect_schema`.

The ``get_X`` extractors raise when they cannot *read* an object type,
instead of returning ``[]`` and making an unreadable schema look like an
empty one. Left unhandled, that turns one unreadable object type into an
aborted introspection: the tables, columns, indexes and partitions
already collected are discarded, which is a worse outcome for the caller
than the swallow it replaced.

So the orchestrator collects per object type. A failure leaves that type
empty, records it, and lets every other type proceed.

The trap these tests exist to prevent: recording the failure *only* on
the result tracker. The tracker is populated only when a caller has
called ``enable_result_tracking()``, so a caller that never opted in
would get an empty list and no indication anything went wrong — the
original bug with an extra layer of indirection. Every case below is
therefore asserted twice, once for a caller that enabled tracking and
once for a caller that did not, and the visible-failure channel
(``result["failures"]``) is the one that must hold for both.
"""

from typing import Any, Dict, List

import pytest

from core.introspection._schema_orchestrator import introspect_schema

pytestmark = [pytest.mark.unit]


#: Every object type the orchestrator collects, with the ``si`` method
#: that produces it and the result key it populates.
COLLECTED_TYPES = [
    ("views", "get_views", "views", "view_count"),
    ("materialized_views", "get_materialized_views", "materialized_views", None),
    ("sequences", "get_sequences", "sequences", "sequence_count"),
    ("triggers", "get_triggers", "triggers", "trigger_count"),
    ("events", "get_events", "events", None),
    ("procedures", "get_procedures", "procedures", "procedure_count"),
    ("functions", "get_functions", "functions", "function_count"),
    ("packages", "get_packages", "packages", "package_count"),
    ("synonyms", "get_synonyms", "synonyms", "synonym_count"),
    ("user_defined_types", "get_user_defined_types", "user_defined_types", None),
    ("extensions", "get_extensions", "extensions", None),
]
_TYPE_IDS = [t[0] for t in COLLECTED_TYPES]


class _Log:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def info(self, msg):
        pass

    def debug(self, msg):
        pass

    def warning(self, msg):
        self.warnings.append(str(msg))

    def error(self, msg):
        self.errors.append(str(msg))


class _VendorQueries:
    """Declares support for everything the orchestrator gates on."""

    def supports_computed_columns(self):
        return False

    def supports_check_constraints(self):
        return False

    def supports_partitions(self):
        return False

    def supports_materialized_views(self):
        return True


class _Table:
    def __init__(self, name):
        self.name = name
        self.columns = ["c1", "c2"]
        self.constraints: List[Any] = []


class _Introspector:
    """A structurally-typed stand-in for ``SchemaIntrospector``.

    Every ``get_X`` returns one placeholder object, except the ones named
    in *failing*, which raise. ``track_results`` mirrors the real
    ``enable_result_tracking()`` opt-in: when off, ``_track_error``
    records nothing, exactly as on the real introspector.
    """

    def __init__(self, failing=(), track_results=False):
        self._failing = set(failing)
        self._track_results = track_results
        self.tracked: List[Dict[str, Any]] = []
        self.log = _Log()
        self.vendor_queries = _VendorQueries()

    def _track_error(self, message, object_type=None, object_name=None, **kwargs):
        if self._track_results:
            self.tracked.append({"message": message, "property": kwargs.get("property_name")})

    def _maybe(self, kind):
        if kind in self._failing:
            raise RuntimeError(f"permission denied reading {kind}")
        return [f"{kind}_1"]

    def get_tables(self, schema, include_views=False):
        if "tables" in self._failing:
            raise RuntimeError("permission denied reading tables")
        return [_Table("t1")]

    def enrich_columns_with_identity(self, schema, table, columns):
        pass

    def enrich_table_with_partition_scheme(self, schema, table, obj):
        pass

    def get_indexes(self, schema, table):
        if "indexes" in self._failing:
            raise RuntimeError("permission denied reading indexes")
        return ["ix_1"]

    def get_views(self, schema):
        return self._maybe("views")

    def get_materialized_views(self, schema):
        return self._maybe("materialized_views")

    def get_sequences(self, schema):
        return self._maybe("sequences")

    def get_triggers(self, schema):
        return self._maybe("triggers")

    def get_events(self, schema):
        return self._maybe("events")

    def get_procedures(self, schema):
        return self._maybe("procedures")

    def get_functions(self, schema):
        return self._maybe("functions")

    def get_packages(self, schema):
        return self._maybe("packages")

    def get_synonyms(self, schema):
        return self._maybe("synonyms")

    def get_user_defined_types(self, schema):
        return self._maybe("user_defined_types")

    def get_extensions(self):
        return self._maybe("extensions")


# ---------------------------------------------------------------------------
# Nothing failing: the contract must not fire spuriously
# ---------------------------------------------------------------------------


class TestCleanRun:
    def test_no_failures_key_is_empty_when_everything_reads(self):
        result = introspect_schema(_Introspector(), "public")

        assert result["failures"] == []
        assert result["table_count"] == 1
        assert result["view_count"] == 1
        assert result["sequence_count"] == 1

    def test_nothing_is_tracked_and_nothing_is_logged_as_error(self):
        si = _Introspector(track_results=True)

        introspect_schema(si, "public")

        assert si.tracked == []
        assert si.log.errors == []


# ---------------------------------------------------------------------------
# One type fails: everything else survives
# ---------------------------------------------------------------------------


class TestOneFailingTypeDoesNotAbortTheSnapshot:
    @pytest.mark.parametrize(
        "kind, _method, result_key, _count_key", COLLECTED_TYPES, ids=_TYPE_IDS
    )
    def test_other_object_types_are_still_present(self, kind, _method, result_key, _count_key):
        result = introspect_schema(_Introspector(failing=[kind]), "public")

        # The spine survives -- this is the whole point.
        assert result["table_count"] == 1
        assert result["total_columns"] == 2
        assert result["indexes"] == {"t1": ["ix_1"]}

        # Every *other* collected type still read normally.
        for other, _m, other_key, _c in COLLECTED_TYPES:
            if other == kind:
                continue
            assert result[other_key] == [f"{other}_1"], f"{other} was lost when {kind} failed"

        # The failing one is empty.
        assert result[result_key] == []

    @pytest.mark.parametrize(
        "kind, _method, _result_key, _count_key", COLLECTED_TYPES, ids=_TYPE_IDS
    )
    def test_failure_is_visible_without_enabling_result_tracking(
        self, kind, _method, _result_key, _count_key
    ):
        """The channel that matters. A caller that never called
        ``enable_result_tracking()`` must still be able to tell an
        unreadable object type from an absent one."""
        si = _Introspector(failing=[kind], track_results=False)

        result = introspect_schema(si, "public")

        assert si.tracked == [], "precondition: this caller did not opt into tracking"
        assert [f["object_type"] for f in result["failures"]] == [kind]
        assert "permission denied" in result["failures"][0]["error"]
        assert result["failures"][0]["exception_type"] == "RuntimeError"

    @pytest.mark.parametrize(
        "kind, _method, _result_key, _count_key", COLLECTED_TYPES, ids=_TYPE_IDS
    )
    def test_failure_is_also_recorded_on_the_tracker_when_enabled(
        self, kind, _method, _result_key, _count_key
    ):
        si = _Introspector(failing=[kind], track_results=True)

        result = introspect_schema(si, "public")

        assert [t["property"] for t in si.tracked] == [kind]
        assert [f["object_type"] for f in result["failures"]] == [kind]

    @pytest.mark.parametrize(
        "kind, _method, _result_key, _count_key", COLLECTED_TYPES, ids=_TYPE_IDS
    )
    def test_failure_is_logged_at_error_level(self, kind, _method, _result_key, _count_key):
        si = _Introspector(failing=[kind])

        introspect_schema(si, "public")

        assert any(kind in line for line in si.log.errors)
        assert any("incomplete" in line for line in si.log.warnings)


class TestSeveralFailingTypes:
    def test_every_failure_is_recorded_and_the_rest_still_read(self):
        failing = ["views", "procedures", "extensions"]
        si = _Introspector(failing=failing, track_results=True)

        result = introspect_schema(si, "public")

        assert sorted(f["object_type"] for f in result["failures"]) == sorted(failing)
        assert sorted(t["property"] for t in si.tracked) == sorted(failing)
        assert result["sequences"] == ["sequences_1"]
        assert result["functions"] == ["functions_1"]
        assert result["table_count"] == 1


# ---------------------------------------------------------------------------
# The deliberate exception: the table phase still aborts
# ---------------------------------------------------------------------------


class TestTablePhaseStillAborts:
    """Columns, indexes and partitions all hang off the table list, so a
    snapshot that could not read tables has nothing partial to return.
    This asymmetry is deliberate; it is pinned so it reads that way."""

    def test_table_read_failure_propagates(self):
        with pytest.raises(RuntimeError, match="permission denied reading tables"):
            introspect_schema(_Introspector(failing=["tables"]), "public")

    def test_index_read_failure_propagates(self):
        with pytest.raises(RuntimeError, match="permission denied reading indexes"):
            introspect_schema(_Introspector(failing=["indexes"]), "public")
