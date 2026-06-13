"""
Utilities for schema validation and comparison.

Provides functions to:
- Compare schemas for equivalence
- Validate property preservation
- Generate comprehensive test schemas
- Report validation results
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.comparison.comparator import ObjectComparator
from core.comparison.type_normalizer import DataTypeNormalizer
from core.sql_model.index import Index
from core.sql_model.sequence import Sequence
from core.sql_model.table import Table
from core.sql_model.view import View


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Represents a validation issue."""

    object_type: str
    object_name: str
    property_name: Optional[str]
    severity: ValidationSeverity
    message: str
    expected: Any = None
    actual: Any = None


@dataclass
class ValidationResult:
    """Results of schema validation."""

    success: bool
    issues: List[ValidationIssue]
    object_counts: Dict[str, int]
    property_counts: Dict[str, int]


class SchemaEquivalenceChecker:
    """Checks if two schemas are equivalent."""

    def __init__(self, dialect: str = "postgresql"):
        """Initialize the equivalence checker."""
        self.dialect = dialect
        self.type_normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.type_normalizer)

    def compare_schemas(
        self,
        expected_schema: Dict[str, List[Any]],
        actual_schema: Dict[str, List[Any]],
    ) -> ValidationResult:
        """Compare two schemas and return validation results."""
        issues: List[ValidationIssue] = []
        object_counts: Dict[str, int] = {}
        property_counts: Dict[str, int] = {}

        # Compare each object type
        for obj_type in ["tables", "views", "indexes", "sequences", "procedures", "functions"]:
            expected_objects = expected_schema.get(obj_type, [])
            actual_objects = actual_schema.get(obj_type, [])

            expected_count = len(expected_objects)
            actual_count = len(actual_objects)
            object_counts[obj_type] = {"expected": expected_count, "actual": actual_count}

            if expected_count != actual_count:
                issues.append(
                    ValidationIssue(
                        object_type=obj_type,
                        object_name="*",
                        property_name=None,
                        severity=ValidationSeverity.ERROR,
                        message=f"Object count mismatch: expected {expected_count}, got {actual_count}",
                        expected=expected_count,
                        actual=actual_count,
                    )
                )

            # Compare individual objects
            if obj_type == "tables":
                issues.extend(self._compare_tables(expected_objects, actual_objects))
            elif obj_type == "views":
                issues.extend(self._compare_views(expected_objects, actual_objects))
            elif obj_type == "indexes":
                issues.extend(self._compare_indexes(expected_objects, actual_objects))
            elif obj_type == "sequences":
                issues.extend(self._compare_sequences(expected_objects, actual_objects))

        # Determine success
        error_count = sum(1 for issue in issues if issue.severity == ValidationSeverity.ERROR)
        success = error_count == 0

        return ValidationResult(
            success=success,
            issues=issues,
            object_counts=object_counts,
            property_counts=property_counts,
        )

    def _compare_tables(
        self, expected_tables: List[Table], actual_tables: List[Table]
    ) -> List[ValidationIssue]:
        """Compare tables and return issues."""
        issues: List[ValidationIssue] = []

        # Create lookup maps
        expected_map = {t.name.lower(): t for t in expected_tables}
        actual_map = {t.name.lower(): t for t in actual_tables}

        # Check for missing tables
        for name, table in expected_map.items():
            if name not in actual_map:
                issues.append(
                    ValidationIssue(
                        object_type="table",
                        object_name=table.name,
                        property_name=None,
                        severity=ValidationSeverity.ERROR,
                        message=f"Table '{table.name}' is missing",
                    )
                )
                continue

            # Compare table properties
            actual_table = actual_map[name]
            diff = self.comparator.compare_tables(table, actual_table, self.dialect)

            if diff.has_diffs:
                # Report column differences
                for col_name in diff.missing_columns:
                    issues.append(
                        ValidationIssue(
                            object_type="table",
                            object_name=table.name,
                            property_name="column",
                            severity=ValidationSeverity.ERROR,
                            message=f"Column '{col_name}' is missing",
                        )
                    )

                for col_name in diff.extra_columns:
                    issues.append(
                        ValidationIssue(
                            object_type="table",
                            object_name=table.name,
                            property_name="column",
                            severity=ValidationSeverity.ERROR,
                            message=f"Unexpected column '{col_name}'",
                        )
                    )

                # Report column modifications
                for col_diff in diff.modified_columns:
                    if col_diff.data_type_diff:
                        issues.append(
                            ValidationIssue(
                                object_type="table",
                                object_name=table.name,
                                property_name=f"column.{col_diff.column_name}.data_type",
                                severity=ValidationSeverity.ERROR,
                                message=f"Data type mismatch for column '{col_diff.column_name}'",
                                expected=col_diff.data_type_diff[0],
                                actual=col_diff.data_type_diff[1],
                            )
                        )

                    if col_diff.nullable_diff:
                        issues.append(
                            ValidationIssue(
                                object_type="table",
                                object_name=table.name,
                                property_name=f"column.{col_diff.column_name}.nullable",
                                severity=ValidationSeverity.ERROR,
                                message=f"Nullable mismatch for column '{col_diff.column_name}'",
                                expected=col_diff.nullable_diff[0],
                                actual=col_diff.nullable_diff[1],
                            )
                        )

        # Check for extra tables
        for name, table in actual_map.items():
            if name not in expected_map:
                issues.append(
                    ValidationIssue(
                        object_type="table",
                        object_name=table.name,
                        property_name=None,
                        severity=ValidationSeverity.WARNING,
                        message=f"Unexpected table '{table.name}'",
                    )
                )

        return issues

    def _compare_views(
        self, expected_views: List[View], actual_views: List[View]
    ) -> List[ValidationIssue]:
        """Compare views and return issues."""
        issues: List[ValidationIssue] = []

        expected_map = {v.name.lower(): v for v in expected_views}
        actual_map = {v.name.lower(): v for v in actual_views}

        for name, view in expected_map.items():
            if name not in actual_map:
                issues.append(
                    ValidationIssue(
                        object_type="view",
                        object_name=view.name,
                        property_name=None,
                        severity=ValidationSeverity.ERROR,
                        message=f"View '{view.name}' is missing",
                    )
                )
                continue

            actual_view = actual_map[name]
            diff = self.comparator.compare_views(view, actual_view, self.dialect)

            if diff and diff.has_diffs:
                if diff.definition_changed:
                    issues.append(
                        ValidationIssue(
                            object_type="view",
                            object_name=view.name,
                            property_name="definition",
                            severity=ValidationSeverity.ERROR,
                            message=f"View definition changed for '{view.name}'",
                            expected=diff.expected_definition,
                            actual=diff.actual_definition,
                        )
                    )

        return issues

    def _compare_indexes(
        self, expected_indexes: List[Index], actual_indexes: List[Index]
    ) -> List[ValidationIssue]:
        """Compare indexes and return issues."""
        issues: List[ValidationIssue] = []

        expected_map = {idx.name.lower(): idx for idx in expected_indexes if idx.name}
        actual_map = {idx.name.lower(): idx for idx in actual_indexes if idx.name}

        for name, index in expected_map.items():
            if name not in actual_map:
                issues.append(
                    ValidationIssue(
                        object_type="index",
                        object_name=index.name or "unnamed",
                        property_name=None,
                        severity=ValidationSeverity.ERROR,
                        message=f"Index '{index.name}' is missing",
                    )
                )
                continue

            actual_index = actual_map[name]
            diff = self.comparator.compare_indexes(index, actual_index, self.dialect)

            if diff and diff.has_diffs:
                if diff.columns_changed:
                    issues.append(
                        ValidationIssue(
                            object_type="index",
                            object_name=index.name or "unnamed",
                            property_name="columns",
                            severity=ValidationSeverity.ERROR,
                            message=f"Index columns changed for '{index.name}'",
                            expected=diff.expected_columns,
                            actual=diff.actual_columns,
                        )
                    )

        return issues

    def _compare_sequences(
        self, expected_sequences: List[Sequence], actual_sequences: List[Sequence]
    ) -> List[ValidationIssue]:
        """Compare sequences and return issues."""
        issues: List[ValidationIssue] = []

        expected_map = {seq.name.lower(): seq for seq in expected_sequences}
        actual_map = {seq.name.lower(): seq for seq in actual_sequences}

        for name, sequence in expected_map.items():
            if name not in actual_map:
                issues.append(
                    ValidationIssue(
                        object_type="sequence",
                        object_name=sequence.name,
                        property_name=None,
                        severity=ValidationSeverity.ERROR,
                        message=f"Sequence '{sequence.name}' is missing",
                    )
                )
                continue

            actual_sequence = actual_map[name]
            diff = self.comparator.compare_sequences(sequence, actual_sequence, self.dialect)

            if diff and diff.has_diffs:
                if diff.start_value_changed:
                    issues.append(
                        ValidationIssue(
                            object_type="sequence",
                            object_name=sequence.name,
                            property_name="start_value",
                            severity=ValidationSeverity.ERROR,
                            message=f"Start value changed for sequence '{sequence.name}'",
                            expected=diff.start_value_changed[0],
                            actual=diff.start_value_changed[1],
                        )
                    )

        return issues


