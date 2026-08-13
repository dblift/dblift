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
    """Declares support for everything the orchestrator gates on, so all
    six per-table lookups actually run."""

    def supports_computed_columns(self):
        return True

    def supports_check_constraints(self):
        return True

    def supports_partitions(self):
        return True

    def supports_materialized_views(self):
        return True


class _Constraint:
    def __init__(self, name):
        self.name = name


class _Table:
    def __init__(self, name):
        self.name = name
        self.columns = ["c1", "c2"]
        self.constraints: List[Any] = []
        self.enriched: List[str] = []


#: Every per-table property the orchestrator collects.
PER_TABLE_PROPERTIES = [
    "computed_columns",
    "identity_columns",
    "check_constraints",
    "partition_scheme",
    "indexes",
    "partitions",
]


class _Introspector:
    """A structurally-typed stand-in for ``SchemaIntrospector``.

    Every ``get_X`` returns one placeholder object, except the ones named
    in *failing*, which raise. ``track_results`` mirrors the real
    ``enable_result_tracking()`` opt-in: when off, ``_track_error``
    records nothing, exactly as on the real introspector.
    """

    def __init__(self, failing=(), track_results=False, tables=("t1", "t2"), table_failures=()):
        self._failing = set(failing)
        self._track_results = track_results
        #: ``{(property, table_name), ...}`` -- per-table lookups that raise.
        self._table_failures = set(table_failures)
        self._table_names = tuple(tables)
        self.tables = [_Table(n) for n in self._table_names]
        self.tracked: List[Dict[str, Any]] = []
        self.log = _Log()
        self.vendor_queries = _VendorQueries()

    def _maybe_table(self, prop, table, value):
        if (prop, table) in self._table_failures:
            raise RuntimeError(f"permission denied reading {prop} of {table}")
        return value

    def _track_error(
        self, message, object_type=None, object_name=None, property_name=None, exception=None
    ):
        if self._track_results:
            self.tracked.append(
                {
                    "message": message,
                    "property": property_name,
                    "object_type": object_type,
                    "object_name": object_name,
                }
            )

    def _maybe(self, kind):
        if kind in self._failing:
            raise RuntimeError(f"permission denied reading {kind}")
        return [f"{kind}_1"]

    def get_tables(self, schema, include_views=False):
        if "tables" in self._failing:
            raise RuntimeError("permission denied reading tables")
        return self.tables

    def _table_by_name(self, name):
        return next(t for t in self.tables if t.name == name)

    def enrich_columns_with_computed(self, schema, table, columns):
        self._maybe_table("computed_columns", table, None)
        self._table_by_name(table).enriched.append("computed_columns")

    def enrich_columns_with_identity(self, schema, table, columns):
        self._maybe_table("identity_columns", table, None)
        self._table_by_name(table).enriched.append("identity_columns")

    def enrich_table_with_partition_scheme(self, schema, table, obj):
        self._maybe_table("partition_scheme", table, None)
        self._table_by_name(table).enriched.append("partition_scheme")

    def get_check_constraints(self, schema, table):
        return self._maybe_table("check_constraints", table, [_Constraint(f"ck_{table}")])

    def get_table_partitions(self, schema, table):
        return self._maybe_table("partitions", table, [f"part_{table}"])

    def get_indexes(self, schema, table):
        if "indexes" in self._failing:
            raise RuntimeError("permission denied reading indexes")
        return self._maybe_table("indexes", table, [f"ix_{table}"])

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
        assert result["table_count"] == 2
        assert result["view_count"] == 1
        assert result["sequence_count"] == 1
        assert result["indexes"] == {"t1": ["ix_t1"], "t2": ["ix_t2"]}

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
        assert result["table_count"] == 2
        assert result["total_columns"] == 4
        assert result["indexes"] == {"t1": ["ix_t1"], "t2": ["ix_t2"]}

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
        assert (
            result["failures"][0]["object_name"] == "public"
        ), "schema-level entries name the schema"
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
        assert result["table_count"] == 2


# ---------------------------------------------------------------------------
# One unreadable table property: that table keeps its row, the rest are whole
# ---------------------------------------------------------------------------


