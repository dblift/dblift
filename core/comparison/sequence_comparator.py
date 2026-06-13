"""Sequence Comparator for Drift Detection.

This module provides the SequenceComparator class which compares sequence objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.diff_models import SequenceDiff
from core.sql_model.sequence import Sequence
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class SequenceComparator:
    """Compares sequence objects and generates diff results.

    This class provides methods to compare sequence objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_sequences(
        self,
        expected: Sequence,
        actual: Sequence,
        dialect: str = "",
    ) -> Optional[SequenceDiff]:
        """Compare two sequence objects.

        Args:
            expected: Expected sequence from migrations
            actual: Actual sequence from database
            dialect: SQL dialect

        Returns:
            SequenceDiff if differences found, None otherwise
        """
        seq_name = expected.name or actual.name
        diff = SequenceDiff(object_name=seq_name, sequence_name=seq_name)
        _quirks = ProviderRegistry.get_quirks(dialect)

        # Compare start value (Sequence uses start_with)
        expected_start = getattr(expected, "start_with", getattr(expected, "start_value", None))
        actual_start = getattr(actual, "start_with", getattr(actual, "start_value", None))
        if expected_start != actual_start and expected_start is not None:
            diff.start_value_changed = (expected_start, actual_start)
            logger.info(
                f"Sequence '{seq_name}': start value changed from {expected_start} to {actual_start}"
            )

        # Compare increment (Sequence uses increment_by)
        expected_inc = getattr(expected, "increment_by", getattr(expected, "increment", None))
        actual_inc = getattr(actual, "increment_by", getattr(actual, "increment", None))
        if expected_inc != actual_inc and expected_inc is not None:
            diff.increment_changed = (expected_inc, actual_inc)
            logger.info(
                f"Sequence '{seq_name}': increment changed from {expected_inc} to {actual_inc}"
            )

        # Compare min value
        expected_min = getattr(expected, "min_value", None)
        actual_min = getattr(actual, "min_value", None)
        if expected_min != actual_min and expected_min is not None:
            diff.min_value_changed = (expected_min, actual_min)
            logger.info(
                f"Sequence '{seq_name}': min value changed from {expected_min} to {actual_min}"
            )

        # Compare max value
        expected_max = getattr(expected, "max_value", None)
        actual_max = getattr(actual, "max_value", None)
        # DB2 uses INT64 max as implicit "no max" — normalise to None match.
        if _quirks.seq_implicit_max_value is not None:
            if (
                expected_max in (None, _quirks.seq_implicit_max_value)
                and actual_max == _quirks.seq_implicit_max_value
            ):
                actual_max = expected_max
        if expected_max != actual_max and expected_max is not None:
            diff.max_value_changed = (expected_max, actual_max)
            logger.info(
                f"Sequence '{seq_name}': max value changed from {expected_max} to {actual_max}"
            )

        # Compare cycle
        expected_cycle = getattr(expected, "cycle", False)
        actual_cycle = getattr(actual, "cycle", False)
        if expected_cycle != actual_cycle:
            diff.cycle_changed = (expected_cycle, actual_cycle)
            logger.info(
                f"Sequence '{seq_name}': cycle changed from {expected_cycle} to {actual_cycle}"
            )

        # Grammar-based: Compare PostgreSQL TEMPORARY
        if _quirks.seq_supports_temp:
            expected_temp = getattr(expected, "temp", False)
            actual_temp = getattr(actual, "temp", False)
            if expected_temp != actual_temp:
                diff.temp_changed = (expected_temp, actual_temp)
                logger.info(
                    f"Sequence '{seq_name}': TEMPORARY changed from {expected_temp} to {actual_temp}"
                )

        expected_owned_table = getattr(expected, "owned_by_table", None)
        expected_owned_column = getattr(expected, "owned_by_column", None)
        actual_owned_table = getattr(actual, "owned_by_table", None)
        actual_owned_column = getattr(actual, "owned_by_column", None)
        expected_owned = (expected_owned_table, expected_owned_column)
        actual_owned = (actual_owned_table, actual_owned_column)
        if expected_owned != actual_owned and (
            expected_owned != (None, None) or actual_owned != (None, None)
        ):
            diff.owned_by_changed = (expected_owned, actual_owned)
            logger.info(
                f"Sequence '{seq_name}': OWNED BY changed from {expected_owned} to {actual_owned}"
            )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