class PropertyPreservationChecker:
    """Checks that properties are preserved during round-trip."""

    def __init__(self, dialect: str = "postgresql"):
        """Initialize the property preservation checker."""
        self.dialect = dialect
        self.comparator = ObjectComparator(DataTypeNormalizer())

    def check_property_preservation(
        self,
        original_objects: Dict[str, List[Any]],
        reintrospected_objects: Dict[str, List[Any]],
    ) -> ValidationResult:
        """Check that all properties are preserved."""
        issues: List[ValidationIssue] = []
        property_counts: Dict[str, int] = {}

        # Check tables
        if "tables" in original_objects and "tables" in reintrospected_objects:
            table_issues, table_props = self._check_table_properties(
                original_objects["tables"], reintrospected_objects["tables"]
            )
            issues.extend(table_issues)
            property_counts["tables"] = table_props

        # Check views
        if "views" in original_objects and "views" in reintrospected_objects:
            view_issues, view_props = self._check_view_properties(
                original_objects["views"], reintrospected_objects["views"]
            )
            issues.extend(view_issues)
            property_counts["views"] = view_props

        success = all(issue.severity != ValidationSeverity.ERROR for issue in issues)

        return ValidationResult(
            success=success,
            issues=issues,
            object_counts={},
            property_counts=property_counts,
        )

    def _check_table_properties(
        self, original_tables: List[Table], reintrospected_tables: List[Table]
    ) -> Tuple[List[ValidationIssue], Dict[str, int]]:
        """Check table property preservation."""
        issues: List[ValidationIssue] = []
        property_counts: Dict[str, int] = {
            "columns": 0,
            "constraints": 0,
            "indexes": 0,
        }

        original_map = {t.name.lower(): t for t in original_tables}
        reintrospected_map = {t.name.lower(): t for t in reintrospected_tables}

        for name, original_table in original_map.items():
            if name not in reintrospected_map:
                issues.append(
                    ValidationIssue(
                        object_type="table",
                        object_name=original_table.name,
                        property_name=None,
                        severity=ValidationSeverity.ERROR,
                        message=f"Table '{original_table.name}' missing after round-trip",
                    )
                )
                continue

            reintrospected_table = reintrospected_map[name]
            diff = self.comparator.compare_tables(
                original_table, reintrospected_table, self.dialect
            )

            if diff.has_diffs:
                # Count properties
                property_counts["columns"] += len(original_table.columns)
                property_counts["constraints"] += len(original_table.constraints)

                # Report issues
                for col_name in diff.missing_columns:
                    issues.append(
                        ValidationIssue(
                            object_type="table",
                            object_name=original_table.name,
                            property_name="column",
                            severity=ValidationSeverity.ERROR,
                            message=f"Column '{col_name}' not preserved",
                        )
                    )

                for col_diff in diff.modified_columns:
                    issues.append(
                        ValidationIssue(
                            object_type="table",
                            object_name=original_table.name,
                            property_name=f"column.{col_diff.column_name}",
                            severity=ValidationSeverity.ERROR,
                            message=f"Column '{col_diff.column_name}' properties changed",
                        )
                    )

        return issues, property_counts

    def _check_view_properties(
        self, original_views: List[View], reintrospected_views: List[View]
    ) -> Tuple[List[ValidationIssue], Dict[str, int]]:
        """Check view property preservation."""
        issues: List[ValidationIssue] = []
        property_counts: Dict[str, int] = {"views": len(original_views)}

        original_map = {v.name.lower(): v for v in original_views}
        reintrospected_map = {v.name.lower(): v for v in reintrospected_views}

        for name, original_view in original_map.items():
            if name not in reintrospected_map:
                issues.append(
                    ValidationIssue(
                        object_type="view",
                        object_name=original_view.name,
                        property_name=None,
                        severity=ValidationSeverity.ERROR,
                        message=f"View '{original_view.name}' missing after round-trip",
                    )
                )
                continue

            reintrospected_view = reintrospected_map[name]
            diff = self.comparator.compare_views(original_view, reintrospected_view, self.dialect)

            if diff and diff.has_diffs:
                if diff.definition_changed:
                    issues.append(
                        ValidationIssue(
                            object_type="view",
                            object_name=original_view.name,
                            property_name="definition",
                            severity=ValidationSeverity.ERROR,
                            message=f"View definition not preserved for '{original_view.name}'",
                        )
                    )

        return issues, property_counts


