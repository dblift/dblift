"""
Tests for IndexComparator expression index handling.

This module tests that IndexComparator correctly handles expression indexes
by using normalize_expression() instead of normalize_identifier() for expressions.
"""

import pytest

from core.comparison.diff_models import DiffSeverity
from core.comparison.index_comparator import IndexComparator
from core.sql_model.index import Index

pytestmark = [pytest.mark.unit]


class TestIndexComparatorExpressionIndexes:
    """Test IndexComparator expression index handling."""

    def setup_method(self):
        """Set up test fixtures."""
        self.comparator = IndexComparator()

    def test_expression_index_comparison_uses_normalize_expression(self):
        """Test that expression indexes use normalize_expression() for comparison."""
        # Create two expression indexes with the same expression (different formatting)
        expected_index = Index(
            name="idx_email_lower",
            table_name="users",
            columns=["LOWER(email)"],
            expression_flags=[True],  # This is an expression
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        actual_index = Index(
            name="idx_email_lower",
            table_name="users",
            columns=["lower(email)"],  # Different case, should normalize to same
            expression_flags=[True],  # This is an expression
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        # Should match because expressions are normalized (case-insensitive)
        assert diff is None or not diff.has_diffs

    def test_expression_index_detects_different_expressions(self):
        """Test that different expressions are detected as different."""
        expected_index = Index(
            name="idx_name",
            table_name="users",
            columns=["LOWER(name)"],
            expression_flags=[True],
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        actual_index = Index(
            name="idx_name",
            table_name="users",
            columns=["UPPER(name)"],  # Different expression
            expression_flags=[True],
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.columns_changed is True

    def test_regular_index_uses_normalize_identifier(self):
        """Test that regular (non-expression) indexes use normalize_identifier()."""
        expected_index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            expression_flags=[False],  # Not an expression
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        actual_index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            expression_flags=[False],  # Not an expression
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        # Should match
        assert diff is None or not diff.has_diffs

    def test_mixed_index_with_expression_and_column(self):
        """Test index with both expression and regular column."""
        expected_index = Index(
            name="idx_mixed",
            table_name="users",
            columns=["LOWER(email)", "name"],
            expression_flags=[True, False],  # First is expression, second is column
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        actual_index = Index(
            name="idx_mixed",
            table_name="users",
            columns=["lower(email)", "name"],  # Expression normalized, column same
            expression_flags=[True, False],
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        # Should match because expression is normalized and column is same
        assert diff is None or not diff.has_diffs

    def test_expression_index_vs_regular_index_detected_as_different(self):
        """Test that expression index and regular index on same column are different."""
        expected_index = Index(
            name="idx_email",
            table_name="users",
            columns=["email"],
            expression_flags=[False],  # Regular column
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        actual_index = Index(
            name="idx_email",
            table_name="users",
            columns=["LOWER(email)"],
            expression_flags=[True],  # Expression
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.columns_changed is True
