"""Trigger Comparator for Drift Detection.

This module provides the TriggerComparator class which compares trigger objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
import re
from typing import Optional

from core.comparison.comparison_utils import (
    normalize_expression,
    normalize_identifier,
)
from core.comparison.diff_models import TriggerDiff
from core.sql_model.trigger import Trigger
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class TriggerComparator:
    """Compares trigger objects and generates diff results.

    This class provides methods to compare trigger objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_triggers(
        self,
        expected: Trigger,
        actual: Trigger,
        dialect: str = "",
    ) -> Optional[TriggerDiff]:
        """Compare two trigger objects.

        Args:
            expected: Expected trigger from migrations
            actual: Actual trigger from database
            dialect: SQL dialect

        Returns:
            TriggerDiff if differences found, None otherwise
        """
        trigger_name = expected.name or actual.name
        table_name = expected.table_name or actual.table_name
        diff = TriggerDiff(
            object_name=trigger_name, trigger_name=trigger_name, table_name=table_name
        )
        _quirks = ProviderRegistry.get_quirks(dialect)

        # Compare timing
        expected_timing = normalize_identifier(getattr(expected, "timing", ""))
        actual_timing = normalize_identifier(getattr(actual, "timing", ""))
        if expected_timing != actual_timing:
            diff.timing_changed = (expected_timing, actual_timing)
            logger.info(
                f"Trigger '{trigger_name}': timing changed from {expected_timing} to {actual_timing}"
            )

        # Compare event(s)
        expected_events = [normalize_identifier(e) for e in getattr(expected, "events", [])]
        actual_events = [normalize_identifier(e) for e in getattr(actual, "events", [])]
        # Fallback to single 'event' attribute if present
        if not expected_events:
            single = getattr(expected, "event", None)
            if single:
                expected_events = [normalize_identifier(single)]
        if not actual_events:
            single = getattr(actual, "event", None)
            if single:
                actual_events = [normalize_identifier(single)]

        if expected_events != actual_events:
            diff.event_changed = (expected_events, actual_events)
            logger.info(
                f"Trigger '{trigger_name}': event changed from {expected_events} to {actual_events}"
            )

        # Compare definition (focus on executed function/procedure for normalization)
        def _normalize_trigger_definition(
            definition: Optional[str],
            dialect: str = "",
        ) -> Optional[str]:
            if not definition:
                return None

            # For PostgreSQL: Look for EXECUTE FUNCTION/PROCEDURE
            action_pattern = re.compile(
                r"EXECUTE\s+(FUNCTION|PROCEDURE)\s+(.+)",
                re.IGNORECASE | re.DOTALL,
            )
            match = action_pattern.search(definition)
            if match:
                action = match.group(0).strip().rstrip(";")
                # Remove schema qualification before function/procedure names (e.g., SCHEMA.FUNC -> FUNC)
                action = re.sub(
                    r"(EXECUTE\s+(?:FUNCTION|PROCEDURE)\s+)(?:(?:[A-Z_][A-Z0-9_$]*\.)+)",
                    r"\1",
                    action,
                    flags=re.IGNORECASE,
                )
                # Collapse whitespace and uppercase for comparison
                return " ".join(action.split()).upper()

            # For SQL Server/Oracle: Look for AS keyword
            body_match = re.search(r"\bAS\b(.*)", definition, re.IGNORECASE | re.DOTALL)
            if body_match:
                body = body_match.group(1).strip().rstrip(";")
                return " ".join(body.split()).upper()

            # For MySQL: Extract body from "FOR EACH ROW" or use definition as-is if it's already just the body
            if ProviderRegistry.get_quirks(dialect).trigger_supports_definer_clause:
                # If definition looks like a full CREATE TRIGGER statement, extract body after FOR EACH ROW
                if re.search(r"\bCREATE\s+.*?\bTRIGGER\b", definition, re.IGNORECASE):
                    # Extract body after FOR EACH ROW
                    for_each_row_match = re.search(
                        r"\bFOR\s+EACH\s+ROW\s+(.*)", definition, re.IGNORECASE | re.DOTALL
                    )
                    if for_each_row_match:
                        body = for_each_row_match.group(1).strip().rstrip(";")
                        return " ".join(body.split()).upper()
                # Otherwise, assume it's already just the body (from introspection)
                return " ".join(definition.strip().rstrip(";").split()).upper()

            return None

        expected_def = _normalize_trigger_definition(expected.definition, dialect)
        actual_def = _normalize_trigger_definition(actual.definition, dialect)

        if expected_def is None or actual_def is None:
            expected_def = normalize_expression(expected.definition)
            actual_def = normalize_expression(actual.definition)

        if expected_def != actual_def:
            diff.definition_changed = True
            logger.info(f"Trigger '{trigger_name}': definition changed")

        # Compare enabled status
        expected_enabled = getattr(expected, "enabled", True)
        actual_enabled = getattr(actual, "enabled", True)
        if expected_enabled != actual_enabled:
            diff.enabled_changed = (expected_enabled, actual_enabled)
            logger.info(
                f"Trigger '{trigger_name}': enabled status changed from {expected_enabled} to {actual_enabled}"
            )

        def _normalize_function_name(value: Optional[str]) -> Optional[str]:
            if not value:
                return None
            return normalize_identifier(value)

        expected_func = _normalize_function_name(getattr(expected, "function_name", None))
        actual_func = _normalize_function_name(getattr(actual, "function_name", None))
        if expected_func != actual_func:
            diff.function_changed = (expected_func, actual_func)
            logger.info(
                f"Trigger '{trigger_name}': function changed from {expected_func} to {actual_func}"
            )

        expected_func_schema = normalize_identifier(getattr(expected, "function_schema", None))
        actual_func_schema = normalize_identifier(getattr(actual, "function_schema", None))
        if expected_func_schema != actual_func_schema:
            diff.function_schema_changed = (expected_func_schema, actual_func_schema)
            logger.info(
                f"Trigger '{trigger_name}': function schema changed from {expected_func_schema} to {actual_func_schema}"
            )

        def _normalize_arguments(arguments: Optional[str]) -> Optional[str]:
            if arguments is None:
                return None
            return " ".join(arguments.replace("\n", " ").split())

        expected_args = _normalize_arguments(getattr(expected, "function_arguments", None))
        actual_args = _normalize_arguments(getattr(actual, "function_arguments", None))
        if expected_args != actual_args:
            diff.function_arguments_changed = (expected_args, actual_args)
            logger.info(
                f"Trigger '{trigger_name}': function arguments changed from {expected_args} to {actual_args}"
            )

        expected_when = normalize_expression(getattr(expected, "when_clause", None)) or ""
        actual_when = normalize_expression(getattr(actual, "when_clause", None)) or ""
        if expected_when != actual_when:
            diff.when_clause_changed = (expected_when, actual_when)
            logger.info(
                f"Trigger '{trigger_name}': WHEN clause changed from {expected_when} to {actual_when}"
            )

        # Grammar-based: Compare PostgreSQL CONSTRAINT TRIGGER
        if _quirks.supports_constraint_triggers:
            expected_constraint = getattr(expected, "is_constraint_trigger", False)
            actual_constraint = getattr(actual, "is_constraint_trigger", False)
            if expected_constraint != actual_constraint:
                diff.constraint_trigger_changed = (expected_constraint, actual_constraint)
                logger.info(
                    f"Trigger '{trigger_name}': CONSTRAINT TRIGGER status changed from {expected_constraint} to {actual_constraint}"
                )
            expected_deferrable = getattr(expected, "constraint_deferrable", None)
            actual_deferrable = getattr(actual, "constraint_deferrable", None)
            if expected_deferrable != actual_deferrable:
                diff.constraint_deferrable_changed = (expected_deferrable, actual_deferrable)
                logger.info(
                    f"Trigger '{trigger_name}': DEFERRABLE changed from {expected_deferrable} to {actual_deferrable}"
                )
            expected_initially_deferred = getattr(expected, "constraint_initially_deferred", None)
            actual_initially_deferred = getattr(actual, "constraint_initially_deferred", None)
            if expected_initially_deferred != actual_initially_deferred:
                diff.constraint_initially_deferred_changed = (
                    expected_initially_deferred,
                    actual_initially_deferred,
                )
                logger.info(
                    f"Trigger '{trigger_name}': INITIALLY DEFERRED changed from "
                    f"{expected_initially_deferred} to {actual_initially_deferred}"
                )

        # Grammar-based: Compare MySQL definer
        if _quirks.trigger_supports_definer_clause:
            expected_definer = getattr(expected, "definer", None)
            actual_definer = getattr(actual, "definer", None)
            # If migration doesn't specify DEFINER but DB has one, or vice versa, or they differ
            if expected_definer != actual_definer:
                diff.definer_changed = (expected_definer, actual_definer)
                logger.info(
                    f"Trigger '{trigger_name}': definer changed from {expected_definer or 'DEFAULT'} to {actual_definer or 'DEFAULT'}"
                )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
