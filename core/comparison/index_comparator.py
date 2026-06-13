"""Index Comparator for Drift Detection.

This module provides the IndexComparator class which compares index objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import List, Optional, Sequence

from core.comparison.comparison_utils import normalize_expression, normalize_identifier
from core.comparison.diff_models import IndexDiff
from core.sql_model.index import Index
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class IndexComparator:
    """Compares index objects and generates diff results.

    This class provides methods to compare index objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    @staticmethod
    def _normalize_index_columns(
        columns: Optional[Sequence[str]], is_expression: bool, flags: List[bool]
    ) -> List[Optional[str]]:
        """Normalize index columns, applying expression or identifier normalization per-flag."""
        return [
            (
                normalize_expression(c)
                if is_expression and i < len(flags) and flags[i]
                else normalize_identifier(c)
            )
            for i, c in enumerate(columns or [])
        ]

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the index comparator.

        Args:
            type_normalizer: Not used for indexes, kept for API compatibility
        """

    @staticmethod
    def _normalize_dialect_index_type(value: Optional[str], default: str) -> str:
        """Normalise a dialect-specific index type: BTREE and the dialect default are equivalent.

        Args:
            value: Raw index type string (may be None or falsy).
            default: The dialect's canonical default (e.g. "NONCLUSTERED", "NORMAL", "REGULAR").

        Returns:
            Normalised uppercase type string.
        """
        if not value:
            return default
        upper = value.upper()
        return default if upper in ("BTREE", default) else upper

    def compare_indexes(
        self,
        expected: Index,
        actual: Index,
        dialect: str = "",
    ) -> Optional[IndexDiff]:
        """Compare two index objects.

        Args:
            expected: Expected index from migrations
            actual: Actual index from database
            dialect: SQL dialect

        Returns:
            IndexDiff if differences found, None otherwise
        """
        index_name = expected.name or actual.name
        table_name = expected.table_name or actual.table_name
        diff = IndexDiff(object_name=index_name, index_name=index_name, table_name=table_name)

        # Compare columns
        # For expression indexes, we need to handle expressions differently than regular column names
        # Check if this is an expression index by looking at expression_flags
        # Store getattr results to avoid AttributeError when accessing expression_flags directly
        expected_flags = getattr(expected, "expression_flags", [])
        actual_flags = getattr(actual, "expression_flags", [])

        expected_is_expression = bool(expected_flags) and bool(expected_flags[0])
        actual_is_expression = bool(actual_flags) and bool(actual_flags[0])

        if expected_is_expression or actual_is_expression:
            # For expression indexes, normalize expressions (not identifiers)
            # expected_flags and actual_flags already retrieved above

            expected_cols = self._normalize_index_columns(
                expected.columns, expected_is_expression, expected_flags
            )
            actual_cols = self._normalize_index_columns(
                actual.columns, actual_is_expression, actual_flags
            )
        else:
            # Regular indexes: normalize as identifiers
            expected_cols = [normalize_identifier(c) for c in (expected.columns or [])]
            actual_cols = [normalize_identifier(c) for c in (actual.columns or [])]

        if expected_cols != actual_cols:
            diff.columns_changed = True
            diff.expected_columns = expected.columns
            diff.actual_columns = actual.columns
            logger.info(
                f"Index '{index_name}': columns changed from {expected_cols} to {actual_cols}"
            )

        # Compare uniqueness
        expected_unique = getattr(expected, "unique", False)
        actual_unique = getattr(actual, "unique", False)
        if expected_unique != actual_unique:
            diff.uniqueness_changed = (expected_unique, actual_unique)
            logger.info(
                f"Index '{index_name}': uniqueness changed from {expected_unique} to {actual_unique}"
            )

        quirks = ProviderRegistry.get_quirks(dialect)

        # Compare index type
        expected_type = normalize_identifier(getattr(expected, "type", "btree"))
        actual_type = normalize_identifier(getattr(actual, "type", "btree"))

        default_type = quirks.default_index_type
        if default_type and default_type != "BTREE":
            expected_type = self._normalize_dialect_index_type(expected_type, default_type)
            actual_type = self._normalize_dialect_index_type(actual_type, default_type)
        if expected_type != actual_type:
            diff.type_changed = (expected_type, actual_type)
            logger.info(f"Index '{index_name}': type changed from {expected_type} to {actual_type}")

        # Grammar-based: Compare MySQL/MariaDB ONLINE/OFFLINE
        if quirks.index_supports_online_offline:
            expected_online = getattr(expected, "online", None)
            actual_online = getattr(actual, "online", None)
            if expected_online is not None and actual_online is not None:
                if expected_online != actual_online:
                    diff.online_changed = (expected_online, actual_online)
                    logger.info(
                        f"Index '{index_name}': ONLINE/OFFLINE status changed from {expected_online} to {actual_online}"
                    )

        # Grammar-based: Compare PostgreSQL CONCURRENTLY
        if quirks.supports_concurrent_index:
            expected_concurrently = getattr(expected, "concurrently", False)
            actual_concurrently = getattr(actual, "concurrently", False)
            if expected_concurrently != actual_concurrently:
                diff.concurrently_changed = (expected_concurrently, actual_concurrently)
                logger.info(
                    f"Index '{index_name}': CONCURRENTLY status changed from {expected_concurrently} to {actual_concurrently}"
                )

        # Grammar-based: Compare Oracle TABLESPACE
        if quirks.index_supports_tablespace:
            expected_tablespace = getattr(expected, "tablespace", None)
            actual_tablespace = getattr(actual, "tablespace", None)
            if expected_tablespace and actual_tablespace:
                # Convert to Python strings to handle driver-returned objects
                if str(expected_tablespace).lower() != str(actual_tablespace).lower():
                    diff.tablespace_changed = (expected_tablespace, actual_tablespace)
                    logger.info(
                        f"Index '{index_name}': TABLESPACE changed from {expected_tablespace} to {actual_tablespace}"
                    )
            elif expected_tablespace and not actual_tablespace:
                diff.tablespace_changed = (expected_tablespace, actual_tablespace)
                logger.info(
                    f"Index '{index_name}': TABLESPACE changed from {expected_tablespace} to {actual_tablespace}"
                )

        # SQL Server: Compare INCLUDE columns
        expected_include = getattr(expected, "include_columns", None) or []
        actual_include = getattr(actual, "include_columns", None) or []
        normalized_expected_include = [normalize_identifier(col) for col in expected_include]
        normalized_actual_include = [normalize_identifier(col) for col in actual_include]
        if normalized_expected_include or normalized_actual_include:
            if normalized_expected_include != normalized_actual_include:
                diff.include_columns_changed = (
                    expected_include or None,
                    actual_include or None,
                )
                logger.info(
                    f"Index '{index_name}': INCLUDE columns changed from {expected_include} to {actual_include}"
                )

        # Calculate final diff status
        diff._calculate_diffs()

        return diff if diff.has_diffs else None
