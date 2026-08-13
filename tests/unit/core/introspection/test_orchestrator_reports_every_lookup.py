"""Every lookup the orchestrator documents must actually report failure.

``_schema_orchestrator`` tells callers that ``result["failures"]`` is
complete — that an empty value is only meaningful once ``failures`` has
been checked. That promise is worth less than nothing if some lookups
still absorb their own errors: an empty ``failures`` would then *certify*
a completeness nothing verified, which is worse than the original silence
because a caller following the documented rule is actively misled.

The existing partial-result tests drive a duck-typed double that
implements ``get_X`` directly, so they never execute the real extractor
bodies and cannot see a handler that swallows inside one. This module
therefore builds a **real** :class:`BaseIntrospector` with its real
extractors and a real ``VendorMetadataQueries`` bundle, fakes only the
driver round trip, makes every catalog query fail, and asserts that all
17 documented lookups are reported.

It is deliberately written as a census rather than a list of individual
cases: a lookup added later that forgets to propagate shows up here as a
missing entry, without anyone remembering to add a test for it.
"""

from typing import Any, List, Optional

import pytest

from core.introspection.base_introspector import BaseIntrospector
from core.introspection.vendor_queries_base import VendorMetadataQueries

pytestmark = [pytest.mark.unit]


#: Every lookup ``_schema_orchestrator`` documents as collected.
SCHEMA_LEVEL = [
    "views",
    "materialized_views",
    "sequences",
    "triggers",
    "events",
    "procedures",
    "functions",
    "packages",
    "synonyms",
    "user_defined_types",
    "extensions",
]
PER_TABLE = [
    "indexes",
    "partitions",
    "check_constraints",
    "computed_columns",
    "identity_columns",
    "partition_scheme",
]
ALL_LOOKUPS = SCHEMA_LEVEL + PER_TABLE


class _EverythingQueries(VendorMetadataQueries):
    """Declares support for every object type, with a real query for each."""

    def _q(self, *_a, **_k):
        return ("SELECT 1", [])

    # abstract surface
    get_check_constraints_query = _q
    get_sequences_query = _q
    get_views_query = _q
    get_view_definition_query = _q
    get_indexes_query = _q
    # optional queries
    get_triggers_query = _q
    get_materialized_views_query = _q
    get_procedures_query = _q
    get_functions_query = _q
    get_events_query = _q
    get_packages_query = _q
    get_synonyms_query = _q
    get_user_defined_types_query = _q
    get_extensions_query = _q
    get_computed_columns_query = _q
    get_identity_columns_query = _q
    get_table_partitions_query = _q
    get_partition_scheme_query = _q
    get_tables_query = _q
    get_columns_query = _q

    def __getattr__(self, name):
        # Any *_query we did not name above still returns a real query.
        # supports_*() cannot be handled here: the ABC *defines* those
        # methods, so __getattr__ is never consulted for them -- they are
        # forced True below instead.
        if name.endswith("_query"):
            return self._q
        raise AttributeError(name)


# Force every capability predicate to True. Done by reflection rather than
# by listing them, so a predicate added to the ABC later is covered here
# without anyone remembering to update this fixture.
for _name in dir(VendorMetadataQueries):
    if _name.startswith("supports_"):
        setattr(_EverythingQueries, _name, (lambda *a, **k: True))


class _FailingExecutor:
    """The driver: every catalog read fails, as for a role with no grants."""

    def execute_query(self, connection, query, params=None):
        raise RuntimeError("permission denied for catalog")


class _Connection:
    closed = False


class _Config:
    class database:
        type = "postgresql"


class _Provider:
    config = _Config()

    def __init__(self):
        self.query_executor = _FailingExecutor()
        self.connection = _Connection()

    def create_connection(self):
        return self.connection


class _Table:
    """One already-discovered table, so the per-table loop runs."""

    def __init__(self, name="orders"):
        self.name = name
        self.columns: List[Any] = []
        self.constraints: List[Any] = []


class _Log:
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def info(self, m):
        pass

    def debug(self, m):
        pass

    def warning(self, m):
        self.warnings.append(str(m))

    def error(self, m):
        self.errors.append(str(m))


def _introspector(track: bool = False) -> BaseIntrospector:
    """A real BaseIntrospector with real extractors and a failing driver.

    Only ``get_tables`` is stubbed, so the table list exists and the
    per-table loop runs; everything else goes through the real extractor
    code paths.
    """
    si = BaseIntrospector(provider=_Provider(), use_vendor_queries=False)
    si.log = _Log()
    si.vendor_queries = _EverythingQueries()
    si.catalog_queries = si.vendor_queries
    si.connection = _Connection()
    si.metadata = object()
    si.get_tables = lambda schema, include_views=False: [_Table()]  # type: ignore[method-assign]
    if track:
        si.enable_result_tracking()
    return si