def generate_validation_report(result: ValidationResult) -> str:
    """Generate a human-readable validation report."""
    lines = [
        "=" * 80,
        "SCHEMA VALIDATION REPORT",
        "=" * 80,
        f"Success: {'✓ PASSED' if result.success else '✗ FAILED'}",
        "",
    ]

    # Object counts
    if result.object_counts:
        lines.append("Object Counts:")
        for obj_type, counts in result.object_counts.items():
            if isinstance(counts, dict):
                lines.append(
                    f"  {obj_type}: expected={counts.get('expected', 0)}, actual={counts.get('actual', 0)}"
                )
            else:
                lines.append(f"  {obj_type}: {counts}")
        lines.append("")

    # Property counts
    if result.property_counts:
        lines.append("Property Counts:")
        for prop_type, count in result.property_counts.items():
            lines.append(f"  {prop_type}: {count}")
        lines.append("")

    # Issues
    if result.issues:
        error_count = sum(1 for i in result.issues if i.severity == ValidationSeverity.ERROR)
        warning_count = sum(1 for i in result.issues if i.severity == ValidationSeverity.WARNING)

        lines.append(
            f"Issues: {len(result.issues)} (Errors: {error_count}, Warnings: {warning_count})"
        )
        lines.append("")

        # Group by severity
        errors = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in result.issues if i.severity == ValidationSeverity.WARNING]

        if errors:
            lines.append("Errors:")
            for issue in errors[:10]:  # Show first 10
                lines.append(f"  - [{issue.object_type}] {issue.object_name}: {issue.message}")
            if len(errors) > 10:
                lines.append(f"  ... and {len(errors) - 10} more errors")
            lines.append("")

        if warnings:
            lines.append("Warnings:")
            for issue in warnings[:10]:  # Show first 10
                lines.append(f"  - [{issue.object_type}] {issue.object_name}: {issue.message}")
            if len(warnings) > 10:
                lines.append(f"  ... and {len(warnings) - 10} more warnings")
            lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)
