"""``get_clean_preview`` must drop TimescaleDB continuous aggregates correctly.

A continuous aggregate's user-facing name is a genuine ``relkind='v'`` row in
PostgreSQL's catalog, so it appears in ``pg_views`` and never in
``pg_matviews``. Enumerating views from ``pg_views`` alone therefore emits
``DROP VIEW`` for it, which PostgreSQL rejects::

    cannot drop continuous aggregate using DROP VIEW
    HINT:  Use DROP MATERIALIZED VIEW to drop a continuous aggregate.

Because every drop runs in one transaction, that single rejection aborts the
transaction and every following object fails with ``InFailedSqlTransaction`` --
so one continuous aggregate leaves the whole schema, including dblift's own
history and lock tables, undropped.

``timescaledb_information`` does not exist on a stock PostgreSQL server, and
querying a missing relation aborts a PostgreSQL transaction outright. A
``try``/``except`` is therefore not a sufficient guard: enumeration shares the
transaction, so every later query fails too, each swallowed by its own
handler, and ``clean`` reports success having dropped nothing. That silent
no-op was reproduced against a live server before this fix was written, which
is why the lookup is gated on a catalog probe valid on every PostgreSQL
server, and why the no-TimescaleDB case is pinned down explicitly below.
"""

import unittest
from unittest.mock import MagicMock

from dblift.db.plugins.postgresql.postgresql.schema_operations import PostgreSqlSchemaOperations

#: Substring identifying the query that reads the aggregate list.
CAGG_FROM = "FROM timescaledb_information.continuous_aggregates"
#: Substring identifying the catalog probe that gates that read.
PROBE = "nspname = 'timescaledb_information'"


def _qx_with_results(results_by_query):
    """Build a query_executor mock returning rows keyed by query substring.

    Keys are matched longest-first so that a specific key cannot be shadowed
    by a shorter one that also occurs in the same statement. Every executed
    query is recorded on ``qx.executed_queries``.
    """
    qx = MagicMock()
    ordered = sorted(results_by_query.items(), key=lambda kv: -len(kv[0]))
    qx.executed_queries = []

    def _execute_query(connection, query, params=None):
        qx.executed_queries.append(query)
        for keyword, rows in ordered:
            if keyword in query:
                return rows
        return []

    qx.execute_query.side_effect = _execute_query
    qx.get_schema_qualified_name.side_effect = lambda s, n: f'"{s}"."{n}"'
    return qx


def _drop_sql_for(summary, name):
    """Return the DROP statement recorded for ``name``."""
    for obj, sql in zip(summary.objects, summary.statements):
        if obj.name == name:
            return sql
    raise AssertionError(f"no object named {name!r} in summary")


def _timescale_qx(extra=None):
    """Query executor for a schema holding one continuous aggregate."""
    results = {
        PROBE: [{"present": 1}],
        "pg_views": [{"view_name": "events_hourly"}, {"view_name": "plain_v"}],
        CAGG_FROM: [{"view_name": "events_hourly"}],
    }
    results.update(extra or {})
    return _qx_with_results(results)


