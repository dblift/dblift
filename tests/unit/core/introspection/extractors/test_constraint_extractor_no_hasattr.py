"""Story 16-13 — vérification suppression guards hasattr redondants dans constraint_extractor."""

import inspect
from unittest.mock import MagicMock

import pytest

from core.introspection.extractors.constraint_extractor import ConstraintExtractor


def _make_extractor(dialect="oracle", vendor_queries=None):
    """Build a ConstraintExtractor with mock dependencies."""
    provider = MagicMock()
    provider.config.database.type = dialect
    provider.query_executor = MagicMock()
    if vendor_queries is None:
        vendor_queries = MagicMock()
        vendor_queries.get_foreign_keys_query.return_value = ("SELECT fk", [])
    connection = MagicMock()
    metadata = MagicMock()
    extractor = ConstraintExtractor(
        provider=provider,
        connection=connection,
        metadata=metadata,
        vendor_queries=vendor_queries,
        dialect=dialect,
    )
    extractor.ensure_metadata = MagicMock()
    return extractor


@pytest.mark.unit
class TestConstraintExtractorNoHasattr:
    """Vérifie que les 5 guards hasattr(constraint, ...) ont été supprimés (SIMP-17)."""

    def test_get_foreign_keys_no_hasattr_reference_schema(self):
        """AC#8.1 — hasattr(constraint, 'reference_schema') supprimé de get_foreign_keys."""
        source = inspect.getsource(ConstraintExtractor.get_foreign_keys)
        assert (
            'hasattr(constraint, "reference_schema")' not in source
        ), "hasattr(constraint, 'reference_schema') encore présent dans get_foreign_keys"

    def test_get_check_constraints_no_hasattr_constraint_attrs(self):
        """AC#8.2 — 4 guards hasattr supprimés de get_check_constraints."""
        source = inspect.getsource(ConstraintExtractor.get_check_constraints)
        for attr in ("is_deferrable", "initially_deferred", "is_enabled", "is_validated"):
            assert (
                f'hasattr(constraint, "{attr}")' not in source
            ), f"hasattr(constraint, '{attr}') encore présent dans get_check_constraints"

    def test_vendor_queries_hasattr_removed_dialect_guard_in_quirks(self):
        """Story 20-18 + H.2 — ``hasattr`` is gone from the extractor and the
        DB2 dialect gate moved to :class:`Db2Quirks.fetch_unique_constraints`."""
        source = inspect.getsource(ConstraintExtractor._get_unique_constraints_via_vendor_queries)
        assert (
            "hasattr" not in source
        ), "hasattr vendor_queries still present — should have been removed by story 20-18"

        # After H.2 the dialect gate lives on Db2Quirks, not the extractor.
        from db.plugins.db2.quirks import Db2Quirks

        quirks_source = inspect.getsource(Db2Quirks.fetch_unique_constraints)
        assert (
            "_get_unique_constraints_via_vendor_queries" in quirks_source
        ), "Db2Quirks.fetch_unique_constraints must delegate to the DB2 SYSCAT path"

    def test_get_foreign_keys_assigns_reference_schema_directly(self):
        """AC#1 behavioral — reference_schema est assigné directement (sans guard hasattr)."""
        extractor = _make_extractor(dialect="postgresql")
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "name": "fk_orders_users",
                "column_name": "user_id",
                "ref_column": "id",
                "ref_table": "users",
                "ref_schema": "public",
                "on_delete": "NO ACTION",
                "on_update": "NO ACTION",
            }
        ]

        constraints = extractor.get_foreign_keys("myschema", "orders")

        assert len(constraints) == 1
        assert constraints[0].reference_schema == "public"

    def test_get_check_constraints_assigns_deferrable_directly(self):
        """AC#2/AC#3 behavioral — is_deferrable et initially_deferred assignés sans guard hasattr."""
        vendor_queries = MagicMock()
        vendor_queries.supports_check_constraints.return_value = True
        vendor_queries.get_check_constraints_query.return_value = ("SELECT 1", [])
        extractor = _make_extractor(dialect="oracle", vendor_queries=vendor_queries)
        extractor.provider.query_executor.execute_query.return_value = [
            {
                "constraint_name": "chk_age",
                "constraint_definition": "age > 0",
                "is_deferrable": "YES",
                "initially_deferred": "NO",
            }
        ]

        constraints = extractor.get_check_constraints("myschema", "employees")

        assert len(constraints) == 1
        assert constraints[0].is_deferrable is True
        assert constraints[0].initially_deferred is False
