"""
Constraint validation layer to catch SQL generation issues before they happen.

This module validates SQL model objects to ensure they can be safely converted
to SQL without errors. It catches common issues like:
- Multiple primary keys
- Invalid foreign key references
- Duplicate constraint names
- Columns referenced by constraints that don't exist
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Optional, Set

from core.sql_model.base import ConstraintType, SqlColumn

if TYPE_CHECKING:
    from core.sql_model.table import Table


@dataclass
class ValidationError:
    """Represents a validation error in a SQL model."""

    severity: str  # "error", "warning", "info"
    message: str
    object_type: str  # "table", "column", "constraint"
    object_name: str
    property_name: Optional[str] = None
    suggestion: Optional[str] = None


class ConstraintValidator:
    """Validates SQL model constraints for correctness."""

    def __init__(self, dialect: str = ""):
        """
        Initialize the validator.

        Args:
            dialect: SQL dialect for dialect-specific validation; supplied by
                the caller (defaults to the unknown sentinel ``""``)
        """
        self.dialect = dialect.lower()

    def validate_table(self, table: "Table") -> List[ValidationError]:
        """
        Validate a table and all its constraints.

        Args:
            table: Table object to validate

        Returns:
            List of validation errors (empty if valid)
        """
        errors: List[ValidationError] = []

        # Validate table has columns
        if not table.columns:
            errors.append(
                ValidationError(
                    severity="error",
                    message="Table has no columns",
                    object_type="table",
                    object_name=table.name,
                    suggestion="Add at least one column to the table",
                )
            )
            return errors  # Can't validate further without columns

        # Validate primary keys
        errors.extend(self._validate_primary_keys(table))

        # Validate foreign keys
        errors.extend(self._validate_foreign_keys(table))

        # Validate unique constraints
        errors.extend(self._validate_unique_constraints(table))

        # Validate check constraints
        errors.extend(self._validate_check_constraints(table))

        # Validate constraint names
        errors.extend(self._validate_constraint_names(table))

        # Validate column references
        errors.extend(self._validate_column_references(table))

        # Validate computed columns
        errors.extend(self._validate_computed_columns(table))

        return errors

    def _validate_primary_keys(self, table: "Table") -> List[ValidationError]:
        """Validate primary key constraints."""
        errors: List[ValidationError] = []

        if not table.constraints:
            return errors

        # Find all PK constraints
        pk_constraints = [
            c for c in table.constraints if c.constraint_type == ConstraintType.PRIMARY_KEY
        ]

        # Check for multiple PKs
        if len(pk_constraints) > 1:
            # Check if they reference the same columns (duplicate)
            pk_column_sets = [frozenset(c.column_names) for c in pk_constraints]

            if len(set(pk_column_sets)) == 1:
                # All PKs reference same columns - duplicate definition
                errors.append(
                    ValidationError(
                        severity="error",
                        message=f"Duplicate PRIMARY KEY constraints detected ({len(pk_constraints)} constraints on same columns)",
                        object_type="constraint",
                        object_name="PRIMARY KEY",
                        suggestion="Remove duplicate PK constraints or use a single composite PK",
                    )
                )
            else:
                # Different column sets - invalid
                errors.append(
                    ValidationError(
                        severity="error",
                        message="Multiple PRIMARY KEY constraints with different columns detected",
                        object_type="constraint",
                        object_name="PRIMARY KEY",
                        suggestion="A table can only have one PRIMARY KEY. Use UNIQUE constraints for additional uniqueness requirements.",
                    )
                )

        # Check if PK columns exist and are NOT NULL
        for pk in pk_constraints:
            for col_name in pk.column_names:
                col = self._find_column(table, col_name)
                if not col:
                    errors.append(
                        ValidationError(
                            severity="error",
                            message=f"PRIMARY KEY references non-existent column '{col_name}'",
                            object_type="constraint",
                            object_name=pk.name or "PRIMARY KEY",
                            suggestion=f"Add column '{col_name}' or remove it from the PRIMARY KEY",
                        )
                    )
                elif col.nullable:
                    errors.append(
                        ValidationError(
                            severity="warning",
                            message=f"PRIMARY KEY column '{col_name}' is nullable",
                            object_type="constraint",
                            object_name=pk.name or "PRIMARY KEY",
                            property_name="nullable",
                            suggestion="PRIMARY KEY columns should be NOT NULL",
                        )
                    )

        # Check for inline PK + table-level PK conflict
        inline_pk_columns = [
            col.name for col in table.columns if getattr(col, "is_primary_key", False)
        ]

        if inline_pk_columns and pk_constraints:
            # Check if inline PK columns match table-level PK
            if len(pk_constraints) == 1 and len(inline_pk_columns) == 1:
                pk_cols = set(c.lower() for c in pk_constraints[0].column_names)
                inline_cols = set(c.lower() for c in inline_pk_columns)
                if pk_cols != inline_cols:
                    errors.append(
                        ValidationError(
                            severity="error",
                            message=f"Conflicting PRIMARY KEY definitions: inline PK on {inline_pk_columns} vs table-level PK on {pk_constraints[0].column_names}",
                            object_type="constraint",
                            object_name="PRIMARY KEY",
                            suggestion="Use either inline PK or table-level PK, not both",
                        )
                    )

        return errors

    def _validate_foreign_keys(self, table: "Table") -> List[ValidationError]:
        """Validate foreign key constraints."""
        errors: List[ValidationError] = []

        if not table.constraints:
            return errors

        fk_constraints = [
            c for c in table.constraints if c.constraint_type == ConstraintType.FOREIGN_KEY
        ]

        for fk in fk_constraints:
            # Check if FK columns exist
            for col_name in fk.column_names:
                if not self._find_column(table, col_name):
                    errors.append(
                        ValidationError(
                            severity="error",
                            message=f"FOREIGN KEY references non-existent column '{col_name}'",
                            object_type="constraint",
                            object_name=fk.name or "FOREIGN KEY",
                            suggestion=f"Add column '{col_name}' or remove it from the FOREIGN KEY",
                        )
                    )

            # Check if referenced table is specified
            if not fk.reference_table:
                errors.append(
                    ValidationError(
                        severity="error",
                        message="FOREIGN KEY missing referenced table",
                        object_type="constraint",
                        object_name=fk.name or "FOREIGN KEY",
                        suggestion="Specify the referenced table for the FOREIGN KEY",
                    )
                )

            # Check if referenced columns are specified
            if not fk.reference_columns:
                errors.append(
                    ValidationError(
                        severity="warning",
                        message="FOREIGN KEY missing referenced columns (will default to primary key)",
                        object_type="constraint",
                        object_name=fk.name or "FOREIGN KEY",
                        suggestion="Explicitly specify referenced columns for clarity",
                    )
                )

            # Check column count matches
            if fk.reference_columns and len(fk.column_names) != len(fk.reference_columns):
                errors.append(
                    ValidationError(
                        severity="error",
                        message=f"FOREIGN KEY column count mismatch: {len(fk.column_names)} local columns vs {len(fk.reference_columns)} referenced columns",
                        object_type="constraint",
                        object_name=fk.name or "FOREIGN KEY",
                        suggestion="Ensure the number of columns matches on both sides of the FOREIGN KEY",
                    )
                )

        return errors

    def _validate_unique_constraints(self, table: "Table") -> List[ValidationError]:
        """Validate UNIQUE constraints."""
        errors: List[ValidationError] = []

        if not table.constraints:
            return errors

        unique_constraints = [
            c for c in table.constraints if c.constraint_type == ConstraintType.UNIQUE
        ]

        for unique in unique_constraints:
            # Check if columns exist
            for col_name in unique.column_names:
                if not self._find_column(table, col_name):
                    errors.append(
                        ValidationError(
                            severity="error",
                            message=f"UNIQUE constraint references non-existent column '{col_name}'",
                            object_type="constraint",
                            object_name=unique.name or "UNIQUE",
                            suggestion=f"Add column '{col_name}' or remove it from the UNIQUE constraint",
                        )
                    )

            # Check for empty column list
            if not unique.column_names:
                errors.append(
                    ValidationError(
                        severity="error",
                        message="UNIQUE constraint has no columns",
                        object_type="constraint",
                        object_name=unique.name or "UNIQUE",
                        suggestion="Add columns to the UNIQUE constraint or remove it",
                    )
                )

        # Check for duplicate UNIQUE constraints
        unique_column_sets = [frozenset(c.column_names) for c in unique_constraints]
        seen: Set[frozenset[str]] = set()
        for col_set in unique_column_sets:
            if col_set in seen:
                errors.append(
                    ValidationError(
                        severity="warning",
                        message=f"Duplicate UNIQUE constraint on columns {list(col_set)}",
                        object_type="constraint",
                        object_name="UNIQUE",
                        suggestion="Remove duplicate UNIQUE constraints",
                    )
                )
            seen.add(col_set)

        return errors

    def _validate_check_constraints(self, table: "Table") -> List[ValidationError]:
        """Validate CHECK constraints."""
        errors: List[ValidationError] = []

        if not table.constraints:
            return errors

        check_constraints = [
            c for c in table.constraints if c.constraint_type == ConstraintType.CHECK
        ]

        for check in check_constraints:
            # Check if expression exists
            check_expr = None
            if check.check_expression:
                check_expr = check.check_expression
            elif check.columns:
                check_expr = " ".join(check.columns)

            if not check_expr or check_expr.strip() in ("", "1=1", "(1=1)"):
                errors.append(
                    ValidationError(
                        severity="warning",
                        message="CHECK constraint has no meaningful expression",
                        object_type="constraint",
                        object_name=check.name or "CHECK",
                        suggestion="Add a CHECK expression or remove the constraint",
                    )
                )

        return errors

    def _validate_constraint_names(self, table: "Table") -> List[ValidationError]:
        """Validate constraint names for duplicates."""
        errors: List[ValidationError] = []

        if not table.constraints:
            return errors

        # Check for duplicate constraint names
        constraint_names = [
            c.name
            for c in table.constraints
            if c.name and not self._is_system_constraint_name(c.name)
        ]

        seen: Set[str] = set()
        for name in constraint_names:
            if name.lower() in seen:
                errors.append(
                    ValidationError(
                        severity="error",
                        message=f"Duplicate constraint name '{name}'",
                        object_type="constraint",
                        object_name=name,
                        suggestion="Ensure all constraint names are unique within the table",
                    )
                )
            seen.add(name.lower())

        return errors

    def _validate_column_references(self, table: "Table") -> List[ValidationError]:
        """Validate that all constraint column references exist."""
        errors: List[ValidationError] = []

        if not table.constraints:
            return errors

        column_names = {col.name.lower() for col in table.columns}

        for constraint in table.constraints:
            for col_name in constraint.column_names:
                if col_name.lower() not in column_names:
                    errors.append(
                        ValidationError(
                            severity="error",
                            message=f"Constraint references non-existent column '{col_name}'",
                            object_type="constraint",
                            object_name=constraint.name or str(constraint.constraint_type),
                            suggestion=f"Add column '{col_name}' to the table or remove it from the constraint",
                        )
                    )

        return errors

    def _validate_computed_columns(self, table: "Table") -> List[ValidationError]:
        """Validate computed/generated columns."""
        errors: List[ValidationError] = []

        for col in table.columns:
            if getattr(col, "is_computed", False):
                # Check if expression exists
                if not getattr(col, "computed_expression", None):
                    errors.append(
                        ValidationError(
                            severity="error",
                            message=f"Computed column '{col.name}' has no expression",
                            object_type="column",
                            object_name=col.name,
                            property_name="computed_expression",
                            suggestion="Add a computed expression or set is_computed=False",
                        )
                    )

                # Dialect-specific computed-column constraints.
                # PostgreSQL only supports STORED computed columns;
                # MariaDB / DB2 / SQL Server / Oracle accept both
                # ``VIRTUAL`` and ``STORED`` so they pass the check.
                from db.provider_registry import ProviderRegistry

                quirks = ProviderRegistry.get_quirks(self.dialect)
                if not quirks.supports_virtual_computed_columns:
                    if not getattr(col, "computed_stored", True):
                        errors.append(
                            ValidationError(
                                severity="warning",
                                message=(
                                    f"{self.dialect} doesn't support VIRTUAL "
                                    "computed columns, will default to STORED"
                                ),
                                object_type="column",
                                object_name=col.name,
                                property_name="computed_stored",
                                suggestion="Set computed_stored=True",
                            )
                        )

        return errors

    def _find_column(self, table: "Table", col_name: str) -> Optional[SqlColumn]:
        """Find a column by name (case-insensitive)."""
        col_name_lower = col_name.lower()
        for col in table.columns:
            if col.name.lower() == col_name_lower:
                # Type assertion: col is SqlColumn from table.columns
                return col
        return None

    def _is_system_constraint_name(self, name: str) -> bool:
        """Check if a constraint name is system-generated."""
        if not name:
            return True

        name_upper = name.strip().upper()

        # Oracle: SYS_* or SYS$* patterns
        if name_upper.startswith("SYS_") or name_upper.startswith("SYS$"):
            return True

        # DB2: SQL followed by decimal digits (e.g., SQL251208171332370)
        if name_upper.startswith("SQL"):
            if re.match(r"^SQL\d+$", name_upper):
                return True

        name_lower = name.lower()

        # Common system-generated patterns
        system_patterns = [
            "$",
            "pk_",
            "fk_",
            "uk_",
            "ck_",
        ]

        return any(name_lower.startswith(pattern) for pattern in system_patterns)
