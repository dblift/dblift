"""DatabaseLink Comparator for Drift Detection.

This module provides the DatabaseLinkComparator class which compares database link objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import normalize_identifier
from core.comparison.diff_models import DatabaseLinkDiff
from core.sql_model.database_link import DatabaseLink

logger = logging.getLogger(__name__)


class DatabaseLinkComparator:
    """Compares database link objects and generates diff results.

    This class provides methods to compare database link objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_database_links(
        self,
        expected: DatabaseLink,
        actual: DatabaseLink,
        dialect: str = "",
    ) -> Optional[DatabaseLinkDiff]:
        """Compare two database link objects (Oracle).

        Args:
            expected: Expected database link from migrations
            actual: Actual database link from database
            dialect: SQL dialect (typically oracle)

        Returns:
            DatabaseLinkDiff if differences found, None otherwise
        """
        link_name = expected.name or actual.name
        diff = DatabaseLinkDiff(object_name=link_name, link_name=link_name)

        # Compare host/connect string
        expected_host = normalize_identifier(expected.host or expected.connect_string)
        actual_host = normalize_identifier(actual.host or actual.connect_string)
        if expected_host != actual_host:
            diff.host_changed = (
                expected.host or expected.connect_string,
                actual.host or actual.connect_string,
            )
            diff.expected_host = expected.host or expected.connect_string
            diff.actual_host = actual.host or actual.connect_string
            logger.info(
                f"Database link '{link_name}': host/connect string changed from {diff.expected_host} to {diff.actual_host}"
            )

        # Compare username
        expected_user = normalize_identifier(expected.username)
        actual_user = normalize_identifier(actual.username)
        if expected_user != actual_user:
            diff.username_changed = (expected.username, actual.username)
            logger.info(
                f"Database link '{link_name}': username changed from {expected.username} to {actual.username}"
            )

        # Compare public/private status
        if expected.public != actual.public:
            diff.public_changed = (expected.public, actual.public)
            logger.info(
                f"Database link '{link_name}': public status changed from {expected.public} to {actual.public}"
            )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
