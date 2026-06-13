"""
Property-level comparison for SQL model objects.

This module provides detailed comparison of SQL objects at the property level,
identifying exactly which properties differ between two versions of the same object.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table


@dataclass
class PropertyDifference:
    """Represents a difference in a single property."""

    object_type: str  # "table", "column", "constraint"
    object_name: str
    property_name: str
    original_value: Any
    regenerated_value: Any
    severity: str = "warning"  # "error", "warning", "info"

    def __str__(self) -> str:
        return (
            f"{self.object_type} '{self.object_name}' property '{self.property_name}': "
            f"{self.original_value} → {self.regenerated_value}"
        )


@dataclass
class ComparisonResult:
    """Result of comparing two SQL objects."""

    differences: List[PropertyDifference] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def is_match(self) -> bool:
        """Check if objects match (no errors)."""
        return len([d for d in self.differences if d.severity == "error"]) == 0

    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len([d for d in self.differences if d.severity == "warning"]) > 0

    def get_summary(self) -> Dict[str, int]:
        """Get summary statistics."""
        return {
            "total_differences": len(self.differences),
            "errors": len([d for d in self.differences if d.severity == "error"]),
            "warnings": len([d for d in self.differences if d.severity == "warning"]),
            "info": len([d for d in self.differences if d.severity == "info"]),
        }


class PropertyComparator:
    """Compares SQL objects at the property level."""

    def __init__(self, dialect: str = "", strict: bool = False):
        """
        Initialize the comparator.

        Args:
            dialect: SQL dialect for dialect-specific comparison rules
            strict: If True, treat warnings as errors
        """
        self.dialect = dialect.lower()
        self.strict = strict

    def compare_tables(self, original: Table, regenerated: Table) -> ComparisonResult:
        """
        Compare two tables at the property level.

        Args:
            original: Original table from introspection
            regenerated: Regenerated table from round-trip

        Returns:
            Comparison result with detailed differences
        """
        result = ComparisonResult()

        # Compare table-level properties
        self._compare_table_properties(original, regenerated, result)

        # Compare columns
        self._compare_columns(original, regenerated, result)

        # Compare constraints
        self._compare_constraints(original, regenerated, result)

        return result

    def _compare_table_properties(
        self, original: Table, regenerated: Table, result: ComparisonResult
    ) -> None:
        """Compare table-level properties."""
        # Table name
        if original.name != regenerated.name:
            result.differences.append(
                PropertyDifference(
                    object_type="table",
                    object_name=original.name,
                    property_name="name",
                    original_value=original.name,
                    regenerated_value=regenerated.name,
                    severity="error",
                )
            )

        # Schema
        if original.schema != regenerated.schema:
            # This is expected if testing in different schema
            result.differences.append(
                PropertyDifference(
                    object_type="table",
                    object_name=original.name,
                    property_name="schema",
                    original_value=original.schema,
                    regenerated_value=regenerated.schema,
                    severity="info",
                )
            )

        # Temporary flag
        if getattr(original, "temporary", False) != getattr(regenerated, "temporary", False):
            result.differences.append(
                PropertyDifference(
                    object_type="table",
                    object_name=original.name,
                    property_name="temporary",
                    original_value=getattr(original, "temporary", False),
                    regenerated_value=getattr(regenerated, "temporary", False),
                    severity="warning",
                )
            )

    def _compare_columns(
        self, original: Table, regenerated: Table, result: ComparisonResult
    ) -> None:
        """Compare columns between two tables."""
        if not original.columns or not regenerated.columns:
            if original.columns or regenerated.columns:
                result.errors.append(
                    f"Column count mismatch: {len(original.columns or [])} vs {len(regenerated.columns or [])}"
                )
            return

        # Compare column count
        if len(original.columns) != len(regenerated.columns):
            result.differences.append(
                PropertyDifference(
                    object_type="table",
                    object_name=original.name,
                    property_name="column_count",
                    original_value=len(original.columns),
                    regenerated_value=len(regenerated.columns),
                    severity="error",
                )
            )
            return  # Can't compare further if counts don't match

        # Compare each column
        orig_cols_by_name = {col.name.lower(): col for col in original.columns}
        regen_cols_by_name = {col.name.lower(): col for col in regenerated.columns}

        for col_name, orig_col in orig_cols_by_name.items():
            if col_name not in regen_cols_by_name:
                result.differences.append(
                    PropertyDifference(
                        object_type="column",
                        object_name=orig_col.name,
                        property_name="existence",
                        original_value="exists",
                        regenerated_value="missing",
                        severity="error",
                    )
                )
                continue

            regen_col = regen_cols_by_name[col_name]
            self._compare_column_properties(orig_col, regen_col, result)

        # Check for extra columns in regenerated
        for col_name in regen_cols_by_name:
            if col_name not in orig_cols_by_name:
                result.differences.append(
                    PropertyDifference(
                        object_type="column",
                        object_name=regen_cols_by_name[col_name].name,
                        property_name="existence",
                        original_value="missing",
                        regenerated_value="exists",
                        severity="error",
                    )
                )

    def _compare_column_properties(
        self, original: SqlColumn, regenerated: SqlColumn, result: ComparisonResult
    ) -> None:
        """Compare properties of two columns."""
        col_name = original.name

        # Data type (normalize for comparison)
        orig_type = self._normalize_data_type(original.data_type)
        regen_type = self._normalize_data_type(regenerated.data_type)
        if orig_type != regen_type:
            result.differences.append(
                PropertyDifference(
                    object_type="column",
                    object_name=col_name,
                    property_name="data_type",
                    original_value=original.data_type,
                    regenerated_value=regenerated.data_type,
                    severity="error",
                )
            )

        # Nullable
        if original.nullable != regenerated.nullable:
            result.differences.append(
                PropertyDifference(
                    object_type="column",
                    object_name=col_name,
                    property_name="nullable",
                    original_value=original.nullable,
                    regenerated_value=regenerated.nullable,
                    severity="warning",
                )
            )

        # Default value (normalize for comparison)
        orig_default = self._normalize_default_value(original.default_value)
        regen_default = self._normalize_default_value(regenerated.default_value)
        if orig_default != regen_default:
            result.differences.append(
                PropertyDifference(
                    object_type="column",
                    object_name=col_name,
                    property_name="default_value",
                    original_value=original.default_value,
                    regenerated_value=regenerated.default_value,
                    severity="warning",
                )
            )

        # Auto-increment / Identity
        orig_auto = getattr(original, "auto_increment", False) or getattr(
            original, "is_identity", False
        )
        regen_auto = getattr(regenerated, "auto_increment", False) or getattr(
            regenerated, "is_identity", False
        )
        if orig_auto != regen_auto:
            result.differences.append(
                PropertyDifference(
                    object_type="column",
                    object_name=col_name,
                    property_name="auto_increment",
                    original_value=orig_auto,
                    regenerated_value=regen_auto,
                    severity="warning",
                )
            )

        # Computed column
        orig_computed = getattr(original, "is_computed", False)
        regen_computed = getattr(regenerated, "is_computed", False)
        if orig_computed != regen_computed:
            result.differences.append(
                PropertyDifference(
                    object_type="column",
                    object_name=col_name,
                    property_name="is_computed",
                    original_value=orig_computed,
                    regenerated_value=regen_computed,
                    severity="warning",
                )
            )

    def _compare_constraints(
        self, original: Table, regenerated: Table, result: ComparisonResult
    ) -> None:
        """Compare constraints between two tables."""
        if not original.constraints and not regenerated.constraints:
            return

        orig_constraints = original.constraints or []
        regen_constraints = regenerated.constraints or []

        # Group constraints by type
        orig_by_type = self._group_constraints_by_type(orig_constraints)
        regen_by_type = self._group_constraints_by_type(regen_constraints)

        # Compare each type
        all_types = set(orig_by_type.keys()) | set(regen_by_type.keys())

        for constraint_type in all_types:
            orig_list = orig_by_type.get(constraint_type, [])
            regen_list = regen_by_type.get(constraint_type, [])

            if len(orig_list) != len(regen_list):
                result.differences.append(
                    PropertyDifference(
                        object_type="constraint",
                        object_name=str(constraint_type),  # lint: allow-enum-str
                        property_name="count",
                        original_value=len(orig_list),
                        regenerated_value=len(regen_list),
                        severity="warning",
                    )
                )

            # Compare constraint details (column names, etc.)
            self._compare_constraint_lists(orig_list, regen_list, constraint_type, result)

    def _compare_constraint_lists(
        self,
        orig_list: List[SqlConstraint],
        regen_list: List[SqlConstraint],
        constraint_type: ConstraintType,
        result: ComparisonResult,
    ) -> None:
        """Compare lists of constraints of the same type."""
        # Create signatures for matching
        orig_sigs = {self._constraint_signature(c): c for c in orig_list}
        regen_sigs = {self._constraint_signature(c): c for c in regen_list}

        # Find missing constraints
        for sig in orig_sigs:
            if sig not in regen_sigs:
                constraint = orig_sigs[sig]
                result.differences.append(
                    PropertyDifference(
                        object_type="constraint",
                        object_name=constraint.name or str(constraint_type),  # lint: allow-enum-str
                        property_name="existence",
                        original_value=f"columns: {constraint.column_names}",
                        regenerated_value="missing",
                        severity="warning",
                    )
                )

        # Find extra constraints
        for sig in regen_sigs:
            if sig not in orig_sigs:
                constraint = regen_sigs[sig]
                result.differences.append(
                    PropertyDifference(
                        object_type="constraint",
                        object_name=constraint.name or str(constraint_type),  # lint: allow-enum-str
                        property_name="existence",
                        original_value="missing",
                        regenerated_value=f"columns: {constraint.column_names}",
                        severity="info",  # Extra constraints might be OK
                    )
                )

    def _normalize_data_type(self, data_type: str) -> str:
        """Normalize data type for comparison."""
        if not data_type:
            return ""

        # Remove whitespace and convert to uppercase
        normalized = data_type.strip().upper()

        # Dialect-specific normalizations from plugin quirks (Wave E).
        from db.provider_registry import ProviderRegistry

        type_map = ProviderRegistry.get_quirks(self.dialect).type_equivalents()
        if type_map:
            base_type = normalized.split("(")[0]
            if base_type in type_map:
                normalized = type_map[base_type]
                if "(" in data_type:
                    normalized += data_type[data_type.index("(") :]

        return normalized

    def _normalize_default_value(self, default_value: Optional[str]) -> Optional[str]:
        """Normalize default value for comparison."""
        if not default_value:
            return None

        # Remove extra whitespace
        normalized = " ".join(default_value.split())

        # Remove quotes if present
        if normalized.startswith("'") and normalized.endswith("'"):
            normalized = normalized[1:-1]

        return normalized

    def _group_constraints_by_type(
        self, constraints: List[SqlConstraint]
    ) -> Dict[ConstraintType, List[SqlConstraint]]:
        """Group constraints by type."""
        grouped: Dict[ConstraintType, List[SqlConstraint]] = {}
        for constraint in constraints:
            if constraint.constraint_type not in grouped:
                grouped[constraint.constraint_type] = []
            grouped[constraint.constraint_type].append(constraint)
        return grouped

    def _constraint_signature(self, constraint: SqlConstraint) -> str:
        """Create a signature for constraint matching."""
        # Sort column names for consistent comparison
        cols = tuple(sorted(c.lower() for c in constraint.column_names))
        return f"{constraint.constraint_type.value}:{cols}"
