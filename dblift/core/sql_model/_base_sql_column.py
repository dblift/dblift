"""``SqlColumn`` representation for database columns.

This module is part of the ``dblift.core.sql_model.base`` split (PR-H13). Public
import paths should continue to use ``from core.sql_model.base import ...``;
this module is re-exported by the ``base`` façade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from dblift.core.sql_model._base_sql_constraint import SqlConstraint


class SqlColumn:
    """Represents a column in a database table."""

    def __init__(
        self,
        name: str,
        data_type: str,
        is_nullable: bool = True,
        default_value: Optional[str] = None,
        is_primary_key: bool = False,
        is_unique: bool = False,
        constraints: Optional[List["SqlConstraint"]] = None,
        dialect: Optional[str] = None,
        # Identity/Auto-increment metadata
        is_identity: bool = False,
        identity_generation: Optional[str] = None,
        identity_seed: Optional[int] = None,
        identity_increment: Optional[int] = None,
        # Computed/Generated column metadata
        is_computed: bool = False,
        computed_expression: Optional[str] = None,
        computed_stored: bool = False,
        # Comment metadata
        comment: Optional[str] = None,
        # Additional metadata
        ordinal_position: Optional[int] = None,
        # Collation metadata
        collation: Optional[str] = None,
    ):
        """Initialize a SQL column.

        Args:
            name: Column name
            data_type: Data type of the column
            is_nullable: Whether the column can be NULL
            default_value: Default value of the column
            is_primary_key: Whether this column is a primary key
            is_unique: Whether this column has a unique constraint
            constraints: List of constraints on this column
            dialect: SQL dialect
            is_identity: Whether this is an identity/auto-increment column
            identity_generation: Identity generation strategy (ALWAYS, BY DEFAULT)
            identity_seed: Starting value for identity column
            identity_increment: Increment value for identity column
            is_computed: Whether this is a computed/generated column
            computed_expression: Expression used to compute the column value
            computed_stored: Whether computed column is physically stored (vs virtual)
            comment: Column comment/description
            ordinal_position: Position of column in table (1-based)
            collation: Column collation (character set collation for text columns)
        """
        self.name = name
        self.data_type = data_type
        self.nullable = is_nullable
        self.default_value = default_value
        self.is_primary_key = is_primary_key
        self.is_unique = is_unique
        self.constraints = constraints or []
        self.dialect = dialect.lower() if dialect else None

        # Identity column metadata
        self.is_identity = is_identity
        self.identity_generation = identity_generation  # ALWAYS, BY DEFAULT
        self.identity_seed = identity_seed
        self.identity_increment = identity_increment

        # Computed column metadata
        self.is_computed = is_computed
        self.computed_expression = computed_expression
        self.computed_stored = computed_stored

        # Documentation
        self.comment = comment

        # Position metadata
        self.ordinal_position = ordinal_position

        # Collation metadata (for text columns)
        self.collation = collation

        self.explicit_properties: Dict[str, bool] = {}

    def __str__(self) -> str:
        """Return string representation of the column."""
        return f"{self.name} {self.data_type}" + (" NOT NULL" if not self.nullable else "")

    def __eq__(self, other: Any) -> bool:
        """Check if two columns are equal."""
        if not isinstance(other, SqlColumn):
            return False
        return (
            self.name.lower() == other.name.lower()
            and self.data_type.lower() == other.data_type.lower()
            and self.collation == other.collation
        )

    def __hash__(self) -> int:
        """Return hash of the column."""
        return hash((self.name.lower(), self.data_type.lower(), self.collation))

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

    def to_dict(self) -> Dict[str, Any]:
        """Convert column to dictionary representation.

        Returns:
            Dictionary with column attributes
        """
        return {
            "name": self.name,
            "data_type": self.data_type,
            "nullable": self.nullable,
            "default_value": self.default_value,
            "is_primary_key": self.is_primary_key,
            "is_unique": self.is_unique,
            "is_identity": self.is_identity,
            "identity_generation": self.identity_generation,
            "identity_seed": self.identity_seed,
            "identity_increment": self.identity_increment,
            "is_computed": self.is_computed,
            "computed_expression": self.computed_expression,
            "computed_stored": self.computed_stored,
            "comment": self.comment,
            "ordinal_position": self.ordinal_position,
            "collation": self.collation,
            "dialect": self.dialect,
            "explicit_properties": self.explicit_properties,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SqlColumn":
        """Create SqlColumn from dictionary representation.

        Args:
            data: Dictionary with column attributes

        Returns:
            SqlColumn instance
        """
        column = cls(
            name=data["name"],
            data_type=data["data_type"],
            is_nullable=data.get("nullable", True),
            default_value=data.get("default_value"),
            is_primary_key=data.get("is_primary_key", False),
            is_unique=data.get("is_unique", False),
            is_identity=data.get("is_identity", False),
            identity_generation=data.get("identity_generation"),
            identity_seed=data.get("identity_seed"),
            identity_increment=data.get("identity_increment"),
            is_computed=data.get("is_computed", False),
            computed_expression=data.get("computed_expression"),
            computed_stored=data.get("computed_stored", False),
            comment=data.get("comment"),
            ordinal_position=data.get("ordinal_position"),
            collation=data.get("collation"),
            dialect=data.get("dialect"),
        )
        # Restore explicit_properties if present in the serialized data
        if "explicit_properties" in data:
            column.explicit_properties = data["explicit_properties"]
        return column
