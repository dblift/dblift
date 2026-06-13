"""ForeignDataWrapper Comparator for Drift Detection.

This module provides the ForeignDataWrapperComparator class which compares foreign data wrapper objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import normalize_identifier
from core.comparison.diff_models import ForeignDataWrapperDiff
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

logger = logging.getLogger(__name__)


class ForeignDataWrapperComparator:
    """Compares foreign data wrapper objects and generates diff results.

    This class provides methods to compare foreign data wrapper objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_foreign_data_wrappers(
        self,
        expected: ForeignDataWrapper,
        actual: ForeignDataWrapper,
        dialect: str = "",
    ) -> Optional[ForeignDataWrapperDiff]:
        """Compare two foreign data wrapper objects (PostgreSQL).

        Args:
            expected: Expected FDW from migrations
            actual: Actual FDW from database
            dialect: SQL dialect (typically postgresql)

        Returns:
            ForeignDataWrapperDiff if differences found, None otherwise
        """
        fdw_name = expected.name or actual.name
        diff = ForeignDataWrapperDiff(object_name=fdw_name, fdw_name=fdw_name)

        # Compare handler
        expected_handler = normalize_identifier(expected.handler)
        actual_handler = normalize_identifier(actual.handler)
        if expected_handler != actual_handler:
            diff.handler_changed = (expected.handler, actual.handler)
            logger.info(
                f"Foreign data wrapper '{fdw_name}': handler changed from {expected.handler} to {actual.handler}"
            )

        # Compare validator
        expected_validator = normalize_identifier(expected.validator)
        actual_validator = normalize_identifier(actual.validator)
        if expected_validator != actual_validator:
            diff.validator_changed = (expected.validator, actual.validator)
            logger.info(
                f"Foreign data wrapper '{fdw_name}': validator changed from {expected.validator} to {actual.validator}"
            )

        # Compare options
        if expected.options != actual.options:
            diff.options_changed = (expected.options, actual.options)
            logger.info(f"Foreign data wrapper '{fdw_name}': options changed")

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
