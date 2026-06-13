"""Round-trip comparison logic extracted from RoundTripTester.

Extracted from round_trip_tester.py (story 20-16) to reduce file size.
Handles comparison of original vs re-introspected database objects.
"""

from typing import Any, Dict, List, Optional

from core.comparison.comparator import ObjectComparator
from core.comparison.diff_models import IndexDiff, ViewDiff
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.view import View


class RoundTripComparator:
    """Compares original and re-introspected database objects for round-trip testing."""

    def __init__(self, dialect: str, log, comparator: ObjectComparator):
        """Bind the dialect, log sink, and underlying object comparator used for round-trip checks."""
        self.dialect = dialect
        self.log = log
        self.comparator = comparator

    def compare_tables(
        self, original: List[Table], reintrospected: List[Table], results: Dict[str, Any]
    ) -> None:
        """Compare tables with detailed property validation."""
        original_map = {t.name.lower(): t for t in original}
        reintrospected_map = {t.name.lower(): t for t in reintrospected}

        for table_name, original_table in original_map.items():
            if table_name not in reintrospected_map:
                results["tables"]["differences"].append(
                    {
                        "table": table_name,
                        "issue": "missing_in_reintrospection",
                        "severity": "error",
                    }
                )
                continue

            reintrospected_table = reintrospected_map[table_name]
            diff = self.comparator.compare_tables(
                original_table, reintrospected_table, self.dialect
            )

            if diff.has_diffs:
                # Create detailed difference report
                diff_details: Dict[str, Any] = {
                    "table": table_name,
                    "severity": "error" if diff.severity.value == "error" else "warning",
                }

                # Add specific property differences
                if diff.missing_columns:
                    diff_details["missing_columns"] = diff.missing_columns
                if diff.extra_columns:
                    diff_details["extra_columns"] = diff.extra_columns
                if diff.modified_columns:
                    diff_details["modified_columns"] = [
                        {
                            "column": col_diff.column_name,
                            "data_type_diff": col_diff.data_type_diff,
                            "nullable_diff": col_diff.nullable_diff,
                            "default_diff": col_diff.default_diff,
                            "identity_diff": col_diff.identity_diff,
                            "computed_diff": col_diff.computed_diff,
                            "collation_diff": col_diff.collation_diff,
                        }
                        for col_diff in diff.modified_columns
                    ]
                if diff.missing_constraints:
                    diff_details["missing_constraints"] = diff.missing_constraints
                if diff.extra_constraints:
                    diff_details["extra_constraints"] = diff.extra_constraints
                if diff.modified_constraints:
                    diff_details["modified_constraints"] = [
                        {
                            "constraint": const_diff.constraint_name,
                            "columns_diff": const_diff.columns_diff,
                            "references_diff": const_diff.references_diff,
                            "check_clause_diff": const_diff.check_clause_diff,
                        }
                        for const_diff in diff.modified_constraints
                    ]

                # Add table-level property differences
                if getattr(diff, "temporary_changed", False):
                    diff_details["temporary_changed"] = True
                if getattr(diff, "partition_method_changed", False):
                    diff_details["partition_method_changed"] = True
                if getattr(diff, "partition_columns_changed", False):
                    diff_details["partition_columns_changed"] = True

                results["tables"]["differences"].append(diff_details)

                # Log detailed differences for debugging
                self.log.debug(f"Table '{table_name}' differences: {diff_details}")

    def compare_views(
        self, original: List[View], reintrospected: List[View], results: Dict[str, Any]
    ) -> None:
        """Compare views with detailed property validation."""
        if not original or not reintrospected:
            return

        original_map = {v.name.lower(): v for v in original}
        reintrospected_map = {v.name.lower(): v for v in reintrospected}

        for view_name, original_view in original_map.items():
            if view_name not in reintrospected_map:
                results["views"]["differences"].append(
                    {
                        "view": view_name,
                        "issue": "missing_in_reintrospection",
                        "severity": "error",
                    }
                )
                continue

            reintrospected_view = reintrospected_map[view_name]
            view_diff: Optional[ViewDiff] = self.comparator.compare_views(
                original_view, reintrospected_view, self.dialect
            )

            if view_diff and view_diff.has_diffs:
                # Create detailed difference report
                diff_details: Dict[str, Any] = {
                    "view": view_name,
                    "severity": ("error" if view_diff.severity.value == "error" else "warning"),
                }

                if view_diff.definition_changed:
                    diff_details["definition_changed"] = True
                    diff_details["expected_definition"] = view_diff.expected_definition
                    diff_details["actual_definition"] = view_diff.actual_definition
                if getattr(view_diff, "materialized_changed", None):
                    diff_details["materialized_changed"] = view_diff.materialized_changed
                if getattr(view_diff, "algorithm_changed", None):
                    diff_details["algorithm_changed"] = view_diff.algorithm_changed
                if getattr(view_diff, "security_definer_changed", None):
                    diff_details["security_definer_changed"] = view_diff.security_definer_changed

                results["views"]["differences"].append(diff_details)

                # Log detailed differences for debugging
                self.log.debug(f"View '{view_name}' differences: {diff_details}")

    def compare_indexes(
        self, original: List[Index], reintrospected: List[Index], results: Dict[str, Any]
    ) -> None:
        """Compare indexes with detailed property validation."""
        if not original or not reintrospected:
            return

        original_map = {idx.name.lower(): idx for idx in original if idx.name}
        reintrospected_map = {idx.name.lower(): idx for idx in reintrospected if idx.name}

        for index_name, original_index in original_map.items():
            if index_name not in reintrospected_map:
                results["indexes"]["differences"].append(
                    {
                        "index": index_name,
                        "issue": "missing_in_reintrospection",
                        "severity": "error",
                    }
                )
                continue

            reintrospected_index = reintrospected_map[index_name]
            index_diff: Optional[IndexDiff] = self.comparator.compare_indexes(
                original_index, reintrospected_index, self.dialect
            )

            if index_diff and index_diff.has_diffs:
                # Create detailed difference report
                diff_details: Dict[str, Any] = {
                    "index": index_name,
                    "severity": ("error" if index_diff.severity.value == "error" else "warning"),
                }

                if index_diff.columns_changed:
                    diff_details["columns_changed"] = True
                    diff_details["expected_columns"] = index_diff.expected_columns
                    diff_details["actual_columns"] = index_diff.actual_columns
                if getattr(index_diff, "uniqueness_changed", None):
                    diff_details["uniqueness_changed"] = index_diff.uniqueness_changed
                if getattr(index_diff, "type_changed", None):
                    diff_details["type_changed"] = index_diff.type_changed
                if getattr(index_diff, "include_columns_changed", None):
                    diff_details["include_columns_changed"] = index_diff.include_columns_changed

                results["indexes"]["differences"].append(diff_details)

                # Log detailed differences for debugging
                self.log.debug(f"Index '{index_name}' differences: {diff_details}")

    def compare_objects_by_name(
        self, obj_type: str, original: List[Any], reintrospected: List[Any], results: Dict[str, Any]
    ) -> None:
        """Compare objects by name (basic comparison for types without full comparators)."""
        original_names = {getattr(obj, "name", "").lower() for obj in original}
        reintrospected_names = {getattr(obj, "name", "").lower() for obj in reintrospected}

        missing = original_names - reintrospected_names
        extra = reintrospected_names - original_names

        for name in missing:
            results[obj_type]["differences"].append(
                {
                    obj_type[:-1]: name,  # Remove 's' from plural
                    "issue": "missing_in_reintrospection",
                    "severity": "error",
                }
            )

        for name in extra:
            results[obj_type]["differences"].append(
                {
                    obj_type[:-1]: name,
                    "issue": "extra_in_reintrospection",
                    "severity": "warning",
                }
            )

    @staticmethod
    def get_summary(results: dict, test_object_types: list) -> str:
        """Get a human-readable summary of test results."""
        lines = [
            "=" * 80,
            "ROUND-TRIP TEST SUMMARY",
            "=" * 80,
            f"Success: {'✓ PASSED' if results['success'] else '✗ FAILED'}",
            "",
            "Object Counts:",
        ]

        for obj_type in test_object_types:
            if obj_type in results:
                original = results[obj_type]["original_count"]
                reintrospected = results[obj_type]["reintrospected_count"]
                lines.append(f"  {obj_type.capitalize()}: {original} → {reintrospected}")

        lines.append("")

        # Show differences
        for obj_type in test_object_types:
            if obj_type in results and results[obj_type]["differences"]:
                diff_count = len(results[obj_type]["differences"])
                lines.append(f"{obj_type.capitalize()} Differences: {diff_count}")
                for diff in results[obj_type]["differences"][:3]:  # Show first 3
                    issue = diff.get("issue", diff.get("diff", "unknown"))
                    obj_name = diff.get(obj_type[:-1], "unknown")
                    lines.append(f"  - {obj_name}: {issue}")

        if results["errors"]:
            lines.append(f"\nErrors: {len(results['errors'])}")
            for error in results["errors"][:5]:  # Show first 5
                lines.append(f"  - {error}")

        if results["warnings"]:
            lines.append(f"\nWarnings: {len(results['warnings'])}")
            for warning in results["warnings"][:5]:  # Show first 5
                lines.append(f"  - {warning}")

        lines.append("=" * 80)
        return "\n".join(lines)