class TestContinuousAggregateClassification(unittest.TestCase):
    def test_continuous_aggregate_uses_drop_materialized_view(self):
        # pg_views legitimately contains both the plain view and the
        # continuous aggregate; only the latter needs the other DROP verb.
        ops = PostgreSqlSchemaOperations(query_executor=_timescale_qx(), log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "dblift_test")

        self.assertEqual(
            _drop_sql_for(summary, "events_hourly"),
            'DROP MATERIALIZED VIEW IF EXISTS "dblift_test"."events_hourly" CASCADE',
        )
        self.assertEqual(
            _drop_sql_for(summary, "plain_v"),
            'DROP VIEW IF EXISTS "dblift_test"."plain_v" CASCADE',
        )

    def test_continuous_aggregate_recorded_as_materialized_view(self):
        ops = PostgreSqlSchemaOperations(query_executor=_timescale_qx(), log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "dblift_test")

        types = {o.name: o.object_type for o in summary.objects}
        self.assertEqual(types["events_hourly"], "materialized_view")
        self.assertEqual(types["plain_v"], "view")

    def test_continuous_aggregate_dropped_before_its_source_hypertable(self):
        # The aggregate depends on the hypertable, so it must stay ahead of
        # the tables phase in the enumeration order.
        qx = _timescale_qx({"pg_tables": [{"table_name": "events"}]})
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "dblift_test")

        names = [o.name for o in summary.objects]
        self.assertLess(names.index("events_hourly"), names.index("events"))

    def test_aggregate_lookup_is_scoped_to_the_requested_schema(self):
        # A same-named aggregate in another schema must not reclassify this
        # schema's plain view, so the lookup is parameterised by schema.
        qx = _timescale_qx()
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        ops.get_clean_preview(MagicMock(), "dblift_test")

        cagg_calls = [c for c in qx.execute_query.call_args_list if CAGG_FROM in c.args[1]]
        self.assertEqual(len(cagg_calls), 1, "aggregate lookup should run exactly once")
        self.assertEqual(cagg_calls[0].kwargs.get("params"), ["dblift_test"])

    def test_aggregate_name_matching_is_case_insensitive(self):
        # pg_views and the TimescaleDB catalog agree on case in practice, but
        # a mismatch must not silently fall back to the failing DROP verb.
        qx = _qx_with_results(
            {
                PROBE: [{"present": 1}],
                "pg_views": [{"view_name": "Events_Hourly"}],
                CAGG_FROM: [{"view_name": "events_hourly"}],
            }
        )
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "dblift_test")

        self.assertEqual(
            _drop_sql_for(summary, "Events_Hourly"),
            'DROP MATERIALIZED VIEW IF EXISTS "dblift_test"."Events_Hourly" CASCADE',
        )


class TestPlainPostgresqlUnaffected(unittest.TestCase):
    """Regression guard: stock PostgreSQL has no ``timescaledb_information``.

    Querying it there aborts the transaction, which would break ``clean`` for
    every non-TimescaleDB user -- strictly worse than the bug being fixed.
    """

    def test_no_aggregate_query_when_catalog_is_absent(self):
        qx = _qx_with_results({"pg_views": [{"view_name": "plain_v"}]})
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        ops.get_clean_preview(MagicMock(), "public")

        touched = [q for q in qx.executed_queries if CAGG_FROM in q]
        self.assertEqual(
            touched,
            [],
            "must not read timescaledb_information when the catalog is absent",
        )

    def test_probe_itself_is_valid_on_stock_postgresql(self):
        # The probe must not reference the relation whose existence it tests.
        qx = _qx_with_results({"pg_views": [{"view_name": "plain_v"}]})
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        ops.get_clean_preview(MagicMock(), "public")

        probes = [q for q in qx.executed_queries if PROBE in q]
        self.assertEqual(len(probes), 1, "expected exactly one catalog probe")
        self.assertNotIn(CAGG_FROM, probes[0])

    def test_plain_views_still_use_drop_view_without_timescaledb(self):
        qx = _qx_with_results(
            {
                "pg_views": [{"view_name": "plain_v"}],
                "pg_matviews": [{"matviewname": "plain_mv"}],
                "pg_tables": [{"table_name": "plain_t"}],
            }
        )
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "public")

        self.assertEqual(
            _drop_sql_for(summary, "plain_v"),
            'DROP VIEW IF EXISTS "public"."plain_v" CASCADE',
        )
        self.assertEqual(
            _drop_sql_for(summary, "plain_mv"),
            'DROP MATERIALIZED VIEW IF EXISTS "public"."plain_mv" CASCADE',
        )
        self.assertEqual(
            _drop_sql_for(summary, "plain_t"),
            'DROP TABLE IF EXISTS "public"."plain_t" CASCADE',
        )

    def test_extension_installed_but_no_aggregates_leaves_views_alone(self):
        qx = _qx_with_results(
            {
                PROBE: [{"present": 1}],
                CAGG_FROM: [],
                "pg_views": [{"view_name": "plain_v"}],
            }
        )
        ops = PostgreSqlSchemaOperations(query_executor=qx, log=MagicMock())

        summary = ops.get_clean_preview(MagicMock(), "public")

        self.assertEqual(
            _drop_sql_for(summary, "plain_v"),
            'DROP VIEW IF EXISTS "public"."plain_v" CASCADE',
        )


if __name__ == "__main__":
    unittest.main()
