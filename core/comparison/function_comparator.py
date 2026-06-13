"""Function Comparator for Drift Detection.

This module provides the FunctionComparator class which compares function objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
import re
from typing import Optional

from core.comparison.comparison_utils import (
    normalize_expression,
    normalize_parameters,
)
from core.comparison.diff_models import FunctionDiff
from core.sql_model.procedure import Procedure
from db.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)


class FunctionComparator:
    """Compares function objects and generates diff results.

    This class provides methods to compare function objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[object] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: Not used, kept for API compatibility
        """

    def compare_functions(
        self,
        expected: Procedure,
        actual: Procedure,
        dialect: str = "",
    ) -> Optional[FunctionDiff]:
        """Compare two function objects (Procedure with is_function=True).

        Args:
            expected: Expected function from migrations (Procedure with is_function=True)
            actual: Actual function from database (Procedure with is_function=True)
            dialect: SQL dialect

        Returns:
            FunctionDiff if differences found, None otherwise
        """
        func_name = expected.name or actual.name
        diff = FunctionDiff(object_name=func_name, function_name=func_name)
        _quirks = ProviderRegistry.get_quirks(dialect)

        # Compare parameters
        expected_params = normalize_parameters(expected.parameters)
        actual_params = normalize_parameters(actual.parameters)

        if expected_params != actual_params:
            diff.parameters_changed = True
            # Convert parameters to string list for diff
            diff.expected_parameters = [str(p) for p in (expected.parameters or [])]
            diff.actual_parameters = [str(p) for p in (actual.parameters or [])]
            logger.info(
                f"Function '{func_name}': parameters changed from {expected_params} to {actual_params}"
            )

        # Compare return type
        expected_return = str(expected.return_type).upper().strip() if expected.return_type else ""
        actual_return = str(actual.return_type).upper().strip() if actual.return_type else ""
        if expected_return != actual_return:
            diff.return_type_changed = (expected_return, actual_return)
            logger.info(
                f"Function '{func_name}': return type changed from {expected_return} to {actual_return}"
            )

        # Compare definition
        def _normalize_function_body(body: Optional[str], definition: Optional[str] = None) -> str:
            # For Oracle, use definition if body is empty (Oracle stores full DDL in definition)
            text_to_use = body or definition or ""
            if not text_to_use:
                return ""

            match = re.search(r"BEGIN\b.*END;?", text_to_use, re.IGNORECASE | re.DOTALL)
            snippet = match.group(0) if match else text_to_use
            normalized = normalize_expression(snippet)
            if not normalized:
                return ""
            normalized = normalized.rstrip(";")
            return f"{normalized};"

        # For Oracle, prefer definition over body if body is empty
        expected_body = expected.body or (
            getattr(expected, "definition", None) if _quirks.proc_uses_definition_field else None
        )
        actual_body = actual.body or (
            getattr(actual, "definition", None) if _quirks.proc_uses_definition_field else None
        )

        expected_def = _normalize_function_body(
            expected_body, getattr(expected, "definition", None)
        )
        actual_def = _normalize_function_body(actual_body, getattr(actual, "definition", None))
        if expected_def != actual_def:
            diff.definition_changed = True
            logger.info(f"Function '{func_name}': definition changed")

        expected_vol = (getattr(expected, "volatility", "") or "").upper()
        actual_vol = (getattr(actual, "volatility", "") or "").upper()
        if expected_vol != actual_vol:
            diff.volatility_changed = (expected_vol or None, actual_vol or None)
            logger.info(
                f"Function '{func_name}': volatility changed from {expected_vol or 'DEFAULT'} to {actual_vol or 'DEFAULT'}"
            )

        expected_sec = bool(getattr(expected, "security_definer", False))
        actual_sec = bool(getattr(actual, "security_definer", False))
        if expected_sec != actual_sec:
            diff.security_definer_changed = (expected_sec, actual_sec)
            logger.info(
                f"Function '{func_name}': SECURITY DEFINER changed from {expected_sec} to {actual_sec}"
            )

        # MySQL-specific metadata
        if _quirks.proc_skip_empty_comparison:
            expected_definer = getattr(expected, "definer", None) or ""
            actual_definer = getattr(actual, "definer", None) or ""
            if expected_definer != actual_definer:
                diff.definer_changed = (expected_definer or None, actual_definer or None)
                logger.info(
                    f"Function '{func_name}': definer changed from {expected_definer or 'DEFAULT'} to {actual_definer or 'DEFAULT'}"
                )

            expected_comment = getattr(expected, "comment", None) or ""
            actual_comment = getattr(actual, "comment", None) or ""
            if expected_comment != actual_comment:
                diff.comment_changed = (expected_comment or None, actual_comment or None)
                logger.info(
                    f"Function '{func_name}': comment changed from {expected_comment or 'NONE'} to {actual_comment or 'NONE'}"
                )

            expected_data_access = getattr(expected, "data_access", None) or ""
            actual_data_access = getattr(actual, "data_access", None) or ""
            if expected_data_access != actual_data_access:
                diff.data_access_changed = (
                    expected_data_access or None,
                    actual_data_access or None,
                )
                logger.info(
                    f"Function '{func_name}': data access changed from {expected_data_access or 'DEFAULT'} to {actual_data_access or 'DEFAULT'}"
                )

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
