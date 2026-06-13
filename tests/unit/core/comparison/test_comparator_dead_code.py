import unittest
from unittest.mock import MagicMock

import pytest

from core.comparison.comparator import ObjectComparator
from core.comparison.type_normalizer import DataTypeNormalizer
from core.sql_model.table import Table
from core.sql_model.view import View

pytestmark = [pytest.mark.unit]


class TestObjectComparatorDeadCode(unittest.TestCase):
    """Tests verifying dead code removal from ObjectComparator (story 13-16).

    Updated in story 19-14: table_comparator was re-added to _COMPARATOR_REGISTRY
    in story 18-11 (lazy init via __getattr__), so hasattr now returns True.
    The test was updated to reflect this and to assert correct lazy-init behaviour.
    """

    def test_object_comparator_table_comparator_via_registry(self):
        """table_comparator is NOT pre-instantiated in __init__ but IS accessible via __getattr__ registry (story 18-11)."""
        normalizer = MagicMock(spec=DataTypeNormalizer)
        comparator = ObjectComparator(normalizer)
        # Verify it's not pre-instantiated in __init__ (must check before first access)
        self.assertNotIn(
            "table_comparator",
            comparator.__dict__,
            "table_comparator should not be pre-instantiated in __init__",
        )
        # Now verify it IS accessible via _COMPARATOR_REGISTRY
        self.assertTrue(
            hasattr(comparator, "table_comparator"),
            "table_comparator should be available via _COMPARATOR_REGISTRY",
        )

    def test_object_comparator_has_no_view_comparator_attribute(self):
        normalizer = MagicMock(spec=DataTypeNormalizer)
        comparator = ObjectComparator(normalizer)
        self.assertFalse(
            hasattr(comparator, "view_comparator"),
            "view_comparator doit être supprimé (dead code)",
        )

    def test_compare_tables_still_works_after_dead_code_removal(self):
        normalizer = MagicMock(spec=DataTypeNormalizer)
        normalizer.normalize.side_effect = lambda x, d: x
        comparator = ObjectComparator(normalizer)
        table = Table(name="users", schema="public")
        result = comparator.compare_tables(table, table)
        self.assertIsNotNone(result)
        self.assertFalse(result.has_diffs, "Identical tables should produce no diff")
        self.assertEqual(result.missing_columns, [])
        self.assertEqual(result.extra_columns, [])
        self.assertEqual(result.modified_columns, [])

    def test_compare_views_still_works_after_dead_code_removal(self):
        normalizer = MagicMock(spec=DataTypeNormalizer)
        normalizer.normalize.side_effect = lambda x, d: x
        comparator = ObjectComparator(normalizer)
        view = View(name="v_users", schema="public", query="SELECT 1")
        # compare_views returns None when views are identical (no diff)
        result = comparator.compare_views(view, view)
        self.assertIsNone(result, "Identical views should produce no diff")


if __name__ == "__main__":
    unittest.main()
