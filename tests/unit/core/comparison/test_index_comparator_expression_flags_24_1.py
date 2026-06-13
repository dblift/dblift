"""Tests for SMELL-20-A: expression_flags[0] is True → bool() fix (story 24-1)."""

import pytest

from core.comparison.index_comparator import IndexComparator
from core.sql_model.index import Index

pytestmark = [pytest.mark.unit]


def _make_index(flags):
    return Index(
        name="idx_test",
        table_name="users",
        columns=["LOWER(email)"],
        expression_flags=flags,
        unique=False,
        dialect="postgresql",
    )


class TestIndexComparatorExpressionFlagsJdbcTypes:
    """AC — JDBC-returned integer/truthy flags must be treated as expression flags (SMELL-20-A)."""

    def setup_method(self):
        self.comparator = IndexComparator()

    def test_integer_1_flag_treated_as_expression(self):
        """expression_flags=[1] (JDBC integer) must be treated as expression index."""
        idx_a = _make_index([1])
        idx_b = _make_index([1])
        # Same expression — should not diff when both are treated as expressions
        idx_b.columns = ["lower(email)"]
        diff = self.comparator.compare_indexes(idx_a, idx_b, "postgresql")
        # If integer 1 is recognised as expression, expressions are normalised → no diff
        assert diff is None or not diff.has_diffs

    def test_bool_true_flag_still_works(self):
        """expression_flags=[True] (pre-existing boolean) must still be treated as expression."""
        idx_a = _make_index([True])
        idx_b = _make_index([True])
        idx_b.columns = ["lower(email)"]
        diff = self.comparator.compare_indexes(idx_a, idx_b, "postgresql")
        assert diff is None or not diff.has_diffs
