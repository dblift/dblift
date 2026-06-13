"""BUG-01/BUG-02 regression: PostgreSQL snapshot queries are de-duplicated.

**BUG-01 (High)**: ``get_sequences_query`` joined ``pg_sequences`` with
``pg_class`` without a schema predicate on the ``pg_sequences`` side. When a
sequence name (e.g. ``order_seq``) existed in multiple schemas, the join
returned one row per (ps × c-in-target-schema) pair, duplicating the sequence
in the export.

**BUG-02 (Medium)**: ``get_views_query`` captured ``relkind IN ('v', 'm')``
while ``get_materialized_views_query`` separately captured ``relkind = 'm'``.
The snapshot service calls both, so every materialized view was emitted
twice. ``get_views_query`` now restricts to ``relkind = 'v'``.
"""

from __future__ import annotations

import pytest

from db.plugins.postgresql.introspection.postgresql_queries import (
    PostgreSQLMetadataQueries,
)


@pytest.mark.unit
class TestPostgreSQLQueriesBUG01BUG02:
    def test_sequences_query_filters_pg_sequences_by_schema(self):
        """BUG-01: query must constrain ``ps.schemaname`` too, not just
        ``n.nspname``. Otherwise the join multiplies rows when the same
        sequence name lives in multiple schemas."""
        q = PostgreSQLMetadataQueries()
        sql, params = q.get_sequences_query("app")
        # Both sides of the join must be schema-filtered.
        assert "ps.schemaname = ?" in sql
        assert "n.nspname = ?" in sql
        # Two placeholders → two bind parameters.
        assert params == ["app", "app"]

    def test_sequences_query_placeholder_count_matches_params(self):
        """The count of ``?`` placeholders must equal the length of params."""
        q = PostgreSQLMetadataQueries()
        sql, params = q.get_sequences_query("public")
        assert sql.count("?") == len(params)

    def test_views_query_excludes_materialized_views(self):
        """BUG-02: ``get_views_query`` must NOT capture ``relkind = 'm'`` —
        that belongs to ``get_materialized_views_query``. Capturing both
        caused every materialized view to appear twice in the snapshot."""
        q = PostgreSQLMetadataQueries()
        sql, _ = q.get_views_query("app")
        assert "c.relkind = 'v'" in sql
        assert "c.relkind IN ('v', 'm')" not in sql
        assert "('v', 'm')" not in sql

    def test_materialized_views_query_still_captures_matviews(self):
        """Companion check: materialized views are still reachable via the
        dedicated query, so fixing BUG-02 does not drop them from snapshots."""
        q = PostgreSQLMetadataQueries()
        sql, _ = q.get_materialized_views_query("app")
        assert "c.relkind = 'm'" in sql
