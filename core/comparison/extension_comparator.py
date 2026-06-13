"""Extension Comparator for Drift Detection.

This module provides the ExtensionComparator class which compares extension objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import normalize_identifier
from core.comparison.diff_models import ExtensionDiff
from core.sql_model.extension import Extension

logger = logging.getLogger(__name__)


class ExtensionComparator:
    """Compares extension objects and generates diff results.

    This class provides methods to compare extension objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_extensions(
        self,
        expected: Extension,
        actual: Extension,
        dialect: str = "",
    ) -> Optional[ExtensionDiff]:
        """Compare two extension objects (PostgreSQL).

        Args:
            expected: Expected extension from migrations
            actual: Actual extension from database
            dialect: SQL dialect (typically postgresql)

        Returns:
            ExtensionDiff if differences found, None otherwise
        """
        extension_name = expected.name or actual.name
        diff = ExtensionDiff(object_name=extension_name, extension_name=extension_name)

        # Compare version
        expected_version = (expected.version or "").strip()
        actual_version = (actual.version or "").strip()
        if expected_version and actual_version and expected_version != actual_version:
            diff.version_changed = (expected.version, actual.version)
            diff.expected_version = expected.version
            diff.actual_version = actual.version
            logger.info(
                f"Extension '{extension_name}': version changed from {expected.version} to {actual.version}"
            )

        # Compare schema
        expected_schema = normalize_identifier(expected.schema)
        actual_schema = normalize_identifier(actual.schema)
        if expected_schema and expected_schema != actual_schema:
            diff.schema_changed = (expected.schema, actual.schema)
            logger.info(
                f"Extension '{extension_name}': schema changed from {expected.schema} to {actual.schema}"
            )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