def _reported(result) -> set:
    return {f["object_type"] for f in result["failures"]}


class TestEveryDocumentedLookupIsReported:
    def test_no_lookup_fails_silently(self):
        """The census. Every entry in ALL_LOOKUPS must appear in
        ``failures`` when its catalog read fails."""
        si = _introspector()

        result = si.introspect_schema("public")

        missing = sorted(set(ALL_LOOKUPS) - _reported(result))
        assert missing == [], f"these lookups failed silently: {missing}"

    @pytest.mark.parametrize("lookup", ALL_LOOKUPS)
    def test_lookup_is_reported_individually(self, lookup):
        si = _introspector()

        result = si.introspect_schema("public")

        assert lookup in _reported(result)

    def test_the_snapshot_is_not_aborted(self):
        si = _introspector()

        result = si.introspect_schema("public")  # must not raise

        assert result["table_count"] == 1
        assert [t.name for t in result["tables"]] == ["orders"]

    def test_counts_are_zero_but_failures_explains_why(self):
        """The pairing that makes the documented rule true: the counts a
        caller reads look exactly like an empty schema, and ``failures``
        is what distinguishes that from an unreadable one."""
        si = _introspector()

        result = si.introspect_schema("public")

        assert result["view_count"] == 0
        assert result["extension_count"] == 0
        assert result["synonym_count"] == 0
        assert result["failures"], "an empty failures list here would be a false all-clear"

    def test_per_table_entries_name_the_table(self):
        si = _introspector()

        result = si.introspect_schema("public")

        for entry in result["failures"]:
            if entry["object_type"] in PER_TABLE:
                assert entry["object_name"] == "orders"
            else:
                assert entry["object_name"] == "public"

    def test_object_name_is_unambiguous_because_the_two_sets_are_disjoint(self):
        """``object_name`` means "table" for one set of ``object_type``
        values and "schema" for the other, which is only readable because
        no value appears in both."""
        assert set(SCHEMA_LEVEL).isdisjoint(PER_TABLE)

    def test_failures_are_also_tracked_when_the_caller_opted_in(self):
        si = _introspector(track=True)

        si.introspect_schema("public")
        tracked = si.get_result()

        assert tracked is not None
        assert tracked.success is False
        properties = {issue.property_name for issue in tracked.errors}
        assert set(ALL_LOOKUPS).issubset(properties)

    def test_every_failure_is_logged_at_error_level(self):
        si = _introspector()

        si.introspect_schema("public")

        for lookup in ALL_LOOKUPS:
            assert any(
                f"Could not read {lookup} for" in line for line in si.log.errors
            ), f"{lookup} was not logged"


class TestARaisingCapabilityPredicateIsCollectedNotFatal:
    """The capability predicate guarding a lookup is folded into the same
    ``_collect`` lambda as the lookup itself.

    ``supports_*()`` is nominally a static fact about a dialect, but a
    catalog-query bundle is free to derive it — from a server version
    probe, say — so it can raise. Left outside ``_collect`` it sat inside
    the orchestrator's outer handler, where one raising predicate aborted
    the whole snapshot and discarded every table and object type already
    read. Folding it in makes that one object type report a failure
    instead, which is the same rule the rest of the module follows."""

    PREDICATES = [
        ("supports_computed_columns", "computed_columns"),
        ("supports_partitions", "partitions"),
        ("supports_check_constraints", "check_constraints"),
        ("supports_materialized_views", "materialized_views"),
    ]

    @pytest.mark.parametrize("predicate, lookup", PREDICATES, ids=[p for p, _ in PREDICATES])
    def test_raising_predicate_is_reported_not_fatal(self, predicate, lookup):
        si = _introspector()

        def _boom(*_a, **_k):
            raise RuntimeError(f"{predicate} blew up")

        setattr(type(si.vendor_queries), predicate, _boom)
        try:
            result = si.introspect_schema("public")  # must not raise
        finally:
            setattr(type(si.vendor_queries), predicate, (lambda *a, **k: True))

        assert lookup in _reported(result)
        assert result["table_count"] == 1, "the snapshot survived"
        entry = next(f for f in result["failures"] if f["object_type"] == lookup)
        assert "blew up" in entry["error"]


class TestASuccessfulRunReportsNothing:
    """The census must not pass by reporting everything unconditionally."""

    def test_no_failures_when_the_driver_works(self):
        class _EmptyExecutor:
            def execute_query(self, connection, query, params=None):
                return []

        si = _introspector()
        si.provider.query_executor = _EmptyExecutor()

        result = si.introspect_schema("public")

        assert result["failures"] == []
        assert si.log.errors == []
