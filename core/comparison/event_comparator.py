"""Event Comparator for Drift Detection.

This module provides the EventComparator class which compares event objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import (
    normalize_expression,
)
from core.comparison.diff_models import EventDiff
from core.sql_model.event import Event
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


def _supports_event_schedule(dialect: str) -> bool:
    """Return True if dialect supports MySQL-style CREATE EVENT scheduling."""
    return ProviderRegistry.get_quirks(dialect).event_supports_mysql_schedule


class EventComparator:
    """Compares event objects and generates diff results.

    This class provides methods to compare event objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_events(
        self,
        expected: Event,
        actual: Event,
        dialect: str = "",
    ) -> Optional[EventDiff]:
        """Compare two event objects (MySQL).

        Args:
            expected: Expected event from migrations
            actual: Actual event from database
            dialect: SQL dialect (typically mysql)

        Returns:
            EventDiff if differences found, None otherwise
        """
        event_name = expected.name or actual.name
        diff = EventDiff(object_name=event_name, event_name=event_name)
        is_event_dialect = _supports_event_schedule(dialect)

        # Compare definition (normalize for comparison)
        expected_def = normalize_expression(expected.definition)
        actual_def = normalize_expression(actual.definition)
        if is_event_dialect and not expected.definition:
            expected_def = actual_def
        if expected_def != actual_def:
            diff.definition_changed = True
            logger.info(f"Event '{event_name}': definition changed")

        # Compare schedule
        expected_schedule = normalize_expression(expected.schedule)
        actual_schedule = normalize_expression(actual.schedule)
        if is_event_dialect and not expected.schedule:
            expected_schedule = actual_schedule
        if expected_schedule != actual_schedule:
            diff.schedule_changed = (expected.schedule, actual.schedule)
            logger.info(
                f"Event '{event_name}': schedule changed from {expected.schedule} to {actual.schedule}"
            )

        # Compare enabled status
        if expected.enabled != actual.enabled:
            diff.enabled_changed = (expected.enabled, actual.enabled)
            logger.info(
                f"Event '{event_name}': enabled status changed from {expected.enabled} to {actual.enabled}"
            )

        # Compare event type
        expected_type = (expected.event_type or "").upper()
        actual_type = (actual.event_type or "").upper()
        if is_event_dialect and not getattr(expected, "schedule", None):
            expected_type = actual_type
        if expected_type != actual_type:
            diff.event_type_changed = (expected.event_type, actual.event_type)
            logger.info(
                f"Event '{event_name}': event type changed from {expected.event_type} to {actual.event_type}"
            )

        # MySQL-specific metadata
        if is_event_dialect:
            expected_definer = getattr(expected, "definer", None) or ""
            actual_definer = getattr(actual, "definer", None) or ""
            if expected_definer != actual_definer:
                diff.definer_changed = (expected_definer or None, actual_definer or None)
                logger.info(
                    f"Event '{event_name}': definer changed from {expected_definer or 'DEFAULT'} to {actual_definer or 'DEFAULT'}"
                )

            expected_comment = getattr(expected, "comment", None) or ""
            actual_comment = getattr(actual, "comment", None) or ""
            if expected_comment != actual_comment:
                diff.comment_changed = (expected_comment or None, actual_comment or None)
                logger.info(
                    f"Event '{event_name}': comment changed from {expected_comment or 'NONE'} to {actual_comment or 'NONE'}"
                )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
