"""View Comparator for Drift Detection.

This module provides the ViewComparator class which compares view objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Optional

from core.comparison.comparison_utils import normalize_view_definition
from core.comparison.diff_models import ViewDiff
from core.sql_model.view import View
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class ViewComparator:
    """Compares view objects and generates diff results.

    This class provides methods to compare view objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the view comparator.

        Args:
            type_normalizer: Not used for views, kept for API compatibility
        """

    def compare_views(
        self,
        expected: View,
        actual: View,
        dialect: str = "",
    ) -> Optional[ViewDiff]:
        """Compare two view objects.

        Args:
            expected: Expected view from migrations
            actual: Actual view from database
            dialect: SQL dialect

        Returns:
            ViewDiff if differences found, None otherwise
        """
        view_name = expected.name or actual.name
        diff = ViewDiff(object_name=view_name, view_name=view_name)
        _quirks = ProviderRegistry.get_quirks(dialect)

        # Compare definitions (normalize whitespace and case)
        expected_def = self._normalize_view_definition(expected.query, dialect)
        actual_def = self._normalize_view_definition(actual.query, dialect)

        if expected_def != actual_def:
            diff.definition_changed = True
            diff.expected_definition = expected.query
            diff.actual_definition = actual.query
            logger.info(f"View '{view_name}': definition changed")

        # Compare materialized status (PostgreSQL)
        expected_mat = getattr(expected, "materialized", False)
        actual_mat = getattr(actual, "materialized", False)
        if expected_mat != actual_mat:
            diff.materialized_changed = (expected_mat, actual_mat)
            logger.info(
                f"View '{view_name}': materialized status changed from {expected_mat} to {actual_mat}"
            )

        # Grammar-based: Compare PostgreSQL UNLOGGED (materialized views)
        if _quirks.view_supports_unlogged_and_security:
            expected_unlogged = getattr(expected, "unlogged", None)
            actual_unlogged = getattr(actual, "unlogged", None)
            if expected_unlogged is not None and actual_unlogged is not None:
                if expected_unlogged != actual_unlogged:
                    diff.unlogged_changed = (expected_unlogged, actual_unlogged)
                    logger.info(
                        f"View '{view_name}': UNLOGGED status changed from {expected_unlogged} to {actual_unlogged}"
                    )

            # Compare security context - Diff-relevant
            expected_security_definer = getattr(expected, "security_definer", None)
            actual_security_definer = getattr(actual, "security_definer", None)
            if expected_security_definer is not None and actual_security_definer is not None:
                if expected_security_definer != actual_security_definer:
                    diff.security_definer_changed = (
                        expected_security_definer,
                        actual_security_definer,
                    )
                    logger.info(
                        f"View '{view_name}': SECURITY DEFINER changed from {expected_security_definer} to {actual_security_definer}"
                    )

            expected_security_invoker = getattr(expected, "security_invoker", None)
            actual_security_invoker = getattr(actual, "security_invoker", None)
            if expected_security_invoker is not None and actual_security_invoker is not None:
                if expected_security_invoker != actual_security_invoker:
                    diff.security_invoker_changed = (
                        expected_security_invoker,
                        actual_security_invoker,
                    )
                    logger.info(
                        f"View '{view_name}': SECURITY INVOKER changed from {expected_security_invoker} to {actual_security_invoker}"
                    )

        # Grammar-based: Compare MySQL view properties
        if _quirks.view_supports_algorithm:
            # Compare algorithm
            expected_algorithm = getattr(expected, "algorithm", None)
            actual_algorithm = getattr(actual, "algorithm", None)
            if expected_algorithm != actual_algorithm:
                diff.algorithm_changed = (expected_algorithm, actual_algorithm)
                logger.info(
                    f"View '{view_name}': algorithm changed from {expected_algorithm} to {actual_algorithm}"
                )

            # Compare SQL SECURITY
            expected_sql_sec = getattr(expected, "sql_security", None)
            actual_sql_sec = getattr(actual, "sql_security", None)
            if expected_sql_sec and actual_sql_sec and expected_sql_sec != actual_sql_sec:
                diff.sql_security_changed = (expected_sql_sec, actual_sql_sec)
                logger.info(
                    f"View '{view_name}': SQL SECURITY changed from {expected_sql_sec} to {actual_sql_sec}"
                )

            # Compare definer
            expected_definer = getattr(expected, "definer", None)
            actual_definer = getattr(actual, "definer", None)
            if expected_definer and actual_definer and expected_definer != actual_definer:
                diff.definer_changed = (expected_definer, actual_definer)
                logger.info(
                    f"View '{view_name}': definer changed from {expected_definer} to {actual_definer}"
                )

        # Grammar-based: Compare Oracle FORCE/NOFORCE
        if _quirks.view_supports_force_noforce:
            expected_force = getattr(expected, "force", None)
            actual_force = getattr(actual, "force", None)
            if expected_force is not None and actual_force is not None:
                if expected_force != actual_force:
                    diff.force_changed = (expected_force, actual_force)
                    logger.info(
                        f"View '{view_name}': FORCE/NOFORCE changed from {expected_force} to {actual_force}"
                    )

        # Compare materialized view specific properties (only if both are materialized)
        if expected_mat and actual_mat:
            # Compare is_populated status
            expected_populated = getattr(expected, "is_populated", None)
            actual_populated = getattr(actual, "is_populated", None)
            if expected_populated is not None and actual_populated is not None:
                if expected_populated != actual_populated:
                    diff.is_populated_changed = (expected_populated, actual_populated)
                    logger.info(
                        f"Materialized view '{view_name}': populated status changed from {expected_populated} to {actual_populated}"
                    )

            # Compare refresh_method
            expected_method = getattr(expected, "refresh_method", None)
            actual_method = getattr(actual, "refresh_method", None)
            if expected_method and actual_method:
                # Normalize for comparison (case-insensitive)
                if expected_method.upper() != actual_method.upper():
                    diff.refresh_method_changed = (expected_method, actual_method)
                    logger.info(
                        f"Materialized view '{view_name}': refresh method changed from {expected_method} to {actual_method}"
                    )

            # Compare refresh_mode (Oracle)
            expected_mode = getattr(expected, "refresh_mode", None)
            actual_mode = getattr(actual, "refresh_mode", None)
            if expected_mode and actual_mode:
                # Normalize for comparison (case-insensitive)
                if expected_mode.upper() != actual_mode.upper():
                    diff.refresh_mode_changed = (expected_mode, actual_mode)
                    logger.info(
                        f"Materialized view '{view_name}': refresh mode changed from {expected_mode} to {actual_mode}"
                    )

            # Compare fast_refreshable (Oracle)
            expected_fast = getattr(expected, "fast_refreshable", None)
            actual_fast = getattr(actual, "fast_refreshable", None)
            if expected_fast is not None and actual_fast is not None:
                if expected_fast != actual_fast:
                    diff.fast_refreshable_changed = (expected_fast, actual_fast)
                    logger.info(
                        f"Materialized view '{view_name}': fast refresh capability changed from {expected_fast} to {actual_fast}"
                    )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None

    def _normalize_view_definition(
        self,
        definition: Optional[str],
        dialect: str = "",
    ) -> str:
        """Normalize view definition for comparison.

        Delegates to the shared ``normalize_view_definition`` utility in
        ``comparison_utils`` so that identical logic is maintained in a single place.

        Args:
            definition: View definition SQL
            dialect: SQL dialect (passed to sqlglot for parsing)

        Returns:
            Normalized definition
        """
        return normalize_view_definition(definition, dialect)
