"""``SqlConstraint`` representation plus the ``ConstraintType`` enum.

This module is part of the ``core.sql_model.base`` split (PR-H13). Public
import paths should continue to use ``from core.sql_model.base import ...``;
this module is re-exported by the ``base`` façade.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union


class ConstraintType(Enum):
    """Types of SQL constraints."""

    PRIMARY_KEY = "PRIMARY KEY"
    FOREIGN_KEY = "FOREIGN KEY"
    UNIQUE = "UNIQUE"
    CHECK = "CHECK"
    NOT_NULL = "NOT NULL"
    DEFAULT = "DEFAULT"
    EXCLUDE = "EXCLUDE"
    UNKNOWN = "UNKNOWN"


def get_constraint_type_name(constraint: Any) -> str:
    """Return the string name of a constraint's type.

    Replaces the recurring pattern:
        constraint.constraint_type.value
        if hasattr(constraint.constraint_type, "value")
        else str(constraint.constraint_type)

    Args:
        constraint: Any object with a constraint_type attribute (SqlConstraint or duck-typed)

    Returns:
        Constraint type string (e.g., "PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK")
    """
    ct = constraint.constraint_type
    if isinstance(ct, ConstraintType):
        return ct.value
    return str(ct)


def _norm_constraint_enabled(x: Optional[bool]) -> bool:
    """Normalize is_enabled/is_validated: None = default = True (enabled/validated)."""
    return x if x is not None else True


def _norm_constraint_deferrable(x: Optional[bool]) -> bool:
    """Normalize is_deferrable/initially_deferred: None = default = False."""
    return x if x is not None else False


class SqlConstraint:
    """Represents a constraint in a database table."""

    def __init__(
        self,
        constraint_type: Union[ConstraintType, str],
        name: Optional[str] = None,
        column_names: Optional[List[str]] = None,
        reference_table: Optional[str] = None,
        reference_columns: Optional[List[str]] = None,
        check_expression: Optional[str] = None,
        dialect: Optional[str] = None,
        on_delete: Optional[str] = None,
        on_update: Optional[str] = None,
        # Constraint state (Oracle, SQL Server) - Diff-relevant
        is_enabled: Optional[bool] = None,
        is_validated: Optional[bool] = None,
        # Deferrable constraints (PostgreSQL, Oracle) - Diff-relevant
        is_deferrable: Optional[bool] = None,
        initially_deferred: Optional[bool] = None,
        # Constraint comment - SQL-generation-only
        comment: Optional[str] = None,
    ):
        """Initialize a SQL constraint.

        Args:
            constraint_type: Type of constraint
            name: Constraint name
            column_names: Names of the columns in the constraint
            reference_table: Table referenced by a foreign key
            reference_columns: Columns referenced by a foreign key
            check_expression: Expression used in a check constraint
            dialect: SQL dialect
            on_delete: ON DELETE action for foreign keys
            on_update: ON UPDATE action for foreign keys
            is_enabled: Whether constraint is enabled (Oracle, SQL Server) - Diff-relevant
            is_validated: Whether constraint is validated (Oracle) - Diff-relevant
            is_deferrable: Whether constraint is deferrable (PostgreSQL, Oracle) - Diff-relevant
            initially_deferred: Whether constraint is initially deferred - Diff-relevant
            comment: Constraint comment/description - SQL-generation-only
        """
        # Handle both enum and string constraint types
        if isinstance(constraint_type, str):
            try:
                self.constraint_type = ConstraintType[constraint_type.upper().replace(" ", "_")]
            except KeyError:
                self.constraint_type = ConstraintType.UNKNOWN
        else:
            self.constraint_type = constraint_type

        self.name = name
        self.column_names = column_names or []
        self.columns = self.column_names  # Alias for compatibility
        self.reference_table = reference_table
        self.reference_columns = reference_columns or []
        self.reference_schema: Optional[str] = None
        self.check_expression = check_expression
        self.dialect = dialect.lower() if dialect else None
        self.explicit_properties: Dict[str, bool] = {}
        self.on_delete = on_delete
        self.on_update = on_update
        # Constraint state (Oracle, SQL Server) - Diff-relevant
        self.is_enabled = is_enabled
        self.is_validated = is_validated
        # Deferrable constraints (PostgreSQL, Oracle) - Diff-relevant
        self.is_deferrable = is_deferrable
        self.initially_deferred = initially_deferred
        # Constraint comment - SQL-generation-only
        self.comment = comment

    def __str__(self) -> str:
        """Return string representation of the constraint."""
        if self.name:
            return f"{self.constraint_type.value} {self.name} ({', '.join(self.column_names)})"
        return f"{self.constraint_type.value} ({', '.join(self.column_names)})"

    def __eq__(self, other: Any) -> bool:
        """Check if two constraints are equal."""
        if not isinstance(other, SqlConstraint):
            return False
        # Core: type, name, columns (or [] guards against None from from_dict etc.)
        cols_self = self.column_names or []
        cols_other = other.column_names or []
        if not (
            self.constraint_type == other.constraint_type
            and (self.name or "").lower() == (other.name or "").lower()
            and set(col.lower() for col in cols_self) == set(col.lower() for col in cols_other)
        ):
            return False
        # FK target
        if (self.reference_table or "").lower() != (other.reference_table or "").lower():
            return False
        if (self.reference_schema or "").lower() != (other.reference_schema or "").lower():
            return False
        ref_cols_self = self.reference_columns or []
        ref_cols_other = other.reference_columns or []
        if set(col.lower() for col in ref_cols_self) != set(col.lower() for col in ref_cols_other):
            return False
        # FK actions
        if (self.on_delete or "").lower() != (other.on_delete or "").lower():
            return False
        if (self.on_update or "").lower() != (other.on_update or "").lower():
            return False
        # CHECK expression (str() guards against non-string driver-returned types)
        if str(self.check_expression or "").strip() != str(other.check_expression or "").strip():
            return False
        # Constraint state (diff-relevant)
        # is_enabled/is_validated: None = default = True (constraints are enabled/validated by default)
        if _norm_constraint_enabled(self.is_enabled) != _norm_constraint_enabled(other.is_enabled):
            return False
        if _norm_constraint_enabled(self.is_validated) != _norm_constraint_enabled(
            other.is_validated
        ):
            return False
        # is_deferrable/initially_deferred: None = default = False (not deferrable by default)
        if _norm_constraint_deferrable(self.is_deferrable) != _norm_constraint_deferrable(
            other.is_deferrable
        ):
            return False
        if _norm_constraint_deferrable(self.initially_deferred) != _norm_constraint_deferrable(
            other.initially_deferred
        ):
            return False
        return True

    def __hash__(self) -> int:
        """Return hash of the constraint — must be consistent with __eq__."""
        cols = self.column_names or []
        ref_cols = self.reference_columns or []
        # Normalize for hash (must match __eq__)
        # is_enabled/is_validated: None -> True; is_deferrable/initially_deferred: None -> False
        return hash(
            (
                self.constraint_type,
                (self.name or "").lower(),
                tuple(sorted(col.lower() for col in cols)),
                (self.reference_table or "").lower(),
                (self.reference_schema or "").lower(),
                tuple(sorted(col.lower() for col in ref_cols)),
                (self.on_delete or "").lower(),
                (self.on_update or "").lower(),
                str(self.check_expression or "").strip(),
                _norm_constraint_enabled(self.is_enabled),
                _norm_constraint_enabled(self.is_validated),
                _norm_constraint_deferrable(self.is_deferrable),
                _norm_constraint_deferrable(self.initially_deferred),
            )
        )

    def mark_property_explicit(self, property_name: str) -> None:
        """Mark a property as explicitly defined (not using a schema default).

        Args:
            property_name: The name of the property
        """
        self.explicit_properties[property_name] = True

    def is_property_explicit(self, property_name: str) -> bool:
        """Check if a property was explicitly defined.

        Args:
            property_name: The name of the property

        Returns:
            True if the property was explicitly defined, False otherwise
        """
        return bool(self.explicit_properties.get(property_name, False))
