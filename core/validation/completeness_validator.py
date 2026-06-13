"""
Completeness validator for schema introspection.

Checks that all expected objects are fully captured with all properties.
"""

import logging
from typing import Dict, List, Optional

from core.sql_model.base import SqlObject
from core.sql_model.table import Table
from core.validation.result import ValidationResult, ValidationSeverity

logger = logging.getLogger(__name__)


class CompletenessValidator:
    """
    Validates completeness of schema introspection.

    Checks:
    - All expected object types are present
    - All properties are captured (not None when expected)
    - No missing critical properties
    """

    def __init__(self):
        """Initialize the completeness validator."""

    def validate_tables(
        self,
        tables: List[Table],
        expected_count: Optional[int] = None,
        required_properties: Optional[List[str]] = None,
    ) -> ValidationResult:
        """Validate completeness of table introspection.

        Args:
            tables: List of introspected tables
            expected_count: Expected number of tables (optional)
            required_properties: List of required property names (optional)

        Returns:
            ValidationResult with completeness issues
        """
        result = ValidationResult(validator_name="CompletenessValidator")

        # Check count if expected
        if expected_count is not None:
            actual_count = len(tables)
            if actual_count != expected_count:
                result.add_issue(
                    ValidationSeverity.ERROR,
                    f"Table count mismatch: expected {expected_count}, got {actual_count}",
                    expected_value=expected_count,
                    actual_value=actual_count,
                )

        # Default required properties for tables
        if required_properties is None:
            required_properties = ["name", "columns"]

        # Check each table for required properties
        for table in tables:
            for prop_name in required_properties:
                if not hasattr(table, prop_name):
                    result.add_issue(
                        ValidationSeverity.ERROR,
                        f"Table missing required property: {prop_name}",
                        object_type="table",
                        object_name=table.name,
                        property_name=prop_name,
                    )
                elif getattr(table, prop_name) is None:
                    # Check if it's a critical property
                    if prop_name in ["name", "columns"]:
                        result.add_issue(
                            ValidationSeverity.ERROR,
                            f"Table has None value for critical property: {prop_name}",
                            object_type="table",
                            object_name=table.name,
                            property_name=prop_name,
                        )
                    else:
                        result.add_issue(
                            ValidationSeverity.WARNING,
                            f"Table has None value for property: {prop_name}",
                            object_type="table",
                            object_name=table.name,
                            property_name=prop_name,
                        )

            # Check columns completeness
            if table.columns:
                for col in table.columns:
                    if not col.name:
                        result.add_issue(
                            ValidationSeverity.ERROR,
                            "Column missing name",
                            object_type="column",
                            object_name=None,
                            property_name="name",
                        )
                    if not col.data_type:
                        result.add_issue(
                            ValidationSeverity.ERROR,
                            f"Column {col.name} missing data_type",
                            object_type="column",
                            object_name=col.name,
                            property_name="data_type",
                        )

        result.metadata["table_count"] = len(tables)
        result.metadata["expected_count"] = expected_count

        return result

    def validate_objects(
        self,
        objects: Dict[str, List[SqlObject]],
        expected_counts: Optional[Dict[str, int]] = None,
    ) -> ValidationResult:
        """Validate completeness of all object types.

        Args:
            objects: Dictionary with keys like 'tables', 'views', 'indexes'
            expected_counts: Dictionary of expected counts per type

        Returns:
            ValidationResult with completeness issues
        """
        result = ValidationResult(validator_name="CompletenessValidator")

        # Check counts for each object type
        if expected_counts:
            for obj_type, expected_count in expected_counts.items():
                actual_objects = objects.get(obj_type, [])
                actual_count = len(actual_objects)
                if actual_count != expected_count:
                    result.add_issue(
                        ValidationSeverity.ERROR,
                        f"{obj_type} count mismatch: expected {expected_count}, got {actual_count}",
                        object_type=obj_type,
                        expected_value=expected_count,
                        actual_value=actual_count,
                    )

        # Validate tables if present
        if "tables" in objects:
            # Cast to List[Table] - we know these are tables from the context
            from core.sql_model.table import Table

            tables = [t for t in objects["tables"] if isinstance(t, Table)]
            table_result = self.validate_tables(tables)
            result.issues.extend(table_result.issues)
            if not table_result.passed:
                result.passed = False

        result.metadata["object_counts"] = {
            obj_type: len(obj_list) for obj_type, obj_list in objects.items()
        }

        return result
