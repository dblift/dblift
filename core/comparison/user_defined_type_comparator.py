"""UserDefinedType Comparator for Drift Detection.

This module provides the UserDefinedTypeComparator class which compares user defined type objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.comparison.diff_models import UserDefinedTypeDiff
from core.comparison.type_normalizer import DataTypeNormalizer
from core.sql_model.user_defined_type import UserDefinedType

logger = logging.getLogger(__name__)


class UserDefinedTypeComparator:
    """Compares user defined type objects and generates diff results.

    This class provides methods to compare user defined type objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    def __init__(self, type_normalizer: Optional[DataTypeNormalizer] = None) -> None:
        """Initialize the comparator.

        Args:
            type_normalizer: DataTypeNormalizer for type comparison
        """
        self.type_normalizer = type_normalizer

    def compare_user_defined_types(
        self,
        expected: UserDefinedType,
        actual: UserDefinedType,
        dialect: str = "",
    ) -> Optional[UserDefinedTypeDiff]:
        """Compare two user-defined type objects.

        Args:
            expected: Expected UDT from migrations
            actual: Actual UDT from database
            dialect: SQL dialect

        Returns:
            UserDefinedTypeDiff if differences found, None otherwise
        """
        type_name = expected.name or actual.name
        diff = UserDefinedTypeDiff(object_name=type_name, type_name=type_name)

        # Compare type category (COMPOSITE, ENUM, DOMAIN, DISTINCT, etc.)
        def _canonical_category(category: str) -> str:
            mapping = {
                "C": "COMPOSITE",
                "R": "COMPOSITE",
                "S": "COMPOSITE",
                "STRUCT": "COMPOSITE",
                "STRUCTURED": "COMPOSITE",
                "OBJECT": "COMPOSITE",  # Oracle OBJECT types are composite types
                "E": "ENUM",
                "ENUM": "ENUM",
                "D": "DOMAIN",
                "DOMAIN": "DOMAIN",
                "DISTINCT": "DISTINCT",
            }
            value = category.upper() if category else "UNKNOWN"
            return mapping.get(value, value)

        expected_category = _canonical_category(expected.type_category)
        actual_category = _canonical_category(actual.type_category)
        if expected_category != actual_category:
            diff.type_category_changed = (expected.type_category, actual.type_category)
            diff.expected_type_category = expected.type_category
            diff.actual_type_category = actual.type_category
            logger.info(
                f"User-defined type '{type_name}': category changed from {expected.type_category} to {actual.type_category}"
            )

        # Compare base type (for DOMAIN and DISTINCT types)
        if expected.base_type or actual.base_type:
            expected_base = (expected.base_type or "").upper()
            actual_base = (actual.base_type or "").upper()
            if expected_base != actual_base:
                diff.base_type_changed = (expected.base_type, actual.base_type)
                diff.expected_base_type = expected.base_type
                diff.actual_base_type = actual.base_type
                logger.info(
                    f"User-defined type '{type_name}': base type changed from {expected.base_type} to {actual.base_type}"
                )

        # Compare attributes (for COMPOSITE types)
        if expected.is_composite and actual.is_composite:

            def _normalize_attributes(
                attrs: Optional[List[Dict[str, Any]]],
            ) -> List[Tuple[str, str]]:
                normalized: List[Tuple[str, str]] = []
                if not attrs:
                    return normalized
                for attr in attrs:
                    # Convert to Python string to handle driver-returned objects
                    name = str(attr.get("name") or "").strip().lower()
                    attr_type_raw = (attr.get("type") or "").strip()
                    assert self.type_normalizer is not None
                    normalized_type = self.type_normalizer.normalize(
                        attr_type_raw,
                        dialect,
                    )
                    normalized.append((name, (normalized_type or attr_type_raw).upper()))
                return normalized

            expected_attrs = _normalize_attributes(expected.attributes)
            actual_attrs = _normalize_attributes(actual.attributes)

            if expected_attrs != actual_attrs:
                diff.attributes_changed = True
                diff.expected_attributes = expected.attributes
                diff.actual_attributes = actual.attributes
                logger.info(f"User-defined type '{type_name}': attributes changed")
                logger.info(f"  Expected attributes (normalized): {expected_attrs}")
                logger.info(f"  Actual attributes (normalized): {actual_attrs}")
                logger.info(f"  Expected attributes (raw): {expected.attributes}")
                logger.info(f"  Actual attributes (raw): {actual.attributes}")

        # Compare enum values (for ENUM types)
        if expected.is_enum and actual.is_enum:
            expected_values = sorted(expected.enum_values or [])
            actual_values = sorted(actual.enum_values or [])
            if expected_values != actual_values:
                diff.enum_values_changed = True
                diff.expected_enum_values = expected.enum_values
                diff.actual_enum_values = actual.enum_values
                logger.info(f"User-defined type '{type_name}': enum values changed")

        # Compare definition (for types with explicit definitions)
        if expected.definition or actual.definition:
            expected_def = (expected.definition or "").strip().upper()
            actual_def = (actual.definition or "").strip().upper()
            if expected_def != actual_def:
                diff.definition_changed = True
                logger.info(f"User-defined type '{type_name}': definition changed")

        diff._calculate_diffs()
        return diff if diff.has_diffs else None
