"""
Accuracy validator for schema introspection.

Compares captured state vs live database to detect drift and verify accuracy.
"""

import logging
from typing import Dict, List, Optional

from core.comparison.comparator import ObjectComparator
from core.comparison.type_normalizer import DataTypeNormalizer
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.validation.result import ValidationResult, ValidationSeverity

logger = logging.getLogger(__name__)


class AccuracyValidator:
    """
    Validates accuracy of schema introspection by comparing captured state
    with live database state.

    This validator:
    - Re-introspects the database
    - Compares captured vs live objects
    - Detects drift between captures
    - Verifies round-trip accuracy
    """

    def __init__(self, introspector=None):
        """Initialize the accuracy validator.

        Args:
            introspector: Optional introspector instance for re-introspection
        """
        self.introspector = introspector
        self.comparator = ObjectComparator(DataTypeNormalizer())

    def validate_tables(
        self,
        captured_tables: List[Table],
        live_tables: List[Table],
        schema: str,
    ) -> ValidationResult:
        """Validate accuracy of captured tables by comparing with live database.

        Args:
            captured_tables: List of captured Table objects
            live_tables: List of live Table objects from re-introspection
            schema: Schema name

        Returns:
            ValidationResult with accuracy issues
        """
        result = ValidationResult(validator_name="AccuracyValidator")

        # Normalize table names for comparison
        captured_map = {self._normalize_name(t.name): t for t in captured_tables}
        live_map = {self._normalize_name(t.name): t for t in live_tables}

        # Check for missing tables in live database
        for captured_name, captured_table in captured_map.items():
            if captured_name not in live_map:
                result.add_issue(
                    ValidationSeverity.ERROR,
                    f"Captured table {schema}.{captured_table.name} not found in live database",
                    object_type="table",
                    object_name=captured_table.name,
                    expected_value="exists",
                    actual_value="not found",
                )

        # Check for extra tables in live database
        for live_name, live_table in live_map.items():
            if live_name not in captured_map:
                result.add_issue(
                    ValidationSeverity.WARNING,
                    f"Live table {schema}.{live_table.name} not in captured state",
                    object_type="table",
                    object_name=live_table.name,
                    expected_value="not captured",
                    actual_value="exists",
                )

        # Compare common tables
        common_names = set(captured_map.keys()) & set(live_map.keys())
        for table_name in common_names:
            captured_table = captured_map[table_name]
            live_table = live_map[table_name]

            # Compare table properties
            table_diff = self.comparator.compare_tables(captured_table, live_table)

            # Check if there are any differences using TableDiff attributes
            has_diffs = (
                table_diff.missing_columns
                or table_diff.extra_columns
                or table_diff.modified_columns
                or table_diff.missing_constraints
                or table_diff.extra_constraints
                or table_diff.modified_constraints
                or any(
                    diff is not None
                    for diff in [
                        getattr(table_diff, "name_changed", None),
                        getattr(table_diff, "schema_changed", None),
                        getattr(table_diff, "temporary_changed", None),
                        getattr(table_diff, "comment_changed", None),
                    ]
                )
            )

            if has_diffs:
                # Check column differences
                if (
                    table_diff.missing_columns
                    or table_diff.extra_columns
                    or table_diff.modified_columns
                ):
                    result.add_issue(
                        ValidationSeverity.ERROR,
                        f"Table {schema}.{captured_table.name} has column differences",
                        object_type="table",
                        object_name=captured_table.name,
                        property_name="columns",
                    )

                # Check constraint differences
                if (
                    table_diff.missing_constraints
                    or table_diff.extra_constraints
                    or table_diff.modified_constraints
                ):
                    result.add_issue(
                        ValidationSeverity.ERROR,
                        f"Table {schema}.{captured_table.name} has constraint differences",
                        object_type="table",
                        object_name=captured_table.name,
                        property_name="constraints",
                    )

                # Check other property differences
                comment_changed = getattr(table_diff, "comment_changed", None)
                if comment_changed:
                    result.add_issue(
                        ValidationSeverity.WARNING,
                        f"Table {schema}.{captured_table.name} comment differs",
                        object_type="table",
                        object_name=captured_table.name,
                        property_name="comment",
                    )

        result.metadata["captured_count"] = len(captured_tables)
        result.metadata["live_count"] = len(live_tables)
        result.metadata["common_count"] = len(common_names)

        return result

    def validate_indexes(
        self,
        captured_indexes: List[Index],
        live_indexes: List[Index],
        schema: str,
        table: Optional[str] = None,
    ) -> ValidationResult:
        """Validate accuracy of captured indexes.

        Args:
            captured_indexes: List of captured Index objects
            live_indexes: List of live Index objects
            schema: Schema name
            table: Optional table name to filter by

        Returns:
            ValidationResult with accuracy issues
        """
        result = ValidationResult(validator_name="AccuracyValidator")

        # Filter by table if specified
        if table:
            captured_indexes = [idx for idx in captured_indexes if idx.table_name == table]
            live_indexes = [idx for idx in live_indexes if idx.table_name == table]

        # Normalize index names
        captured_map = {self._normalize_name(idx.name): idx for idx in captured_indexes}
        live_map = {self._normalize_name(idx.name): idx for idx in live_indexes}

        # Check for missing indexes
        for captured_name, captured_idx in captured_map.items():
            if captured_name not in live_map:
                result.add_issue(
                    ValidationSeverity.ERROR,
                    f"Captured index {schema}.{captured_idx.name} not found in live database",
                    object_type="index",
                    object_name=captured_idx.name,
                    expected_value="exists",
                    actual_value="not found",
                )

        # Check for extra indexes
        for live_name, live_idx in live_map.items():
            if live_name not in captured_map:
                result.add_issue(
                    ValidationSeverity.WARNING,
                    f"Live index {schema}.{live_idx.name} not in captured state",
                    object_type="index",
                    object_name=live_idx.name,
                    expected_value="not captured",
                    actual_value="exists",
                )

        result.metadata["captured_count"] = len(captured_indexes)
        result.metadata["live_count"] = len(live_indexes)

        return result

    def validate_round_trip(
        self,
        original_tables: List[Table],
        schema: str,
    ) -> ValidationResult:
        """Validate round-trip accuracy by re-introspecting.

        This method:
        1. Re-introspects the database
        2. Compares with original capture
        3. Detects any drift

        Args:
            original_tables: Original captured tables
            schema: Schema name

        Returns:
            ValidationResult with round-trip issues
        """
        result = ValidationResult(validator_name="AccuracyValidator")

        if not self.introspector:
            result.add_issue(
                ValidationSeverity.WARNING,
                "No introspector provided for round-trip validation",
            )
            return result

        try:
            # Re-introspect
            live_tables = self.introspector.get_tables(schema)

            # Compare
            accuracy_result = self.validate_tables(original_tables, live_tables, schema)
            result.issues.extend(accuracy_result.issues)
            if not accuracy_result.passed:
                result.passed = False

            result.metadata["round_trip_successful"] = accuracy_result.passed

        except Exception as e:
            result.add_issue(
                ValidationSeverity.ERROR,
                f"Round-trip validation failed: {e}",
            )
            result.metadata["round_trip_successful"] = False

        return result

    def validate_all(
        self,
        captured_objects: Dict[str, List],
        live_objects: Dict[str, List],
        schema: str,
    ) -> ValidationResult:
        """Validate accuracy of all object types.

        Args:
            captured_objects: Dictionary with keys like 'tables', 'indexes', 'views'
            live_objects: Dictionary with same keys containing live objects
            schema: Schema name

        Returns:
            ValidationResult with all accuracy issues
        """
        result = ValidationResult(validator_name="AccuracyValidator")

        # Validate tables
        if "tables" in captured_objects and "tables" in live_objects:
            table_result = self.validate_tables(
                captured_objects["tables"],
                live_objects["tables"],
                schema,
            )
            result.issues.extend(table_result.issues)
            if not table_result.passed:
                result.passed = False

        # Validate indexes
        if "indexes" in captured_objects and "indexes" in live_objects:
            index_result = self.validate_indexes(
                captured_objects["indexes"],
                live_objects["indexes"],
                schema,
            )
            result.issues.extend(index_result.issues)
            if not index_result.passed:
                result.passed = False

        result.metadata["object_types_validated"] = list(captured_objects.keys())

        return result

    @staticmethod
    def _normalize_name(name: Optional[str]) -> str:
        """Normalize name for comparison (case-insensitive).

        Args:
            name: Object name

        Returns:
            Normalized name (lowercase)
        """
        if name is None:
            return ""
        return str(name).lower().strip()
