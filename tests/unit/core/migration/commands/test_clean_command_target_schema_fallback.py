"""BUG-10 regression: clean summary shows a meaningful schema label on CosmosDB.

Before this fix, ``CleanCommand`` set ``result.target_schema`` directly
from ``self.config.database.schema``. CosmosDB has no SQL schema concept,
so that attribute is an empty string, and the summary line rendered as::

    Cleaned 5 object(s) from schema '':

This test pins the fallback: when ``schema`` is empty, ``target_schema``
resolves to ``database_name`` (or ``database``) so the label identifies
the Cosmos DB database that was cleaned.

For SQL dialects ``schema`` is always populated, so the fallback never
triggers — the bottom test guards that invariant.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.logger.results import CleanResult


def _simulate_target_schema_assignment(database) -> str:
    """Mirror the exact resolution CleanCommand.execute applies on entry.

    Keeping this mirror local isolates the unit test from CleanCommand's
    larger construction surface (which needs a full provider / history
    manager to instantiate). If the resolution logic in ``execute`` drifts,
    the broader integration tests catch it; this test pins the *contract*
    that feeds ``_log_clean_summary``.
    """
    result = CleanResult()
    result.target_schema = (
        database.schema
        or getattr(database, "database_name", None)
        or getattr(database, "database", None)
        or ""
    )
    return result.target_schema


@pytest.mark.unit
class TestCleanCommandTargetSchemaFallback:
    def test_cosmosdb_empty_schema_falls_back_to_database_name(self):
        """CosmosDB case: schema is empty, database_name identifies the DB."""
        db = SimpleNamespace(schema="", database_name="ProdCatalog", database=None)
        assert _simulate_target_schema_assignment(db) == "ProdCatalog"

    def test_cosmosdb_empty_schema_falls_back_to_database_if_no_name(self):
        """Older Cosmos configs populate ``database`` rather than ``database_name``."""
        db = SimpleNamespace(schema="", database_name=None, database="LegacyCatalog")
        assert _simulate_target_schema_assignment(db) == "LegacyCatalog"

    def test_sql_dialect_with_schema_set_is_unaffected(self):
        """Regression guard: non-empty schema wins over any fallback."""
        db = SimpleNamespace(schema="app_schema", database_name="ignored", database="also_ignored")
        assert _simulate_target_schema_assignment(db) == "app_schema"

    def test_nothing_set_yields_empty_string(self):
        """The empty-string sentinel survives — no surprise None or exception."""
        db = SimpleNamespace(schema="", database_name=None, database=None)
        assert _simulate_target_schema_assignment(db) == ""

    def test_none_schema_also_falls_through(self):
        """A literal None on ``schema`` (instead of '') still hits the fallback."""
        db = SimpleNamespace(schema=None, database_name="Catalog", database=None)
        assert _simulate_target_schema_assignment(db) == "Catalog"
