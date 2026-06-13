"""Package Comparator for Drift Detection.

This module provides the PackageComparator class which compares package objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import (
    normalize_package_code,
)
from core.comparison.diff_models import PackageDiff
from core.sql_model.package import Package

logger = logging.getLogger(__name__)


class PackageComparator:
    """Compares package objects and generates diff results.

    This class provides methods to compare package objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_packages(
        self,
        expected: Package,
        actual: Package,
        dialect: str = "",
    ) -> Optional[PackageDiff]:
        """Compare two package objects (Oracle).

        Args:
            expected: Expected package from migrations
            actual: Actual package from database
            dialect: SQL dialect (typically oracle)

        Returns:
            PackageDiff if differences found, None otherwise
        """
        package_name = expected.name or actual.name
        diff = PackageDiff(object_name=package_name, package_name=package_name)

        # Compare package specification
        expected_spec = normalize_package_code(expected.spec)
        actual_spec = normalize_package_code(actual.spec)

        if expected_spec != actual_spec:
            diff.spec_changed = True
            diff.expected_spec = expected.spec
            diff.actual_spec = actual.spec
            logger.info(f"Package '{package_name}': specification changed")

        # Compare package body
        expected_body = normalize_package_code(expected.body)
        actual_body = normalize_package_code(actual.body)

        if expected_body != actual_body:
            diff.body_changed = True
            diff.expected_body = expected.body
            diff.actual_body = actual.body
            logger.info(f"Package '{package_name}': body changed")

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
