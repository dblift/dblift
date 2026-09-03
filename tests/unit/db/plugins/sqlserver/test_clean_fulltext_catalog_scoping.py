"""Regression test: fulltext-catalog enumeration must be scoped to the
target schema, not enumerate every catalog in the database.

Full-text catalogs have no ``schema_id`` of their own, but a catalog is
only ever populated by full-text indexes, and every full-text index
belongs to a table, and every table belongs to a schema. So a catalog
can — and must — be scoped indirectly: via
``sys.fulltext_indexes.object_id -> sys.tables.schema_id -> sys.schemas``.

Without that scoping, ``clean --clean-enabled`` on one schema enumerates
(and attempts to drop) full-text catalogs that belong to *other* schemas
in the same database. ``DROP FULLTEXT CATALOG`` does not cascade — it
fails outright if any full-text index still references the catalog — so
in any database with more than one schema, cleaning schema A while schema
B has its own full-text catalog spuriously fails the clean of A, solely
because of an object clean was never supposed to touch.
"""

from unittest.mock import MagicMock

import pytest

from dblift.db.plugins.sqlserver.sqlserver.schema_operations import SqlServerSchemaOperations


def _make_two_schema_query_executor():
    """Simulate a database with two schemas, each owning its own full-text
    catalog via a full-text index on a table in that schema.

    - schema "dbo" has table "orders", fulltext-indexed into catalog "dbo_catalog".
    - schema "reporting" has table "audit_logs", fulltext-indexed into catalog
      "reporting_catalog".

    A correctly *scoped* fulltext-catalog query (joining through
    sys.fulltext_indexes -> sys.tables -> sys.schemas, filtered by the
    schema param) returns only the catalog owned by the requested schema.
    An *unscoped* query (bare ``SELECT ... FROM sys.fulltext_catalogs``)
    returns every catalog in the database regardless of schema — this is
    what real SQL Server would do, since catalogs are not schema-owned.
    """
    query_executor = MagicMock()
    query_executor.get_schema_qualified_name.side_effect = (
        lambda schema, name: f"[{schema}].[{name}]"
    )

    catalogs_by_schema = {
        "dbo": [{"catalog_name": "dbo_catalog"}],
        "reporting": [{"catalog_name": "reporting_catalog"}],
    }
    all_catalogs = [{"catalog_name": "dbo_catalog"}, {"catalog_name": "reporting_catalog"}]

    def execute_query(_connection, query, params=None):
        # Every other object type this step iterates over is irrelevant here.
        if "sys.foreign_keys" in query:
            return []
        if "INFORMATION_SCHEMA.VIEWS" in query:
            return []
        if "INFORMATION_SCHEMA.TABLES" in query:
            return []
        if "temporal_type" in query:
            return []
        if "INFORMATION_SCHEMA.ROUTINES" in query:
            return []
        if "sys.sequences" in query:
            return []
        if "sys.types" in query:
            return []
        if "sys.synonyms" in query:
            return []
        if "sys.fulltext_catalogs" in query:
            is_scoped_join = "sys.fulltext_indexes" in query and "sys.schemas" in query
            if is_scoped_join and params:
                return catalogs_by_schema.get(params[0], [])
            # Unscoped: a bare query against sys.fulltext_catalogs has no
            # way to filter by schema and genuinely returns every catalog
            # in the database, exactly like real SQL Server would.
            return all_catalogs
        raise AssertionError(f"Unexpected query: {query}")

    query_executor.execute_query.side_effect = execute_query
    return query_executor


@pytest.mark.unit
def test_enumerate_clean_candidates_does_not_enumerate_other_schemas_fulltext_catalog():
    """Cleaning "dbo" must not enumerate "reporting"'s full-text catalog."""
    connection = object()
    operations = SqlServerSchemaOperations(_make_two_schema_query_executor(), MagicMock())

    candidates = operations.enumerate_clean_candidates(connection, "dbo")

    catalog_names = {c.name for c in candidates if c.object_type == "fulltext_catalog"}

    assert catalog_names == {"dbo_catalog"}, (
        "enumerate_clean_candidates('dbo') must only enumerate full-text catalogs "
        f"owned by tables in the 'dbo' schema, got {catalog_names!r} — a catalog "
        "belonging only to another schema's tables must not be enumerated at all."
    )