class TestOneFailingTableDoesNotAbortTheSnapshot:
    """The finer-grained half of the same rule. Before this, one table
    whose indexes could not be read killed the entire introspection and
    discarded every table already collected -- for indexes specifically
    that was worse than the silent ``[]`` it replaced."""

    @pytest.mark.parametrize("prop", PER_TABLE_PROPERTIES)
    def test_every_other_table_is_still_read_in_full(self, prop):
        si = _Introspector(tables=("t1", "t2", "t3"), table_failures=[(prop, "t2")])

        result = introspect_schema(si, "public")

        # All three tables are present -- the failing one has not been dropped.
        assert [t.name for t in result["tables"]] == ["t1", "t2", "t3"]
        assert result["table_count"] == 3

        # The healthy tables are complete.
        for name in ("t1", "t3"):
            table = si._table_by_name(name)
            assert result["indexes"][name] == [f"ix_{name}"]
            assert result["partitions"][name] == [f"part_{name}"]
            assert [c.name for c in table.constraints] == [f"ck_{name}"]
            assert set(table.enriched) == {
                "computed_columns",
                "identity_columns",
                "partition_scheme",
            }

    @pytest.mark.parametrize("prop", PER_TABLE_PROPERTIES)
    def test_the_failing_table_keeps_its_row_with_that_property_empty(self, prop):
        si = _Introspector(tables=("t1", "t2"), table_failures=[(prop, "t2")])

        result = introspect_schema(si, "public")

        t2 = si._table_by_name("t2")
        assert t2 in result["tables"]
        if prop == "indexes":
            assert result["indexes"]["t2"] == []
        elif prop == "partitions":
            assert "t2" not in result["partitions"]
        elif prop == "check_constraints":
            assert t2.constraints == []
        else:
            assert prop not in t2.enriched
        # ...and nothing else about that table was lost.
        if prop != "indexes":
            assert result["indexes"]["t2"] == ["ix_t2"]

    @pytest.mark.parametrize("prop", PER_TABLE_PROPERTIES)
    def test_failure_names_the_table_and_is_visible_without_tracking(self, prop):
        """Without this, an operator sees an empty index list for one
        table and cannot tell which table was unreadable, or that any
        were -- the original bug at table granularity."""
        si = _Introspector(tables=("t1", "t2"), table_failures=[(prop, "t2")], track_results=False)

        result = introspect_schema(si, "public")

        assert si.tracked == [], "precondition: this caller did not opt into tracking"
        assert len(result["failures"]) == 1
        entry = result["failures"][0]
        assert entry["object_type"] == prop
        assert entry["object_name"] == "t2", "per-table entries name the table"
        assert entry["exception_type"] == "RuntimeError"
        assert "permission denied" in entry["error"]

    @pytest.mark.parametrize("prop", PER_TABLE_PROPERTIES)
    def test_failure_is_also_recorded_on_the_tracker_when_enabled(self, prop):
        si = _Introspector(tables=("t1", "t2"), table_failures=[(prop, "t2")], track_results=True)

        introspect_schema(si, "public")

        assert len(si.tracked) == 1
        assert si.tracked[0]["property"] == prop
        assert si.tracked[0]["object_type"] == "table"
        assert si.tracked[0]["object_name"] == "t2"

    def test_the_same_property_failing_on_several_tables_is_reported_per_table(self):
        si = _Introspector(
            tables=("t1", "t2", "t3"),
            table_failures=[("indexes", "t1"), ("indexes", "t3")],
        )

        result = introspect_schema(si, "public")

        assert sorted(f["object_name"] for f in result["failures"]) == ["t1", "t3"]
        assert all(f["object_type"] == "indexes" for f in result["failures"])
        assert result["indexes"] == {"t1": [], "t2": ["ix_t2"], "t3": []}
        # The summary line names the kind once, not once per table.
        assert any("indexes" in w and "2 failure(s)" in w for w in si.log.warnings)

    def test_schema_level_and_per_table_failures_share_one_list(self):
        si = _Introspector(
            failing=["views"], tables=("t1", "t2"), table_failures=[("indexes", "t2")]
        )

        result = introspect_schema(si, "public")

        assert sorted((f["object_type"], f["object_name"]) for f in result["failures"]) == [
            ("indexes", "t2"),
            ("views", "public"),
        ]
        assert all(
            set(f) == {"object_type", "object_name", "error", "exception_type"}
            for f in result["failures"]
        ), "one list, one shape, one reader"

    def test_a_failing_table_property_does_not_abort_the_run(self):
        si = _Introspector(tables=("t1", "t2"), table_failures=[("indexes", "t2")])

        result = introspect_schema(si, "public")  # must not raise

        assert result["view_count"] == 1
        assert result["sequence_count"] == 1
        assert result["total_indexes"] == 1


# ---------------------------------------------------------------------------
# The deliberate exception: the table phase still aborts
# ---------------------------------------------------------------------------


class TestTableDiscoveryStillAborts:
    """Every per-table property hangs off the table list, so a snapshot
    that could not read *tables* has nothing partial to return. Table
    discovery is the one lookup that still aborts; this asymmetry is
    deliberate and pinned so it reads that way."""

    def test_table_discovery_failure_propagates(self):
        with pytest.raises(RuntimeError, match="permission denied reading tables"):
            introspect_schema(_Introspector(failing=["tables"]), "public")
