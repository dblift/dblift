"""LinkedServer Comparator for Drift Detection.

This module provides the LinkedServerComparator class which compares linked server objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import normalize_identifier
from core.comparison.diff_models import LinkedServerDiff
from core.sql_model.linked_server import LinkedServer

logger = logging.getLogger(__name__)


class LinkedServerComparator:
    """Compares linked server objects and generates diff results.

    This class provides methods to compare linked server objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_linked_servers(
        self,
        expected: LinkedServer,
        actual: LinkedServer,
        dialect: str = "",
    ) -> Optional[LinkedServerDiff]:
        """Compare two linked server objects (SQL Server).

        Args:
            expected: Expected linked server from migrations
            actual: Actual linked server from database
            dialect: SQL dialect (typically sqlserver)

        Returns:
            LinkedServerDiff if differences found, None otherwise
        """
        server_name = expected.name or actual.name
        diff = LinkedServerDiff(object_name=server_name, server_name=server_name)

        # Compare product
        expected_product = normalize_identifier(expected.product)
        actual_product = normalize_identifier(actual.product)
        if expected_product != actual_product:
            diff.product_changed = (expected.product, actual.product)
            logger.info(
                f"Linked server '{server_name}': product changed from {expected.product} to {actual.product}"
            )

        # Compare provider
        expected_provider = normalize_identifier(expected.provider)
        actual_provider = normalize_identifier(actual.provider)
        if expected_provider != actual_provider:
            diff.provider_changed = (expected.provider, actual.provider)
            logger.info(
                f"Linked server '{server_name}': provider changed from {expected.provider} to {actual.provider}"
            )

        # Compare data source
        expected_datasrc = normalize_identifier(expected.data_source)
        actual_datasrc = normalize_identifier(actual.data_source)
        if expected_datasrc != actual_datasrc:
            diff.data_source_changed = (expected.data_source, actual.data_source)
            logger.info(
                f"Linked server '{server_name}': data source changed from {expected.data_source} to {actual.data_source}"
            )

        # Compare catalog
        expected_catalog = normalize_identifier(expected.catalog)
        actual_catalog = normalize_identifier(actual.catalog)
        if expected_catalog != actual_catalog:
            diff.catalog_changed = (expected.catalog, actual.catalog)
            logger.info(
                f"Linked server '{server_name}': catalog changed from {expected.catalog} to {actual.catalog}"
            )

        # Compare username
        expected_user = normalize_identifier(expected.username)
        actual_user = normalize_identifier(actual.username)
        if expected_user != actual_user:
            diff.username_changed = (expected.username, actual.username)
            logger.info(
                f"Linked server '{server_name}': username changed from {expected.username} to {actual.username}"
            )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
